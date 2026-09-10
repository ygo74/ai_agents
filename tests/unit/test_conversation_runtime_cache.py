"""Tests of the state a conversation keeps between two HTTP requests.

Holding an agent between requests is what makes a conversation possible and what
makes a public endpoint dangerous. Three failures matter, and each has its own
class below: serving one person's conversation to another, accumulating agents
until the process dies, and dropping an MCP session without closing it.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from ai_agent_lab.core.security.principal import Principal
from ai_agent_lab.core.serving.runtimes import ConversationRuntimeCache

ADA = Principal(subject="ada-3f9a", email="ada@example.com")
BOB = Principal(subject="bob-77c1", email="bob@example.com")
NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


class FakeRuntime:
    """A runtime that records whether it was released."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.closed = False


class RuntimeFactory:
    """Builds fake runtimes and counts how often it was asked to."""

    def __init__(self, *, delay: float = 0.0) -> None:
        self.builds: list[tuple[str, str]] = []
        self.closed: list[FakeRuntime] = []
        self._delay = delay

    async def build(self, principal: Principal, conversation_id: str) -> FakeRuntime:
        """Build the runtime of one conversation."""
        self.builds.append((principal.subject, conversation_id))
        if self._delay:
            await asyncio.sleep(self._delay)
        return FakeRuntime(f"{principal.subject}:{conversation_id}")

    async def close(self, runtime: FakeRuntime) -> None:
        """Release a runtime, as the cache does on eviction."""
        runtime.closed = True
        self.closed.append(runtime)


class MovableClock:
    """A clock the test advances by hand."""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, amount: timedelta) -> None:
        """Move time forward."""
        self.now += amount


def build_cache(factory: RuntimeFactory, clock: MovableClock, **options) -> ConversationRuntimeCache[FakeRuntime]:
    """Assemble a cache over the fake factory."""
    return ConversationRuntimeCache(factory.build, factory.close, clock=clock, **options)


class TestAConversationIsKeptBetweenRequests:
    """Without this, every HTTP request would start a new conversation."""

    async def test_the_same_conversation_reuses_one_runtime(self):
        factory = RuntimeFactory()
        cache = build_cache(factory, MovableClock(NOW))

        first = await cache.acquire(ADA, "conv-1")
        second = await cache.acquire(ADA, "conv-1")

        assert first is second
        assert len(factory.builds) == 1

    async def test_two_conversations_of_one_person_stay_apart(self):
        factory = RuntimeFactory()
        cache = build_cache(factory, MovableClock(NOW))

        first = await cache.acquire(ADA, "conv-1")
        second = await cache.acquire(ADA, "conv-2")

        assert first is not second

    async def test_concurrent_requests_share_a_single_build(self):
        """A model triggers overlapping work; two builds would open two sessions."""
        factory = RuntimeFactory(delay=0.01)
        cache = build_cache(factory, MovableClock(NOW))

        runtimes = await asyncio.gather(*(cache.acquire(ADA, "conv-1") for _ in range(5)))

        assert len({id(runtime) for runtime in runtimes}) == 1
        assert len(factory.builds) == 1


@pytest.mark.security
class TestConversationsAreNotConfused:
    """A conversation identifier is a routing handle, not a permission."""

    async def test_the_same_identifier_gives_each_person_their_own(self):
        factory = RuntimeFactory()
        cache = build_cache(factory, MovableClock(NOW))

        ada = await cache.acquire(ADA, "shared-id")
        bob = await cache.acquire(BOB, "shared-id")

        assert ada is not bob
        assert ada.label.startswith(ADA.subject)
        assert bob.label.startswith(BOB.subject)

    async def test_guessing_an_identifier_reaches_nobody_else(self):
        """Bob quotes Ada's conversation and still gets his own."""
        factory = RuntimeFactory()
        cache = build_cache(factory, MovableClock(NOW))
        ada = await cache.acquire(ADA, "conv-private")

        bob = await cache.acquire(BOB, "conv-private")

        assert bob is not ada
        assert factory.builds == [(ADA.subject, "conv-private"), (BOB.subject, "conv-private")]

    async def test_releasing_one_person_leaves_the_other_alone(self):
        factory = RuntimeFactory()
        cache = build_cache(factory, MovableClock(NOW))
        ada = await cache.acquire(ADA, "shared-id")
        bob = await cache.acquire(BOB, "shared-id")

        await cache.release(ADA, "shared-id")

        assert ada.closed
        assert not bob.closed


@pytest.mark.security
class TestTheCacheStaysBounded:
    """A public endpoint must not be made to accumulate agents."""

    async def test_an_idle_conversation_expires(self):
        factory = RuntimeFactory()
        clock = MovableClock(NOW)
        cache = build_cache(factory, clock, idle_lifetime=timedelta(minutes=30))
        first = await cache.acquire(ADA, "conv-1")

        clock.advance(timedelta(minutes=31))
        second = await cache.acquire(ADA, "conv-1")

        assert second is not first
        assert first.closed

    async def test_using_a_conversation_keeps_it_alive(self):
        factory = RuntimeFactory()
        clock = MovableClock(NOW)
        cache = build_cache(factory, clock, idle_lifetime=timedelta(minutes=30))
        first = await cache.acquire(ADA, "conv-1")

        for _ in range(3):
            clock.advance(timedelta(minutes=20))
            again = await cache.acquire(ADA, "conv-1")

        assert again is first
        assert not first.closed

    async def test_reaching_the_ceiling_evicts_the_least_recently_used(self):
        factory = RuntimeFactory()
        clock = MovableClock(NOW)
        cache = build_cache(factory, clock, max_conversations=2)

        oldest = await cache.acquire(ADA, "conv-1")
        clock.advance(timedelta(minutes=1))
        await cache.acquire(ADA, "conv-2")
        clock.advance(timedelta(minutes=1))
        await cache.acquire(ADA, "conv-3")

        assert oldest.closed
        assert cache.live_conversations == 2

    async def test_a_cache_holding_nothing_is_refused(self):
        with pytest.raises(ValueError, match="cannot serve one"):
            ConversationRuntimeCache(RuntimeFactory().build, RuntimeFactory().close, max_conversations=0)


class TestNothingIsDroppedWithoutBeingClosed:
    """A runtime holds an MCP session; losing the reference would leak it."""

    async def test_eviction_closes_what_it_removes(self):
        factory = RuntimeFactory()
        clock = MovableClock(NOW)
        cache = build_cache(factory, clock, max_conversations=1)

        first = await cache.acquire(ADA, "conv-1")
        clock.advance(timedelta(minutes=1))
        await cache.acquire(ADA, "conv-2")

        assert factory.closed == [first]

    async def test_shutting_down_closes_every_conversation(self):
        factory = RuntimeFactory()
        cache = build_cache(factory, MovableClock(NOW))
        await cache.acquire(ADA, "conv-1")
        await cache.acquire(BOB, "conv-2")

        await cache.aclose()

        assert len(factory.closed) == 2
        assert cache.live_conversations == 0

    async def test_a_failing_release_does_not_break_shutdown(self):
        """Whatever went wrong, the entry is gone and nothing can reach it."""

        async def refuse_to_close(runtime: FakeRuntime) -> None:
            raise RuntimeError("the session was already gone")

        factory = RuntimeFactory()
        cache = ConversationRuntimeCache(factory.build, refuse_to_close, clock=MovableClock(NOW))
        await cache.acquire(ADA, "conv-1")

        await cache.aclose()

        assert cache.live_conversations == 0


class TestAFailedBuildIsNotRemembered:
    """The next request deserves a fresh attempt, not a cached exception."""

    async def test_the_failure_reaches_the_caller(self):
        async def fail(principal: Principal, conversation_id: str) -> FakeRuntime:
            raise RuntimeError("the mail server could not be reached")

        cache = ConversationRuntimeCache(fail, RuntimeFactory().close, clock=MovableClock(NOW))

        with pytest.raises(RuntimeError, match="could not be reached"):
            await cache.acquire(ADA, "conv-1")

    async def test_a_later_request_tries_again(self):
        attempts: list[str] = []

        async def fail_once(principal: Principal, conversation_id: str) -> FakeRuntime:
            attempts.append(conversation_id)
            if len(attempts) == 1:
                raise RuntimeError("transient")
            return FakeRuntime("recovered")

        cache = ConversationRuntimeCache(fail_once, RuntimeFactory().close, clock=MovableClock(NOW))
        with pytest.raises(RuntimeError):
            await cache.acquire(ADA, "conv-1")

        assert (await cache.acquire(ADA, "conv-1")).label == "recovered"
        assert cache.live_conversations == 1
