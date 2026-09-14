# Ideas backlog

Not scheduled - parked here so they don't get lost.

## Weekly / monthly leaderboard
Currently `db.get_leaderboard()` is all-time only (no date window). Add a
`since` param, filter `submissions.submitted_at >= ?` in `LEADERBOARD_TOTALS`
/ `LEADERBOARD_SOLVE_TIMES`, and a cron variant (or a flag on the existing
`/cron/send-leaderboard`) to post weekly/monthly resets.
