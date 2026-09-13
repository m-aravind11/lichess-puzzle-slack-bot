import chess
import pytest

from daily_puzzle import LichessDailyPuzzle

lp = LichessDailyPuzzle()

START_FEN = chess.STARTING_FEN


def fen_after(*san_moves: str) -> str:
    board = chess.Board()
    for san in san_moves:
        board.push_san(san)
    return board.fen()


def test_exact_match():
    assert lp.check_answer(START_FEN, ["e4", "e5", "Nf3"], ["e4", "e5", "Nf3"])


def test_wrong_moves_return_false():
    assert not lp.check_answer(START_FEN, ["e4", "e5", "Nf3"], ["d4", "d5", "Nf3"])


@pytest.mark.parametrize("submitted", [
    ["e4", "e5", "nf3"],
    ["E4", "E5", "NF3"],
    ["e4", "e5", "nF3"],
])
def test_case_insensitive(submitted):
    assert lp.check_answer(START_FEN, ["e4", "e5", "Nf3"], submitted)


def test_missing_check_and_mate_suffixes():
    # Fool's mate: 1. f3 e5 2. g4 Qh4# - solution as produced by convert_uci_solution_to_san
    # includes the '#', submitted answers shouldn't be required to include it.
    solution = ["f3", "e5", "g4", "Qh4#"]
    assert lp.check_answer(START_FEN, solution, ["f3", "e5", "g4", "Qh4"])
    assert lp.check_answer(START_FEN, solution, ["f3", "e5", "g4", "qh4#"])
    assert lp.check_answer(START_FEN, solution, ["f3", "e5", "g4", "qh4"])


def test_missing_capture_x():
    fen = fen_after("e4", "d5")
    assert lp.check_answer(fen, ["exd5"], ["ed5"])


def test_asterisk_as_capture_marker():
    fen = fen_after("e4", "d5")
    assert lp.check_answer(fen, ["exd5"], ["e*d5"])


def test_capture_with_x_and_lowercase_piece():
    # A piece capture, not just a pawn capture: after 1. e4 e5 2. Nf3 Nc6 3. Nxe5
    fen = fen_after("e4", "e5", "Nf3", "Nc6")
    assert lp.check_answer(fen, ["Nxe5"], ["nxe5"])
    assert lp.check_answer(fen, ["Nxe5"], ["ne5"])


@pytest.mark.parametrize("submitted", ["o-o", "0-0", "O-O"])
def test_castling_case_and_digit_variants(submitted):
    fen = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
    assert lp.check_answer(fen, ["O-O"], [submitted])


@pytest.mark.parametrize("submitted", ["o-o-o", "0-0-0", "O-O-O"])
def test_queenside_castling_case_and_digit_variants(submitted):
    fen = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
    assert lp.check_answer(fen, ["O-O-O"], [submitted])


def test_illegal_move_returns_false_not_error():
    assert not lp.check_answer(START_FEN, ["e4"], ["Ka1"])


def test_garbage_token_returns_false_not_error():
    assert not lp.check_answer(START_FEN, ["e4"], ["Zz9"])


def test_wrong_move_count_returns_false():
    assert not lp.check_answer(START_FEN, ["e4", "e5"], ["e4"])
