"""Exception hierarchy with exit codes."""


class BlunderButlerError(Exception):
    """Base exception for Blunder Butler."""

    exit_code: int = 5

    def __init__(self, message: str, exit_code: int | None = None):
        super().__init__(message)
        if exit_code is not None:
            self.exit_code = exit_code


class BadArgumentsError(BlunderButlerError):
    """Invalid CLI arguments or configuration."""

    exit_code = 2


class NetworkError(BlunderButlerError):
    """Network or API error (Chess.com, LLM endpoint)."""

    exit_code = 3


class EngineError(BlunderButlerError):
    """Stockfish engine error (not found, crashed, etc.)."""

    exit_code = 4


class UnexpectedError(BlunderButlerError):
    """Unexpected internal error."""

    exit_code = 5
