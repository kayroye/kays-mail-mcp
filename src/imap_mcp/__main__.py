"""start the authenticated MCP endpoint from validated environment settings
stop before serving when IMAP or OIDC configuration is incomplete
"""

from .auth import create_auth, load_auth_settings
from .config import SettingsError, load_settings
from .server import create_server


def main() -> None:
    """load configuration, build the authenticated server, and start HTTP transport"""
    # load both settings sets before starting so auth errors cannot expose a partial service
    try:
        settings = load_settings()
        auth = create_auth(load_auth_settings())
    except SettingsError as exc:
        raise SystemExit(str(exc)) from None
    create_server(settings, auth=auth).run(
        transport="http",
        host=settings.http.host,
        port=settings.http.port,
        stateless_http=True,
        json_response=True,
        show_banner=False,
        uvicorn_config={"access_log": False, "proxy_headers": False},
    )


if __name__ == "__main__":
    main()
