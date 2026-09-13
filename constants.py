import os
import re

from pydantic import BaseModel

SAN_TOKEN_RE = re.compile(r'^(?:[O0]-[O0](?:-[O0])?|[KQRBN]?[a-h]?[1-8]?[x*]?[a-h][1-8](?:=[QRBN])?)[+#]?$', re.IGNORECASE)
INDEX_HTML_PATH = os.path.join(os.path.dirname(__file__), 'static', 'index.html')
CRON_SECRET = os.environ.get('CRON_SECRET')

# Chessvision's board images have no size parameter, so PUBLIC_BASE_URL lets us proxy
# and resize the image ourselves for the channel post (see GET /puzzle-image/{puzzle_id}
# in app.py) - override it for local dev (e.g. an ngrok URL), since Slack needs to fetch it.
PUBLIC_BASE_URL = os.environ.get('PUBLIC_BASE_URL', 'https://lichess-puzzle-slack-bot.vercel.app')

# Answer-submission modal: a button on the puzzle post opens this privately, so
# moves never appear in the thread where others could see or copy them.
ACTION_OPEN_ANSWER_MODAL = "open_answer_modal"
ANSWER_MODAL_CALLBACK_ID = "answer_modal"
MOVES_BLOCK_ID = "moves_block"
MOVES_ACTION_ID = "moves_input"


class Submission(BaseModel):
    lichess_puzzle_id: str
    user_id: str
    moves: str
