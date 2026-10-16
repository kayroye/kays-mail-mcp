from __future__ import annotations

from email.message import EmailMessage

import pytest

from imap_mcp.mime_parser import MimeParseError, attachment_content, parse_message


def multipart_message() -> bytes:
    message = EmailMessage()
    message["Subject"] = "=?utf-8?b?UG9zdGEg4pyT?="
    message["From"] = "Sender <sender@example.test>"
    message["To"] = "Recipient <recipient@example.test>"
    message["Message-ID"] = "<fixture@example.test>"
    message.set_content("Safe plain text body.")
    message.add_alternative(
        '<p>Unsafe HTML body <a href="https://tracker.example.test/id">link</a></p>'
        "<script>ignore()</script>",
        subtype="html",
    )
    message.add_attachment(
        b"fixture pdf", maintype="application", subtype="pdf", filename="report.pdf"
    )
    return message.as_bytes()


def test_parse_message_prefers_plain_text_and_decodes_headers() -> None:
    parsed = parse_message(multipart_message(), max_body_bytes=1024)

    assert parsed.subject == "Posta ✓"
    assert parsed.sender == "Sender <sender@example.test>"
    assert parsed.recipients == ("Recipient <recipient@example.test>",)
    assert parsed.body == "Safe plain text body."
    assert parsed.attachments[0].filename == "report.pdf"
    assert parsed.attachments[0].content_type == "application/pdf"


def test_html_body_is_converted_to_plain_text_without_attributes_or_scripts() -> None:
    message = EmailMessage()
    message.set_content(
        '<p>Visible <a href="https://tracker.example.test/id">text</a></p><script>bad()</script>',
        subtype="html",
    )

    parsed = parse_message(message.as_bytes(), max_body_bytes=1024)

    assert parsed.body == "Visible text"
    assert "tracker" not in parsed.body
    assert "bad" not in parsed.body


def test_parse_message_rejects_oversized_body() -> None:
    message = EmailMessage()
    message.set_content("x" * 20)

    with pytest.raises(MimeParseError, match="body exceeds"):
        parse_message(message.as_bytes(), max_body_bytes=10)


def test_attachment_content_returns_only_allowed_attachment() -> None:
    attachment, content = attachment_content(
        multipart_message(), attachment_index=0, max_attachment_bytes=1024
    )

    assert attachment.filename == "report.pdf"
    assert content == b"fixture pdf"


def test_attachment_content_rejects_unknown_type_and_oversize() -> None:
    message = EmailMessage()
    message.set_content("body")
    message.add_attachment(
        b"binary", maintype="application", subtype="x-msdownload", filename="run.exe"
    )

    with pytest.raises(MimeParseError, match="not allowed"):
        attachment_content(message.as_bytes(), attachment_index=0, max_attachment_bytes=1024)

    with pytest.raises(MimeParseError, match="size limit"):
        attachment_content(multipart_message(), attachment_index=0, max_attachment_bytes=1)
