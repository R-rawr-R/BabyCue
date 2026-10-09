# BabyCue Camera (Android)

Native Android camera source for the BabyCue desktop viewer. It uses CameraX to capture the phone
camera and serves it as MJPEG over HTTP on the local network. The Python desktop app
remains the viewer and processing system; nothing from it is ported here.

**Status: Batch 4 (protocol validation and connection guidance on top of Batch 3).** Start opens the rear camera and starts an HTTP
server on port **8080** that serves the live stream at `/video`. The Python desktop app connects to it.

> **Security:** the stream is plain **unencrypted HTTP with no password**. Anyone on the same network
> who knows the address can watch it. Use it only on a trusted home Wi-Fi network, never on public Wi-Fi.

## Prerequisites

| Item | Version |
|---|---|
| JDK | 17 or newer (17 recommended) |
| Android SDK | Platform **36** and a matching Build-Tools (Android Studio installs these on request) |
| Gradle | 8.13, supplied by the included wrapper (`gradlew`), no separate install |
| Android Gradle Plugin / Kotlin | 8.13.1 / 2.2.21 (see `gradle/libs.versions.toml`) |
| CameraX | 1.6.2 |
| Phone | Android 7.0 (API 24) or newer |

## Build

1. Open this `android/` folder in Android Studio and let it sync, **or** use the command line.
2. Command line: point Gradle at your SDK once by creating `android/local.properties`
   (this file is git-ignored):

   ```
   sdk.dir=C\:\\Users\\<you>\\AppData\\Local\\Android\\Sdk
   ```
   (Linux/macOS: `sdk.dir=/home/<you>/Android/Sdk`), or set `ANDROID_HOME`.
3. From `android/`:

   ```
   ./gradlew :app:testDebugUnitTest      # JVM unit tests
   ./gradlew :app:assembleDebug          # APK: app/build/outputs/apk/debug/app-debug.apk
   ```
   On Windows use `gradlew.bat`. If `gradlew` is not executable after checkout: `chmod +x gradlew`.

## Install on a phone

Enable **Developer options → USB debugging**, connect the phone, then:

```
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Or run from Android Studio with the phone selected.

## Using it

1. Connect the phone to the **same Wi-Fi network** as the PC.
2. Open the app and tap **Start**; allow camera access when asked.
3. The screen shows `Stream URL: http://<phone-ip>:8080/video`, the number of connected viewers, and
   a frames/fps line. The phone's IP is detected automatically (private Wi-Fi/hotspot/Ethernet
   address; cellular and VPN addresses are ignored).
4. In the BabyCue desktop app, enter that address (host = the phone IP, port `8080`, path `/video`).
   A desktop browser may also be able to show the stream (not verified).
5. Tap **Stop** to end streaming; viewers are disconnected and the port is released.

Status lines: "Server: running" with a URL means viewers can connect. "running ... no Wi-Fi/LAN
address" means the server is up but the phone is not on a network. "Server error: ..." shows e.g. port
8080 already in use; tap Stop, then Start.

## Connecting from the Windows PC

See the step-by-step procedure and the error table in the repository's top-level `README.md`
("Phone side: BabyCue Android app"). In short: same trusted Wi-Fi, tap **Start**, enter the
`http://PHONE_IP:8080/video` URL shown by the app into the desktop viewer, and check that frames
arrive. Common blockers: guest Wi-Fi / router client isolation, Windows Firewall, VPNs, and the
app leaving the foreground (streaming stops by design).

## Manual phone-to-PC test checklist

Not yet performed. These need a physical Android phone and a Windows PC.

- [ ] `adb install` of the debug APK succeeds and the app starts.
- [ ] Both devices on the same trusted Wi-Fi; the app shows `Stream URL: http://PHONE_IP:8080/video`.
- [ ] Desktop viewer connects with that URL; status **Live**, resolution about 1280x720, frames increasing.
- [ ] Picture is correctly oriented and not frozen; note latency and fps.
- [ ] Phone shows 1 connected viewer; disconnecting in the viewer returns it to 0.
- [ ] Tap **Stop** on the phone: viewer shows reconnecting/connection lost, no frozen live image.
- [ ] Tap **Start** again: viewer reconnects without restarting the desktop app.
- [ ] Press Home or lock the screen: streaming stops; return to the app and tap **Start**: it resumes.
- [ ] Wrong path (`/stream`) gives the HTTP 404 message; wrong IP gives a timeout message.
- [ ] Phone on guest Wi-Fi or with client isolation fails with a clear timeout, not a hang.
- [ ] Windows Firewall blocking case produces a timeout; allowing it fixes the connection.
- [ ] Leave streaming for 30 minutes: no growing delay, crash, or memory growth on either side.

## Behaviour and limits

- Camera permission: tap Start; if Android stops asking, use **Open app settings**.
- The screen is kept on while streaming. The camera and server are tied to the app being in the
  foreground: **if you leave the app, lock the phone, or the app is destroyed, streaming stops**
  (the server is shut down; returning to the app restarts it). Background streaming would need a
  foreground service, which is not implemented yet.
- Up to 4 viewers at once; a 5th gets HTTP 503. Only `GET /video` is served; other paths give 404,
  other methods 405.
- Frames are not queued: each viewer always gets the newest frame, and slow viewers skip frames.
  If the camera is stopped no data is sent, so a viewer will time out after a few seconds.
- No authentication and no HTTPS (prototype). The Python app and any `http://` client can connect.
- Resolution is about 1280x720 at JPEG quality 80; the JPEG encoder runs on the phone CPU, so very low-end
  phones may reach only a few fps.

## Layout

```
app/src/main/java/com/babycue/camera/
  MainActivity.kt        permission flow, Start/Stop, rendering
  ui/ScreenModel.kt      pure-Kotlin screen logic (unit-tested on the JVM)
  capture/CameraCapture.kt      CameraX ImageAnalysis (keep-only-latest), lifecycle, errors
  capture/YuvConversion.kt      YUV_420_888 -> rotated NV21 (row/pixel strides), pure Kotlin
  capture/FramePipeline.kt      NV21 -> JPEG -> store; JpegEncoder interface
  capture/AndroidJpegEncoder.kt YuvImage-based encoder
  capture/JpegFrame.kt          JpegFrame, JpegFrameSource, LatestFrameStore
  server/MjpegServer.kt         ServerSocket MJPEG server (accept thread + one thread per viewer)
  server/MjpegProtocol.kt       exact response/part byte formatting, boundary, error responses
  server/HttpRequest.kt         strict request-head parser
  server/StreamingController.kt keeps camera and server in step (start/stop/background/shutdown)
  server/LanAddress.kt          finds the phone's Wi-Fi/LAN IPv4 address
  ui/ServerStatus.kt            pure status model for the server section
app/src/test/...                JVM unit tests for screen model, YUV conversion, store, pipeline
```

## Security note

The planned stream is plain HTTP, which is **not encrypted**. Use it only on a trusted local network.
