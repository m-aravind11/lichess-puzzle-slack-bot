# API Reference

Base URL (deployed): `https://lichess-puzzle-slack-bot.vercel.app`

## Authentication

Every route below except `GET /` and `POST /slack/interactions` requires:

```
Authorization: Bearer $CRON_SECRET
```

Missing or wrong token -> `401 Invalid Bearer Token`. This fails closed: if
`CRON_SECRET` isn't set in the environment, every route above rejects every
request (nothing can authenticate against a secret that doesn't exist).
`CRON_SECRET` must be set, in every environment including local dev.

`POST /slack/interactions` is authenticated differently: Slack signs each
request (see `src/slack_verify.py`), and a missing/stale/invalid signature
gets `401`. You won't call this endpoint directly; Slack calls it when a
user opens the answer modal or submits it.

---

## `GET /`

Serves the static `index.html`. No auth, no response body documented here.

---

## `GET /cron/send-puzzle`

Fetches a puzzle from Lichess and posts it to the configured Slack channel.
Meant to be hit once a day by a cron trigger, but safe to retrigger; see
`?force` and `?new_puzzle` below.

**Query params** (both optional, default `false`):

| Param        | Effect |
|--------------|--------|
| `force`      | If today's puzzle was already sent, **resend that same puzzle** (re-post to Slack, no new Lichess fetch, no new DB row). Use this for a retry after a network/Slack failure. If nothing active exists for today (e.g. it was deactivated), falls back to generating a fresh one. |
| `new_puzzle` | Always fetches a **different** puzzle from Lichess and posts+saves it, regardless of whether one was already sent today. Lichess has no stable "today's puzzle" id (unlike the official daily puzzle), so this is the explicit way to ask for a different one rather than a resend. |

With neither flag: if a puzzle was already sent today (active or
deactivated), this is a no-op. It protects against a duplicate cron trigger
spamming the channel with a second, different random puzzle.

**Responses**

- `200`: handled (sent, resent, skipped as already-sent, or generated fresh; check logs to tell which)
- `401`: bad/missing bearer token
- `500`: Lichess fetch failed after retries, or an unexpected error

```
curl "https://.../cron/send-puzzle" \
  -H "Authorization: Bearer $CRON_SECRET"

curl "https://.../cron/send-puzzle?force=true" \
  -H "Authorization: Bearer $CRON_SECRET"
```

---

## `GET /cron/send-leaderboard`

Posts current standings to the Slack channel. No-ops (still `200`) if the
leaderboard is empty (nobody has submitted anything yet).

**Responses**

- `200`: posted, or nothing to post
- `401`: bad/missing bearer token
- `500`: unexpected error

```
curl "https://.../cron/send-leaderboard" \
  -H "Authorization: Bearer $CRON_SECRET"
```

---

## `POST /admin/migrate`

Runs any pending schema migrations (`src/migrations.py`) against the DB. Not
run automatically on startup; trigger manually after deploying a schema
change.

**Responses**

- `200`: migrations applied (or already up to date)
- `401`: bad/missing bearer token
- `500`: migration failed

```
curl -X POST "https://.../admin/migrate" \
  -H "Authorization: Bearer $CRON_SECRET"
```

---

## `DELETE /submissions/{submission_id}`

Soft-deletes a submission by its numeric id (removes it from the leaderboard
and frees the user to resubmit for that puzzle).

**Path params**

- `submission_id` (int, required)

**Responses**

- `200`: deleted
- `401`: bad/missing bearer token
- `404`: no such submission (or already deleted)

```
curl -X DELETE "https://.../submissions/42" \
  -H "Authorization: Bearer $CRON_SECRET"
```

---

## `DELETE /puzzles/{puzzle_id}`

Soft-deletes a puzzle by its Lichess puzzle id. Refuses if the puzzle still
has active submissions against it (those feed the leaderboard, so deactivate
the submissions first, or use the reactivate endpoint if this was a mistake).

**Path params**

- `puzzle_id` (string, required)

**Responses**

- `200`: deactivated
- `401`: bad/missing bearer token
- `404`: no active puzzle with that id
- `409`: puzzle has active submissions, refused

```
curl -X DELETE "https://.../puzzles/abc123" \
  -H "Authorization: Bearer $CRON_SECRET"
```

---

## `POST /puzzles/{puzzle_id}/reactivate`

Reverses a soft-delete from `DELETE /puzzles/{puzzle_id}`.

**Path params**

- `puzzle_id` (string, required)

**Responses**

- `200`: reactivated
- `401`: bad/missing bearer token
- `404`: no puzzle with that id exists at all
- `409`: puzzle is already active

```
curl -X POST "https://.../puzzles/abc123/reactivate" \
  -H "Authorization: Bearer $CRON_SECRET"
```

---

## `POST /slack/interactions`

Slack's interactivity endpoint. Receives both the "Submit Answer" button
click (`block_actions`) and the answer modal submission (`view_submission`).
Body is `application/x-www-form-urlencoded` with a `payload` field containing
JSON, per Slack's interactivity payload format. Requests are authenticated by
Slack's request signature, not a bearer token.

**Responses**

- `200`: handled. For `view_submission`, the body may be a
  [modal response](https://api.slack.com/surfaces/modals/using#displaying_errors)
  with `response_action: "errors"` if the submitted moves were invalid,
  unparseable, for a stale puzzle, or a duplicate submission.
- `401`: missing/stale/invalid Slack signature
