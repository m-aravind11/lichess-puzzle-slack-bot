import io
import logging
import os
import time
from datetime import datetime
import requests

import chess.pgn
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

import db
from constants import SlackActions

logger = logging.getLogger(__name__)

class Constants:
    # /api/puzzle/next?difficulty=easiest (anonymous) skews puzzle rating to
    # roughly 800-950 - an easier on-ramp than the official daily puzzle,
    # which can land at any rating.
    LICHESS_DAILY_PUZZLE_URL = "https://lichess.org/api/puzzle/next?angle=mix&difficulty=easiest"
    CHESSVISION_FEN_TO_IMAGE_URL = "https://fen2image.chessvision.ai/"
    FETCH_RETRIES = 2
    FETCH_RETRY_DELAY_SECONDS = 3

class LichessDailyPuzzle:
    def __init__(self):
        self.LICHESS_OAUTH_TOKEN = os.environ['LICHESS_OAUTH_TOKEN']
        self.SLACK_CHANNEL_ID = os.environ['SLACK_CHANNEL_ID']

    def get_lichess_daily_puzzle(self) -> dict:
        # The cron trigger doesn't retry a failed run on its own, so a couple of
        # in-process retries here are the only thing standing between a transient
        # Lichess hiccup and no puzzle getting posted for the day.
        attempts = Constants.FETCH_RETRIES + 1
        for attempt in range(1, attempts + 1):
            response = requests.get(Constants.LICHESS_DAILY_PUZZLE_URL)
            try:
                response.raise_for_status()
                return response.json()
            except requests.HTTPError:
                logger.error(
                    "Lichess daily puzzle fetch failed (attempt %d/%d): %s %s",
                    attempt, attempts, response.status_code, response.text[:500],
                )
                if attempt == attempts:
                    raise
                time.sleep(Constants.FETCH_RETRY_DELAY_SECONDS)
    
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

    def _normalize_san_token(self, token: str) -> str:
        token = token.strip().replace('*', 'x')
        lowered = token.lower()
        if lowered in ('o-o', '0-0'):
            return 'O-O'
        if lowered in ('o-o-o', '0-0-0'):
            return 'O-O-O'
        token = lowered
        if token and token[0] in 'kqrbn':
            token = token[0].upper() + token[1:]
        return token

    def check_answer(self, fen: str, san_solution: list, submitted_moves: list) -> bool:
        """submitted_moves = player's own moves only (san_solution[0::2]); opponent
        replies (odd indices) come from san_solution itself, never from the user -
        Lichess's solution only records one of possibly several valid replies.
        Tolerant of a missing/'*' capture marker, case, and check/mate suffixes."""
        expected_player_move_count = len(san_solution[0::2])
        if len(submitted_moves) != expected_player_move_count:
            return False

        board = self.get_board_from_fen(fen)
        submitted_iter = iter(submitted_moves)
        try:
            for ply, san in enumerate(san_solution):
                solution_move = board.parse_san(san)
                if ply % 2 == 0:
                    token = next(submitted_iter)
                    submitted_move = board.parse_san(self._normalize_san_token(token))
                    if submitted_move != solution_move:
                        return False
                board.push(solution_move)
        except (chess.InvalidMoveError, chess.IllegalMoveError, chess.AmbiguousMoveError):
            return False

        return True

    def encode_fen_for_url(self,fen: str) -> str:
        return fen.replace("/", "%2F").replace(" ", "%20")

    def get_image_link_from_fen(self,fen: str) -> str:
        return Constants.CHESSVISION_FEN_TO_IMAGE_URL + fen

    def send_puzzle_to_slack(self,board,date_str: str,puzzle_id: str,image_link: str,num_moves: int) -> str | None:
        slack_client = WebClient(token=self.LICHESS_OAUTH_TOKEN)
        move_label = "move" if num_moves == 1 else "moves"

        try:
            root = slack_client.chat_postMessage(
                channel=self.SLACK_CHANNEL_ID,
                text=f"<!channel> *Puzzle for the day ({date_str})* - {self.whose_move(board).upper()} to play, {num_moves} {move_label}.",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": (
                                f"<!channel> *Puzzle for the day ({date_str})*\n"
                                f"`{self.whose_move(board).upper()} TO PLAY · {num_moves} {move_label.upper()}`\n\n"
                                f"Click *Submit Answer* below and enter only your own moves, e.g. `Nf3 Bb5` "
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

    def _resend_puzzle(self, existing: dict, today: datetime) -> None:
        logger.info("Resending puzzle %s for %s", existing['puzzle_id'], today.strftime("%Y-%m-%d"))
        thread_ts = self.send_puzzle_to_slack(
            self.get_board_from_fen(existing['fen']),
            today.strftime("%B %d, %Y"),
            existing['puzzle_id'],
            self.get_image_link_from_fen(self.encode_fen_for_url(existing['fen'])),
            len(existing['solution'][0::2]),
        )
        db.update_puzzle_slack_ts(existing['puzzle_id'], thread_ts)

    def _fetch_new_puzzle(self) -> tuple[str, str, list]:
        daily_puzzle = self.get_lichess_daily_puzzle()
        pgn = self.get_pgn_from_daily_puzzle(daily_puzzle)
        fen = self.get_fen_from_pgn(pgn)
        puzzle_id = daily_puzzle['puzzle']['id']
        san_solution = self.convert_uci_solution_to_san(fen, daily_puzzle['puzzle']['solution'])
        return fen, puzzle_id, san_solution

    def _post_and_save_puzzle(self, fen: str, puzzle_id: str, san_solution: list, today: datetime) -> None:
        thread_ts = self.send_puzzle_to_slack(
            self.get_board_from_fen(fen),
            today.strftime("%B %d, %Y"),
            puzzle_id,
            self.get_image_link_from_fen(self.encode_fen_for_url(fen)),
            len(san_solution[0::2]),
        )
        db.save_puzzle(
            puzzle_id=puzzle_id,
            date=today.strftime("%Y-%m-%d"),
            fen=fen,
            solution=san_solution,
            slack_ts=thread_ts,
        )

    def _generate_and_send_puzzle(self, today: datetime) -> None:
        fen, puzzle_id, san_solution = self._fetch_new_puzzle()
        self._post_and_save_puzzle(fen, puzzle_id, san_solution, today)

    async def handle_puzzle_generation_and_sending(self, force: bool = False, new_puzzle: bool = False) -> None:
        today = datetime.now()
        date_str = today.strftime("%Y-%m-%d")

        if new_puzzle:
            # Explicit override: always fetch a different puzzle, ignoring force
            # and whatever's already been sent today.
            self._generate_and_send_puzzle(today)
            return

        if force:
            # Network-issue retry: repost today's puzzle rather than fetching a
            # new random one. Falls through to a fresh fetch if there's nothing
            # active left to resend (e.g. it was deactivated).
            existing = db.get_active_puzzle_by_date(date_str)
            if existing:
                self._resend_puzzle(existing, today)
                return
            self._generate_and_send_puzzle(today)
            return

        if db.puzzle_sent_for_date(date_str):
            # Default idempotency guard: a retriggered cron with no flags must
            # not post a second, different puzzle for the same day.
            logger.info("Puzzle already sent for %s, skipping", date_str)
            return

        self._generate_and_send_puzzle(today)
