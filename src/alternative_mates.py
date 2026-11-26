import chess


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


def forces_mate(parse_move, board: chess.Board, tokens: list) -> bool:
    """Whether the line mates against one of the defender's best replies at every turn."""
    try:
        move = parse_move(board, tokens[0])
    except ValueError:
        return False
    board = board.copy(stack=False)
    board.push(move)

    if board.is_checkmate():
        return len(tokens) == 1
    if len(tokens) == 1 or board.is_game_over():
        return False

    replies = best_defences(board, len(tokens) - 1)
    if replies is None:
        return False
    # Equally long defences tie often and a typed line can follow only one,
    # just as the stored solution follows its one recorded reply.
    for reply in replies:
        child = board.copy(stack=False)
        child.push(reply)
        if forces_mate(parse_move, child, tokens[1:]):
            return True
    return False
