from fastapi import FastAPI
from pydantic import BaseModel
from daily_puzzle import LichessDailyPuzzle

class Submission(BaseModel):
    lichess_puzzle_id: str
    user_id: str
    moves: str
    
app = FastAPI()
lichess = LichessDailyPuzzle()

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