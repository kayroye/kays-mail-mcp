"""verify exclusive connection reuse, expiry, recovery and settings isolation"""

from __future__ import annotations

import imaplib
from collections.abc import Iterator
from dataclasses import replace
from threading import Event

import pytest
from test_imap_client import FakeConnection, settings

from imap_mcp import imap_client
from imap_mcp.errors import ImapAuthenticationError
from imap_mcp.imap_client import ImapClient


class ReusableConnection(FakeConnection):
    """count real client lifecycle calls without contacting an IMAP provider"""

    logins = 0
    probes = 0
    stale = False

    def login(self, user: str, password: str) -> tuple[str, list[bytes]]:
        self.logins += 1
        return super().login(user, password)

    def noop(self) -> tuple[str, list[bytes]]:
        self.probes += 1
        if self.stale:
            raise imaplib.IMAP4.abort("fixture connection expired")
        return "OK", [b"ready"]


@pytest.fixture
def connections(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[ReusableConnection]]:
    """replace only network creation and close production pools after each test"""
    created: list[ReusableConnection] = []

    def create(*_: object) -> ReusableConnection:
        connection = ReusableConnection()
        created.append(connection)
        return connection

    monkeypatch.setattr(imap_client, "_open_connection", create)
    yield created
    imap_client.close_connection_pools()


def test_successful_calls_reuse_one_authenticated_connection(
    connections: list[ReusableConnection],
) -> None:
    for _ in range(2):
        with ImapClient(settings()) as client:
            assert client.list_mailboxes() == ("INBOX",)
    assert len(connections) == 1
    assert connections[0].logins == 1
    assert connections[0].probes == 1
    assert connections[0].logged_out is False


def test_simultaneous_callers_never_share_one_connection(
    connections: list[ReusableConnection],
) -> None:
    with ImapClient(settings()) as first:
        with ImapClient(settings()) as second:
            first.list_mailboxes()
            second.list_mailboxes()
            assert len(connections) == 2
            assert all(c.logins == 1 and c.probes == 0 for c in connections)


def test_failed_operation_discards_connection(connections: list[ReusableConnection]) -> None:
    with pytest.raises(RuntimeError):
        with ImapClient(settings()):
            raise RuntimeError("synthetic operation failed")
    with ImapClient(settings()) as client:
        client.list_mailboxes()
    assert len(connections) == 2
    assert connections[0].logged_out is True


def test_stale_session_is_replaced_before_operation(connections: list[ReusableConnection]) -> None:
    with ImapClient(settings()) as client:
        client.list_mailboxes()
    connections[0].stale = True
    with ImapClient(settings()) as client:
        assert client.list_mailboxes() == ("INBOX",)
    assert len(connections) == 2
    assert connections[0].logged_out is True
    assert connections[1].logins == 1


def test_credentials_do_not_share_a_pool(connections: list[ReusableConnection]) -> None:
    for configuration in (settings(), replace(settings(), password="another-password")):
        with ImapClient(configuration) as client:
            client.list_mailboxes()
    assert len(connections) == 2


def test_reused_session_reselects_and_rechecks_uidvalidity(
    connections: list[ReusableConnection],
) -> None:
    with ImapClient(settings()) as client:
        client.fetch_rfc822("INBOX", 42, 101)
    with ImapClient(settings()) as client:
        with pytest.raises(ValueError, match="mailbox changed"):
            client.fetch_rfc822("Archive", 42, 100)
    assert len(connections) == 1
    assert connections[0].selected == [('"INBOX"', True), ('"Archive"', True)]


def test_zero_idle_lifetime_disables_reuse(connections: list[ReusableConnection]) -> None:
    configuration = replace(settings(), connection_idle_seconds=0)
    for _ in range(2):
        with ImapClient(configuration) as client:
            client.list_mailboxes()
    assert len(connections) == 2
    assert all(c.logged_out for c in connections)


def test_idle_timer_closes_connection_without_another_request(
    connections: list[ReusableConnection],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """catch idle connections remaining open forever when no later request arrives"""
    closed = Event()
    original_logout = ReusableConnection.logout

    def logout(self: ReusableConnection) -> tuple[str, list[bytes]]:
        result = original_logout(self)
        closed.set()
        return result

    monkeypatch.setattr(ReusableConnection, "logout", logout)
    with ImapClient(replace(settings(), connection_idle_seconds=1)) as client:
        client.list_mailboxes()
    assert closed.wait(timeout=2)
    assert connections[0].logged_out is True


def test_checked_out_connection_is_not_closed_by_its_old_idle_timer(
    connections: list[ReusableConnection],
) -> None:
    configuration = replace(settings(), connection_idle_seconds=1)
    with ImapClient(configuration) as client:
        client.list_mailboxes()
    with ImapClient(configuration) as client:
        assert not Event().wait(timeout=1.1)
        assert connections[0].logged_out is False
        assert client.list_mailboxes() == ("INBOX",)


def test_failed_login_does_not_poison_pool_or_consume_a_slot(
    connections: list[ReusableConnection],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_login = ReusableConnection.login
    attempts = 0

    def login(self: ReusableConnection, user: str, password: str) -> tuple[str, list[bytes]]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise imaplib.IMAP4.error("synthetic authentication failure")
        return original_login(self, user, password)

    monkeypatch.setattr(ReusableConnection, "login", login)
    with pytest.raises(ImapAuthenticationError):
        with ImapClient(settings()):
            pytest.fail("failed login was accepted")
    with ImapClient(settings()) as client:
        assert client.list_mailboxes() == ("INBOX",)
    assert len(connections) == 2
    assert connections[0].logged_out is True
