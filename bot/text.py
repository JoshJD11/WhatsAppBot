"""Text helpers shared by both reply engines."""

import re
import unicodedata

WHATSAPP_MAX_LENGTH = 4096

# Emoji and pictograph ranges, plus the joiners and variation selectors that build them.
_EMOJI_RE = re.compile(
    "["
    "\U0001f000-\U0001faff"  # Mahjong, cards, emoticons, symbols, pictographs, transport
    "\U00002600-\U000027bf"  # Misc symbols and dingbats
    "\U00002b00-\U00002bff"  # Arrows and stars such as the white star
    "\U0001f1e6-\U0001f1ff"  # Regional indicators (flags)
    "‍︎️⃣"  # Zero width joiner, variation selectors, keycap
    "]",
    flags=re.UNICODE,
)
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_NON_WORD_RE = re.compile(r"[^a-z0-9]+")


def normalize(text: str) -> str:
    """Lowercase, strip accents and punctuation, and collapse spaces.

    Used to compare customer messages with keywords: "¿Cuánto CUESTA?" -> "cuanto cuesta".
    """
    decomposed = unicodedata.normalize("NFKD", text.lower())
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _NON_WORD_RE.sub(" ", without_accents).strip()


def contains_phrase(normalized_text: str, normalized_phrase: str) -> bool:
    """True when the phrase appears as whole words inside the text."""
    if not normalized_phrase:
        return False
    return f" {normalized_phrase} " in f" {normalized_text} "


def sanitize_outgoing(text: str) -> str:
    """Enforce the bot's writing rules on every message it sends.

    Removes emojis, replaces double hyphens, and keeps the text within WhatsApp's limit.
    """
    cleaned = _EMOJI_RE.sub("", text)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    cleaned = "\n".join(_MULTI_SPACE_RE.sub(" ", line).rstrip() for line in cleaned.splitlines())
    cleaned = cleaned.strip()
    if len(cleaned) > WHATSAPP_MAX_LENGTH:
        cleaned = cleaned[: WHATSAPP_MAX_LENGTH - 3].rstrip() + "..."
    return cleaned


def mask_number(number: str) -> str:
    """Hide most digits of a phone number for logs: 50671413393 -> *******3393."""
    if len(number) <= 4:
        return "*" * len(number)
    return "*" * (len(number) - 4) + number[-4:]


def format_number_for_humans(number: str) -> str:
    """Format a Costa Rican number as +506 7141 3393; other numbers get a leading plus."""
    if number.startswith("506") and len(number) == 11:
        return f"+506 {number[3:7]} {number[7:]}"
    return f"+{number}"
