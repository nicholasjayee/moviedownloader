"""Parse launcher options and reserve a listening socket before starting Uvicorn."""

import argparse
import errno
import json
import os
import socket
from pathlib import Path

import uvicorn
from uvicorn.supervisors import ChangeReload

from moviebox_app.config import Settings
from moviebox_app.launcher_network import network_addresses


def port_number(value: str) -> int:
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("port must be an integer from 1 to 65535") from None
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be an integer from 1 to 65535")
    return port


def reserve_port(host: str, start_port: int) -> tuple[socket.socket, int]:
    """Keep the socket open so another process cannot claim the selected port."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    for port in range(start_port, 65536):
        listener = socket.socket(family, socket.SOCK_STREAM)
        try:
            # Avoid SO_REUSEADDR: on macOS it can let a wildcard listener share
            # a port already occupied on localhost, making the local URL hang.
            listener.bind((host, port))
            listener.listen(socket.SOMAXCONN)
            return listener, port
        except OSError as exc:
            listener.close()
            if exc.errno != errno.EADDRINUSE:
                raise
            print(f"Port {port} is in use; trying the next port.", flush=True)
    raise OSError(errno.EADDRINUSE, f"No available port from {start_port} to 65535.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run Moviebox, advancing to the next port when the requested port is busy."
    )
    parser.add_argument("port", nargs="?", type=port_number, help="starting port (default: 8765)")
    parser.add_argument("-p", "--port", dest="port_option", type=port_number, help="starting port")
    parser.add_argument(
        "--dev",
        action="store_true",
        help="enable network access and reload on Python, HTML, CSS, or JavaScript edits",
    )
    args = parser.parse_args(argv)
    if args.port is not None and args.port_option is not None:
        parser.error("specify the port either as a positional argument or with --port, not both")

    settings = Settings()
    start_port = args.port_option or args.port or settings.port
    bind_host = "0.0.0.0" if args.dev else settings.host
    addresses = network_addresses() if args.dev else []
    if args.dev:
        # The reload subprocess reads its host allowlist from the environment.
        os.environ["MOVIEBOX_ALLOWED_HOSTS"] = json.dumps(
            list(dict.fromkeys([*settings.allowed_hosts, *addresses]))
        )
    try:
        listener, selected_port = reserve_port(bind_host, start_port)
    except OSError as exc:
        parser.exit(1, f"Could not start Moviebox: {exc}\n")

    with listener:
        local_host = "127.0.0.1" if args.dev else settings.host
        host = f"[{local_host}]" if ":" in local_host else local_host
        if args.dev:
            print("Moviebox (development)", flush=True)
            print(f"  Local:   http://127.0.0.1:{selected_port}", flush=True)
            for address in addresses:
                print(f"  Network: http://{address}:{selected_port}", flush=True)
            if not addresses:
                print("  Network: unavailable (no LAN IPv4 address detected)", flush=True)
        else:
            print(f"Moviebox: http://{host}:{selected_port}", flush=True)
        project_dir = Path(__file__).resolve().parent.parent
        config = uvicorn.Config(
            "moviebox_app.app:create_app",
            factory=True,
            host=bind_host,
            port=selected_port,
            reload=args.dev,
            reload_dirs=[str(project_dir / "moviebox_app")] if args.dev else None,
            reload_includes=["*.py", "*.html", "*.css", "*.js"] if args.dev else None,
            reload_excludes=[
                str(path)
                for path in [
                    settings.data_dir.resolve(),
                    settings.download_dir.resolve(),
                    project_dir / ".venv",
                    project_dir / ".git",
                ]
                # Uvicorn treats nonexistent paths as globs, which cannot be absolute.
                if path.is_dir()
            ]
            if args.dev
            else None,
        )
        server = uvicorn.Server(config)
        try:
            if args.dev:
                print(
                    "Development mode: watching source files. Refresh the browser after edits.",
                    flush=True,
                )
                listener.set_inheritable(True)
                ChangeReload(config, target=server.run, sockets=[listener]).run()
            else:
                server.run(sockets=[listener])
        except KeyboardInterrupt:
            # Uvicorn re-raises Ctrl+C after completing its graceful shutdown.
            # Treat it as a normal exit; the context manager closes the socket.
            pass
