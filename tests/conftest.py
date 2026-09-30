import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Read at import time, though these tests don't use them.
os.environ.setdefault("TURSO_DATABASE_URL", "libsql://test.turso.io")
os.environ.setdefault("TURSO_AUTH_TOKEN", "test-token")
os.environ.setdefault("LICHESS_OAUTH_TOKEN", "xoxb-test")
os.environ.setdefault("SLACK_CHANNEL_ID", "C000000")
os.environ.setdefault("SLACK_SIGNING_SECRET", "test-signing-secret")
