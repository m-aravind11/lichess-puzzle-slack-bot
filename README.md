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

- **Scoring.** Solve points for speed, a podium bonus for the first five
  correct answers, and a streak bonus for solving puzzles in a row. See
  [Scoring](#scoring).
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

## Scoring

A puzzle's points are its solve points plus any podium bonus, and streak
bonuses are added on top.

Each puzzle allows two attempts. A wrong first attempt is DMed as wrong
without revealing the solution; the solution is DMed only after a correct
answer or a second wrong one. A correct second attempt earns half the solve
points and no podium bonus.

### Solve points

Counted from when the puzzle is posted. Each range includes its start, not
its end. Any correct answer before the solution is revealed earns at least 1.

| Time after posting | Points | Time after posting | Points |
|---|---|---|---|
| 0 – 10 min | 10 | 4 h – 5 h | 5 |
| 10 – 20 min | 9.5 | 5 h – 6 h | 4.5 |
| 20 – 30 min | 9 | 6 h – 7 h 30 min | 4 |
| 30 – 45 min | 8.5 | 7 h 30 min – 9 h | 3.5 |
| 45 min – 1 h | 8 | 9 h – 11 h | 3 |
| 1 h – 1 h 30 min | 7.5 | 11 h – 13 h | 2.5 |
| 1 h 30 min – 2 h | 7 | 13 h – 16 h | 2 |
| 2 h – 2 h 30 min | 6.5 | 16 h – 20 h | 1.5 |
| 2 h 30 min – 3 h | 6 | 20 h – solution reveal | 1 |
| 3 h – 4 h | 5.5 | Wrong answer | 0 |

### Podium bonus

The first five correct first-attempt answers to a puzzle get a bonus on top of
their solve points, so a puzzle is worth at most 15.

| Correct answer | Bonus |
|---|---|
| 1st | +5 |
| 2nd | +3 |
| 3rd | +2 |
| 4th | +1 |
| 5th | +1 |

### Streak bonus

A streak is the number of puzzles solved in a row. A wrong or missed answer
resets it; holidays and days with no puzzle don't. Each milestone's bonus is
added once, on the day it's reached, and counts toward that month's points.
Bonuses already earned are kept when the streak breaks, and a new streak can
earn them all again.

| Streak reaches | Bonus that day | Total from the streak |
|---|---|---|
| 3 | +3 | 3 |
| 7 | +2 | 5 |
| 14 | +5 | 10 |
| 30 | +15 | 25 |
| 50 | +10 | 35 |
| 100 | +25 | 60 |
| 150 | +20 | 80 |
| 200 | +15 | 95 |
| 250 | +15 | 110 |
| 300 | +10 | 120 |
| 365 | +10 | 130 |

For example, solving 25 minutes after posting as the 2nd correct answer, on
your 7th solve in a row, earns 9 + 3 + 2 = 14 points.

Ties on points go to more correct answers, then the faster average solve
time.

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
