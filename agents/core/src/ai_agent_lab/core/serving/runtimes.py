"""Keeping one conversation's state, without keeping everybody's forever.

A console session builds an agent once and lives as long as the process. An HTTP
surface cannot: each request is separate, yet a conversation must continue, so
something has to hold the agent, its history and its open MCP session between two
requests.

That something is dangerous in three specific ways, and this class exists to
address all three:

* **Confusion.** State is keyed by the *authenticated subject* first. A caller
  supplying somebody else's conversation identifier gets their own conversation,
  never that person's, because the key they control is only half of it.
* **Leaking.** Entries expire when idle and the cache is bounded, so a public
  endpoint cannot be made to accumulate agents indefinitely.
* **Dangling resources.** An evicted runtime holds an MCP session. Dropping the
  reference would leak the connection, so eviction closes it.

Microsoft's own Python hosting helpers ship a session store that is, in their
words, process-local with no eviction policy, and .NET's per-principal isolation
has no Python equivalent. This is that missing piece, written without knowing
anything about mail so it can serve any agent - and be contributed upstream.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ai_agent_lab.core.security.principal import Principal

DEFAULT_IDLE_LIFETIME = timedelta(minutes=30)
DEFAULT_MAX_CONVERSATIONS = 200

Clock = Callable[[], datetime]

_logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    """Return the current instant, always timezone-aware."""
    return datetime.now(UTC)


@dataclass(slots=True)
class _Entry[RuntimeT]:
    """One conversation's runtime, and when it was last used."""

    build: asyncio.Future[RuntimeT]
    last_used: datetime

    def touch(self, now: datetime) -> None:
        """Record that this conversation is still alive."""
        self.last_used = now


class ConversationRuntimeCache[RuntimeT]:
    """Holds one runtime per conversation, per authenticated subject.

    Args:
        factory: Builds the runtime of a conversation. Awaited once per entry,
            even when several requests race for the same conversation.
        closer: Releases a runtime. Called on eviction, on expiry and on
            shutdown, because a runtime holds an MCP session.
        max_conversations: Upper bound on live conversations. Reaching it evicts
            the least recently used, which is a bounded service degrading rather
            than a process growing without limit.
        idle_lifetime: How long an untouched conversation is kept.
        clock: Injected so expiry is testable without waiting.
    """

    def __init__(
        self,
        factory: Callable[[Principal, str], Awaitable[RuntimeT]],
        closer: Callable[[RuntimeT], Awaitable[None]],
        *,
        max_conversations: int = DEFAULT_MAX_CONVERSATIONS,
        idle_lifetime: timedelta = DEFAULT_IDLE_LIFETIME,
        clock: Clock = _utc_now,
    ) -> None:
        if max_conversations < 1:
            raise ValueError("a cache holding no conversation cannot serve one")
        self._factory = factory
        self._closer = closer
        self._max_conversations = max_conversations
        self._idle_lifetime = idle_lifetime
        self._clock = clock
        self._entries: dict[tuple[str, str], _Entry[RuntimeT]] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, principal: Principal, conversation_id: str) -> RuntimeT:
        """Return the runtime of a conversation, building it if needed.

        Concurrent callers of the same conversation share one build. A model
        routinely triggers overlapping work, and building twice would open two
        MCP sessions and silently discard one.
        """
        key = (principal.subject, conversation_id)
        async with self._lock:
            now = self._clock()
            await self._expire(now)
            entry = self._entries.get(key)
            if entry is None:
                # `ensure_future` rather than `create_task`: the factory is typed
                # as returning an awaitable, and a future can be awaited by every
                # caller that races for this conversation.
                entry = _Entry(
                    build=asyncio.ensure_future(self._factory(principal, conversation_id)),
                    last_used=now,
                )
                self._entries[key] = entry
                await self._enforce_bound()
            else:
                entry.touch(now)
            build = entry.build

        try:
            return await build
        except BaseException:
            # A failed build must not be cached: the next request deserves a
            # fresh attempt rather than the same exception for half an hour.
            await self._forget(key, close=False)
            raise

    async def release(self, principal: Principal, conversation_id: str) -> None:
        """Close and forget one conversation."""
        await self._forget((principal.subject, conversation_id), close=True)

    async def aclose(self) -> None:
        """Close every live conversation, on shutdown."""
        async with self._lock:
            keys = list(self._entries)
        for key in keys:
            await self._forget(key, close=True)

    @property
    def live_conversations(self) -> int:
        """How many conversations are currently held."""
        return len(self._entries)

    async def _expire(self, now: datetime) -> None:
        """Drop conversations nobody has touched for a while."""
        deadline = now - self._idle_lifetime
        for key in [key for key, entry in self._entries.items() if entry.last_used <= deadline]:
            await self._close(self._entries.pop(key))

    async def _enforce_bound(self) -> None:
        """Keep the number of live conversations under the configured ceiling."""
        while len(self._entries) > self._max_conversations:
            oldest = min(self._entries, key=lambda key: self._entries[key].last_used)
            _logger.info("evicting the least recently used conversation to stay within bounds")
            await self._close(self._entries.pop(oldest))

    async def _forget(self, key: tuple[str, str], *, close: bool) -> None:
        """Remove one entry, optionally releasing what it holds."""
        async with self._lock:
            entry = self._entries.pop(key, None)
        if entry is not None and close:
            await self._close(entry)

    async def _close(self, entry: _Entry[RuntimeT]) -> None:
        """Release a runtime, tolerating one that never finished building.

        Shutting down must not raise: whatever went wrong, the entry is already
        gone from the cache and nothing can reach it any more.
        """
        try:
            runtime = await entry.build
        except Exception as error:  # noqa: BLE001 - a build that failed holds nothing to close
            _logger.debug("discarded a conversation that never built: %s", type(error).__name__)
            return

        try:
            await self._closer(runtime)
        except Exception as error:  # noqa: BLE001 - see the docstring
            _logger.warning("could not release a conversation: %s", type(error).__name__)
