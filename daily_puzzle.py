import io
import logging
import os
from datetime import datetime
import requests

import chess.pgn
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

import db

logger = logging.getLogger(__name__)

class Constants:
    LICHESS_DAILY_PUZZLE_URL = "https://lichess.org/api/puzzle/daily"
    LICHESS_PUZZLE_SOLUTION_URL = "https://lichess.org/api/puzzle/"
    CHESSVISION_FEN_TO_IMAGE_URL = "https://fen2image.chessvision.ai/"
    PUZZLE_IMAGE_FILENAME_TEMPLATE = "Lichess Daily Puzzle {}.png"

class LichessDailyPuzzle:
    def __init__(self):
        self.LICHESS_OAUTH_TOKEN = os.environ['LICHESS_OAUTH_TOKEN']
        self.SLACK_CHANNEL_ID = os.environ['SLACK_CHANNEL_ID']
        
    def get_lichess_daily_puzzle(self) -> dict:
        return requests.get(Constants.LICHESS_DAILY_PUZZLE_URL).json()
    
    def get_solution(self, puzzle_id:str) -> list:
        return requests.get(Constants.LICHESS_PUZZLE_SOLUTION_URL+puzzle_id).json()['puzzle']['solution']
         
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

    def convert_san_moves_to_uci(self, fen: str, san_moves: list) -> list:
        board = self.get_board_from_fen(fen)
        uci_moves = []
        for san in san_moves:
            move = board.parse_san(san)
            uci_moves.append(move.uci())
            board.push(move)
        return uci_moves

    def encode_fen_for_url(self,fen: str) -> str:
        return fen.replace("/", "%2F").replace(" ", "%20")

    def get_image_link_from_fen(self,fen: str) -> str:
        return Constants.CHESSVISION_FEN_TO_IMAGE_URL + fen
    
    def save_puzzle_image(self, img_link: str, filename: str) -> None:
        get_response = requests.get(img_link, stream=True)
        with open(filename, 'wb') as f:
            for chunk in get_response.iter_content(chunk_size=1024):
                if chunk:
                    f.write(chunk)

    def _get_latest_message_ts(self, slack_client: WebClient) -> str | None:
        history = slack_client.conversations_history(channel=self.SLACK_CHANNEL_ID, limit=1)
        messages = history.get('messages', [])
        return messages[0]['ts'] if messages else None

    def send_puzzle_to_slack(self,board) -> str | None:
        slack_client = WebClient(token=self.LICHESS_OAUTH_TOKEN)

        try:
            filepath="./{}".format(self.puzzle_filename)
            response = slack_client.files_upload_v2(
                channel=self.SLACK_CHANNEL_ID,
                file=filepath,
                initial_comment="{} to play".format(self.whose_move(board).upper()))
            logger.info("Puzzle posted: %s", response)
            assert response["file"]  # the uploaded file

            thread_ts = self._get_latest_message_ts(slack_client)
            if thread_ts:
                slack_client.chat_postMessage(
                    channel=self.SLACK_CHANNEL_ID,
                    thread_ts=thread_ts,
                    text="Reply in this thread with your solution (e.g. Nf3 Nc6 Bb5).",
                )
            else:
                logger.error("Could not find message ts in upload response, replies won't be trackable")
            return thread_ts
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
        encoded_fen = self.encode_fen_for_url(fen)

        self.puzzle_filename = Constants.PUZZLE_IMAGE_FILENAME_TEMPLATE.format(datetime.now().strftime("%Y-%m-%d"))

        self.save_puzzle_image(self.get_image_link_from_fen(encoded_fen), self.puzzle_filename)
        thread_ts = self.send_puzzle_to_slack(self.get_board_from_fen(fen))

        db.save_puzzle(
            puzzle_id=daily_puzzle['puzzle']['id'],
            date=datetime.now().strftime("%Y-%m-%d"),
            fen=fen,
            solution=daily_puzzle['puzzle']['solution'],
            slack_ts=thread_ts,
        )
