import chess

from daily_puzzle import LichessDailyPuzzle
from puzzle_stats import build_puzzle_stats
from slack_helpers import format_solution_reveal

lp = LichessDailyPuzzle()

POSTED = "1788264000"  # 2026-09-01T12:00:00Z
PUZZLE = {
    "puzzle_id": "p1",
    "posted_at": "2026-09-01T12:00:00+00:00",
    "fen": chess.STARTING_FEN,
    "solution": ["e4", "e5", "Nf3"],
    "slack_ts": POSTED,
}


def at(minutes, seconds=0):
    return f"2026-09-01T{12 + minutes // 60:02d}:{minutes % 60:02d}:{seconds:02d}+00:00"


def sub(user_id, moves, correct=False, podium_rank=None, submitted_at=at(60)):
    return {
        "user_id": user_id, "moves": moves, "correct": int(correct),
        "podium_rank": podium_rank, "submitted_at": submitted_at,
    }


def stats(*submissions, earlier_first_solves=(), broken_streaks=()):
    data = {
        "submissions": list(submissions),
        "earlier_first_solves": list(earlier_first_solves),
        "broken_streaks": list(broken_streaks),
    }
    return build_puzzle_stats(PUZZLE, data, lp.submitted_move_san)


def test_counts_players_not_attempts():
    result = stats(sub("U1", "d4"), sub("U1", "e4 Nf3", correct=True), sub("U2", "c4"), sub("U2", "a4"))
    assert (result["players"], result["solved"]) == (2, 1)


def test_tempting_move_is_normalised_and_counted_per_player():
    result = stats(sub("U1", "d4"), sub("U1", "d4"), sub("U2", "d2d4"), sub("U3", "c4"))
    assert result["tempting_move"] == {"san": "d4", "players": 2}


def test_illegal_moves_and_one_off_wrong_moves_are_not_tempting():
    assert stats(sub("U1", "Qh5"), sub("U2", "Qh5"), sub("U3", "d4"))["tempting_move"] is None


def test_so_close_counts_players_who_found_the_first_move_but_never_solved():
    result = stats(
        sub("U1", "e4 Nc3"),
        sub("U1", "e4 Bc4"),
        sub("U2", "E2E4 Nc3"),
        sub("U3", "e4 Nc3"),
        sub("U3", "e4 Nf3", correct=True),
        sub("U4", "e4"),
    )
    assert result["so_close"] == {"san": "e4", "players": 2}


def test_nobody_slipping_has_no_so_close():
    assert stats(sub("U1", "d4"))["so_close"] is None


def test_podium_filled_time_is_the_last_spot():
    result = stats(*[sub(f"U{rank}", "e4 Nf3", True, rank, at(rank * 2, 30)) for rank in range(1, 6)])
    assert result["podium"]["filled_seconds"] == 630


def test_podium_partly_taken():
    result = stats(sub("U1", "e4 Nf3", True, 1), sub("U2", "e4 Nf3", True, 2), sub("U3", "e4 Nf3", True))
    assert result["podium"] == {"taken": 2, "spots": 5, "filled_seconds": None}


def test_no_first_try_solves_has_no_podium():
    assert stats(sub("U1", "d4"), sub("U1", "e4 Nf3", correct=True))["podium"] is None


def earlier(minutes):
    return {"slack_ts": "1788177600", "first_solved_at": f"2026-08-31T12:{minutes:02d}:00+00:00"}


def test_month_record_when_faster_than_every_earlier_first_solve():
    result = stats(
        sub("U1", "e4 Nf3", True, 1, at(0, 47)),
        sub("U2", "e4 Nf3", True, 2, at(3)),
        earlier_first_solves=[earlier(1), earlier(5)],
    )
    assert result["month_record"] == {"seconds": 47, "user_id": "U1"}


def test_no_month_record_when_an_earlier_puzzle_was_faster_or_equal():
    assert stats(sub("U1", "e4 Nf3", True, 1, at(1)), earlier_first_solves=[earlier(1)])["month_record"] is None


def test_first_puzzle_of_the_month_is_not_a_record():
    assert stats(sub("U1", "e4 Nf3", True, 1, at(0, 5)))["month_record"] is None


def test_solve_before_a_repost_is_ignored():
    early = sub("U1", "e4 Nf3", True, 1, "2026-09-01T11:00:00+00:00")
    assert stats(early, earlier_first_solves=[earlier(1)])["month_record"] is None


def test_broken_streaks_report_everyone_tied_for_the_longest():
    result = stats(broken_streaks=[
        {"user_id": "U3", "streak": 21}, {"user_id": "U5", "streak": 21}, {"user_id": "U1", "streak": 4},
    ])
    assert result["broken_streaks"] == {"count": 3, "longest": 21, "longest_user_ids": ["U3", "U5"]}


def broken_line(*streaks):
    text = format_solution_reveal(PUZZLE, stats(broken_streaks=[{"user_id": u, "streak": n} for u, n in streaks]))
    return text.split("\n")[-2]


def test_broken_streak_wording():
    assert broken_line(("U1", 21)) == ":broken_heart: Ended <@U1>'s 21-day streak."
    assert broken_line(("U1", 21), ("U2", 21)) == ":broken_heart: Ended <@U1>'s and <@U2>'s 21-day streaks."
    assert broken_line(("U1", 21), ("U2", 4)) == ":broken_heart: Ended 2 streaks, including <@U1>'s 21-day run."
    assert broken_line(("U1", 21), ("U2", 21), ("U3", 21), ("U4", 4)) == (
        ":broken_heart: Ended 4 streaks, including <@U1>'s, <@U2>'s and <@U3>'s 21-day runs."
    )


def test_reveal_shows_every_stat_between_solution_and_ps():
    text = format_solution_reveal(PUZZLE, stats(
        *[sub(f"U{rank}", "e4 Nf3", True, rank, at(rank * 2, 30)) for rank in range(1, 6)],
        sub("U6", "d4"), sub("U7", "d4"), sub("U8", "e4 Nc3"),
        earlier_first_solves=[earlier(5)],
        broken_streaks=[{"user_id": "U9", "streak": 21}, {"user_id": "U8", "streak": 4}],
    ))
    assert text.endswith(
        "You: `Nf3`\n"
        "*How everyone did:* 5 of 8 solved it (62%).\n"
        ":zap: <@U1>'s 2m 30s is the fastest solve this month.\n"
        ":checkered_flag: Podium filled in 10m 30s.\n"
        ":dart: Most tempting wrong move: `d4` (2 players).\n"
        ":sweat_smile: So close: 1 player found `e4` but slipped on the follow-up.\n"
        ":broken_heart: Ended 2 streaks, including <@U9>'s 21-day run.\n"
        "_PS: this puzzle is no longer accepting answers._"
    )


def test_reveal_partial_podium_and_single_broken_streak():
    text = format_solution_reveal(PUZZLE, stats(
        sub("U1", "e4 Nf3", True, 1), sub("U2", "d4"),
        broken_streaks=[{"user_id": "U2", "streak": 5}],
    ))
    assert ":checkered_flag: Only 1 of 5 podium spots taken.\n:broken_heart: Ended <@U2>'s 5-day streak.\n_PS:" in text


def test_reveal_with_no_submissions_still_mourns_broken_streaks():
    text = format_solution_reveal(PUZZLE, stats(broken_streaks=[{"user_id": "U1", "streak": 3}]))
    assert "How everyone did" not in text
    assert ":broken_heart: Ended <@U1>'s 3-day streak." in text


def test_reveal_with_nothing_to_say_has_no_stats():
    assert format_solution_reveal(PUZZLE, stats()).endswith("You: `Nf3`\n_PS: this puzzle is no longer accepting answers._")
