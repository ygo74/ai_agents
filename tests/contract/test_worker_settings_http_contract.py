"""Pin the installed runtime's manifest-driven ``WorkerSettings`` contract.

CR-003 found that the deployed ``ygo74-agent-runtime-agents`` package did not
yet carry the ``http_settings`` field ``WorkerSettings`` needed, even though both
service factories already called it that way. The fix was not a code change in
this repository: it was fast-forwarding the editable checkout at
``C:\\devel\\ai-enterprise-agent-runtime`` to a commit the runtime's own `main`
already had. That kind of fix leaves nothing in this repository's history or
diff to prove it happened, so a hidden environment mutation could silently
regress again without any red test appearing in a normal `git diff` review.

This module exercises the real installed library's public contract - not a
manifest, not a service factory - directly:

* ``WorkerSettings(http_settings=...)`` builds without the separate
  ``authentication``/``surfaces`` fields, and refuses to accept both forms at
  once (CR-003's actual defect: the field did not exist at all).
* ``HostingFactory.add_http_settings`` derives surfaces, authentication *and*
  rate limiting from one ``AgentHttpRuntimeSettings``, and registers ASGI
  shutdown cleanup for it - the "surfaces, authentication, rate limits,
  discovery, identity, cleanup" set of manifest policies CR-003 is required to
  preserve.

No speculative guarantee is pinned beyond what is actually installed: this
test fails loudly, with a clear message, against any installed runtime that
regresses the contract, rather than silently skipping. It does not depend on
the Mail/Wiki services to prove the library behaviour, so it would have failed
on the exact combination of code and dependency this repository had before the
editable checkout was advanced.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ygo74.agent_runtime.domains.auth.apikey_authenticator import StaticApiKeyUserResolver
from ygo74.agent_runtime.domains.auth.authentication_policy import AuthenticationPolicy
from ygo74.agent_runtime.domains.configuration.agent_http_configuration import (
    AgentHttpRuntimeSettings,
)
from ygo74.agent_runtime.domains.contracts.http_configuration import HttpEndpoint
from ygo74.agent_runtime.domains.endpoints.hosting_factory import EndpointSurface, HostingFactory
from ygo74.agent_runtime.domains.endpoints.managed_worker import WorkerSettings
from ygo74.agent_runtime.domains.endpoints.rate_limiting import RateLimitSettings


def _authentication(key: str = "demo-key") -> AuthenticationPolicy:
    """One concrete, non-anonymous authentication policy, the way a manifest builds one."""
    return AuthenticationPolicy.api_key(StaticApiKeyUserResolver({key: "diana"}))


class TestWorkerSettingsAcceptsManifestHttpSettings:
    """The exact shape both service factories rely on (CR-003's regression)."""

    def test_http_settings_alone_is_sufficient(self):
        """A manifest-only configuration needs no separate authentication/surfaces."""
        settings = WorkerSettings(
            deployment_id="contract-probe",
            identity_namespace="contract-probe",
            http_settings=AgentHttpRuntimeSettings(
                endpoints=(HttpEndpoint.CHAT_COMPLETIONS,),
                authentication=_authentication(),
            ),
        )

        assert settings.authentication is None
        assert settings.surfaces is None
        assert settings.http_settings is not None

    def test_http_settings_cannot_be_combined_with_separate_authentication(self):
        """CR-003's other half: the two configuration styles remain mutually exclusive."""
        with pytest.raises(ValueError, match="cannot be combined"):
            WorkerSettings(
                deployment_id="contract-probe",
                identity_namespace="contract-probe",
                http_settings=AgentHttpRuntimeSettings(
                    endpoints=(HttpEndpoint.CHAT_COMPLETIONS,),
                    authentication=_authentication(),
                ),
                authentication=_authentication(),
            )

    def test_http_settings_cannot_be_combined_with_separate_surfaces(self):
        with pytest.raises(ValueError, match="cannot be combined"):
            WorkerSettings(
                deployment_id="contract-probe",
                identity_namespace="contract-probe",
                http_settings=AgentHttpRuntimeSettings(
                    endpoints=(HttpEndpoint.CHAT_COMPLETIONS,),
                    authentication=_authentication(),
                ),
                surfaces=(EndpointSurface.OPENAI_CHAT_COMPLETIONS,),
            )

    def test_legacy_explicit_authentication_still_works_unmodified(self):
        """The pre-manifest construction style - used by hosts with no manifest - is untouched."""
        settings = WorkerSettings(
            deployment_id="contract-probe",
            identity_namespace="contract-probe",
            authentication=_authentication(),
            surfaces=(EndpointSurface.OPENAI_CHAT_COMPLETIONS,),
        )

        assert settings.http_settings is None
        assert settings.authentication is not None


class TestHostingFactoryPreservesManifestPolicies:
    """``add_http_settings`` must carry every manifest policy CR-003 is required to keep."""

    def test_surfaces_authentication_and_rate_limit_all_derive_from_one_settings_object(self):
        """One ``AgentHttpRuntimeSettings`` is the sole source of all three policies."""
        app = FastAPI()
        rate_limit = RateLimitSettings(limits=("5/minute",))
        settings = AgentHttpRuntimeSettings(
            endpoints=(HttpEndpoint.CHAT_COMPLETIONS,),
            authentication=_authentication(),
            rate_limit=rate_limit,
        )

        factory = HostingFactory(app)
        returned = factory.add_http_settings(settings)

        assert returned is factory
        assert factory._surfaces == frozenset({EndpointSurface.OPENAI_CHAT_COMPLETIONS})
        assert factory._authentication is settings.authentication
        assert factory._rate_limit is rate_limit

    def test_http_settings_cannot_be_combined_with_separately_configured_security(self):
        """A host must not mix manifest-sourced and hand-built authentication."""
        app = FastAPI()
        factory = HostingFactory(app).add_security(_authentication())

        with pytest.raises(Exception, match="cannot be combined"):
            factory.add_http_settings(
                AgentHttpRuntimeSettings(
                    endpoints=(HttpEndpoint.CHAT_COMPLETIONS,),
                    authentication=_authentication(),
                )
            )

    async def test_registering_http_settings_installs_asgi_shutdown_cleanup(self, monkeypatch):
        """Discovery, identity and cleanup - not only authentication - come from the one object."""
        closed = []
        settings = AgentHttpRuntimeSettings(
            endpoints=(HttpEndpoint.CHAT_COMPLETIONS,),
            authentication=_authentication(),
        )
        monkeypatch.setattr(type(settings), "close", lambda self: closed.append(True))

        @asynccontextmanager
        async def _entrypoint(*_args: object, **_kwargs: object) -> AsyncIterator[None]:
            yield None

        from datetime import UTC, datetime

        from ygo74.agent_runtime.domains.discovery.agent_descriptor import (
            AgentCapabilitySet,
            AgentDescriptor,
        )

        app = FastAPI()
        descriptor = AgentDescriptor(
            agent_id="contract-probe",
            route_key="contract-probe",
            display_name="Contract Probe",
            description="worker settings contract probe",
            version="0.0.0",
            owner="test",
            created_at_utc=datetime.now(UTC),
            capabilities=AgentCapabilitySet(),
        )
        HostingFactory(app).add_agent(_entrypoint, descriptor).add_http_settings(settings).register()

        with TestClient(app):
            assert not closed
        assert closed == [True]
