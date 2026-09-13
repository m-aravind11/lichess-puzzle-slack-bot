# Lichess Puzzle Slack Bot

Posts the Lichess daily puzzle to a Slack channel, lets people answer by replying in
the thread, DMs each person whether they got it right, and tracks a leaderboard.

## How it works

1. A cron (or a manual `POST /send_puzzle`) fetches the day's puzzle from Lichess,
   renders the position as an image, and posts it to a Slack channel as a message
   thread. The FEN and solution (converted to SAN) are stored against that thread's
   `ts` in the database.
2. People reply in the thread with their answer, e.g. `Nf3 Nc6 Bb5`. Slack delivers
   that as an Events API callback to `POST /slack/events`. The handler looks up the
   puzzle by thread `ts`, checks the reply hasn't already been answered, verifies the
   moves against the solution, records the submission, and DMs the result.
3. `/leaderboard` (a Slack slash command) posts the current standings to the channel.

Move verification (`LichessDailyPuzzle.check_answer` in `daily_puzzle.py`) parses
both the submitted and solution moves with `python-chess` and compares the resulting
UCI move sequence, rather than comparing strings directly - so `Qe2`, `Qxe2`, `Q*e2`
and `qxe2#` are all treated as the same move when legal, and check/mate suffixes,
capture markers, and letter case don't have to match exactly.

## Files

| File | Responsibility |
|---|---|
| `app.py` | FastAPI routes: puzzle trigger, Slack events, leaderboard command |
| `daily_puzzle.py` | Talks to the Lichess API and Slack, chess move parsing/verification |
| `db.py` | Query layer (Turso/libSQL) |
| `migrations.py` | Schema migrations, tracked in a `schema_migrations` table |
| `slack_helpers.py` | Slack API helpers shared across routes (DM, display name lookup) |
| `slack_verify.py` | Verifies Slack request signatures |

## Storage

Uses [Turso](https://turso.tech) (hosted libSQL, SQLite-compatible) via the
`turso-serverless` driver - not a local SQLite file. This matters because the app is
deployed on Vercel, whose serverless functions have a read-only filesystem outside
`/tmp`, and `/tmp` isn't persisted between invocations. A local `sqlite3` file works
fine for local development but cannot be the system of record once deployed.

Migrations live in `migrations.py` as small idempotent functions tracked by name in a
`schema_migrations` table, applied automatically on startup (`db.init_db()`) - no
separate migration step or tool required.

## Environment variables

| Variable | Used for |
|---|---|
| `LICHESS_OAUTH_TOKEN` | Slack bot token (historical name - this is not a Lichess credential, it's passed straight to `slack_sdk.WebClient`) |
| `SLACK_CHANNEL_ID` | Channel the daily puzzle is posted to |
| `SLACK_SIGNING_SECRET` | Verifies incoming Slack requests (events + slash commands) |
| `TURSO_DATABASE_URL` | e.g. `libsql://<db>-<org>.turso.io` |
| `TURSO_AUTH_TOKEN` | Turso auth token |

## Slack app configuration

The bot needs:

- **Bot token scopes**: `channels:history` (or `groups:history` for a private
  channel), `chat:write`, `commands`, `files:write`, `im:write`, `users:read`.
- **Event Subscriptions**: Request URL `https://<host>/slack/events`, subscribed to
  the bot event `message.channels` (or `message.groups` for a private channel).
- **Slash commands**: `/leaderboard` → `https://<host>/slack/leaderboard`.

Slash commands are rejected by Slack inside a thread reply - that's why answering a
puzzle is a plain thread reply handled through the Events API instead of a command.

## Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /` | Status page |
| `POST /send_puzzle` | Fetches and posts the daily puzzle (call this from a scheduler) |
| `POST /slack/events` | Slack Events API callback - puzzle answers |
| `POST /slack/leaderboard` | Slack slash command - posts the leaderboard |
| `POST /submit` | Older, standalone endpoint: verifies `moves` against a given `lichess_puzzle_id` directly against the Lichess API. Not used by the Slack flow. |

## Local development

```
pip install -r requirements.txt
export LICHESS_OAUTH_TOKEN=xoxb-...
export SLACK_CHANNEL_ID=...
export SLACK_SIGNING_SECRET=...
export TURSO_DATABASE_URL=libsql://...
export TURSO_AUTH_TOKEN=...
uvicorn app:app --reload
```

Slack needs a public HTTPS URL to reach `/slack/events` and `/slack/leaderboard` -
use a tunnel (e.g. `ngrok http 8000`) during local development and update the Slack
app's Request URLs to match.
