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

- **Scoring.** Points for solving fast, a podium bonus for the first five
  correct answers, and a bonus for solving puzzles in a row. See
  [Scoring](#scoring).
- **Leaderboard.** Ranks players by points and tracks streaks, calling out
  milestones. Posted to Slack and viewable on the web.
- **Monthly standings.** Points reset each calendar month. See
  [Monthly standings](#monthly-standings).
- **Houses.** Players can be grouped into teams that compete on a house
  leaderboard.
- **Difficulty mix.** Each puzzle's Lichess difficulty (easiest to hardest)
  is picked at random, weighted towards the easier ones by default. The
  difficulty and puzzle rating are shown on the Slack post.

The leaderboard, houses and difficulty web pages are linked from the home
page and ask for the admin secret.

### Monthly standings

- A puzzle counts toward the month it was posted in.
- On the 1st, the leaderboard posts the final standings of the month just
  ended, then a separate all-time leaderboard (every finished month added
  up). If that run is missed, the next one catches up.
- Every finished month is stored, and the web leaderboard lets you browse
  past months and the all-time standings.
- Streaks carry across months.

## Scoring

A puzzle's points are **solve points + podium bonus**. Streak bonuses are
added on top.

For example, solving 25 minutes after posting as the 2nd correct answer, on
your 7th solve in a row, earns 9 + 3 + 2 = **14 points**.

Ties on points go to more correct answers, then the faster average solve
time.

### Attempts

- Each puzzle allows two attempts.
- A wrong first attempt is DMed as wrong, without the solution.
- The solution is DMed after a correct answer or a second wrong one.
- A correct second attempt earns half the solve points and no podium bonus.

### Solve points

Counted from when the puzzle is posted. A wrong answer scores 0.

| Solved in under | Points |
|---|---|
| 10 min | 10 |
| 20 min | 9.5 |
| 30 min | 9 |
| 45 min | 8.5 |
| 1 h | 8 |
| 1 h 30 min | 7.5 |
| 2 h | 7 |
| 2 h 30 min | 6.5 |
| 3 h | 6 |
| 4 h | 5.5 |
| 5 h | 5 |
| 6 h | 4.5 |
| 7 h 30 min | 4 |
| 9 h | 3.5 |
| 11 h | 3 |
| 13 h | 2.5 |
| 16 h | 2 |
| 20 h | 1.5 |
| Any time before the solution is revealed | 1 |

### Podium bonus

The first five correct first-attempt answers get a bonus, so a puzzle is
worth at most 15.

| Correct answer | Bonus |
|---|---|
| 1st | +5 |
| 2nd | +3 |
| 3rd | +2 |
| 4th | +1 |
| 5th | +1 |

### Streak bonus

A streak is the number of puzzles solved in a row.

- A wrong or missed answer resets it. Days with no puzzle don't.
- Each milestone's bonus is added once, on the day it's reached, and counts
  toward that month's points.
- Bonuses already earned are kept when the streak breaks, and a new streak
  can earn them all again.
- The bonus per streak day grows with each milestone, so longer streaks earn
  proportionately more.

| Streak reaches | Bonus that day | Total from the streak |
|---|---|---|
| 3 | +1 | 1 |
| 7 | +2 | 3 |
| 14 | +4 | 7 |
| 30 | +11 | 18 |
| 50 | +17 | 35 |
| 75 | +22 | 57 |
| 100 | +23 | 80 |
| 125 | +26 | 106 |
| 150 | +29 | 135 |
| 175 | +31 | 166 |
| 200 | +34 | 200 |
| 225 | +36 | 236 |
| 250 | +39 | 275 |
| 275 | +41 | 316 |
| 300 | +44 | 360 |
| 325 | +44 | 404 |
| 365 | +71 | 475 |

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
