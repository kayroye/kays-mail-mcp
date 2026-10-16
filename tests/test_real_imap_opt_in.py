"""hold the real-account read-only inventory smoke test behind an explicit opt-in
require a disposable account before this test contacts an IMAP server
"""

from __future__ import annotations

import os

import pytest

from imap_mcp.config import load_settings
from imap_mcp.imap_client import ImapClient


@pytest.mark.skipif(
    os.environ.get("IMAP_INTEGRATION_TEST") != "1",
    reason="set IMAP_INTEGRATION_TEST=1 with a disposable mailbox to opt in",
)
def test_real_account_readonly_inventory() -> None:
    """check an opted-in account exposes only configured mailbox names"""
    settings = load_settings()
    with ImapClient(settings) as client:
        mailboxes = client.list_mailboxes()

    assert set(mailboxes).issubset(settings.allowed_mailboxes)
