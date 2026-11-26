import csv
from pathlib import Path

import chess
import pytest

from alternative_mates import _mates_after, forces_mate, mates_within
from daily_puzzle import LichessDailyPuzzle

lp = LichessDailyPuzzle()

# Any bishop move uncovers check from b8; Black can only block with ...Rc8, then Rxc8#.
FEN = "1R3B1k/K5pp/2r5/8/8/8/8/8 w - - 0 1"
SOLUTION = ["Be7+", "Rc8", "Rxc8#"]

# Stored line is Qxg6+ Kh8 Rh1+ Qh4 Rxh4#, but ...Qh7 blocks the check just as well.
BLOCK_FEN = "r4rk1/p3q3/1p2p1p1/3n4/3p4/2P3Q1/PP2NP2/2K3R1 w - - 0 23"
BLOCK_SOLUTION = ["Qxg6+", "Kh8", "Rh1+", "Qh4", "Rxh4#"]


@pytest.mark.parametrize("moves", [["Be7", "Rxc8"], ["Bd6+", "Rxc8#"], ["Ba3", "Rxc8"], ["bb4", "rxc8"]])
def test_a_different_first_move_that_forces_mate_is_accepted(moves):
    assert lp.check_answer(FEN, SOLUTION, moves)


@pytest.mark.parametrize("moves", [
    ["Qh5", "Rxc8"],
    ["Bxg7+", "Rxc8"],
    ["Rb7", "Rxc8"],
    ["Bd6+"],
    ["Bd6+", "Rxc8", "Kb7"],
    ["Bd6+", "Rb7"],
    [],
])
def test_lines_that_do_not_force_mate_are_rejected(moves):
    assert not lp.check_answer(FEN, SOLUTION, moves)


@pytest.mark.parametrize("moves", [["Qxg6+", "Rh1+", "Rxh7#"], ["qg6", "rh1", "qh7"], ["Qg6", "Rh1", "Rh4"]])
def test_line_against_an_equally_good_reply_to_the_recorded_one_is_accepted(moves):
    assert lp.check_answer(BLOCK_FEN, BLOCK_SOLUTION, moves)


@pytest.mark.parametrize("moves", [["Qxg6+", "Qxg7#"], ["Qg6", "Qg7"], ["Qxg6+", "Qxg7", "Rh1#"], ["Qg6", "Rh1", "Rg7"]])
def test_line_that_needs_a_weaker_reply_is_rejected(moves):
    assert not lp.check_answer(BLOCK_FEN, BLOCK_SOLUTION, moves)


@pytest.mark.parametrize("moves, expected", [
    (["Qxg6+", "Rh1+", "Rxh4#"], True),
    (["qg6", "rh1", "rh4"], True),
    (["Qxg6+", "Rh1+", "Rxh7#"], False),
    (["Qxg6+", "Rh1+"], False),
    (["Qxg6+", "Rh1+", "Rxh4#", "Kb1"], False),
    (["Qh5", "Rh1", "Rxh4"], False),
])
def test_matches_solution_is_only_the_exact_lichess_line(moves, expected):
    assert lp.matches_solution(BLOCK_FEN, BLOCK_SOLUTION, moves) is expected


def _real_puzzles() -> list:
    # Lichess publishes only puzzles whose winning first move is unique, checked with Stockfish.
    with open(Path(__file__).parent / "data" / "mate_puzzles.csv") as f:
        return [
            pytest.param(r["fen"], r["solution"].split(), int(r["theme"][-1]), id=r["puzzle_id"])
            for r in csv.DictReader(f)
        ]


REAL_PUZZLES = _real_puzzles()


@pytest.mark.parametrize("fen, solution, moves", REAL_PUZZLES)
def test_solver_finds_mate_in_exactly_the_puzzle_length(fen, solution, moves):
    board = chess.Board(fen)
    assert mates_within(board, moves)
    assert not mates_within(board, moves - 1)


@pytest.mark.parametrize("fen, solution, moves", REAL_PUZZLES)
def test_stored_line_forces_mate_without_the_exact_match(fen, solution, moves):
    assert forces_mate(lp._parse_submitted_move, chess.Board(fen), solution[0::2])


@pytest.mark.parametrize("fen, solution, moves", REAL_PUZZLES)
def test_stored_line_missing_its_last_move_is_rejected(fen, solution, moves):
    assert not lp.check_answer(fen, solution, solution[0::2][:-1])


@pytest.mark.parametrize("fen, solution, moves", REAL_PUZZLES)
def test_no_other_first_move_forces_mate(fen, solution, moves):
    board = chess.Board(fen)
    expected = board.parse_san(solution[0])
    for move in board.legal_moves:
        if move == expected:
            continue
        board.push(move)
        replies = list(board.legal_moves)
        forced = board.is_checkmate() or (replies and all(_mates_after(board, r, moves - 1) for r in replies))
        board.pop()
        assert not forced, board.san(move)
