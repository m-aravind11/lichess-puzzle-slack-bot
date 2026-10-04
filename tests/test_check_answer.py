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
    assert lp.check_answer(START_FEN, ["e4", "e5", "Nf3"], ["e4", "Nf3"])


def test_wrong_moves_return_false():
    assert not lp.check_answer(START_FEN, ["e4", "e5", "Nf3"], ["d4", "Nf3"])


@pytest.mark.parametrize("submitted", [
    ["e4", "nf3"],
    ["E4", "NF3"],
    ["e4", "nF3"],
])
def test_case_insensitive(submitted):
    assert lp.check_answer(START_FEN, ["e4", "e5", "Nf3"], submitted)


def test_missing_check_and_mate_suffixes():
    fen = fen_after("f3", "e5", "g4")
    solution = ["Qh4#"]
    assert lp.check_answer(fen, solution, ["Qh4"])
    assert lp.check_answer(fen, solution, ["qh4#"])
    assert lp.check_answer(fen, solution, ["qh4"])


def test_missing_capture_x():
    fen = fen_after("e4", "d5")
    assert lp.check_answer(fen, ["exd5"], ["ed5"])


def test_asterisk_as_capture_marker():
    fen = fen_after("e4", "d5")
    assert lp.check_answer(fen, ["exd5"], ["e*d5"])


def test_capture_with_x_and_lowercase_piece():
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


PAWN_ONLY_TAKES_C3_FEN = "4k3/8/8/8/8/2n5/1P6/4K3 w - - 0 1"
BISHOP_ONLY_TAKES_C3_FEN = "4k3/8/8/8/8/2n5/3B4/4K3 w - - 0 1"
PAWN_AND_BISHOP_TAKE_C3_FEN = "4k3/8/8/8/8/2n5/1P1B4/4K3 w - - 0 1"


@pytest.mark.parametrize("submitted", ["bxc3", "Bxc3"])
def test_b_file_pawn_capture_accepted_in_either_case_when_no_bishop_can(submitted):
    assert lp.check_answer(PAWN_ONLY_TAKES_C3_FEN, ["bxc3"], [submitted])


@pytest.mark.parametrize("submitted", ["bxc3", "Bxc3"])
def test_bishop_capture_accepted_in_either_case_when_no_pawn_can(submitted):
    assert lp.check_answer(BISHOP_ONLY_TAKES_C3_FEN, ["Bxc3"], [submitted])


def test_case_decides_between_pawn_and_bishop_when_both_can_capture():
    assert lp.check_answer(PAWN_AND_BISHOP_TAKE_C3_FEN, ["bxc3"], ["bxc3"])
    assert not lp.check_answer(PAWN_AND_BISHOP_TAKE_C3_FEN, ["bxc3"], ["Bxc3"])
    assert lp.check_answer(PAWN_AND_BISHOP_TAKE_C3_FEN, ["Bxc3"], ["Bxc3"])
    assert not lp.check_answer(PAWN_AND_BISHOP_TAKE_C3_FEN, ["Bxc3"], ["bxc3"])


@pytest.mark.parametrize("submitted", ["b2b4", "B2B4"])
def test_uci_b_file_pawn_move_accepted(submitted):
    assert lp.check_answer(START_FEN, ["b4"], [submitted])


def test_illegal_move_returns_false_not_error():
    assert not lp.check_answer(START_FEN, ["e4"], ["Ka1"])


def test_garbage_token_returns_false_not_error():
    assert not lp.check_answer(START_FEN, ["e4"], ["Zz9"])


def test_wrong_move_count_returns_false():
    assert not lp.check_answer(START_FEN, ["e4", "e5", "Nf3"], ["e4"])


@pytest.mark.parametrize("submitted", ["e2e4", "E2E4"])
def test_uci_style_move_accepted(submitted):
    assert lp.check_answer(START_FEN, ["e4", "e5", "Nf3"], [submitted, "Nf3"])


def test_uci_style_piece_move_accepted():
    fen = fen_after("e4", "e5")
    assert lp.check_answer(fen, ["Nf3"], ["g1f3"])


@pytest.mark.parametrize("submitted", ["e8=Q", "e8=q", "e7e8q", "e7e8Q", "e7e8=q"])
def test_promotion_accepts_uci_and_mixed_case(submitted):
    fen = "k7/4P3/8/8/8/8/8/4K3 w - - 0 1"
    assert lp.check_answer(fen, ["e8=Q"], [submitted])


def test_same_puzzle_accepts_both_san_and_uci_submissions():
    solution = ["e4", "e5", "Nf3"]
    assert lp.check_answer(START_FEN, solution, ["e4", "Nf3"])
    assert lp.check_answer(START_FEN, solution, ["e2e4", "g1f3"])


def test_same_puzzle_accepts_a_mix_of_san_and_uci_within_one_submission():
    solution = ["e4", "e5", "Nf3"]
    assert lp.check_answer(START_FEN, solution, ["e2e4", "Nf3"])
    assert lp.check_answer(START_FEN, solution, ["e4", "g1f3"])


def test_same_promotion_puzzle_accepts_both_san_and_uci_submissions():
    fen = "k7/4P3/8/8/8/8/8/4K3 w - - 0 1"
    solution = ["e8=Q"]
    assert lp.check_answer(fen, solution, ["e8=Q"])
    assert lp.check_answer(fen, solution, ["e7e8q"])


def test_extra_moves_return_false():
    assert not lp.check_answer(START_FEN, ["e4", "e5", "Nf3"], ["e4", "Nf3", "Bc4"])


# Back rank: Ra8# and Re8# both mate; Ra7 doesn't.
ALT_MATE_FEN = "6k1/5ppp/1p6/8/8/8/8/R3R1K1 w - - 0 1"


def test_alternate_mate_on_last_move_accepted():
    assert lp.check_answer(ALT_MATE_FEN, ["Ra8#"], ["Re8"])


def test_alternate_non_mating_move_rejected():
    assert not lp.check_answer(ALT_MATE_FEN, ["Ra8#"], ["Ra7"])


def test_shorter_mate_mid_line_accepted():
    solution = ["Ra7", "b5", "Re8#"]
    assert lp.check_answer(ALT_MATE_FEN, solution, ["Re8"])


def test_moves_after_alternate_mate_rejected():
    solution = ["Ra7", "b5", "Re8#"]
    assert not lp.check_answer(ALT_MATE_FEN, solution, ["Re8", "Ra8"])
