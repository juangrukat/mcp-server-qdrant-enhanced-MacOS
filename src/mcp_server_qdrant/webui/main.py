"""Entry point: `mcp-server-qdrant-webui --host 127.0.0.1 --port 8765`."""

import argparse

import uvicorn

from mcp_server_qdrant.webui.api import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="mcp-server-qdrant-enhanced REST API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--cors",
        nargs="*",
        default=None,
        help="Allowed CORS origins (e.g. http://localhost:3000)",
    )
    parser.add_argument("--reload", action="store_true", help="Auto-reload on code changes (dev only)")
    args = parser.parse_args()

    app = create_app(cors_origins=args.cors)
    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
