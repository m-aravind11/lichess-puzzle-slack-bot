# Ideas backlog

Not scheduled - parked here so they don't get lost.

## Monthly scoring revamp (next up, after houses)
Agreed design - replaces the current time-decayed `scoring.compute_score` and
the all-time leaderboard. Fresh start: old points aren't carried over.

**Per puzzle**

- Correctness: correct = 10, wrong = 0, whenever it's submitted (up to the
  reveal, when the puzzle closes).
- Speed (correct answers): +5 under 5 min, +4 under 10, +3 under 20,
  +2 under 1h, +1 under 2h, 0 after. Measured from the puzzle's `slack_ts`;
  if that's missing, give the full +5 (same as today's full-credit fallback).
- Participation (wrong answers): +2 within 15 min, +1 otherwise.
- Streak bonus (correct answers only), by position in the streak:
  3rd-4th +1, 5th-6th +2, 7th-13th +3, 14th onward +5.
- Perfect month: +25 once, for a correct answer to every active puzzle posted
  that month. A month with zero puzzles awards nothing (no vacuous truth).

Sanity check: worst correct answer (10) is 5x the best wrong one (2); a
perfect 30-day month is ~587 pts (correctness ~51%).

**Months**

- A submission counts toward the month of its puzzle's `posted_at` (UTC), so
  the puzzle posted on the last day, answered on the 1st, counts for the old month.
- Leaderboard resets on the 1st. Tiebreak: more correct, then faster average
  solve time.
- The real streak (`LeaderboardQueries.STREAKS`) never resets - it keeps
  driving the leaderboard's streak column and `Streaks.MILESTONES` shout-outs.
  Only the bonus resets: it uses the streak counted within the current month,
  i.e. min(real streak, this month's run).
- Month close: final standings can only be posted after the month's last
  puzzle closes (perfect-month bonus depends on it) - i.e. the first
  leaderboard run of the new month, after the reveal. Post them, then
  snapshot into a `season_results` table (season 'YYYY-MM', user_id,
  user_name, house_id, points, rank, correct, attempted, best_streak;
  PK (season, user_id)), written idempotently (upsert) so a cron retry is safe.
  Old submissions stay untouched.

**Implementation notes**

- Compute points at read time from raw facts (`correct`, `submitted_at`,
  puzzle `slack_ts`/`posted_at`) in a pure function that walks each user's
  history in post order - streak bonuses depend on history, which changes when
  a puzzle is deactivated. The stored `submissions.score` becomes unused.
- The DM / thread reply compute the same breakdown for just that user, and
  show it: `Correct! +10 · +5 speed · +2 streak (5) = 17`.
- All tier numbers go in a `Scoring` class in `constants.py`.
- House board (see houses) switches from all-time sums to monthly sums.
  Players never change house; when someone leaves the company their mapping
  is soft-deleted and nothing else changes - their points still count toward
  their house (`LeaderboardQueries.HOUSE_MEMBERS` includes inactive rows).

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
