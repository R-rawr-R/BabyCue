import http.client
import ssl
import urllib.error
import urllib.request

import pytest

from babycue_server.certs import ensure_certs
from babycue_server.http_server import RelayServer
from tests.conftest import wait_until
from tests.helpers import make_jpeg


def fetch(port: int, path: str):
    return urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3)


@pytest.fixture
def site(tmp_path):
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><title>BabyCue app</title>")
    (root / "assets" / "app-abc123.js").write_text("console.log(1)")
    (root / "manifest.webmanifest").write_text('{"name":"BabyCue"}')
    (tmp_path / "secret.txt").write_text("nope")
    return root


def test_the_website_is_served_at_the_root(site):
    with RelayServer("127.0.0.1", 0, web_root=site) as server, fetch(server.port, "/") as response:
        assert response.status == 200
        assert "BabyCue app" in response.read().decode()
        assert response.headers["Cache-Control"] == "no-cache"


def test_assets_are_cached_for_a_year_and_typed(site):
    with RelayServer("127.0.0.1", 0, web_root=site) as server, fetch(server.port, "/assets/app-abc123.js") as response:
        assert "immutable" in response.headers["Cache-Control"]
        assert "javascript" in response.headers["Content-Type"]


def test_manifest_has_the_pwa_content_type(site):
    with RelayServer("127.0.0.1", 0, web_root=site) as server, fetch(server.port, "/manifest.webmanifest") as response:
        assert response.headers["Content-Type"].startswith("application/manifest+json")


def test_unknown_page_paths_open_the_app_but_missing_files_are_404(site):
    with RelayServer("127.0.0.1", 0, web_root=site) as server:
        with fetch(server.port, "/watch") as response:
            assert "BabyCue app" in response.read().decode()
        for path in ("/assets/missing.js", "/nope.png"):
            with pytest.raises(urllib.error.HTTPError) as error:
                fetch(server.port, path)
            assert error.value.code == 404


def test_paths_cannot_escape_the_website_folder(site):
    with RelayServer("127.0.0.1", 0, web_root=site) as server:
        for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/../../secret.txt"):
            try:
                with fetch(server.port, path) as response:
                    assert "nope" not in response.read().decode()
            except urllib.error.HTTPError as error:
                assert error.code == 404


def test_without_a_built_website_a_test_page_is_shown(tmp_path):
    with RelayServer("127.0.0.1", 0, web_root=tmp_path) as server, fetch(server.port, "/") as response:
        assert "not built yet" in response.read().decode()


def test_the_ca_certificate_is_offered_for_download(tmp_path):
    certs = ensure_certs(["192.168.1.20"], tmp_path / "certs")
    with RelayServer("127.0.0.1", 0, ca_path=certs.ca) as server, fetch(server.port, "/ca.crt") as response:
        assert response.headers["Content-Type"] == "application/x-x509-ca-cert"
        assert response.read() == certs.ca.read_bytes()


def test_no_ca_means_404(tmp_path):
    with RelayServer("127.0.0.1", 0) as server, pytest.raises(urllib.error.HTTPError) as error:
        fetch(server.port, "/ca.crt")
    assert error.value.code == 404


def test_certificates_are_reused_and_renewed_for_new_addresses(tmp_path):
    first = ensure_certs(["192.168.1.20"], tmp_path)
    stamp = first.cert.read_bytes()
    assert ensure_certs(["192.168.1.20"], tmp_path).cert.read_bytes() == stamp
    ca = first.ca.read_bytes()
    assert ensure_certs(["192.168.1.99"], tmp_path).cert.read_bytes() != stamp
    assert first.ca.read_bytes() == ca  # phones that trusted the CA keep trusting it


@pytest.fixture
def tls_relay(tmp_path):
    certs = ensure_certs([], tmp_path)
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(certs.cert, certs.key)
    client_context = ssl.create_default_context(cafile=str(certs.ca))
    server = RelayServer("127.0.0.1", 0, input_timeout=2.0, ssl_context=server_context).start()
    yield server, client_context
    server.stop()


def test_frames_and_status_work_over_https(tls_relay):
    server, context = tls_relay
    frame = make_jpeg(1)
    conn = http.client.HTTPSConnection("localhost", server.port, timeout=3, context=context)
    conn.request("POST", "/frame", body=frame, headers={"Content-Type": "image/jpeg"})
    assert conn.getresponse().status == 204
    conn.close()
    assert server.hub.latest().data == frame
    with urllib.request.urlopen(f"https://localhost:{server.port}/status", timeout=3, context=context) as response:
        assert b'"input_connected": true' in response.read()


def test_a_viewer_over_https_receives_frames_and_frees_its_slot(tls_relay):
    server, context = tls_relay
    frame = make_jpeg(2)
    conn = http.client.HTTPSConnection("localhost", server.port, timeout=3, context=context)
    conn.request("GET", "/view")
    response = conn.getresponse()
    assert response.status == 200
    assert wait_until(lambda: server.hub.stats()["viewers"] == 1)

    poster = http.client.HTTPSConnection("localhost", server.port, timeout=3, context=context)
    poster.request("POST", "/frame", body=frame)
    assert poster.getresponse().status == 204
    poster.close()
    received = b""
    while frame not in received:
        chunk = response.read1(len(frame) + 400)
        assert chunk, "the stream ended before the frame arrived"
        received += chunk

    response.close()  # the response holds the socket open until it is closed too
    conn.close()
    assert wait_until(lambda: server.hub.stats()["viewers"] == 0, timeout=6)


def test_a_client_that_distrusts_the_certificate_does_not_wedge_the_server(tls_relay):
    server, _ = tls_relay
    with pytest.raises(ssl.SSLError):
        http.client.HTTPSConnection("localhost", server.port, timeout=3, context=ssl.create_default_context()).request(
            "GET", "/status"
        )
    _, good = tls_relay
    with urllib.request.urlopen(f"https://localhost:{server.port}/status", timeout=3, context=good) as response:
        assert response.status == 200
