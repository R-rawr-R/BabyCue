"""Run the relay: ``python -m babycue_server [--host 0.0.0.0] [--port 8080]``."""

from __future__ import annotations

import argparse
import logging
import socket
import time
from pathlib import Path

from babycue_server.http_server import RelayServer
from babycue_server.protocol import DEFAULT_PORT, INGEST_PATH, VIEW_PATH

DEFAULT_APK = Path(__file__).resolve().parents[1] / "android/app/build/outputs/apk/debug/app-debug.apk"


def lan_addresses() -> list[str]:
    """Best-effort private IPv4 addresses of this machine (no packets are sent)."""
    found: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 1))
            found.append(probe.getsockname()[0])
    except OSError:
        pass
    try:
        for address in socket.gethostbyname_ex(socket.gethostname())[2]:
            if address not in found and not address.startswith("127."):
                found.append(address)
    except OSError:
        pass
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: all interfaces)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--apk", type=Path, default=DEFAULT_APK, help="Android app file to share at /install")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    try:
        server = RelayServer(args.host, args.port, apk_path=args.apk).start()
    except OSError as exc:
        print(f"Cannot listen on {args.host}:{args.port}: {exc}")
        return 1
    addresses = lan_addresses()
    print("BabyCue server running. Plain HTTP, no encryption: use a trusted local network only.")
    print(f"  Input phone  -> server address: {', '.join(f'{a}:{server.port}' for a in addresses) or '?'}")
    print(f"  Output phone -> same address (it reads {VIEW_PATH}; the input phone posts to {INGEST_PATH})")
    print(f"  Check in a browser on this PC: http://localhost:{server.port}/")
    if args.apk.is_file():
        print("  Install the app on any phone on this network by opening:")
        for address in addresses:
            print(f"      http://{address}:{server.port}/install")
    else:
        print(f"  (No app file at {args.apk}; build it or pass --apk to share the Android app at /install.)")
    print("Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
