# BabyCue

A local, privacy-first video relay for infant monitoring. One phone films (the **baby phone**), a Python
**server** on your PC receives the video, can run logic on every frame, and relays it to a second phone
(the **parent phone**). The phones use a normal website (React) that the PC itself serves, and which can be
installed as an app (PWA). Nothing leaves your local network. With the optional models installed, the server also
watches for the two main safe-sleep risks: a baby who rolls off their back, and toys in the crib. It never shows
invented results.

```
 Baby phone (browser/PWA)       PC: BabyCue server (Python)                Parent phone (browser/PWA)
 ┌────────────────┐  POST       ┌──────────────────────────────┐   GET       ┌─────────────────┐
 │ camera → JPEG  │ ─────────▶  │ /frame → FramePipeline ──┐   │ ◀────────   │ /view  → live   │
 └────────────────┘  /frame     │   (your logic here)      ▼   │   /view     │ /status → alerts│
                                │   FrameHub (newest frame)    │             └─────────────────┘
   serves the website:  GET /   │   /status (JSON)  /ca.crt    │
                                └──────────────────────────────┘
```

## Quick start

Requirements: Python 3.11+, Node 20+ (only to build the website), phones on the **same trusted Wi-Fi**.

```powershell
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-ml.txt            # optional: safe-sleep detection (see below)
cd web; npm install; npm run build; cd ..     # builds the website into web/dist
python -m babycue_server                      # prints the address to open on the phones
```

1. Allow the server through Windows Firewall when prompted (inbound TCP **8080**, private networks).
2. On **each phone**, open the `https://<PC-IP>:8080/` address the server printed, in Chrome (Android) or Safari
   (iPhone). The first time, the browser warns that the certificate isn't trusted (it is the PC's own, made on your
   machine): choose **Advanced, Proceed**. The camera works from then on.
3. **Install it as an app.** Chrome menu (⋮) → **Install app** / **Add to Home screen**; Safari: Share → **Add to
   Home Screen**. For a full install on Android (no certificate warning, own window and icon), first install the PC's
   certificate: open `https://<PC-IP>:8080/ca.crt`, then Settings → Security → *Install a certificate* → *CA
   certificate*, and reopen the site.
4. **Baby phone**: choose *Baby phone*, tap Connect, allow the camera. Point it at the crib and keep it plugged in.
5. **Parent phone**: choose *Watch*, tap Connect. You see the video, how the camera is doing, and a history of what
   happened.

No phone handy? Run `python -m babycue_server.devtools.fake_input` as a stand-in baby phone and open
`https://localhost:8080/` on the PC. For website development, `cd web; npm run dev` (it proxies to the running
server).

## Safe-sleep detection

The AAP guidance for preventing sudden unexpected infant death (SUID/SIDS) is: on the **back**, in a **bare crib**.
With the `ml` extra installed, the server checks both on the baby phone's video. It runs beside the relay on a
background thread that always takes the newest frame, so the models never slow the video.

| Check | Models | What the parent phone shows |
|---|---|---|
| **Sleep position / roll-over** | MediaPipe Pose. When MediaPipe loses the torso (covered or unusual poses), FiDIP takes over; FiDIP is an infant-specific HRNet. The position counts once it has held for 8 analyses in a row. | *Sleep position* card. Tummy raises a **critical** alert, "Baby is on their tummy". On a side raises a **heads-up**. |
| **Crib hazards** | YOLO26n-seg trained on CribHD-T (`hard-toy`, `soft-toy`). An object counts once it is seen in 3 of the last 5 analyses. | *Crib check* card listing each toy, its confidence, and whether it is near the baby. Raises a **heads-up**, "Toy in the crib". |

All models live in [`models/`](models/README.md), stored with Git LFS (`git lfs install`, then `git lfs pull`). The
FiDIP code is vendored in `babycue_server/detection/fidip/`. Nothing outside this repository is used.

- Install `pip install -r requirements-ml.txt` (or `pip install -e .[ml]`). Without these packages the server runs as
  a plain relay and says so.
- All inference runs on the PC; the phones only film, encode and show pictures. For an NVIDIA GPU, swap in the CUDA
  build of PyTorch afterwards (plain `pip install torch` on Windows is CPU-only):
  `pip install --force-reinstall --no-deps torch torchvision --index-url https://download.pytorch.org/whl/cu126`.
  At startup the server prints the device it loaded the models on, and warns when that is the CPU. FiDIP and YOLO
  run on the GPU; MediaPipe's Python package has no GPU support on Windows, so its small pose model stays on the CPU.
- Alarms: while the parent app is open, an alert sounds an alarm (critical alerts repeat until acknowledged or
  snoozed). With the app in the background or closed, the PC sends a Web Push notification instead, which uses the
  phone's notification sound and vibration. Each parent phone taps **Turn on background alarms** once. This needs:
  internet on the PC and the phone (pushes go through Google's or Apple's push service, end-to-end encrypted;
  video never does), the home PC's certificate installed on the phone, and on iPhone BabyCue added to the Home
  Screen (iOS 16.4+). The signing key is `~/.babycue/vapid.pem`; signed-up phones are kept in the database.
- Flags:
  - `--no-detect` turns detection off.
  - `--detect` refuses to start without detection.
  - `--models-dir`, `--device auto|cpu|cuda|0` (a GPU that is asked for but unusable stops the server), `--yolo-conf`, `--mp-threshold`, `--fidip-threshold`.
- What `/status` adds, both `null` with no camera connected or no analysis in the last 5 s:
  ```json
  "alert": {"level": "crit", "title": "Baby is on their tummy", "detail": "Lying face-down for 12 s · MediaPipe"},
  "detection": {"posture": {"label": "prone", "source": "MediaPipe", "since_s": 12, "stable": true},
                "hazards": [{"label": "soft-toy", "score": 0.82, "near_baby": true}]}
  ```
- **Accuracy.** Measured on the 104 labelled photos of the hackathon set with
  `python -m babycue_server.devtools.eval_posture PHOTO_DIR`:
  - 70% of positions are right.
  - Tummy is found in 24 of 34 photos.
  - A back is mistaken for tummy in 1 of 34.
  - Side-lying is the weakest: it is often read as back.

**This is not a medical device.** It can miss a roll-over or a toy, and it can raise false alarms. It supports
safe-sleep practice and never replaces it. FiDIP and its weights are licensed for non-commercial use only; see
`babycue_server/detection/fidip/NOTICE.md`.

## Why HTTPS

Browsers only give out the camera, and allow "install as app", on secure pages. `http://192.168.x.x` is not one,
so the server makes a small certificate authority and a certificate for the PC's addresses (in `~/.babycue`) and
serves everything over HTTPS. `--http` turns that off (the phone camera then won't work). Nothing is sent to any
outside service.

## How it works

| Piece | Role |
|---|---|
| `babycue_server/http_server.py` | `RelayServer`: serves the website at `/`; `POST /frame` and `POST /ingest` (one input at a time, else 409), `GET /view` (up to 4 viewers, else 503), `GET /status`, `GET /ca.crt` |
| `babycue_server/certs.py` | Local CA + server certificate for HTTPS, renewed when the PC's addresses change |
| `babycue_server/hub.py` | `FrameHub`: keeps only the newest frame, so slow viewers skip frames instead of building a delay |
| `babycue_server/pipeline.py` | `FramePipeline`: the hook where future logic transforms or inspects each JPEG (passthrough today) |
| `babycue_server/bodyreader.py` | Interruptible socket/chunked-body readers (a vanished phone or server shutdown always frees the thread, also on Windows and over TLS) |
| `babycue_server/protocol.py` | The wire contract; mirrored in `web/src/net/wireProtocol.ts` and checked by a test |
| `babycue_server/detection/` | Safe-sleep detection: `worker.py` (background analysis, `/status` snapshot), `posture.py` (position + roll-over tracker), `rules.py` (alerts), `pose.py` / `hazards.py` / `fidip/` (models) |
| `babycue_server/processing/` | Image-quality diagnostics and display enhancement, ready to be wired into the pipeline |
| `web/` | The website (React + TypeScript + Vite, PWA). Two roles: *Baby phone* posts camera pictures, *Watch* shows `/view`, polls `/status` and raises alerts. Screens follow the BabyCue design. See [web/README.md](web/README.md) |

**Wire protocol.** Baby phone → server: `POST /frame` with one JPEG as the body, or `POST /ingest`, one long
chunked body of `[uint32 big-endian length][JPEG]` records (used by `devtools/fake_input`). A frame-posting phone
holds the input slot for 5 s after its last frame. Server → parent phone: `GET /view` as
`multipart/x-mixed-replace` with a `Content-Length` per part (an `<img>` plays it).

### Adding logic

Add a function `(jpeg: bytes) -> bytes` to the pipeline in `babycue_server/__main__.py`
(`RelayServer(pipeline=FramePipeline([my_stage]))`). A stage that raises is logged and skipped, so it can never
stop the video. Stages run on the ingest thread; keep them fast or hand work to a worker thread. To show an alert
in the app, put `{"alert": {"level": "warn" | "crit", "title": "...", "detail": "..."}}` in `/status`.

## Privacy and security

- Video goes only phone → your PC → phone. No cloud, analytics, or telemetry. Nothing is recorded or written to disk.
- The connection is encrypted (HTTPS), but there is **no login**: anyone on the same network who can reach the PC
  could open the site, send video or watch it. Use a trusted WPA2/WPA3 network, never public Wi-Fi, and never
  forward the port on your router. Keep `~/.babycue/ca.key` private; install the CA only on your own phones.
- Streaming runs while the page is open on screen: a locked or backgrounded phone pauses the camera (the app asks the
  phone to keep the screen on while streaming).

## Testing

```powershell
pip install -r requirements-dev.txt
pytest
ruff check .
cd web; npm test; npm run typecheck; npm run build
```

Python tests use real localhost sockets, also over TLS (hub, ingest and frame protocols, viewers, website serving,
certificates, relay end to end, pipeline, wire-contract drift guard). Website tests (Vitest) cover status handling,
the history log and the frame pusher with its reconnect/backoff. **Not yet verified:** anything on real phones or a
real network; see [docs/MANUAL_TESTS.md](docs/MANUAL_TESTS.md).

## Status and ideas

Done: relay of one baby phone to up to four parent phones, reconnection on both, passthrough pipeline, HTTPS with a
local CA, an installable website that follows the BabyCue design (setup, baby phone, live, heads-up and critical
alerts, history), safe-sleep detection (sleep position and crib toys). Next: better side-lying accuracy (more
labelled infant photos), loose-bedding detection, several named baby phones, a login.

See [docs/NETWORK.md](docs/NETWORK.md) for firewall and Wi-Fi troubleshooting.
