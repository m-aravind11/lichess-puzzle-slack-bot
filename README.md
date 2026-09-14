# Lichess Puzzle Slack Bot

Posts the Lichess daily puzzle to Slack. People answer through a private modal
(not a thread reply, so answers can't be copied), get DMed the result, and
there's a points-based leaderboard.

## How it works

1. The `/cron/send-puzzle` cron fetches the day's puzzle from Lichess and
   posts one Slack message: the board image (linked straight from
   [chessvision.ai](https://fen2image.chessvision.ai), no upload needed) plus
   a "Submit Answer" button. The puzzle's FEN, solution, and this message's
   `ts` are saved to the DB, keyed by puzzle id.
2. Clicking the button opens a modal (`POST /slack/interactions`). Submitting
   it checks the moves against the solution, scores it, records the
   submission, and DMs the result. A correct answer also gets a "solved it in
   M:SS (+N pts)" reply posted in the puzzle's thread.
3. `/cron/send-leaderboard` posts current standings to the channel.

Storage is Turso (hosted libSQL), not a local SQLite file - Vercel's
serverless functions have a read-only filesystem outside `/tmp`, and `/tmp`
doesn't persist between invocations. Schema migrations live in
`src/migrations.py` and aren't run automatically on startup (that check alone
added seconds to every cold start); trigger them after deploying a schema
change:

```
curl -X POST https://lichess-puzzle-slack-bot.vercel.app/admin/migrate \
  -H "Authorization: Bearer $CRON_SECRET"
```

## Scoring and functionality

A correct answer is worth `MAX_SCORE` (10) points, decayed by how long after
the puzzle was posted it was submitted - points halve every
`HALF_LIFE_MINUTES` (120), so a solve 2 hours in is worth 5, 4 hours in worth
2.5 (rounded), and so on. A wrong answer is worth 0. If the puzzle's post
time can't be determined (no `slack_ts`, or a negative elapsed time from a
stale repost), the submission gets full credit rather than being penalized
for a measurement that isn't there. See `src/scoring.py`.

The leaderboard ranks by total points, ties broken by fastest average solve
time (correct answers only).

Move checking (`LichessDailyPuzzle.check_answer`) parses both sides with
`python-chess` and compares UCI move sequences instead of raw strings, so
`Qe2`, `Qxe2`, `Q*e2`, and `qxe2#` all count as the same move.

## Local setup

```
pip install -r requirements-dev.txt
export LICHESS_OAUTH_TOKEN=xoxb-...     # Slack bot token (historical name)
export SLACK_CHANNEL_ID=...
export SLACK_SIGNING_SECRET=...
export TURSO_DATABASE_URL=libsql://...
export TURSO_AUTH_TOKEN=...
uvicorn app:app --reload --app-dir src
```

Slack needs a public HTTPS URL for `/slack/interactions` - use ngrok locally
and point the Slack app's Request URL at it. To configure the Slack app
itself, paste `manifest.json` into the App Manifest tab at api.slack.com/apps
(swap in your host in the request URL) and reinstall.

Run tests with:

```
pytest
```

`tests/conftest.py` puts `src/` on `sys.path` and sets dummy credentials so
modules can be imported without a real Turso/Slack connection.
