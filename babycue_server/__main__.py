"""Run the relay: ``python -m babycue_server [--host 0.0.0.0] [--port 8080]``."""

from __future__ import annotations

import argparse
import logging
import socket
import ssl
import time
from pathlib import Path

from babycue_server.certs import DEFAULT_DIR, ensure_certs
from babycue_server.db import Database
from babycue_server.detection import (
    DEFAULT_MODELS_DIR,
    DetectionSettings,
    build_worker,
    describe_device,
    missing_models,
    missing_packages,
    resolve_device,
)
from babycue_server.http_server import RelayServer
from babycue_server.protocol import CA_PATH, DEFAULT_PORT

DEFAULT_WEB = Path(__file__).resolve().parents[1] / "web" / "dist"


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


def load_detector(args: argparse.Namespace):
    """The safe-sleep worker, ``None`` when detection is off, or a ``str`` error that should stop the server."""
    if args.detect is False:
        print("Safe-sleep detection is off (--no-detect).")
        return None
    packages = missing_packages()
    if packages:
        if args.detect:
            return f"--detect needs the ML packages ({', '.join(packages)}). Install them: pip install -e .[ml]"
        print(f"Safe-sleep detection is off: missing {', '.join(packages)}. Install them: pip install -e .[ml]")
        return None
    models = missing_models(args.models_dir)
    if models:
        names = ", ".join(str(m) for m in models)
        return f"Missing model: {names}. Run 'git lfs pull', or start with --no-detect."
    try:
        device = resolve_device(args.device)
    except (RuntimeError, ValueError) as exc:
        return str(exc)
    if device == "cpu":
        print("WARNING: no usable GPU, so safe-sleep inference runs on the CPU (slow). For the GPU, install the")
        print("  CUDA build: pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126")
    print(f"Loading the safe-sleep models on {describe_device(device)}...")
    settings = DetectionSettings(
        models_dir=args.models_dir,
        device=device,
        yolo_confidence=args.yolo_conf,
        mp_threshold=args.mp_threshold,
        fidip_threshold=args.fidip_threshold,
    )
    return build_worker(settings)


def _unit(value: str) -> float:
    number = float(value)
    if not 0 <= number <= 1:
        raise argparse.ArgumentTypeError("must be between 0 and 1")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: all interfaces)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--web", type=Path, default=DEFAULT_WEB, help="built website to serve (default: web/dist)")
    parser.add_argument("--http", action="store_true", help="plain HTTP: the phone camera will NOT work (browsers need HTTPS)")
    parser.add_argument("--cert-dir", type=Path, default=DEFAULT_DIR, help="where the local CA and server certificate live")
    parser.add_argument(
        "--db", type=Path, default=DEFAULT_DIR / "babycue.db", help="SQLite file for the baby's name and the detection log"
    )
    parser.add_argument("--log-level", default="INFO")
    ml = parser.add_argument_group("safe-sleep detection")
    ml.add_argument(
        "--detect",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="sleep-position and crib-hazard alerts (default: on when the ML packages are installed)",
    )
    ml.add_argument("--models-dir", type=Path, default=DEFAULT_MODELS_DIR, help="model files (default: models/)")
    ml.add_argument("--device", default="auto", help="auto (GPU when available), cpu, cuda, or a GPU index such as 0; a GPU that is missing is an error")
    ml.add_argument("--yolo-conf", type=_unit, default=0.65, help="crib-hazard confidence threshold")
    ml.add_argument("--mp-threshold", type=_unit, default=0.5, help="MediaPipe keypoint threshold")
    ml.add_argument("--fidip-threshold", type=_unit, default=0.2, help="FiDIP keypoint threshold")
    args = parser.parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    detector = load_detector(args)
    if isinstance(detector, str):
        print(detector)
        return 2

    db = Database(args.db)
    baby = db.baby()
    print(f"Database: {args.db} ({'baby: ' + baby['name'] if baby else 'no baby yet: the first phone to connect asks for the name'})")

    addresses = lan_addresses()
    context = None
    ca_path = None
    if not args.http:
        certs = ensure_certs([*addresses, socket.gethostname()], args.cert_dir)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(certs.cert, certs.key)
        ca_path = certs.ca
    scheme = "http" if args.http else "https"
    try:
        server = RelayServer(
            args.host, args.port, web_root=args.web, ca_path=ca_path, ssl_context=context, detector=detector, db=db
        ).start()
    except OSError as exc:
        print(f"Cannot listen on {args.host}:{args.port}: {exc}")
        return 1
    print("BabyCue is running. Nothing leaves your home network. Use a trusted Wi-Fi only.")
    if detector is not None:
        print("  Safe-sleep alerts are on: sleep position and toys in the crib. They support, never replace,")
        print("  safe-sleep practice: baby on their back, in a bare crib.")
    print("Open this address in Chrome on each phone (same Wi-Fi):")
    for address in addresses or ["?"]:
        print(f"      {scheme}://{address}:{server.port}/")
    if not args.http:
        print("  First visit: the browser warns the certificate is not trusted. Choose Advanced > Proceed;")
        print("  the camera then works. To install it as an app, first install the certificate from")
        print(f"      {scheme}://{(addresses or ['?'])[0]}:{server.port}{CA_PATH}")
        print("  (Android: Settings > Security > Install a certificate > CA certificate), then reopen the site.")
    else:
        print("  Plain HTTP: phones will refuse camera access and app install. Use it only for testing on this PC.")
    if not (args.web / "index.html").is_file():
        print(f"  (No website at {args.web}. Build it: cd web; npm install; npm run build)")
    print(f"  Check on this PC: {scheme}://localhost:{server.port}/")
    print("Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
