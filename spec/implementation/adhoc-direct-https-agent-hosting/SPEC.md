# Specification — direct HTTPS and branch quality gates

## Request source and repositories

- Request: allow an agent to serve its HTTPS MCP resource directly, without a
  reverse proxy, then commit and push the change. During delivery, the user
  authorized resolving the MCP and CI blockers found by required checks.
- Primary repository: `ai_agents`, which owns the Mail and Wiki launchers,
  container images, deployment guides, and their CI workflow.
- Secondary dependency: `ai-enterprise-agent-runtime` supplies the runtime
  contracts consumed by `ai_agents`. No runtime source changes are currently
  planned. The CI workflow still uses `V0.8.2`; the user asked to defer any
  workflow update until the runtime feature is merged and a compatible version
  is published.
- No Issue is associated with this ad hoc request.

## Objective and current context

Mail's checked-in manifest declares
`MAIL_AGENT_HTTP_MCP_RESOURCE_URL` as the public HTTPS `/mcp` resource URL for
JWT-protected MCP. That value is used for OAuth protected-resource metadata; it
does not configure TLS on the socket. Mail and Wiki can be launched through
repository-owned Python launchers or their Docker images, both using Uvicorn.
Before this request, the launchers exposed host, port, and reload options but no
TLS certificate options. The container images bound plain HTTP, and their local
health checks used HTTP.

The delivery checks exposed a CI version mismatch: `.github/workflows/quality.yml`
checks out runtime release `V0.8.2`, while the Mail manifest on this branch uses
MCP endpoint fields supported by runtime commit
`98c7fad26cfc8f258d57f85d511de63a22f802d8`. The user asked to leave CI unchanged
until that runtime work is merged and a compatible version is published. The
Wiki real-stdio MCP test timed out inside the restricted local runner but passed
outside that isolation; no product or test-harness change is indicated.

## Scope and exclusions

In scope:

- Direct TLS for both Mail and Wiki HTTP services, since they share the same
  hosting pattern.
- A PEM certificate chain and private-key file supplied by the operator at
  process startup; TLS remains disabled when neither file is configured.
- The repository-owned Mail and Wiki launchers, container invocation guidance,
  health checks, and user deployment documentation needed for the new mode.
- Keep the declared MCP `resource_url` separate from listener configuration;
  operators must make the HTTPS URL point to the TLS-enabled listener.
- Update affected JWT test fixtures to provide the MCP resource URL required by
  the compatible runtime contract; keep test behavior and runtime production
  code unchanged.

Out of scope:

- Obtaining, renewing, or rotating certificates, or managing a certificate
  authority.
- HTTPS support for the standalone MCP-server process, which has a distinct
  launcher and deployment lifecycle.
- Changes to authentication, OAuth metadata, agent routes, or runtime source
  APIs.
- Changes to `.github/workflows/quality.yml`; revisit CI runtime alignment after
  the runtime feature is merged and a compatible version is published.
- Publishing images, packages, or releases.

## Expected user behavior

- Operators can start Mail or Wiki with both a TLS certificate file and private
  key file, causing Uvicorn to serve HTTPS directly on its configured bind
  address and port.
- Supplying only one member of the certificate/key pair fails fast with a clear
  configuration error. Supplying neither preserves the current HTTP behavior.
- Docker deployments can mount certificate files read-only and pass their paths
  to the service without copying certificates or private keys into the image.
- The container liveness check continues to work when the listener uses HTTPS.
- With TLS enabled, callers use the matching `https://` service URL. For
  JWT-protected MCP, `http.mcp.resource_url` remains the canonical externally
  reachable HTTPS URL ending in `/mcp`.

## Architecture, permissions, and data

- TLS is configured at the outer Uvicorn adapter. Agent domain behavior,
  manifests, and the runtime ASGI composition remain independent of listener
  certificates.
- Certificate contents and private-key contents are never read into application
  configuration, logged, or included in errors. Only file paths are supplied
  to Uvicorn; deployments keep private keys in a secret store or protected,
  read-only mount.
- The local HTTPS health probe may establish TLS without authenticating to the
  service. Its certificate-verification behavior must be narrowly scoped to the
  loopback liveness check and documented; external clients continue to validate
  the server certificate normally.
- TLS does not replace agent authentication or authorization.

## Constraints and decisions

- Use Uvicorn's existing SSL certificate and key options rather than adding a
  TLS implementation or placing certificate paths in `agent.yaml`.
- Expose the options through the Mail and Wiki Python service launchers. Docker
  images already invoke Uvicorn directly, so the deployment plan should use its
  standard command-line options and read-only mounts unless inspection finds a
  concrete gap.
- Preserve the current HTTP default for development and existing deployments.
- The implementation plan must check how the image health check can probe a
  locally TLS-enabled listener without adding credentials or trusting remote
  certificates.

## Acceptance criteria

1. Both service launchers accept a certificate path and private-key path and
   pass them to Uvicorn only when TLS is configured.
2. A missing certificate or key counterpart is rejected before Uvicorn starts;
   no TLS options are passed when neither is provided.
3. The launcher behavior is covered by deterministic tests that do not bind a
   real network port or read private key contents.
4. Docker guidance shows how to mount a certificate and private key read-only
   and start the service with direct HTTPS; neither secret is baked into an
   image or committed configuration.
5. Container health checks work for both HTTP and direct HTTPS listener modes,
   with TLS verification bypass limited to the local liveness probe if needed.
6. User documentation explains the TLS startup options, certificate handling,
   URL scheme/port, and the fact that `resource_url` advertises the endpoint but
   does not enable TLS.
7. Existing HTTP startup and health-check behavior remains unchanged when TLS
   options are omitted.
8. The complete pytest suite passes against the compatible runtime source,
   including the Mail manifest scenario and Wiki MCP stdio protocol tests.
9. The CI version mismatch is recorded for follow-up after a compatible runtime
   release; this request does not change the workflow.

## Validation impact

The PLAN will select focused launcher tests, health-check tests, and repository
quality checks for the changed Python and deployment files. No live identity
provider, agent model, or enterprise service is needed. This request changes no
retained application state and has no language-parity impact. Startup cost is
limited to Uvicorn loading the supplied certificate and key; no separate runtime
performance budget is required.

## Risks and open questions

- The operator is responsible for certificate validity, hostname coverage,
  permissions, expiry monitoring, and renewal.
- The Docker health check needs to verify listener availability over TLS while
  avoiding an unsafe general-purpose certificate-verification bypass. The PLAN
  must constrain any bypass to its loopback probe and preserve normal external
  certificate verification.
- The service still needs to bind a reachable interface and publish the chosen
  port; enabling HTTPS alone does not change container networking or firewalls.
- The current CI job uses runtime `V0.8.2`, which predates the MCP endpoint
  manifest fields on this branch. Per the user's direction, update CI only after
  the runtime change is merged and a compatible version is published.
