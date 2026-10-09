# BabyCue website (React + TypeScript + Vite, installable PWA)

One site, two roles, following the BabyCue design (Organic design system, Nunito, Lucide icons, the prototype's
motion):

| Role | Flow |
|---|---|
| **Baby phone** | Setup → camera permission → *Watching over {name}* (camera preview, link status, hold 2 s to stop) → back to setup |
| **Watch** (parent) | Setup → *Live* (video, how the camera is doing, connection) ↔ *History*; a *Heads up* banner or full-screen *Critical* alert appears when the server reports one |

```powershell
npm install
npm run build        # into dist/, which `python -m babycue_server` serves at /
npm run dev          # Vite dev server; proxies /status /view /frame /ca.crt to https://localhost:8080
npm test             # Vitest: status/alert handling, history, frame pusher + backoff
npm run typecheck
```

The home PC is whichever server served the page, so there is no address to type. Only the parent phone names the baby
(stored on that phone); the baby phone just says "Watching over your baby".

## How it talks to the server

- **Baby phone**: `getUserMedia` (back camera, asked for 640x360 at 15 fps) → a hidden `<canvas>` → JPEG (480 px wide,
  quality 0.5, up to about 15 a second) → `POST /frame` over one kept-alive connection. Small pictures and no new
  connection per picture keep the delay low; the constants are at the top of `BabyScreen.tsx`. Failures back off 0.5 s
  doubling to 5 s. A second baby phone gets `409`: "Another phone is already sending video".
- **Watch**: `<img src="/view">` plays the multipart JPEG stream and is re-pointed if it drops; `GET /status` every
  2 s: unreachable twice in a row = *Reconnecting*, `input_connected: false` = *Can't see {name}*, otherwise *camera
  is live*.
- Constants are in `src/net/wireProtocol.ts`; `tests/test_wire_contract.py` fails if they drift from the server.

## Haptics

`src/haptics.ts` names each vibration by what the touch means (Chrome on Android; iPhone Safari has no vibration API,
so nothing happens there). Browsers can't set strength, so the kinds differ in length and rhythm (ms, on/off):

| Kind | Pattern | Used for |
|---|---|---|
| `tap` | 8 | any ordinary press (the default for buttons) |
| `tab` | 12 | Live / History tabs |
| `select` | 6 · 35 · 6 | choosing Watch or Baby phone, preview chips |
| `confirm` | 18 · 45 · 30 | Got it, I'm checking now, Install |
| `soft` | 28 | Snooze (put off for later) |
| `leave` | 10 · 30 · 10 | Disconnect, Back |
| `success` | 12 · 50 · 26 | Connect worked (played on the result, not the press) |
| `error` | 60 · 40 · 60 · 40 · 110 | camera blocked, page not secure |
| `tick` | 5 | each quarter of the 2 s hold-to-stop |
| `stop` | 30 · 40 · 90 | hold-to-stop finished |
| `warn` / `critical` / `lost` | 30·70·30 / 250·120·250·120·250 / 60 | a heads-up, a critical alert, connection dropped |

A `<Button haptic="soft">` picks its kind; `haptic={null}` gives none, for screens that play the outcome themselves.

## Rotation

Portrait and landscape both work (the manifest has `orientation: any`). On a phone held sideways (landscape and under
600 px tall) the screens switch to two columns: Setup (words and Connect on the left, choices on the right), Live and
Baby phone (video left, card or stop button right), History (two columns), and the critical alert (icon, words and
buttons side by side). Side padding respects a notch. Layouts are in the last block of `src/styles.css`.

## PWA

`public/manifest.webmanifest` (name, colours, icons incl. maskable), `public/sw.js` (the app shell opens offline;
`/view`, `/status`, `/frame` and `/ca.crt` are never cached). The service worker and "install" need HTTPS, which the
Python server provides; see the root README for trusting its certificate. Icons are in `public/`.

## No invented results

The site only says something about the baby's position or about objects when the server's safe-sleep models
reported it (see the root README). `/status` then carries

```json
{ "alert": { "level": "warn" | "crit", "title": "…", "detail": "…" },
  "detection": { "posture": { "label": "supine" | "side" | "prone" | "unknown", "source": "MediaPipe",
                              "since_s": 42, "stable": true },
                 "hazards": [ { "label": "soft-toy", "score": 0.82, "near_baby": true } ] } }
```

The live screen then shows a *Sleep position* card (`PostureCard`) and a *Crib check* card (`HazardCard`). The text
for both is in `src/safeSleep.ts`. A position that has not held yet reads "Checking position", and a body the models
cannot see reads "Position unclear", never a guess. The cards are hidden when `detection` is `null`: a server without
the models, no camera, or no fresh analysis. To see every state anyway, **long-press the title** on the first screen.
That opens a clearly labelled preview with example states. History lists only what the page saw: the PC connection,
the baby phone camera, alerts, and changes of the confirmed sleep position.

## Known limits

- Pictures are posted one at a time, so it is a fast slideshow (about 15 a second at best), not true video. Quality is
  deliberately low for speed; raise `MAX_WIDTH` / `JPEG_QUALITY` in `BabyScreen.tsx` if you prefer a sharper picture.
- A locked or backgrounded phone pauses the camera, so the baby phone must stay on screen (it asks to keep the screen
  awake). Vibration works in Chrome on Android only.
- Not yet run on a real phone: see `../docs/MANUAL_TESTS.md`.
