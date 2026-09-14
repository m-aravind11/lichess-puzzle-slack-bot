# Ideas backlog

Not scheduled - parked here so they don't get lost.

## Weekly / monthly leaderboard
Currently `db.get_leaderboard()` is all-time only (no date window). Add a
`since` param, filter `submissions.submitted_at >= ?` in `LEADERBOARD_TOTALS`
/ `LEADERBOARD_SOLVE_TIMES`, and a cron variant (or a flag on the existing
`/cron/send-leaderboard`) to post weekly/monthly resets.

## Streaks
Consecutive-day solve count per user, persisted (derived from `submissions`
grouped by user + date, or a dedicated counter updated on each correct
submission). Show alongside leaderboard.

## Puzzle difficulty / theme
Lichess's daily-puzzle API already returns a puzzle rating and themes (fork,
endgame, etc.) - currently discarded in `daily_puzzle.py`. Store and show it
on the Slack post; could also weight scoring by difficulty.

## Personal stats lookup
Slash command or DM ("my stats") giving a user their own rank, streak, avg
solve time, without waiting for the periodic leaderboard post.

## Rank-change indicator
Show up/down arrows on the leaderboard vs. the previous post. Needs
snapshotting the prior ranking somewhere (e.g. a `leaderboard_snapshots`
table) to diff against.

## Archive / past puzzles
Let people solve older puzzles on demand (browse by date), not just today's.

## Reminder DM
Opt-in nudge a few hours before the puzzle window closes, sent to anyone who
hasn't submitted yet.

## Achievements
Badges like "10-correct streak" or "fastest solve this week" - depends on
streaks and/or weekly leaderboard existing first.
