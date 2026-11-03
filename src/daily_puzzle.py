import io
import logging
import os
import random
import time
from datetime import datetime, timezone
import requests

import chess.pgn
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

import db
from constants import SlackActions

logger = logging.getLogger(__name__)

class Constants:
    MATE_THEMES = ("mateIn2", "mateIn3")
    LICHESS_RANDOM_PUZZLE_URL = "https://lichess.org/api/puzzle/next?angle={theme}&difficulty={difficulty}"
    CHESSVISION_FEN_TO_IMAGE_URL = "https://fen2image.chessvision.ai/"
    FETCH_TIMEOUT_SECONDS = 10
    FETCH_RETRY_DELAYS_SECONDS = (1, 3)

def _is_retryable(error: requests.RequestException) -> bool:
    # Lichess wants a full minute after a 429, longer than is worth blocking on.
    if isinstance(error, requests.HTTPError):
        return error.response.status_code >= 500
    return isinstance(error, (requests.Timeout, requests.ConnectionError))

class LichessDailyPuzzle:
    def __init__(self):
        self.LICHESS_OAUTH_TOKEN = os.environ['LICHESS_OAUTH_TOKEN']
        self.SLACK_CHANNEL_ID = os.environ['SLACK_CHANNEL_ID']

    def _fetch_json_with_retries(self, url: str) -> dict:
        # The cron doesn't retry a failed run, so retry here.
        attempts = len(Constants.FETCH_RETRY_DELAYS_SECONDS) + 1
        for attempt, delay in enumerate((*Constants.FETCH_RETRY_DELAYS_SECONDS, None), 1):
            try:
                response = requests.get(url, timeout=Constants.FETCH_TIMEOUT_SECONDS)
                response.raise_for_status()
                return response.json()
            except requests.RequestException as e:
                body = e.response.text[:500] if e.response is not None else ""
                logger.error("Lichess puzzle fetch failed (attempt %d/%d): %s %s", attempt, attempts, e, body)
                if delay is None or not _is_retryable(e):
                    raise
                time.sleep(delay)

    def _fetch_random_puzzle(self, theme: str, difficulty: str) -> dict:
        return self._fetch_json_with_retries(
            Constants.LICHESS_RANDOM_PUZZLE_URL.format(theme=theme, difficulty=difficulty)
        )

    def pick_difficulty(self) -> str:
        weights = db.get_difficulty_weights()
        return random.choices(list(weights), weights=list(weights.values()))[0]

    def get_random_puzzle(self, difficulty: str) -> dict:
        return self._fetch_random_puzzle(random.choice(Constants.MATE_THEMES), difficulty)

    def resolve_puzzle(self, daily_puzzle: dict) -> dict:
        fen = self.get_fen_from_pgn(self.get_pgn_from_daily_puzzle(daily_puzzle))
        return {
            "puzzle_id": daily_puzzle['puzzle']['id'],
            "fen": fen,
            "solution": self.convert_uci_solution_to_san(fen, daily_puzzle['puzzle']['solution']),
            "rating": daily_puzzle['puzzle'].get('rating'),
        }

    def _fetch_random_resolved_puzzle(self) -> dict:
        difficulty = self.pick_difficulty()
        return {**self.resolve_puzzle(self.get_random_puzzle(difficulty)), "difficulty": difficulty}

    def get_pgn_from_daily_puzzle(self,daily_puzzle: dict) -> str:
        return daily_puzzle['game']['pgn']

    def whose_move(self,board) -> str:
        return 'White' if board.turn == chess.WHITE else 'Black'

    def get_fen_from_pgn(self,pgn: str) -> str:
        game = chess.pgn.read_game(io.StringIO(pgn))
        board = game.board()
        for move in game.mainline_moves():
            board.push(move)
        return board.fen()

    def get_board_from_fen(self,fen: str):
        board = chess.Board()
        board.set_fen(fen)
        return board

    def convert_uci_solution_to_san(self, fen: str, uci_moves: list) -> list:
        board = self.get_board_from_fen(fen)
        san_moves = []
        for uci in uci_moves:
            move = chess.Move.from_uci(uci)
            san_moves.append(board.san(move))
            board.push(move)
        return san_moves

    def _parse_submitted_move(self, board, token: str) -> chess.Move:
        token = token.strip().replace('*', 'x')
        lowered = token.lower()
        if lowered in ('o-o', '0-0'):
            return board.parse_san('O-O')
        if lowered in ('o-o-o', '0-0-0'):
            return board.parse_san('O-O-O')
        if lowered[:1] in ('k', 'q', 'r', 'n'):
            return board.parse_san(lowered[0].upper() + lowered[1:])
        if lowered[:1] != 'b':
            return board.parse_san(lowered)

        # 'b' is both the bishop and the b-file, so the typed case only decides
        # when both readings are legal (e.g. bxc3 vs Bxc3).
        as_pawn, as_bishop = lowered, 'B' + lowered[1:]
        preferred, fallback = (as_bishop, as_pawn) if token[0] == 'B' else (as_pawn, as_bishop)
        try:
            return board.parse_san(preferred)
        except ValueError:
            return board.parse_san(fallback)

    def check_answer(self, fen: str, san_solution: list, submitted_moves: list) -> bool:
        # san_solution alternates player move / opponent reply. Users submit only their
        # own moves; replies are replayed from the solution, since Lichess records just
        # one of possibly several valid replies.
        player_moves = san_solution[0::2]
        opponent_replies = san_solution[1::2]
        board = self.get_board_from_fen(fen)
        try:
            for turn, expected_san in enumerate(player_moves):
                if turn >= len(submitted_moves):
                    return False
                expected = board.parse_san(expected_san)
                submitted = self._parse_submitted_move(board, submitted_moves[turn])

                if submitted != expected:
                    # Like Lichess, a different move that mates on the spot also solves it,
                    # as long as nothing was submitted after it.
                    board.push(submitted)
                    is_last_submitted = turn == len(submitted_moves) - 1
                    return board.is_checkmate() and is_last_submitted

                board.push(expected)
                if turn < len(opponent_replies):
                    board.push_san(opponent_replies[turn])
        except (chess.InvalidMoveError, chess.IllegalMoveError, chess.AmbiguousMoveError):
            return False

        return len(submitted_moves) == len(player_moves)

    def encode_fen_for_url(self,fen: str) -> str:
        return fen.replace("/", "%2F").replace(" ", "%20")

    def get_image_link_from_fen(self,fen: str) -> str:
        return Constants.CHESSVISION_FEN_TO_IMAGE_URL + fen

    def send_puzzle_to_slack(self,board,date_str: str,puzzle_id: str,image_link: str,num_moves: int,is_mate: bool = False) -> str | None:
        slack_client = WebClient(token=self.LICHESS_OAUTH_TOKEN)
        move_label = f"mate in {num_moves}" if is_mate else f"{num_moves} {'move' if num_moves == 1 else 'moves'}"

        try:
            root = slack_client.chat_postMessage(
                channel=self.SLACK_CHANNEL_ID,
                text=f"<!channel> *Puzzle for the day ({date_str})* - {self.whose_move(board).upper()} to play, {move_label}.",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": (
                                f"<!channel> *Puzzle for the day ({date_str})*\n"
                                f"`{self.whose_move(board).upper()} TO PLAY — {move_label.upper()}`\n\n"
                                f"Click *Submit Answer* below and *ENTER YOUR OWN MOVES ONLY*, e.g. `Nf3 Bb5` "
                                f"(your opponent's replies are added automatically). You'll get the result by DM."
                            ),
                        },
                    },
                    {
                        "type": "image",
                        "image_url": image_link,
                        "alt_text": f"Puzzle for the day ({date_str})",
                    },
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "action_id": SlackActions.OPEN_ANSWER_MODAL,
                                "text": {"type": "plain_text", "text": "Submit Answer"},
                                "value": puzzle_id,
                            }
                        ],
                    },
                ],
            )
            return root['ts']
        except SlackApiError as e:
            logger.error("Got an error: %s", e.response['error'])
            return None

    def _send_puzzle(self, puzzle: dict, today: datetime) -> str | None:
        return self.send_puzzle_to_slack(
            self.get_board_from_fen(puzzle['fen']),
            today.strftime("%B %d, %Y"),
            puzzle['puzzle_id'],
            self.get_image_link_from_fen(self.encode_fen_for_url(puzzle['fen'])),
            len(puzzle['solution'][0::2]),
            puzzle['solution'][-1].endswith('#'),
        )

    def _resend_puzzle(self, existing: dict, today: datetime) -> None:
        logger.info("Resending puzzle %s for %s", existing['puzzle_id'], today.strftime("%Y-%m-%d"))
        db.update_puzzle_slack_ts(existing['puzzle_id'], self._send_puzzle(existing, today))

    def _fetch_new_puzzle(self) -> dict:
        return db.get_next_queued_puzzle() or self._fetch_random_resolved_puzzle()

    def prepare_next_puzzle(self) -> None:
        queued = db.get_next_queued_puzzle()
        if queued:
            logger.info("Puzzle %s already queued, skipping", queued["puzzle_id"])
            return

        db.queue_puzzle(**self._fetch_random_resolved_puzzle())

    def _generate_and_send_puzzle(self, today: datetime) -> None:
        puzzle = self._fetch_new_puzzle()
        db.save_puzzle(**puzzle, slack_ts=self._send_puzzle(puzzle, today))

    async def handle_puzzle_generation_and_sending(self, force: bool = False, new_puzzle: bool = False) -> None:
        today = datetime.now(timezone.utc)
        date_str = today.strftime("%Y-%m-%d")

        if new_puzzle:
            self._generate_and_send_puzzle(today)
            return

        if force:
            existing = db.get_active_puzzle_by_date(date_str)
            if existing:
                self._resend_puzzle(existing, today)
                return
            self._generate_and_send_puzzle(today)
            return

        if db.puzzle_sent_for_date(date_str):
            logger.info("Puzzle already sent for %s, skipping", date_str)
            return

        self._generate_and_send_puzzle(today)
