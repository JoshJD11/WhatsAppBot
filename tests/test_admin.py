import pytest

from bot.admin import parse_command


@pytest.mark.parametrize(
    "text,mode",
    [
        ("#bosca ia", "ai"),
        ("#BOSCA IA", "ai"),
        ("  #bosca   ia ", "ai"),
        ("#bosca menu", "rule"),
        ("#Bosca Menú", "rule"),
    ],
)
def test_parse_command_accepts_the_two_commands(text, mode):
    assert parse_command(text) == mode


@pytest.mark.parametrize("text", ["#bosca", "#bosca ia por favor", "bosca ia", "#bosca recargar", "hola", ""])
def test_parse_command_rejects_anything_else(text):
    assert parse_command(text) is None
