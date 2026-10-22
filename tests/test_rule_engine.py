from bot.engines.rule import find_match, rule_reply
from bot.knowledge import DEFAULT_MESSAGES, FaqEntry, Knowledge, MenuOption, Product


def test_menu_number_lists_products_of_its_category(knowledge):
    reply = rule_reply(knowledge, "1", is_new_conversation=False)
    assert "- Caja Prueba: Caja de prueba." in reply.text
    assert "Llavero" not in reply.text
    assert reply.text.endswith("escribe 3.")


def test_handoff_option_requests_a_person(knowledge):
    reply = rule_reply(knowledge, " 3 ", is_new_conversation=False)
    assert reply.handoff
    assert "Hablar con una persona" in reply.summary


def test_keyword_jumps_to_faq_answer(knowledge):
    reply = rule_reply(knowledge, "¿Hacen ENVÍOS a Limón?", is_new_conversation=False)
    assert reply.text == "Respuesta de prueba sobre envíos."


def test_product_name_shows_product_details(knowledge):
    reply = rule_reply(knowledge, "info del llavero prueba", is_new_conversation=False)
    assert "*Llavero Prueba*" in reply.text
    assert DEFAULT_MESSAGES["sin_precio"][0] in reply.text


def test_handoff_keyword_inside_sentence(knowledge):
    reply = rule_reply(knowledge, "quiero cotizar algo", is_new_conversation=False)
    assert reply.handoff


def test_longest_keyword_wins():
    knowledge = Knowledge(
        menu=(MenuOption(number="1", label="Cajas", action="responder", answer="general", keywords=("caja",)),),
        faq=(FaqEntry(question="q", answer="especifica", keywords=("caja musical",)),),
    )
    assert find_match(knowledge, "una caja musical").answer == "especifica"


def test_find_match_returns_none_without_keywords(knowledge):
    assert find_match(knowledge, "el clima de hoy") is None


def test_greeting_shows_welcome_and_menu(knowledge):
    reply = rule_reply(knowledge, "Hola!", is_new_conversation=False)
    assert reply.text.startswith(DEFAULT_MESSAGES["bienvenida"][0])
    assert "3. Hablar con una persona" in reply.text


def test_catalog_request_shows_menu(knowledge):
    reply = rule_reply(knowledge, "Quiero ver el CATÁLOGO", is_new_conversation=False)
    assert reply.text.startswith(DEFAULT_MESSAGES["menu_intro"][0])
    assert "1. Cajas musicales" in reply.text


def test_specific_product_wins_over_catalog_request(knowledge):
    reply = rule_reply(knowledge, "catálogo del llavero prueba", is_new_conversation=False)
    assert "*Llavero Prueba*" in reply.text


def test_catalog_request_without_menu_goes_to_handoff():
    knowledge = Knowledge(loaded=True)
    assert rule_reply(knowledge, "qué venden", is_new_conversation=False).handoff


def test_unknown_message_in_new_conversation_shows_welcome(knowledge):
    reply = rule_reply(knowledge, "qwerty", is_new_conversation=True)
    assert reply.text.startswith(DEFAULT_MESSAGES["bienvenida"][0])


def test_unknown_message_later_says_it_does_not_know_and_shows_menu(knowledge):
    reply = rule_reply(knowledge, "qwerty", is_new_conversation=False)
    assert reply.text.startswith(DEFAULT_MESSAGES["no_entiendo"][0])
    assert "1. Cajas musicales" in reply.text


def test_responder_option_sends_its_answer():
    knowledge = Knowledge(menu=(MenuOption(number="4", label="Envíos", action="responder", answer="Texto envío"),))
    assert rule_reply(knowledge, "4", is_new_conversation=False).text == "Texto envío"


def test_empty_category_shows_no_products_message():
    knowledge = Knowledge(
        menu=(MenuOption(number="1", label="Cajas", action="productos", category="Cajas"),),
        products=(Product(name="Otro", category="Llaveros"),),
    )
    reply = rule_reply(knowledge, "1", is_new_conversation=False)
    assert reply.text == DEFAULT_MESSAGES["sin_productos"][0]


def test_unloaded_knowledge_hands_off():
    reply = rule_reply(Knowledge.empty(), "hola", is_new_conversation=True)
    assert reply.handoff


def test_no_menu_and_no_match_hands_off():
    reply = rule_reply(Knowledge(), "algo raro", is_new_conversation=False)
    assert reply.handoff
    assert "algo raro" in reply.summary


def test_handoff_summary_truncates_long_messages(knowledge):
    reply = rule_reply(knowledge, "persona " + "x" * 500, is_new_conversation=False)
    assert reply.handoff
    assert len(reply.summary) < 400
