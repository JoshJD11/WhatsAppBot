import asyncio
from datetime import timedelta

import pytest

from bot.state import SEEN_MESSAGES_LIMIT, BotState, StateFile, utc_now


@pytest.fixture
def state(clock) -> BotState:
    return BotState(
        mode="rule",
        handoff_pause=timedelta(minutes=60),
        rate_limit_max=2,
        rate_limit_window=timedelta(seconds=60),
        history_limit=4,
        history_idle=timedelta(minutes=30),
        clock=clock,
    )


def test_utc_now_is_timezone_aware():
    assert utc_now().tzinfo is not None


def test_is_duplicate_detects_repeated_ids(state):
    assert not state.is_duplicate("a")
    assert state.is_duplicate("a")


def test_is_duplicate_forgets_oldest_ids_past_the_limit(state):
    for index in range(SEEN_MESSAGES_LIMIT + 1):
        state.is_duplicate(str(index))
    assert not state.is_duplicate("0")


def test_pause_lasts_exactly_the_configured_time(state, clock):
    state.pause("c")
    clock.advance(minutes=59)
    assert state.is_paused("c")
    clock.advance(minutes=1)
    assert not state.is_paused("c")
    assert not state.is_paused("other")


def test_allow_reply_enforces_rate_limit_per_window(state, clock):
    assert state.allow_reply("c")
    assert state.allow_reply("c")
    assert not state.allow_reply("c")
    assert state.allow_reply("other")
    clock.advance(seconds=60)
    assert state.allow_reply("c")


def test_is_new_conversation_after_long_silence(state, clock):
    assert state.is_new_conversation("c")
    clock.advance(hours=1)
    assert not state.is_new_conversation("c")
    clock.advance(hours=12)
    assert state.is_new_conversation("c")


def test_history_keeps_last_turns_and_expires_when_idle(state, clock):
    for index in range(6):
        state.remember("c", "customer", str(index))
    assert [turn.text for turn in state.history("c")] == ["2", "3", "4", "5"]
    clock.advance(minutes=30)
    assert state.history("c") == []


def test_history_disabled_when_limit_is_zero(clock):
    state = BotState("ai", timedelta(minutes=1), 1, timedelta(seconds=1), 0, timedelta(minutes=1), clock)
    state.remember("c", "customer", "hola")
    assert state.history("c") == []


def test_forget_clears_history(state):
    state.remember("c", "bot", "hola")
    state.forget("c")
    assert state.history("c") == []


def test_owner_window_opens_with_a_message_and_closes_before_24_hours(state, clock):
    assert not state.owner_window_open()
    state.record_owner_message()
    clock.advance(hours=23, minutes=54)
    assert state.owner_window_open()
    clock.advance(minutes=1)
    assert not state.owner_window_open()


def test_customer_lock_is_reused_per_customer(state):
    assert state.customer_lock("c") is state.customer_lock("c")
    assert isinstance(state.customer_lock("c"), asyncio.Lock)


def test_prune_drops_expired_entries(state, clock):
    state.pause("c")
    state.allow_reply("c")
    state.is_new_conversation("c")
    state.remember("c", "customer", "hola")
    state.customer_lock("c")
    clock.advance(hours=13)
    state.prune()
    assert state._paused_until == {}
    assert state._recent_replies == {}
    assert state._last_activity == {}
    assert state._history == {}
    assert state._customer_locks == {}


def test_snapshot_round_trip_keeps_mode_owner_window_and_active_pauses(state, clock):
    state.mode = "ai"
    state.record_owner_message()
    state.pause("active")
    snapshot = state.to_snapshot()

    restored = BotState("rule", timedelta(minutes=60), 2, timedelta(seconds=60), 4, timedelta(minutes=30), clock)
    restored.restore_snapshot(snapshot)
    assert restored.mode == "ai"
    assert restored.owner_window_open()
    assert restored.is_paused("active")


def test_snapshot_skips_expired_pauses(state, clock):
    state.pause("old")
    clock.advance(minutes=61)
    assert state.to_snapshot()["paused_until"] == {}


def test_restore_snapshot_ignores_invalid_and_expired_entries(state, clock):
    state.restore_snapshot(
        {
            "mode": "turbo",
            "owner_last_message": "yesterday",
            "paused_until": {
                "expired": (clock() - timedelta(minutes=1)).isoformat(),
                "broken": 42,
                "naive": "2026-10-16T16:00:00",
            },
        }
    )
    assert state.mode == "rule"
    assert not state.owner_window_open()
    assert not state.is_paused("expired")
    assert not state.is_paused("broken")
    assert state.is_paused("naive")


def test_restore_snapshot_with_wrong_types_does_nothing(state):
    state.restore_snapshot({"paused_until": ["not", "a", "dict"]})
    assert state.to_snapshot()["paused_until"] == {}


def test_state_file_save_and_load(tmp_path):
    state_file = StateFile(str(tmp_path / "nested" / "state.json"))
    state_file.save({"mode": "ai"})
    assert state_file.load() == {"mode": "ai"}
    assert not (tmp_path / "nested" / "state.tmp").exists()


def test_state_file_missing_or_corrupt_returns_none(tmp_path):
    path = tmp_path / "state.json"
    assert StateFile(str(path)).load() is None
    path.write_text("{not json")
    assert StateFile(str(path)).load() is None
    path.write_text("[1, 2]")
    assert StateFile(str(path)).load() is None

