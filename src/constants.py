import os
import re

SAN_TOKEN_RE = re.compile(r'^(?:[O0]-[O0](?:-[O0])?|[KQRBN]?[a-h]?[1-8]?[x*]?[a-h][1-8](?:=[QRBN])?)[+#]?$', re.IGNORECASE)
INDEX_HTML_PATH = os.path.join(os.path.dirname(__file__), 'static', 'index.html')
CRON_SECRET = os.environ.get('CRON_SECRET')

# Answer-submission modal: a button on the puzzle post opens this privately, so
# moves never appear in the thread where others could see or copy them.
ACTION_OPEN_ANSWER_MODAL = "open_answer_modal"
ANSWER_MODAL_CALLBACK_ID = "answer_modal"
MOVES_BLOCK_ID = "moves_block"
MOVES_ACTION_ID = "moves_input"
