from io import BytesIO

from bot.knowledge import DEFAULT_MESSAGES, parse_workbook
from bot.template import build_template
from bot.text import sanitize_outgoing
from scripts.create_excel_template import main


def _parse(workbook):
    buffer = BytesIO()
    workbook.save(buffer)
    return parse_workbook(buffer.getvalue())


def test_template_has_all_sheets():
    assert build_template().sheetnames == ["Instrucciones", "Productos", "Preguntas", "Menu", "Mensajes", "Solicitudes"]


def test_template_contains_no_business_data():
    knowledge = _parse(build_template())
    assert knowledge.products == ()
    assert knowledge.faq == ()


def test_template_menu_and_messages_parse_back():
    knowledge = _parse(build_template())
    assert [option.label for option in knowledge.menu] == ["Cajas musicales", "Otros productos", "Hablar con una persona"]
    assert knowledge.handoff_option().number == "3"
    assert set(knowledge.messages) == set(DEFAULT_MESSAGES)


def test_default_messages_follow_writing_rules():
    for text, _ in DEFAULT_MESSAGES.values():
        assert sanitize_outgoing(text) == text


def test_script_writes_template(tmp_path, capsys):
    output = tmp_path / "out" / "bot.xlsx"
    main(["create_excel_template", str(output)])
    assert output.exists()
    assert str(output) in capsys.readouterr().out
