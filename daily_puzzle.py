import io
import os
from datetime import datetime
import requests

import chess.pgn
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

class Constants:
    LICHESS_DAILY_PUZZLE_URL = "https://lichess.org/api/puzzle/daily"
    LICHESS_PUZZLE_SOLUTION_URL = "https://lichess.org/api/puzzle/"
    CHESSVISION_FEN_TO_IMAGE_URL = "https://fen2image.chessvision.ai/"
    PUZZLE_IMAGE_FILENAME_TEMPLATE = "Lichess Daily Puzzle {}.png"

class LichessDailyPuzzle:
    def __init__(self):
        self.LICHESS_OAUTH_TOKEN = "xoxb-458414646086-10111224817207-uPdYAu7kdTD1tBrFD00yNX7c"
        self.SLACK_CHANNEL_ID = "C0A4113U1CZ"
        
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

    def send_puzzle_to_slack(self,board) -> None:
        slack_client = WebClient(token=self.LICHESS_OAUTH_TOKEN)

        try:
            filepath="./{}".format(self.puzzle_filename)
            response = slack_client.files_upload_v2(
                channel=self.SLACK_CHANNEL_ID, 
                file=filepath, 
                initial_comment="{} to play".format(self.whose_move(board).upper()))
            print (response)
            assert response["file"]  # the uploaded file
        except SlackApiError as e:
            # You will get a SlackApiError if "ok" is False
            assert e.response["ok"] is False
            assert e.response["error"]  # str like 'invalid_auth', 'channel_not_found'
            print(f"Got an error: {e.response['error']}")

    async def handle_puzzle_generation_and_sending(self) -> None:
        pgn = self.get_pgn_from_daily_puzzle(self.get_lichess_daily_puzzle())
        fen = self.get_fen_from_pgn(pgn)
        encoded_fen = self.encode_fen_for_url(fen)

        self.puzzle_filename = Constants.PUZZLE_IMAGE_FILENAME_TEMPLATE.format(datetime.now().strftime("%Y-%m-%d"))

        self.save_puzzle_image(self.get_image_link_from_fen(encoded_fen), self.puzzle_filename)
        self.send_puzzle_to_slack(self.get_board_from_fen(fen))
