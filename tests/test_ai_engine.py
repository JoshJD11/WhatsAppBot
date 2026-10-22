import asyncio
from types import SimpleNamespace

import pytest

from bot.engines.ai import AIEngine, GeminiProvider, build_system_prompt, parse_answer
from bot.engines.base import EngineUnavailable
from bot.knowledge import DEFAULT_MESSAGES, Knowledge
from bot.state import Turn

from .conftest import FakeProvider, ai_json


def _run(coro):
    return asyncio.run(coro)


def test_answer_action_returns_reply_text(knowledge):
    engine = AIEngine(FakeProvider(ai_json("answer", "Tenemos la Caja Prueba.")))
    reply = _run(engine.reply(knowledge, [], "¿Qué cajas tienen?"))
    assert reply.text == "Tenemos la Caja Prueba."
    assert not reply.handoff


def test_handoff_action_returns_summary(knowledge):
    engine = AIEngine(FakeProvider(ai_json("handoff", "", "Quiere cotizar una caja.")))
    reply = _run(engine.reply(knowledge, [], "Quiero cotizar"))
    assert reply.handoff
    assert reply.summary == "Quiere cotizar una caja."


def test_handoff_without_summary_uses_customer_message(knowledge):
    engine = AIEngine(FakeProvider(ai_json("handoff")))
    reply = _run(engine.reply(knowledge, [], "Necesito ayuda"))
    assert "Necesito ayuda" in reply.summary


def test_off_topic_uses_excel_refusal_not_model_text(knowledge):
    engine = AIEngine(FakeProvider(ai_json("off_topic", "La capital de Francia es París.")))
    reply = _run(engine.reply(knowledge, [], "¿Capital de Francia?"))
    assert reply.text == DEFAULT_MESSAGES["fuera_de_tema"][0]


@pytest.mark.parametrize(
    "response",
    [RuntimeError("429 quota exhausted"), TimeoutError("slow"), "not json", ai_json("answer", "   ")],
)
def test_failures_raise_engine_unavailable(knowledge, response):
    engine = AIEngine(FakeProvider(response))
    with pytest.raises(EngineUnavailable):
        _run(engine.reply(knowledge, [], "hola"))


def test_without_provider_raises_engine_unavailable(knowledge):
    with pytest.raises(EngineUnavailable):
        _run(AIEngine(None).reply(knowledge, [], "hola"))


def test_unloaded_knowledge_raises_engine_unavailable():
    engine = AIEngine(FakeProvider(ai_json("answer", "x")))
    with pytest.raises(EngineUnavailable):
        _run(engine.reply(Knowledge.empty(), [], "hola"))


def test_provider_receives_prompt_history_and_truncated_message(knowledge):
    provider = FakeProvider(ai_json("answer", "ok"))
    history = [Turn("customer", "hola"), Turn("bot", "¡Hola!")]
    _run(AIEngine(provider).reply(knowledge, history, "x" * 5000))
    call = provider.calls[0]
    assert "Caja Prueba" in call["system"]
    assert call["history"] == history
    assert len(call["message"]) == 1000
    assert set(call["schema"]["properties"]) == {"action", "reply", "summary"}


def test_system_prompt_contains_rules_and_business_data(knowledge):
    prompt = build_system_prompt(knowledge)
    assert "Never invent" in prompt
    assert "Never send the whole product list" in prompt
    assert "Respuesta de prueba sobre envíos." in prompt
    assert "{knowledge}" not in prompt


def test_parse_answer_rejects_unknown_action():
    with pytest.raises(EngineUnavailable):
        parse_answer(ai_json("change_mode", "ok"))


def test_gemini_provider_builds_interaction_request(monkeypatch):
    captured = {}

    class FakeInteractions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(output_text='{"action":"answer","reply":"hola","summary":""}', status="completed")

    class FakeClient:
        def __init__(self, api_key):
            captured["api_key"] = api_key
            self.interactions = FakeInteractions()

    monkeypatch.setattr("google.genai.Client", FakeClient)
    provider = GeminiProvider("key", "model-x", "low", 12.0)
    result = provider.generate("system", [Turn("customer", "hola"), Turn("bot", "¡Hola!")], "precio?", {"type": "object"})

    assert result.startswith('{"action"')
    assert captured["api_key"] == "key"
    assert captured["model"] == "model-x"
    assert captured["store"] is False
    assert captured["timeout"] == 12.0
    assert captured["system_instruction"] == "system"
    assert [step["type"] for step in captured["input"]] == ["user_input", "model_output", "user_input"]
    assert captured["input"][-1]["content"][0]["text"] == "precio?"
    assert captured["response_format"]["mime_type"] == "application/json"
    assert captured["generation_config"]["thinking_level"] == "low"


def test_gemini_provider_raises_when_no_text(monkeypatch):
    class FakeClient:
        def __init__(self, api_key):
            self.interactions = SimpleNamespace(
                create=lambda **kwargs: SimpleNamespace(output_text=None, status="failed")
            )

    monkeypatch.setattr("google.genai.Client", FakeClient)
    with pytest.raises(RuntimeError, match="failed"):
        GeminiProvider("key", "m", "low", 5).generate("s", [], "hola", {})

