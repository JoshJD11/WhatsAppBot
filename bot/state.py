"""Runtime state.

Most of it lives in memory. The part that must survive a restart (mode, handoff
pauses, the owner's last message time) can be saved to a JSON file with
`StateFile`. A serverless host needs a shared store instead (see CLAUDE.md,
Open Questions).
"""

import asyncio
import json
import logging
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Literal, cast

from .config import BotMode

logger = logging.getLogger(__name__)

Clock = Callable[[], datetime]
Role = Literal["customer", "bot"]

OWNER_WINDOW = timedelta(hours=24)
# Stop notifying a few minutes early so a message is never sent after the window closes.
OWNER_WINDOW_MARGIN = timedelta(minutes=5)
SEEN_MESSAGES_LIMIT = 5000
NEW_CONVERSATION_AFTER = timedelta(hours=12)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Turn:
    role: Role
    text: str


class BotState:
    def __init__(
        self,
        mode: BotMode,
        handoff_pause: timedelta,
        rate_limit_max: int,
        rate_limit_window: timedelta,
        history_limit: int,
        history_idle: timedelta,
        clock: Clock = utc_now,
    ) -> None:
        self.mode: BotMode = mode
        self._clock = clock
        self._handoff_pause = handoff_pause
        self._rate_limit_max = rate_limit_max
        self._rate_limit_window = rate_limit_window
        self._history_limit = history_limit
        self._history_idle = history_idle

        self._seen_messages: OrderedDict[str, None] = OrderedDict()
        self._paused_until: dict[str, datetime] = {}
        self._recent_replies: dict[str, deque[datetime]] = {}
        self._history: dict[str, deque[Turn]] = {}
        self._history_touched: dict[str, datetime] = {}
        self._last_activity: dict[str, datetime] = {}
        self._owner_last_message: datetime | None = None
        self._customer_locks: dict[str, asyncio.Lock] = {}

    def now(self) -> datetime:
        return self._clock()

    # Deduplication

    def is_duplicate(self, message_id: str) -> bool:
        """Record the message ID and report whether it was already seen."""
        if message_id in self._seen_messages:
            return True
        self._seen_messages[message_id] = None
        if len(self._seen_messages) > SEEN_MESSAGES_LIMIT:
            self._seen_messages.popitem(last=False)
        return False

    # Handoff pause

    def pause(self, customer: str) -> None:
        self._paused_until[customer] = self.now() + self._handoff_pause

    def is_paused(self, customer: str) -> bool:
        until = self._paused_until.get(customer)
        if until is None:
            return False
        if self.now() >= until:
            del self._paused_until[customer]
            return False
        return True

    # Rate limit

    def allow_reply(self, customer: str) -> bool:
        """Count a reply for the customer; False once the limit for the window is reached."""
        now = self.now()
        replies = self._recent_replies.setdefault(customer, deque())
        while replies and now - replies[0] >= self._rate_limit_window:
            replies.popleft()
        if len(replies) >= self._rate_limit_max:
            return False
        replies.append(now)
        return True

    # Conversation tracking

    def is_new_conversation(self, customer: str) -> bool:
        """True when the customer has not written recently. Also records this activity."""
        now = self.now()
        last = self._last_activity.get(customer)
        self._last_activity[customer] = now
        return last is None or now - last >= NEW_CONVERSATION_AFTER

    def history(self, customer: str) -> list[Turn]:
        turns = self._history.get(customer)
        if not turns:
            return []
        touched = self._history_touched.get(customer)
        if touched is not None and self.now() - touched >= self._history_idle:
            self.forget(customer)
            return []
        return list(turns)

    def remember(self, customer: str, role: Role, text: str) -> None:
        if self._history_limit == 0:
            return
        turns = self._history.setdefault(customer, deque(maxlen=self._history_limit))
        turns.append(Turn(role=role, text=text))
        self._history_touched[customer] = self.now()

    def forget(self, customer: str) -> None:
        self._history.pop(customer, None)
        self._history_touched.pop(customer, None)

    # Owner 24 hour window

    def record_owner_message(self) -> None:
        self._owner_last_message = self.now()

    def owner_window_open(self) -> bool:
        if self._owner_last_message is None:
            return False
        return self.now() - self._owner_last_message < OWNER_WINDOW - OWNER_WINDOW_MARGIN

    # Concurrency

    def customer_lock(self, customer: str) -> asyncio.Lock:
        """One lock per customer so their messages are answered in order."""
        return self._customer_locks.setdefault(customer, asyncio.Lock())

    # Persistence

    def to_snapshot(self) -> dict[str, Any]:
        """The state that must survive a restart, as JSON-friendly data."""
        now = self.now()
        return {
            "mode": self.mode,
            "owner_last_message": self._owner_last_message.isoformat() if self._owner_last_message else None,
            "paused_until": {
                customer: until.isoformat() for customer, until in self._paused_until.items() if until > now
            },
        }

    def restore_snapshot(self, snapshot: dict[str, Any]) -> None:
        """Load a snapshot made by `to_snapshot`. Invalid entries are skipped."""
        mode = snapshot.get("mode")
        if mode in ("ai", "rule"):
            self.mode = cast(BotMode, mode)
        owner = _parse_time(snapshot.get("owner_last_message"))
        if owner is not None:
            self._owner_last_message = owner
        paused = snapshot.get("paused_until")
        if isinstance(paused, dict):
            for customer, raw in paused.items():
                until = _parse_time(raw)
                if until is not None and until > self.now():
                    self._paused_until[str(customer)] = until

    # Housekeeping

    def prune(self) -> None:
        """Drop expired entries so memory does not grow forever."""
        now = self.now()
        for customer in [c for c, until in self._paused_until.items() if now >= until]:
            del self._paused_until[customer]
        for customer in [c for c, r in self._recent_replies.items() if not r or now - r[-1] >= self._rate_limit_window]:
            del self._recent_replies[customer]
        stale = [c for c, last in self._last_activity.items() if now - last >= NEW_CONVERSATION_AFTER]
        for customer in stale:
            del self._last_activity[customer]
            self.forget(customer)
            lock = self._customer_locks.get(customer)
            if lock is not None and not lock.locked():
                del self._customer_locks[customer]


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class StateFile:
    """Saves and loads a state snapshot as JSON. Blocking; run it in a worker thread."""

    def __init__(self, path: str) -> None:
        self._path = Path(path)

    def load(self) -> dict[str, Any] | None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            logger.warning("State file %s is unreadable; starting with a fresh state", self._path)
            return None
        return data if isinstance(data, dict) else None

    def save(self, snapshot: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
        temporary.replace(self._path)
