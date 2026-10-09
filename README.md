# BabyCue

A local, privacy-first video relay for infant monitoring. One phone films (the **input**), a Python
**server** on your PC receives the video, can run logic on every frame, and relays it to a second phone
(the **output**). Nothing leaves your local network. For now the server only passes the video through; it
does no detection and never shows invented results.

```
 Input phone                    PC: BabyCue server (Python)                  Output phone
 ┌────────────────┐  POST       ┌─────────────────────────────┐   GET        ┌─────────────────┐
 │ CameraX → JPEG │ ─────────▶  │ /ingest → FramePipeline ──┐  │ ◀─────────  │ /view → ImageView│
 └────────────────┘  /ingest    │          (your logic here) ▼  │   /view     └─────────────────┘
   BabyCue app       chunked    │            FrameHub (newest frame only) │    BabyCue app
   role: Input       HTTP       │ /status  (JSON)                          │    role: Output
                                └─────────────────────────────┘
```

## Quick start

Requirements: Python 3.11+, an Android phone or two (Android 7.0+), all on the **same trusted Wi-Fi**.

```powershell
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m babycue_server            # prints the address to type into the phones
```

1. Allow the server through Windows Firewall when prompted (inbound TCP **8080**, private networks).
2. Install the Android app on both phones. Build it once (`cd android; .\gradlew.bat :app:assembleDebug`, see
   [android/README.md](android/README.md)); the server then shares it: open the **install link it prints**
   (`http://<PC-IP>:8080/install`) in the phone's browser, download, and allow "Install unknown apps" when asked.
   Use `--apk path\to\app-debug.apk` to share a different file.
3. **Input phone**: choose *Input*, enter the address the server printed (e.g. `192.168.1.20:8080`), tap Start,
   allow the camera.
4. **Output phone**: choose *Output*, enter the same address, tap Start. You see the input phone's video.

No phone handy? Run `python -m babycue_server.devtools.fake_input` as a stand-in input and open
`http://localhost:8080/` in a PC browser to watch the relay.

## How it works

| Piece | Role |
|---|---|
| `babycue_server/http_server.py` | `RelayServer`: `POST /ingest` (one input at a time, else 409), `GET /view` (up to 4 viewers, else 503), `GET /status`, `GET /` (browser test page) |
| `babycue_server/hub.py` | `FrameHub`: keeps only the newest frame, so slow viewers skip frames instead of building a delay |
| `babycue_server/pipeline.py` | `FramePipeline`: the hook where future logic transforms or inspects each JPEG (passthrough today) |
| `babycue_server/bodyreader.py` | Interruptible socket/chunked-body readers (a vanished phone or server shutdown always frees the thread, also on Windows) |
| `babycue_server/protocol.py` | The wire contract; mirrored in `android/.../net/WireProtocol.kt` and checked by a test |
| `babycue_server/processing/` | Image-quality diagnostics and display enhancement, ready to be wired into the pipeline |
| `android/` | One Kotlin app, two roles: `FramePusher` (input) and `FrameReceiver` (output) |

**Wire protocol.** Input → server: `POST /ingest`, chunked body of `[uint32 big-endian length][JPEG]` records.
Server → output: `GET /view` as `multipart/x-mixed-replace` with a `Content-Length` per part (so a browser can
open it too).

### Adding logic

Add a function `(jpeg: bytes) -> bytes` to the pipeline in `babycue_server/__main__.py`
(`RelayServer(pipeline=FramePipeline([my_stage]))`). A stage that raises is logged and skipped, so it can never
stop the video. Stages run on the ingest thread; keep them fast or hand work to a worker thread.

## Privacy and security

- Video goes only phone → your PC → phone. No cloud, analytics, or telemetry. Nothing is recorded or written to disk.
- **The stream is unencrypted HTTP with no login.** Anyone on the same network who knows the address could send
  video to the server or watch it. Use a trusted WPA2/WPA3 network, never public Wi-Fi, and never forward the port
  on your router. Android is told to allow plain HTTP (`usesCleartextTraffic`) for this prototype.
- Streaming is tied to the app being in the foreground on both phones: leave the app or lock the phone and it
  stops (no foreground service yet).

## Testing

```powershell
pip install -r requirements-dev.txt
pytest
ruff check .
cd android; .\gradlew.bat :app:testDebugUnitTest :app:assembleDebug   # needs JDK 17 and the Android SDK
```

Python tests use real localhost sockets (hub, ingest protocol, viewers, relay end to end, pipeline, wire-contract
drift guard). Android JVM tests cover the pusher and receiver against local fake servers, the part parser,
reconnect/backoff, address parsing and screen logic. **Not yet verified:** anything on real phones or a real
network; see [docs/MANUAL_TESTS.md](docs/MANUAL_TESTS.md).

## Status and ideas

Done: relay of one input to up to four output viewers, reconnection on both phones, passthrough pipeline.
Next: server-side detection as pipeline stages, several named inputs, optional login/HTTPS, a foreground service so
streaming survives a locked screen.

See [docs/NETWORK.md](docs/NETWORK.md) for firewall and Wi-Fi troubleshooting.
