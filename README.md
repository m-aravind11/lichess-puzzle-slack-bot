# Lichess Puzzle Slack Bot

Posts the Lichess daily puzzle to Slack. People answer through a private modal
(not a thread reply, so answers can't be copied), get DMed the result, and
there's a leaderboard.

## How it works

1. `POST /send_puzzle` (or the `/cron/send-puzzle` cron) fetches the day's
   puzzle from Lichess and posts one Slack message: the board image (linked
   straight from [chessvision.ai](https://fen2image.chessvision.ai), no
   upload needed) plus a "Submit Answer" button. The puzzle's FEN, solution,
   and this message's `ts` are saved to the DB, keyed by puzzle id.
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
| `app.py` | FastAPI routes |
| `daily_puzzle.py` | Lichess API + Slack posting, move parsing/verification |
| `db.py` | Query layer (Turso/libSQL) |
| `queries.py` | Raw SQL used by `db.py` |
| `migrations.py` | Schema migrations |
| `constants.py` | Shared constants and request models |
| `slack_helpers.py` | Slack API helpers (DM, display name, message formatting) |
| `slack_verify.py` | Verifies Slack request signatures |
| `manifest.json` | Slack app manifest - paste into the App Manifest tab at api.slack.com/apps |

## Storage

Turso (hosted libSQL) via `turso-serverless`, not a local SQLite file - Vercel's
serverless functions have a read-only filesystem outside `/tmp`, and `/tmp`
doesn't persist between invocations.

Migrations are idempotent functions in `migrations.py`, tracked by name in a
`schema_migrations` table, and run automatically by `db.init_db()`.

## Environment variables

| Variable | Used for |
|---|---|
| `LICHESS_OAUTH_TOKEN` | Slack bot token (historical name, not a Lichess credential) |
| `SLACK_CHANNEL_ID` | Channel the daily puzzle is posted to |
| `SLACK_SIGNING_SECRET` | Verifies incoming Slack requests |
| `CRON_SECRET` | Bearer token required on `/cron/send-puzzle`; check is skipped if unset |
| `TURSO_DATABASE_URL` | e.g. `libsql://<db>-<org>.turso.io` |
| `TURSO_AUTH_TOKEN` | Turso auth token |
| `PUBLIC_BASE_URL` | Where `/puzzle-image` is publicly reachable; defaults to the production Vercel domain. **Must** be overridden to your tunnel URL for local development - Slack fetches this URL directly, so it can't be `localhost` or a stale production host |

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
| `POST /send_puzzle` | Fetches and posts the daily puzzle |
| `GET /cron/send-puzzle` | Same, gated by `CRON_SECRET` - what Vercel's cron actually hits (see `vercel.json`) |
| `POST /slack/interactions` | Opens the answer modal, handles its submission |
| `POST /slack/leaderboard` | Slash command - posts the leaderboard |
| `DELETE /submissions/{id}` | Soft-deletes a submission by id |
| `POST /submit` | Old standalone endpoint - checks moves against a given puzzle id directly via the Lichess API. Not used by the Slack flow. |

## Local development

```
pip install -r requirements.txt
export LICHESS_OAUTH_TOKEN=xoxb-...
export SLACK_CHANNEL_ID=...
export SLACK_SIGNING_SECRET=...
export TURSO_DATABASE_URL=libsql://...
export TURSO_AUTH_TOKEN=...
export PUBLIC_BASE_URL=https://<your-ngrok-subdomain>.ngrok-free.app
uvicorn app:app --reload
```

Slack needs a public HTTPS URL for `/slack/interactions`, `/slack/leaderboard`,
and `/puzzle-image` - use ngrok locally, point the Slack app's Request URLs at
it, and set `PUBLIC_BASE_URL` to it too. Skipping `PUBLIC_BASE_URL` locally
means the puzzle image link falls back to the production domain, which Slack
will fetch instead of your local server - `POST /send_puzzle` will fail with
`invalid_blocks` if that image URL doesn't resolve.
