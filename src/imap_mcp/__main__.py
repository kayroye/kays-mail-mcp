"""Serve the authenticated MCP endpoint; incomplete auth configuration fails closed."""

from .auth import create_auth, load_auth_settings
from .config import SettingsError, load_settings
from .server import create_server


def main() -> None:
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
