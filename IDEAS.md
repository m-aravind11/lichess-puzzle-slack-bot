# Ideas backlog

Not scheduled - parked here so they don't get lost.

## Perfect-month bonus
+25 once, for a correct answer to every active puzzle posted that month. A
month with zero puzzles awards nothing (no vacuous truth). It can only be
awarded once the month's last puzzle closes, i.e. on the first leaderboard
run of the new month, before that month is stored in `monthly_scores`.

Already shipped instead of the earlier per-puzzle redesign: half-point solve
slabs, the podium bonus and streak milestone bonuses (README's Scoring
section).

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
Badges like "fastest solve this week" - depends on the weekly leaderboard
existing first. Streak milestones are already announced under the leaderboard.

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
