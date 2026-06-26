"""
writer.py — Out-of-Band Audit Writer + Durable Acknowledgment (ADR-007 §2.4, §2.5)

Responsibility: Write canonical audit events to the audit sink via a path
that is independent of the MCP lifecycle being observed (out-of-band,
non-recursive). Produce a FailureSignal when writing fails.

Bounds (ADR-007 §2.4, §2.5):
  - Does NOT use any MCP tool, MCP server, or MCP-like mechanism.
  - Does NOT re-trigger PreToolUse/PostToolUse lifecycle events.
  - On write failure: signals failure only; never implies dispatch was allowed.
  - Successful synchronous SQLite commit = application-level durable ack.
  - FailureSignal uses only closed failure_category enum values;
    no raw identity, no exception text, no free text.
"""

from dataclasses import dataclass

from ._constants import VALID_FAILURE_CATEGORIES


@dataclass(frozen=True)
class FailureSignal:
    """
    Out-of-band, non-recursive failure notification (ADR-007 §2.6).

    Contains only a closed failure_category enum value. No raw identity,
    no exception text, no URL, no token, no PII, no free text.

    This is NOT part of the 15-field audit event payload.
    It is NOT a human approval or capability validation substitute.
    Its display location is an open technical decision (ADR-007 §6 item 8).
    """
    failure_category: str

    def __post_init__(self) -> None:
        if self.failure_category not in VALID_FAILURE_CATEGORIES or self.failure_category is None:
            raise ValueError(
                f"FailureSignal.failure_category must be a non-None closed enum value; "
                f"got {self.failure_category!r}"
            )


class AuditWriter:
    """
    Out-of-band writer wrapping an audit sink.

    Accepts any object with a write_event(event: dict) -> bool method,
    enabling test doubles without subclassing.
    """

    def __init__(self, sink) -> None:
        self._sink = sink

    def write_with_ack(self, event: dict) -> bool:
        """
        Attempt to write event to the sink.

        Returns True if the sink's write_event() returned True (application-level
        durable acknowledgment per ADR-007 §2.5).
        Returns False on any failure; does not raise.
        Does NOT dispatch, does NOT trigger any MCP/audit lifecycle.
        """
        try:
            result = self._sink.write_event(event)
            return bool(result)
        except Exception:
            return False

    @staticmethod
    def make_failure_signal(failure_category: str) -> FailureSignal:
        """
        Create a FailureSignal with the given closed enum failure_category.

        The signal must not contain raw identity, exception text, or free text.
        """
        return FailureSignal(failure_category=failure_category)
