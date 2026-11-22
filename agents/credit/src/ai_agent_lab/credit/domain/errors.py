"""Stable application failure independent of MCP and framework implementations."""

from ai_agent_lab.credit.domain.models import ErrorCode


class EdgarAccessError(Exception):
    """Carry a safe code plus optional server-requested retry delay."""

    def __init__(self, code: ErrorCode, *, transient: bool = False, retry_after: float | None = None) -> None:
        """Initialize the category and retry metadata; never retain an upstream payload."""
        super().__init__(code.value)
        self.code = code
        self.transient = transient
        self.retry_after = retry_after


class EdgarNoMatchError(Exception):
    """An explicit COMPANY_NOT_FOUND server code, distinct from any transport error."""
