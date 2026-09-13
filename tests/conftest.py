import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# daily_puzzle imports db, which reads Turso credentials at module import time,
# and LichessDailyPuzzle() reads Slack credentials in __init__ - neither is
# actually used by check_answer, but both must be set for the import to work.
os.environ.setdefault("VERCEL_TURSO_TURSO_DATABASE_URL", "libsql://test.turso.io")
os.environ.setdefault("VERCEL_TURSO_TURSO_AUTH_TOKEN", "test-token")
os.environ.setdefault("LICHESS_OAUTH_TOKEN", "xoxb-test")
os.environ.setdefault("SLACK_CHANNEL_ID", "C000000")
