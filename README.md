# Lichess Puzzle Slack Bot

Posts the Lichess daily puzzle to Slack. People answer through a private modal
(not a thread reply, so answers can't be copied), get DMed the result, and
there's a leaderboard.

## How it works

1. The `/cron/send-puzzle` cron fetches the day's puzzle from Lichess and
   posts one Slack message: the board image (linked straight from
   [chessvision.ai](https://fen2image.chessvision.ai), no upload needed) plus
   a "Submit Answer" button. The puzzle's FEN, solution, and this message's
   `ts` are saved to the DB, keyed by puzzle id.
2. Clicking the button opens a modal (`POST /slack/interactions`). Submitting
   it checks the moves against the solution, records the submission, and DMs
   the result. A correct answer also gets a "solved it in M:SS" reply posted
   in the puzzle's thread.
3. `/leaderboard` posts current standings to the channel.

Move checking (`LichessDailyPuzzle.check_answer`) parses both sides with
`python-chess` and compares UCI move sequences instead of raw strings, so
`Qe2`, `Qxe2`, `Q*e2`, and `qxe2#` all count as the same move.

## Files

| File | What it does |
|---|---|
| `app.py` | Root shim for Vercel - re-exports `src/app.py`'s `app` |
| `src/app.py` | FastAPI routes |
| `src/interactions.py` | Answer modal handling - opening it and processing its submission |
| `src/daily_puzzle.py` | Lichess API + Slack posting, move parsing/verification |
| `src/db.py` | Query layer (Turso/libSQL) |
| `src/queries.py` | Raw SQL used by `db.py` |
| `src/migrations.py` | Schema migrations |
| `src/constants.py` | Shared constants |
| `src/slack_helpers.py` | Slack API helpers (DM, message formatting) |
| `src/slack_verify.py` | Verifies Slack request signatures |
| `src/static/index.html` | Status page served at `GET /` |
| `tests/` | Pytest suite (currently: `check_answer` move-parsing tolerance) |
| `manifest.json` | Slack app manifest - paste into the App Manifest tab at api.slack.com/apps |

## Storage

Turso (hosted libSQL) via `turso-serverless`, not a local SQLite file - Vercel's
serverless functions have a read-only filesystem outside `/tmp`, and `/tmp`
doesn't persist between invocations.

Migrations are idempotent functions in `src/migrations.py`, tracked by name in
a `schema_migrations` table.

## Migrations

Not run automatically on app startup - the check alone (one round trip to
Turso per already-applied migration) added seconds to every cold-start
request when it lived in the request path. Trigger it yourself after
deploying a change to `migrations.py`, gated by `CRON_SECRET` like the cron
endpoint:

```
curl -X POST https://lichess-puzzle-slack-bot.vercel.app/admin/migrate \
  -H "Authorization: Bearer $CRON_SECRET"
```

## Environment variables

| Variable | Used for |
|---|---|
| `LICHESS_OAUTH_TOKEN` | Slack bot token (historical name, not a Lichess credential) |
| `SLACK_CHANNEL_ID` | Channel the daily puzzle is posted to |
| `SLACK_SIGNING_SECRET` | Verifies incoming Slack requests |
| `CRON_SECRET` | Bearer token required on `/cron/send-puzzle`; check is skipped if unset |
| `TURSO_DATABASE_URL` | e.g. `libsql://<db>-<org>.turso.io` |
| `TURSO_AUTH_TOKEN` | Turso auth token |

## Slack app configuration

Paste `manifest.json` into the App Manifest tab at api.slack.com/apps, swap
in your host in the two URLs, and reinstall the app. It sets:

- Bot scopes: `chat:write`, `commands`, `im:write`, `users:read`
- Interactivity, Request URL → `/slack/interactions`
- Slash command `/leaderboard` → `/slack/leaderboard`

## Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /` | Status page |
| `GET /cron/send-puzzle` | Fetches and posts the daily puzzle, gated by `CRON_SECRET` - what Vercel's cron actually hits (see `vercel.json`) |
| `POST /admin/migrate` | Applies pending migrations, gated by `CRON_SECRET` - trigger manually after deploying a schema change |
| `POST /slack/interactions` | Opens the answer modal, handles its submission |
| `POST /slack/leaderboard` | Slash command - posts the leaderboard |
| `DELETE /submissions/{id}` | Soft-deletes a submission by id |

## Local development

```
pip install -r requirements-dev.txt
export LICHESS_OAUTH_TOKEN=xoxb-...
export SLACK_CHANNEL_ID=...
export SLACK_SIGNING_SECRET=...
export TURSO_DATABASE_URL=libsql://...
export TURSO_AUTH_TOKEN=...
uvicorn app:app --reload --app-dir src
```

Slack needs a public HTTPS URL for `/slack/interactions` and
`/slack/leaderboard` - use ngrok locally and point the Slack app's Request
URLs at it.

## Tests

```
pip install -r requirements-dev.txt
pytest
```

`tests/conftest.py` puts `src/` on `sys.path` and sets dummy credentials so
`daily_puzzle` (and the `db` module it imports) can be imported without a
real Turso/Slack connection.
