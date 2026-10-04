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
    # difficulty=easier keeps puzzles around 1150-1300 rating; rare patterns ignore it.
    MATE_LENGTH_THEMES = ("mateIn2", "mateIn3")
    # Patterns come in any mate length and the API takes one angle, so a few refetches
    # make mate in 2/3 likely; an occasional mate in 1 or 4 still gets through.
    MATE_PATTERN_THEMES = (
        "anastasiaMate", "arabianMate", "backRankMate", "balestraMate", "blindSwineMate",
        "bodenMate", "cornerMate", "doubleBishopMate", "dovetailMate", "epauletteMate",
        "hookMate", "killBoxMate", "morphysMate", "operaMate", "pillsburysMate",
        "smotheredMate", "swallowstailMate", "triangleMate", "vukovicMate",
    )
    PATTERN_FETCH_ATTEMPTS = 3
    LICHESS_RANDOM_PUZZLE_URL = "https://lichess.org/api/puzzle/next?angle={theme}&difficulty=easier"
    LICHESS_PUZZLE_BY_ID_URL = "https://lichess.org/api/puzzle/{puzzle_id}"
    CHESSVISION_FEN_TO_IMAGE_URL = "https://fen2image.chessvision.ai/"
    FETCH_RETRIES = 2
    FETCH_RETRY_DELAY_SECONDS = 3

class LichessDailyPuzzle:
    def __init__(self):
        self.LICHESS_OAUTH_TOKEN = os.environ['LICHESS_OAUTH_TOKEN']
        self.SLACK_CHANNEL_ID = os.environ['SLACK_CHANNEL_ID']

    def _fetch_json_with_retries(self, url: str) -> dict:
        # The cron doesn't retry a failed run, so retry here.
        attempts = Constants.FETCH_RETRIES + 1
        for attempt in range(1, attempts + 1):
            response = requests.get(url)
            try:
                response.raise_for_status()
                return response.json()
            except requests.HTTPError:
                logger.error(
                    "Lichess puzzle fetch failed (attempt %d/%d): %s %s",
                    attempt, attempts, response.status_code, response.text[:500],
                )
                if attempt == attempts:
                    raise
                time.sleep(Constants.FETCH_RETRY_DELAY_SECONDS)

    def _fetch_random_puzzle(self, theme: str) -> dict:
        return self._fetch_json_with_retries(Constants.LICHESS_RANDOM_PUZZLE_URL.format(theme=theme))

    def get_random_puzzle(self) -> dict:
        theme = random.choice(Constants.MATE_LENGTH_THEMES + Constants.MATE_PATTERN_THEMES)
        for _ in range(Constants.PATTERN_FETCH_ATTEMPTS):
            puzzle = self._fetch_random_puzzle(theme)
            if set(puzzle['puzzle']['themes']) & set(Constants.MATE_LENGTH_THEMES):
                break
        return puzzle

    def get_puzzle_by_id(self, puzzle_id: str) -> dict:
        return self._fetch_json_with_retries(Constants.LICHESS_PUZZLE_BY_ID_URL.format(puzzle_id=puzzle_id))

    def resolve_puzzle(self, daily_puzzle: dict) -> tuple[str, str, list]:
        pgn = self.get_pgn_from_daily_puzzle(daily_puzzle)
        fen = self.get_fen_from_pgn(pgn)
        puzzle_id = daily_puzzle['puzzle']['id']
        san_solution = self.convert_uci_solution_to_san(fen, daily_puzzle['puzzle']['solution'])
        return fen, puzzle_id, san_solution

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

    def _resend_puzzle(self, existing: dict, today: datetime) -> None:
        logger.info("Resending puzzle %s for %s", existing['puzzle_id'], today.strftime("%Y-%m-%d"))
        thread_ts = self.send_puzzle_to_slack(
            self.get_board_from_fen(existing['fen']),
            today.strftime("%B %d, %Y"),
            existing['puzzle_id'],
            self.get_image_link_from_fen(self.encode_fen_for_url(existing['fen'])),
            len(existing['solution'][0::2]),
            existing['solution'][-1].endswith('#'),
        )
        db.update_puzzle_slack_ts(existing['puzzle_id'], thread_ts)

    def _fetch_new_puzzle(self) -> tuple[str, str, list]:
        queued = db.get_next_queued_puzzle()
        if queued:
            return queued["fen"], queued["puzzle_id"], queued["solution"]

        return self.resolve_puzzle(self.get_random_puzzle())

    def _post_and_save_puzzle(self, fen: str, puzzle_id: str, san_solution: list, today: datetime) -> None:
        thread_ts = self.send_puzzle_to_slack(
            self.get_board_from_fen(fen),
            today.strftime("%B %d, %Y"),
            puzzle_id,
            self.get_image_link_from_fen(self.encode_fen_for_url(fen)),
            len(san_solution[0::2]),
            san_solution[-1].endswith('#'),
        )
        db.save_puzzle(
            puzzle_id=puzzle_id,
            fen=fen,
            solution=san_solution,
            slack_ts=thread_ts,
        )

    def _generate_and_send_puzzle(self, today: datetime) -> None:
        fen, puzzle_id, san_solution = self._fetch_new_puzzle()
        self._post_and_save_puzzle(fen, puzzle_id, san_solution, today)

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

        if db.is_holiday(date_str):
            logger.info("%s is a holiday, skipping", date_str)
            return

        if db.puzzle_sent_for_date(date_str):
            logger.info("Puzzle already sent for %s, skipping", date_str)
            return

        self._generate_and_send_puzzle(today)
