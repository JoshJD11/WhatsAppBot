import pytest

from bot.text import (
    WHATSAPP_MAX_LENGTH,
    contains_phrase,
    format_number_for_humans,
    mask_number,
    normalize,
    sanitize_outgoing,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("¿Cuánto CUESTA?", "cuanto cuesta"),
        ("  Envío   a Cartago!! ", "envio a cartago"),
        ("menú", "menu"),
        ("", ""),
    ],
)
def test_normalize(raw, expected):
    assert normalize(raw) == expected


def test_contains_phrase_matches_whole_words_only():
    assert contains_phrase("quiero una caja musical", "caja musical")
    assert not contains_phrase("cajas", "caja")
    assert not contains_phrase("hola", "")


def test_sanitize_outgoing_removes_emojis_and_double_hyphens():
    assert sanitize_outgoing("Hola 😊 amigo -- listo ---") == "Hola amigo - listo -"


def test_sanitize_outgoing_keeps_accents_and_colon_sign():
    assert sanitize_outgoing("Precio: ₡25.000, ¿algo más?") == "Precio: ₡25.000, ¿algo más?"


def test_sanitize_outgoing_truncates_long_text():
    result = sanitize_outgoing("a" * (WHATSAPP_MAX_LENGTH + 50))
    assert len(result) == WHATSAPP_MAX_LENGTH
    assert result.endswith("...")


def test_mask_number_hides_all_but_last_four_digits():
    assert mask_number("50671413393") == "*******3393"
    assert mask_number("123") == "***"


def test_format_number_for_humans():
    assert format_number_for_humans("50671413393") == "+506 7141 3393"
    assert format_number_for_humans("15551234567") == "+15551234567"
