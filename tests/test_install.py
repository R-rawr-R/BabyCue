import urllib.error
import urllib.request

import pytest

from babycue_server.http_server import RelayServer


def fetch(port: int, path: str):
    return urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3)


@pytest.fixture
def apk(tmp_path):
    path = tmp_path / "app-debug.apk"
    path.write_bytes(b"PK\x03\x04" + bytes(range(256)) * 400)
    return path


def test_apk_is_served_byte_for_byte_as_a_download(apk):
    with RelayServer("127.0.0.1", 0, apk_path=apk) as server, fetch(server.port, "/app.apk") as response:
        assert response.status == 200
        assert response.headers["Content-Type"] == "application/vnd.android.package-archive"
        assert 'filename="app-debug.apk"' in response.headers["Content-Disposition"]
        assert int(response.headers["Content-Length"]) == apk.stat().st_size
        assert response.read() == apk.read_bytes()


def test_install_page_links_to_the_download(apk):
    with RelayServer("127.0.0.1", 0, apk_path=apk) as server, fetch(server.port, "/install") as response:
        page = response.read().decode()
    assert "href='/app.apk'" in page and "Install unknown apps" in page


def test_without_an_apk_the_page_explains_and_the_download_is_404(tmp_path):
    with RelayServer("127.0.0.1", 0, apk_path=tmp_path / "missing.apk") as server:
        with fetch(server.port, "/install") as response:
            assert "not available" in response.read().decode()
        with pytest.raises(urllib.error.HTTPError) as error:
            fetch(server.port, "/app.apk")
        assert error.value.code == 404


def test_only_the_configured_file_can_be_downloaded(apk):
    with RelayServer("127.0.0.1", 0, apk_path=apk) as server:
        for path in ("/app.apk/../x", "/../app.apk", "/other.apk"):
            with pytest.raises(urllib.error.HTTPError) as error:
                fetch(server.port, path)
            assert error.value.code == 404


def test_streaming_still_works_while_the_apk_is_hosted(apk):
    with RelayServer("127.0.0.1", 0, apk_path=apk) as server:
        assert fetch(server.port, "/status").status == 200
