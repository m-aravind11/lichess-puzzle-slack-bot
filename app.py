"""Vercel entrypoint - the actual app lives in src/app.py. Kept here (and named
app.py) because Vercel's zero-config Python detection looks for app.py at the
project root; this just loads that file and re-exports its FastAPI instance."""
import importlib.util
import os
import sys

_SRC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
sys.path.insert(0, _SRC_DIR)

_spec = importlib.util.spec_from_file_location("_lichess_app", os.path.join(_SRC_DIR, "app.py"))
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

app = _module.app
