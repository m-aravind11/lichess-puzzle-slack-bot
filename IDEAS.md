# Ideas backlog

Not scheduled - parked here so they don't get lost.

## Weekly / monthly leaderboard
Currently `db.get_leaderboard()` is all-time only (no date window). Add a
`since` param, filter `submissions.submitted_at >= ?` in `LEADERBOARD_TOTALS`
/ `LEADERBOARD_SOLVE_TIMES`, and a cron variant (or a flag on the existing
`/admin/leaderboard:send`) to post weekly/monthly resets.

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

## Interactive board (lichess-style)
Slack Block Kit can't render a drag/drop chessboard, so the modal's plain
text input is the ceiling for in-Slack solving. A closer-to-lichess.org
experience would need a separate hosted mini web app (chessground/chess.js)
opened via a link button instead of the modal: it auto-plays the opponent's
moves like lichess's own trainer, lets the user drag their own, then POSTs
the result back to a new bot endpoint which records it and posts to Slack.
Needs session linking between the Slack click and the web page (puzzle_id +
a short-lived token in the URL) and hosting for the static app + endpoint -
a real new service, not a modal tweak.
