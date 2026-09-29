from slack_helpers import format_solution


def test_moves_are_labelled_you_and_opponent_in_turn():
    text = format_solution(["Bc2+", "Ka1", "Re1+", "Nb1", "Rxb1#"])
    assert "Correct answer: `Bc2+ Re1+ Rxb1#`" in text
    assert "You: `Bc2+`\nOpponent: `Ka1`\nYou: `Re1+`\nOpponent: `Nb1`\nYou: `Rxb1#`" in text



def test_one_move_puzzle_shows_only_the_answer():
    assert format_solution(["Qh4#"]) == "Correct answer: `Qh4#`"
