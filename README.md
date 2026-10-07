# Lichess Puzzle Slack Bot

A daily chess puzzle for your Slack channel.

Every day the bot posts a Lichess puzzle. People answer through a private
popup rather than a thread reply, so nobody can copy anyone else's answer.
Each person gets their result by DM, and a leaderboard keeps score.

## How it works

1. **The puzzle is posted.** Every day the bot posts a puzzle with a
   picture of the board and a **Submit Answer** button.
2. **People answer privately.** The button opens a popup where you type your
   moves. The bot checks them and DMs you the result. Correct solves get a
   shout-out in the thread.
3. **The solution is revealed.** The next day the bot posts the solution,
   followed by the leaderboard.

## Features

- **Scoring.** Faster correct answers earn more points, and wrong answers
  earn none. The first five correct answers to each puzzle get a podium
  bonus (+5, +3, +2, +1, +1).
- **Leaderboard.** Ranks players by points and tracks streaks of correct
  answers, calling out milestones. It's posted to Slack and also viewable on
  the web.
- **Monthly standings.** Points start afresh each calendar month; a puzzle
  counts toward the month it was posted in. On the 1st the leaderboard posts
  the final standings of the month just ended, followed by a separate
  all-time leaderboard (every finished month added up); if that run is
  missed, the next one catches up. Every finished
  month's board is stored, and the web leaderboard lets you browse past
  months and the all-time standings. Streaks carry across months.
- **Houses.** Players can be grouped into teams that compete on a house
  leaderboard.
- **Holidays.** Pick days off, and no puzzle is posted. Holidays never break
  anyone's streak.
- **Curated puzzles.** Queue specific puzzles to post next. Otherwise the bot
  picks a random one.

The web pages for the leaderboard, houses and holidays are linked from the
home page and ask for the admin secret.

## Running it

Built with Python (FastAPI) and deployed on Vercel. Data is stored in
[Turso](https://turso.tech). A Cloudflare Worker cron (in
`cloudflare-worker/`) triggers the daily posts.

### Environment variables

| Variable | What it is |
|---|---|
| `LICHESS_OAUTH_TOKEN` | Slack bot token (`xoxb-...`). The name is historical. |
| `SLACK_CHANNEL_ID` | Channel to post in |
| `SLACK_SIGNING_SECRET` | Verifies requests come from Slack |
| `TURSO_DATABASE_URL` | Database URL (`libsql://...`) |
| `TURSO_AUTH_TOKEN` | Database token |
| `ADMIN_SECRET` | Password for the admin pages and API |
| `CRON_SECRET` | Used only by the Cloudflare cron |

### Locally

```
pip install -r requirements-dev.txt
export LICHESS_OAUTH_TOKEN=... SLACK_CHANNEL_ID=... SLACK_SIGNING_SECRET=... \
       TURSO_DATABASE_URL=... TURSO_AUTH_TOKEN=... ADMIN_SECRET=... CRON_SECRET=...
uvicorn app:app --reload --app-dir src
```

Slack has to reach your machine, so expose it with ngrok and set the Slack
app's Request URL to `https://<your-host>/webhooks/slack`. To set up the
Slack app itself, paste `manifest.json` into the App Manifest tab at
api.slack.com/apps.

Run the tests with `pytest`. They don't need real Slack or Turso credentials.

### After deploying

If the deploy changed the database schema, run the migrations:

```
curl -X POST https://<your-host>/admin/migrations:run \
  -H "Authorization: Bearer $ADMIN_SECRET"
```

## More

[API.md](API.md) documents every route.
