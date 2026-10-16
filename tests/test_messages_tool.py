"""verify message tool responses use safe MIME output and stable identifiers
replace the transport with a fixture client to keep these checks offline
"""

from __future__ import annotations

from email.message import EmailMessage

import pytest

from imap_mcp.config import Settings, load_settings
from imap_mcp.tools.messages import make_get_message


class FakeMessageClient:
    """return one deterministic RFC822 message for the requested mailbox identity"""

    body = "Safe text"

    def __init__(self, settings: Settings) -> None:
        """retain the settings passed through the tool factory"""
        self.settings = settings

    def __enter__(self) -> FakeMessageClient:
        """provide the fake as a context-managed session"""
        return self

    def __exit__(self, *_: object) -> None:
        """finish the fake session without external cleanup"""
        return None

    def fetch_rfc822(self, mailbox: str, uid: int, uidvalidity: int) -> bytes:
        """check the requested identity and build a message with one safe attachment"""
        assert (mailbox, uid, uidvalidity) == ("INBOX", 9, 101)
        message = EmailMessage()
        message["Subject"] = "Fixture"
        message["From"] = "sender@example.test"
        message.set_content(self.body)
        message.add_attachment(
            b"test pdf", maintype="application", subtype="pdf", filename="report.pdf"
        )
        return message.as_bytes()


def settings() -> Settings:
    """build minimal valid settings for message retrieval"""
    return load_settings(
        {
            "IMAP_HOST": "imap.example.test",
            "IMAP_USERNAME": "test-user",
            "IMAP_PASSWORD": "test-password",
            "IMAP_ALLOWED_MAILBOXES": "INBOX",
        }
    )


def test_get_message_returns_safe_content_and_attachment_inventory() -> None:
    """check stable message identifiers, body text, and attachment metadata"""
    result = make_get_message(settings(), client_factory=FakeMessageClient)("INBOX", 9, 101)

    assert result["mailbox"] == "INBOX"
    assert result["uid"] == 9
    assert result["body"] == "Safe text"
    assert result["body_truncated"] is False
    assert result["attachments"] == [
        {"index": 0, "filename": "report.pdf", "content_type": "application/pdf", "size_bytes": 8}
    ]


def test_get_message_rejects_invalid_uid_before_connection() -> None:
    """check invalid UIDs are rejected before the fake session is opened"""
    tool = make_get_message(settings(), client_factory=FakeMessageClient)

    with pytest.raises(ValueError, match="positive IMAP UID"):
        tool("INBOX", 0, 101)


def test_default_preview_bounds_unicode_without_changing_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """catch unbounded defaults and slicing encoded bytes instead of characters"""
    monkeypatch.setattr(FakeMessageClient, "body", "é" * 3999 + "🙂end")
    result = make_get_message(settings(), client_factory=FakeMessageClient)("INBOX", 9, 101)

    assert result["body"] == "é" * 3999 + "🙂"
    assert result["body_truncated"] is True
    assert (result["mailbox"], result["uid"], result["uidvalidity"]) == ("INBOX", 9, 101)
    assert result["attachments"][0]["filename"] == "report.pdf"


@pytest.mark.parametrize(
    ("body_limit", "expected", "truncated"),
    [(4, "Safe", True), (9, "Safe text", False), (20, "Safe text", False)],
)
def test_requested_preview_length_and_exact_boundary(
    body_limit: int, expected: str, truncated: bool
) -> None:
    """catch ignored caller limits and incorrect truncation at the exact boundary"""
    result = make_get_message(settings(), client_factory=FakeMessageClient)(
        "INBOX", 9, 101, body_limit=body_limit
    )

    assert result["body"] == expected
    assert result["body_truncated"] is truncated


def test_larger_request_recovers_full_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """catch a fixed preview ceiling that prevents agents from reading more"""
    monkeypatch.setattr(FakeMessageClient, "body", "a" * 4500)
    result = make_get_message(settings(), client_factory=FakeMessageClient)(
        "INBOX", 9, 101, body_limit=5000
    )

    assert result["body"] == "a" * 4500
    assert result["body_truncated"] is False


@pytest.mark.parametrize("body_limit", [0, -1])
def test_invalid_preview_limit_is_rejected_before_connection(body_limit: int) -> None:
    """catch invalid limits reaching IMAP or turning negative slicing into a preview"""

    def unexpected_connection(configuration: Settings) -> FakeMessageClient:
        raise AssertionError("invalid preview limit reached IMAP")

    tool = make_get_message(settings(), client_factory=unexpected_connection)
    with pytest.raises(ValueError, match="body_limit"):
        tool("INBOX", 9, 101, body_limit=body_limit)


def test_preview_does_not_bypass_parser_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """catch short previews accidentally bypassing the server's decoded body limit"""
    monkeypatch.setattr(FakeMessageClient, "body", "x" * 65537)
    tool = make_get_message(settings(), client_factory=FakeMessageClient)
    with pytest.raises(ValueError, match="body exceeds"):
        tool("INBOX", 9, 101, body_limit=10)
