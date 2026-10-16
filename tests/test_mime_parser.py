"""verify MIME normalization, size checks, and part-count bounds
exercise the safe outputs consumed by message and attachment tools
"""

from __future__ import annotations

from email.message import EmailMessage

import pytest

from imap_mcp.mime_parser import MimeParseError, attachment_content, parse_message


def multipart_message() -> bytes:
    """build a multipart fixture with encoded headers, plain text, HTML, and a PDF"""
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
    """check normalized headers, plain text preference, and attachment inventory"""
    parsed = parse_message(multipart_message(), max_body_bytes=1024)

    assert parsed.subject == "Posta ✓"
    assert parsed.sender == "Sender <sender@example.test>"
    assert parsed.recipients == ("Recipient <recipient@example.test>",)
    assert parsed.body == "Safe plain text body."
    assert parsed.attachments[0].filename == "report.pdf"
    assert parsed.attachments[0].content_type == "application/pdf"


def test_html_body_is_converted_to_plain_text_without_attributes_or_scripts() -> None:
    """check HTML output retains visible text and drops markup attributes and scripts"""
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
    """check the configured body cap is applied before returning decoded text"""
    message = EmailMessage()
    message.set_content("x" * 20)

    with pytest.raises(MimeParseError, match="body exceeds"):
        parse_message(message.as_bytes(), max_body_bytes=10)


def test_attachment_content_returns_only_allowed_attachment() -> None:
    """check an explicitly indexed allowed attachment returns its bytes and metadata"""
    attachment, content = attachment_content(
        multipart_message(), attachment_index=0, max_attachment_bytes=1024
    )

    assert attachment.filename == "report.pdf"
    assert content == b"fixture pdf"


def test_attachment_content_rejects_unknown_type_and_oversize() -> None:
    """check attachment type policy and configured byte cap reject unsafe payloads"""
    message = EmailMessage()
    message.set_content("body")
    message.add_attachment(
        b"binary", maintype="application", subtype="x-msdownload", filename="run.exe"
    )

    with pytest.raises(MimeParseError, match="not allowed"):
        attachment_content(message.as_bytes(), attachment_index=0, max_attachment_bytes=1024)

    with pytest.raises(MimeParseError, match="size limit"):
        attachment_content(multipart_message(), attachment_index=0, max_attachment_bytes=1)


def test_mime_part_bomb_is_rejected_before_building_unbounded_objects() -> None:
    """check both message and attachment paths share the MIME part-count boundary"""
    raw = (
        b"Content-Type: multipart/mixed; boundary=x\r\n\r\n"
        + (b"--x\r\nContent-Type: text/plain\r\n\r\ny\r\n" * 300)
        + b"--x--\r\n"
    )
    with pytest.raises(MimeParseError, match="MIME part limit"):
        parse_message(raw, max_body_bytes=1024)
    with pytest.raises(MimeParseError, match="MIME part limit"):
        attachment_content(raw, attachment_index=0, max_attachment_bytes=1024)


@pytest.mark.parametrize(
    "raw",
    [b"X: y\n" * 250001, b"Subject: " + b"x" * 1048577 + b"\n\nbody"],
    ids=["many-lines", "long-line"],
)
def test_pathological_physical_lines_are_rejected_before_parser_allocation(raw: bytes) -> None:
    """check many short lines and one oversized line are rejected at parse entry"""
    with pytest.raises(MimeParseError, match="line limit"):
        parse_message(raw, max_body_bytes=1024)
