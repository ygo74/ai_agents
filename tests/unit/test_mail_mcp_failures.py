"""Dialects preserve error meaning without duplicating native wire decoding."""

import pytest

from ai_agent_lab.mail.application.errors import (
    MailAccessDeniedError,
    MailNotFoundError,
    MailToolProtocolError,
    MailToolUnavailableError,
)
from ai_agent_lab.mail.infrastructure.mcp.google.errors import decode_failure as google_failure
from ai_agent_lab.mail.infrastructure.mcp.native.errors import decode_failure as native_failure
from mail_mcp.protocol.errors import MailErrorCode, encode


@pytest.mark.parametrize("decoder", [native_failure, google_failure])
@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (MailErrorCode.NOT_FOUND, MailNotFoundError),
        (MailErrorCode.ACCESS_DENIED, MailAccessDeniedError),
        (MailErrorCode.UNAVAILABLE, MailToolUnavailableError),
        (MailErrorCode.PROTOCOL, MailToolProtocolError),
    ],
)
def test_known_error_keeps_its_meaning(decoder, code, expected):
    error = decoder(f"Error executing tool: {encode(code, 'missing resource')}")

    assert isinstance(error, expected)
    assert str(error) == "missing resource"


@pytest.mark.parametrize("decoder", [native_failure, google_failure])
def test_first_code_wins_and_later_text_is_not_reinterpreted(decoder):
    reported = "wrapper mail_access_denied: refused; mail_not_found: missing"

    error = decoder(reported)

    assert isinstance(error, MailAccessDeniedError)
    assert str(error) == "refused; mail_not_found: missing"


@pytest.mark.parametrize("decoder", [native_failure, google_failure])
@pytest.mark.parametrize("reported", ["uncoded server failure", "mail_not_found: "])
def test_unknown_or_empty_details_preserve_the_reported_failure(decoder, reported):
    error = decoder(reported)

    assert str(error) == reported
    if reported.startswith("mail_not_found"):
        assert isinstance(error, MailNotFoundError)
    else:
        assert isinstance(error, MailToolProtocolError)
