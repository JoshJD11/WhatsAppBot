"""Types shared by the reply engines."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Reply:
    """What an engine decided to do with a customer message.

    When `handoff` is True the caller ignores `text`, runs the handoff flow, and
    uses `summary` in the owner notification and the requests sheet.
    """

    text: str = ""
    handoff: bool = False
    summary: str = ""


class EngineUnavailable(Exception):
    """The AI engine could not answer; the caller falls back to rule mode."""
