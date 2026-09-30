import os
import re


class Paths:
    INDEX_HTML_PATH = os.path.join(os.path.dirname(__file__), 'static', 'index.html')
    HOUSES_HTML_PATH = os.path.join(os.path.dirname(__file__), 'static', 'houses.html')
    LEADERBOARD_HTML_PATH = os.path.join(os.path.dirname(__file__), 'static', 'leaderboard.html')
    HOLIDAYS_HTML_PATH = os.path.join(os.path.dirname(__file__), 'static', 'holidays.html')


class Security:
    CRON_SECRET = os.environ.get('CRON_SECRET')
    ADMIN_SECRET = os.environ.get('ADMIN_SECRET')


class Validation:
    # '=' is optional so UCI-style promotions (e7e8q) pass through to parse_san.
    SAN_TOKEN_RE = re.compile(r'^(?:[O0]-[O0](?:-[O0])?|[KQRBN]?[a-h]?[1-8]?[x*]?[a-h][1-8](?:=?[QRBN])?)[+#]?$', re.IGNORECASE)


class SlackActions:
    OPEN_ANSWER_MODAL = "open_answer_modal"
    ANSWER_MODAL_CALLBACK_ID = "answer_modal"
    MOVES_BLOCK_ID = "moves_block"
    MOVES_ACTION_ID = "moves_input"


class Streaks:
    # Matched exactly, not >=, so each is announced once, the day it's hit.
    MILESTONES = (3, 7, 14, 30, 50, 100, 150, 200, 250, 300, 365)


class SubmissionResult:
    RECORDED = "recorded"
    DUPLICATE = "duplicate"
    PUZZLE_CLOSED = "puzzle_closed"


class PuzzleSource:
    CURATED = "curated"
    RANDOM = "random"


class PuzzleState:
    QUEUED = "queued"
    POSTED = "posted"


class PuzzleResult:
    DEACTIVATED = "deactivated"
    REACTIVATED = "reactivated"
    NOT_FOUND = "not_found"
    ALREADY_ACTIVE = "already_active"
    HAS_ACTIVE_SUBMISSIONS = "has_active_submissions"


class PlayerHouseResult:
    ASSIGNED = "assigned"
    PLAYER_NOT_FOUND = "player_not_found"
    HOUSE_NOT_FOUND = "house_not_found"
    ALREADY_ASSIGNED = "already_assigned"
