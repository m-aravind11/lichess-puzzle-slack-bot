from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from pydantic import BaseModel
from slack_sdk import WebClient

import db
from daily_puzzle import LichessDailyPuzzle
from slack_verify import verify_slack_request

class Submission(BaseModel):
    lichess_puzzle_id: str
    user_id: str
    moves: str

app = FastAPI()
lichess = LichessDailyPuzzle()
slack_client = WebClient(token=lichess.LICHESS_OAUTH_TOKEN)

db.init_db()

@app.get('/')
async def root():
    return {"Message": "Welcome to Lichess bot app home"}

@app.post('/submit')
async def submit_response(submission: Submission) -> bool:
    moves=submission.moves.split(' ')
    solution=lichess.get_solution(submission.lichess_puzzle_id)
    return True if moves==solution else False

@app.post('/send_puzzle')
async def send_daily_puzzle():
    await lichess.handle_puzzle_generation_and_sending()
    return "Ok"

@app.post('/slack/solve')
async def solve_command(request: Request):
    body = await verify_slack_request(request)
    form = parse_qs(body.decode('utf-8'))
    user_id = form['user_id'][0]
    user_name = form.get('user_name', [''])[0]
    text = form.get('text', [''])[0].strip()

    if not text:
        return {"response_type": "ephemeral", "text": "Usage: /solve <moves in SAN>, e.g. /solve Nf3 Nc6 Bb5"}

    puzzle = db.get_latest_puzzle()
    if puzzle is None:
        return {"response_type": "ephemeral", "text": "No puzzle available yet."}

    if db.has_submitted(puzzle['puzzle_id'], user_id):
        return {"response_type": "ephemeral", "text": "You've already answered today's puzzle."}

    san_moves = text.split()
    try:
        uci_moves = lichess.convert_san_moves_to_uci(puzzle['fen'], san_moves)
    except (ValueError, IndexError):
        return {"response_type": "ephemeral", "text": "Couldn't parse those moves. Use standard notation, e.g. Nf3 Nc6 Bb5"}

    correct = uci_moves == puzzle['solution']
    db.record_submission(puzzle['puzzle_id'], user_id, user_name, text, correct)

    dm_text = "✅ Correct! Well solved." if correct else f"❌ Not quite. Solution: {' '.join(puzzle['solution'])}"
    im = slack_client.conversations_open(users=[user_id])
    slack_client.chat_postMessage(channel=im['channel']['id'], text=dm_text)

    return {"response_type": "ephemeral", "text": "Answer received — check your DMs!"}

@app.post('/slack/leaderboard')
async def leaderboard_command(request: Request):
    await verify_slack_request(request)
    board = db.get_leaderboard()

    if not board:
        return {"response_type": "ephemeral", "text": "No submissions yet."}

    lines = [f"{i + 1}. <@{row['user_id']}> — {row['score']}" for i, row in enumerate(board)]
    return {"response_type": "in_channel", "text": "*🏆 Leaderboard*\n" + "\n".join(lines)}