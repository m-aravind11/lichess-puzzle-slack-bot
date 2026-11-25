"""Accepts alternative lines that force mate against best defence; podium ranks and bonuses are never revisited."""

from datetime import datetime, timezone
from typing import NamedTuple

import chess

from scoring import RETRY_SCORE_FACTOR, compute_score


class Verdict(NamedTuple):
    accepted: bool
    reason: str


def _checks_first(board: chess.Board) -> list:
    return sorted(board.legal_moves, key=lambda m: not board.gives_check(m))


def mates_within(board: chess.Board, moves: int) -> bool:
    """Whether the side to move forces mate in at most `moves` of its own moves."""
    for move in _checks_first(board):
        if moves == 1 and not board.gives_check(move):
            break
        board.push(move)
        try:
            if board.is_checkmate():
                return True
            # Without the emptiness check a stalemate would count as mate.
            replies = list(board.legal_moves) if moves > 1 else []
            if replies and all(_mates_after(board, reply, moves - 1) for reply in replies):
                return True
        finally:
            board.pop()
    return False


def _mates_after(board: chess.Board, reply: chess.Move, moves: int) -> bool:
    board.push(reply)
    try:
        return mates_within(board, moves)
    finally:
        board.pop()


def best_defences(board: chess.Board, budget: int) -> list | None:
    """The defender's replies that hold out longest, or None if one escapes mate within `budget`."""
    longest, best = 0, []
    for reply in board.legal_moves:
        board.push(reply)
        try:
            holds = next((n for n in range(1, budget + 1) if mates_within(board, n)), None)
        finally:
            board.pop()
        if holds is None:
            return None
        if holds > longest:
            longest, best = holds, [reply]
        elif holds == longest:
            best.append(reply)
    return best


def _play_out(parse_move, board: chess.Board, tokens: list) -> tuple[int, list]:
    """Plays tokens against every best defence; returns (branches mated, failure reasons)."""
    try:
        move = parse_move(board, tokens[0])
    except ValueError:
        return 0, [f"{tokens[0]} is illegal"]
    san = board.san(move)
    board = board.copy(stack=False)
    board.push(move)

    if board.is_checkmate():
        return (1, []) if len(tokens) == 1 else (0, [f"{san} mates but more moves follow"])
    if board.is_game_over():
        return 0, [f"{san} ends the game without mate"]
    if len(tokens) == 1:
        return 0, [f"{san} doesn't mate"]

    replies = best_defences(board, len(tokens) - 1)
    if replies is None:
        return 0, [f"{san} lets the defence escape"]
    wins, failures = 0, []
    for reply in replies:
        reply_san = board.san(reply)
        child = board.copy(stack=False)
        child.push(reply)
        child_wins, child_failures = _play_out(parse_move, child, tokens[1:])
        wins += child_wins
        failures += [f"{san} {reply_san}: {reason}" for reason in child_failures]
    return wins, failures


def judge(lichess, puzzle: dict, tokens: list) -> Verdict:
    fen, solution = puzzle["fen"], puzzle["solution"]
    if lichess.check_answer(fen, solution, tokens):
        return Verdict(True, "matches the solution")

    move_count = len(solution[0::2])
    if not tokens:
        return Verdict(False, "no moves")
    if len(tokens) > move_count:
        return Verdict(False, f"{len(tokens)} moves for a {move_count}-move puzzle")

    # The recorded replies are just one of possibly several equally long defences,
    # and a typed line only has to beat one of them, as the stored solution does.
    board = lichess.get_board_from_fen(fen)
    wins, failures = _play_out(lichess._parse_submitted_move, board, tokens)
    if wins:
        return Verdict(True, f"mates against {wins} of {wins + len(failures)} best defences")
    return Verdict(False, "; ".join(failures))


def _time_score(puzzle: dict, submitted_at: str) -> float:
    if not puzzle.get("slack_ts"):
        return compute_score(True, None)
    posted = datetime.fromtimestamp(float(puzzle["slack_ts"]), tz=timezone.utc)
    submitted = datetime.fromisoformat(submitted_at)
    if submitted.tzinfo is None:
        submitted = submitted.replace(tzinfo=timezone.utc)
    return compute_score(True, (submitted - posted).total_seconds())


def plan_regrade(lichess, puzzle: dict, submissions: list) -> list:
    """Changes to apply, as dicts holding the submission and its new correct/score."""
    verdicts: dict = {}

    def verdict(row: dict) -> Verdict:
        tokens = tuple(row["moves"].split())
        if tokens not in verdicts:
            verdicts[tokens] = judge(lichess, puzzle, list(tokens))
        return verdicts[tokens]

    by_user: dict = {}
    for row in submissions:
        by_user.setdefault(row["user_id"], {})[row["attempt"]] = row

    changes = []
    for attempts in by_user.values():
        first, second = attempts.get(1), attempts.get(2)
        if first is None or first["correct"]:
            continue

        first_verdict = verdict(first)
        if first_verdict.accepted:
            changes.append(_change(first, correct=1, score=_time_score(puzzle, first["submitted_at"]), verdict=first_verdict))
            if second is not None and second["correct"]:
                # Leaderboard and streak queries expect at most one correct row per puzzle.
                changes.append(_change(second, correct=0, score=0, verdict=Verdict(False, "first attempt now correct")))
        elif second is not None and not second["correct"]:
            second_verdict = verdict(second)
            if second_verdict.accepted:
                score = _time_score(puzzle, second["submitted_at"]) * RETRY_SCORE_FACTOR
                changes.append(_change(second, correct=1, score=score, verdict=second_verdict))

    return [c for c in changes if (c["correct"], c["score"]) != (c["oldCorrect"], c["oldScore"])]


def _change(row: dict, correct: int, score: float, verdict: Verdict) -> dict:
    return {
        "submissionId": row["id"],
        "userId": row["user_id"],
        "userName": row["user_name"],
        "attempt": row["attempt"],
        "moves": row["moves"],
        "reason": verdict.reason,
        "oldCorrect": row["correct"],
        "oldScore": row["score"],
        "correct": correct,
        "score": score,
    }
