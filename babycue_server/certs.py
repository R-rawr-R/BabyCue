"""A small local certificate authority, so phones can open the site over HTTPS.

Browsers only allow the camera and "install as app" on secure origins. ``http://192.168.x.x`` is not one, so the
server generates its own CA and a server certificate for this PC's addresses. Open the site once and accept the
warning (camera works), or install ``/ca.crt`` on the phone so the browser fully trusts it (then it also installs
as an app). Nothing here leaves your PC.
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import json
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

DEFAULT_DIR = Path.home() / ".babycue"
_LEAF_DAYS = 800
_RENEW_BEFORE = dt.timedelta(days=30)


@dataclass(frozen=True)
class Certs:
    ca: Path
    cert: Path
    key: Path


def _write_key(path: Path, key: ec.EllipticCurvePrivateKey) -> None:
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )


def _name(common: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "BabyCue"), x509.NameAttribute(NameOID.COMMON_NAME, common)])


def _load_or_create_ca(folder: Path) -> tuple[x509.Certificate, ec.EllipticCurvePrivateKey]:
    ca_pem, key_pem = folder / "ca.crt", folder / "ca.key"
    if ca_pem.is_file() and key_pem.is_file():
        cert = x509.load_pem_x509_certificate(ca_pem.read_bytes())
        key = serialization.load_pem_private_key(key_pem.read_bytes(), password=None)
        if cert.not_valid_after_utc > dt.datetime.now(dt.UTC) + _RENEW_BEFORE and isinstance(key, ec.EllipticCurvePrivateKey):
            return cert, key
    key = ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(_name("BabyCue local CA"))
        .issuer_name(_name("BabyCue local CA"))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, key_cert_sign=True, crl_sign=True, content_commitment=False,
                key_encipherment=False, data_encipherment=False, key_agreement=False,
                encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    ca_pem.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    _write_key(key_pem, key)
    return cert, key


def _san(hosts: list[str]) -> list[x509.GeneralName]:
    names: list[x509.GeneralName] = []
    for host in hosts:
        try:
            names.append(x509.IPAddress(ipaddress.ip_address(host)))
        except ValueError:
            names.append(x509.DNSName(host))
    return names


def ensure_certs(hosts: list[str], folder: Path | None = None) -> Certs:
    """CA and server certificate for ``hosts`` (IPs and names), created or renewed only when needed."""
    folder = Path(folder) if folder else DEFAULT_DIR
    folder.mkdir(parents=True, exist_ok=True)
    wanted = sorted({"localhost", "127.0.0.1", *hosts})
    certs = Certs(folder / "ca.crt", folder / "server.crt", folder / "server.key")
    ca_cert, ca_key = _load_or_create_ca(folder)

    meta = folder / "server.json"
    try:
        current = json.loads(meta.read_text())
        cert = x509.load_pem_x509_certificate(certs.cert.read_bytes())
        ca_ok = cert.issuer == ca_cert.subject
        fresh = cert.not_valid_after_utc > dt.datetime.now(dt.UTC) + _RENEW_BEFORE
        if current == wanted and ca_ok and fresh and certs.key.is_file():
            return certs
    except (OSError, ValueError):
        pass

    key = ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(_name("BabyCue server"))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=_LEAF_DAYS))
        .add_extension(x509.SubjectAlternativeName(_san(wanted)), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    certs.cert.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    _write_key(certs.key, key)
    meta.write_text(json.dumps(wanted))
    return certs
