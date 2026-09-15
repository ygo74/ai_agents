"""Is this process answering?

Deliberately narrow. A health probe answers one question - is the process
listening and serving - and must not be tempted into answering others.

In particular it does **not** authenticate. All three services here refuse
unauthenticated callers, so a 401 is a perfectly good sign of life: something is
listening, routing, and applying its security policy. Giving the probe a
credential so it could see a 200 would put a credential in the image, in the
compose file and in the orchestrator, to learn nothing more.

Anything that answers is alive. A refused connection, a timeout or a 5xx is not.

Usage::

    python /app/healthcheck.py http://127.0.0.1:8123/v1/models
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request

TIMEOUT_SECONDS = 4
ALIVE_STATUSES = frozenset({200, 401, 403})


def alive(url: str) -> bool:
    """Whether the service answered at all."""
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310 - a loopback URL
            return int(response.status) in ALIVE_STATUSES
    except urllib.error.HTTPError as refusal:
        # It answered. Refusing us is the policy working, not the process dying.
        return int(refusal.code) in ALIVE_STATUSES
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def main() -> int:
    """Return 0 when the service answered, 1 otherwise."""
    if len(sys.argv) != 2:
        print("usage: healthcheck.py <url>", file=sys.stderr)
        return 2
    return 0 if alive(sys.argv[1]) else 1


if __name__ == "__main__":
    sys.exit(main())
