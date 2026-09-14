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
from constants import ACTION_OPEN_ANSWER_MODAL

logger = logging.getLogger(__name__)

class Constants:
    LICHESS_DAILY_PUZZLE_URL = "https://lichess.org/api/puzzle/daily"
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
        """Tolerant of a missing/'*' capture marker, letter case, and check/mate suffixes -
        e.g. Qe2, Qxe2, Q*e2 and qxe2# all resolve to the same move when legal."""
        board = self.get_board_from_fen(fen)
        try:
            submitted_uci = []
            for token in submitted_moves:
                move = board.parse_san(self._normalize_san_token(token))
                submitted_uci.append(move.uci())
                board.push(move)

            solution_board = self.get_board_from_fen(fen)
            solution_uci = []
            for san in san_solution:
                move = solution_board.parse_san(san)
                solution_uci.append(move.uci())
                solution_board.push(move)
        except (chess.InvalidMoveError, chess.IllegalMoveError, chess.AmbiguousMoveError):
            return False

        return submitted_uci == solution_uci

    def encode_fen_for_url(self,fen: str) -> str:
        return fen.replace("/", "%2F").replace(" ", "%20")

    def get_image_link_from_fen(self,fen: str) -> str:
        return Constants.CHESSVISION_FEN_TO_IMAGE_URL + fen

    def send_puzzle_to_slack(self,board,date_str: str,puzzle_id: str,image_link: str) -> str | None:
        slack_client = WebClient(token=self.LICHESS_OAUTH_TOKEN)

        try:
            root = slack_client.chat_postMessage(
                channel=self.SLACK_CHANNEL_ID,
                text=f"*Daily Puzzle - {date_str}* - {self.whose_move(board).upper()} to play.",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Daily Puzzle - {date_str}*\n\n{self.whose_move(board).upper()} to play -- Click *Submit Answer* (below the image) to record your response.",
                        },
                    },
                    {
                        "type": "image",
                        "image_url": image_link,
                        "alt_text": f"Daily puzzle - {date_str}",
                    },
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "action_id": ACTION_OPEN_ANSWER_MODAL,
                                "text": {"type": "plain_text", "text": "Submit Answer"},
                                "value": puzzle_id,
                            }
                        ],
                    },
                ],
            )
            return root['ts']
        except SlackApiError as e:
            # You will get a SlackApiError if "ok" is False
            assert e.response["ok"] is False
            assert e.response["error"]  # str like 'invalid_auth', 'channel_not_found'
            logger.error("Got an error: %s", e.response['error'])
            return None

    async def handle_puzzle_generation_and_sending(self) -> None:
        daily_puzzle = self.get_lichess_daily_puzzle()
        pgn = self.get_pgn_from_daily_puzzle(daily_puzzle)
        fen = self.get_fen_from_pgn(pgn)
        puzzle_id = daily_puzzle['puzzle']['id']

        today = datetime.now()
        thread_ts = self.send_puzzle_to_slack(
            self.get_board_from_fen(fen),
            today.strftime("%B %d, %Y"),
            puzzle_id,
            self.get_image_link_from_fen(self.encode_fen_for_url(fen)),
        )

        san_solution = self.convert_uci_solution_to_san(fen, daily_puzzle['puzzle']['solution'])

        db.save_puzzle(
            puzzle_id=puzzle_id,
            date=today.strftime("%Y-%m-%d"),
            fen=fen,
            solution=san_solution,
            slack_ts=thread_ts,
        )
