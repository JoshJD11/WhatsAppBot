"""Admin commands. Handled in code before any reply engine, so the AI cannot trigger them."""

from .config import BotMode

# The command must be the whole message, case insensitive. "menú" with an accent is
# accepted too because phone keyboards often add it.
COMMANDS: dict[str, BotMode] = {
    "#bosca ia": "ai",
    "#bosca menu": "rule",
    "#bosca menú": "rule",
}
CONFIRMATIONS: dict[BotMode, str] = {
    "ai": "Modo IA activado.",
    "rule": "Modo menú activado.",
}


def parse_command(text: str) -> BotMode | None:
    """Return the mode a command switches to, or None if the text is not a command."""
    return COMMANDS.get(" ".join(text.lower().split()))
