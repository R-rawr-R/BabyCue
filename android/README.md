# BabyCue Android app

One app with two roles. **Input** films with CameraX and streams JPEG frames to the BabyCue server.
**Output** shows the video the server relays. The server is the Python program in the repository root.

> **Security:** traffic is plain **unencrypted HTTP with no password**. Use it only on a trusted home Wi-Fi.

## Prerequisites

| Item | Version |
|---|---|
| JDK | 17 or newer |
| Android SDK | Platform **36** with matching Build-Tools |
| Gradle | 8.13, via the included wrapper |
| Android Gradle Plugin / Kotlin / CameraX | 8.13.1 / 2.2.21 / 1.6.2 (`gradle/libs.versions.toml`) |
| Phone | Android 7.0 (API 24) or newer; the Output role needs no camera |

## Build and test

Create `android/local.properties` once (git-ignored), or set `ANDROID_HOME`:

```
sdk.dir=C\:\\Users\\<you>\\AppData\\Local\\Android\\Sdk
```

From `android/` (on Windows use `gradlew.bat`, with `JAVA_HOME` pointing at JDK 17):

```
./gradlew :app:testDebugUnitTest    # JVM unit tests
./gradlew :app:assembleDebug        # app/build/outputs/apk/debug/app-debug.apk
```

## Install

With USB debugging: `adb install -r app/build/outputs/apk/debug/app-debug.apk`. Without adb: copy the APK
to the phone (USB file transfer, cloud drive), open it in the Files app, and allow "Install unknown apps" for
that app. Samsung's Auto Blocker may need to be turned off.

## Using it

1. Start the server on the PC (`python -m babycue_server`); it prints the address, e.g. `192.168.1.20:8080`.
2. Open the app, pick **Input** or **Output**, type the server address, tap **Start**.
3. Input asks for camera permission and shows the link state, frame count and fps. Output shows the video.
4. Tap **Stop** to leave the server. The chosen role and address are remembered.

Link states: *Connecting*, *Sending video / Receiving video*, or *<reason>. Retrying in N s* (cannot reach the
server, another phone is already the input, the server has the maximum number of viewers, ...). Both roles
reconnect automatically with a capped backoff. Frames are never queued: after a slow moment the newest frame wins.

## Behaviour and limits

- Streaming is tied to the app being in the foreground: leaving the app, locking the phone, or closing it
  stops the link (a foreground service is not implemented yet). The screen is kept on while running.
- One input phone at a time; a second one is rejected (HTTP 409) and keeps retrying.
- The camera is the rear camera at about 640x480, JPEG quality 50 (encoded on the phone CPU), to keep each
  frame small on Wi-Fi. Raise `CameraCapture.TARGET_SIZE` and `FramePipeline.DEFAULT_JPEG_QUALITY` for a sharper picture.

## Layout

```
app/src/main/java/com/babycue/camera/
  MainActivity.kt          role picker, permission flow, Start/Stop, rendering
  ui/ScreenModel.kt        pure-Kotlin screen logic (Role, permission, capture state)
  capture/                 CameraX capture, YUV->NV21->JPEG, LatestFrameStore (unchanged)
  net/WireProtocol.kt      constants shared with babycue_server/protocol.py
  net/ServerAddress.kt     parses "host[:port]"
  net/ReconnectingLink.kt  thread + capped exponential backoff + state reporting
  net/FramePusher.kt       input: chunked POST of length-prefixed JPEGs to /ingest
  net/FrameReceiver.kt     output: GET /view, hands JPEGs to the UI
  net/MjpegPartReader.kt   parses multipart parts strictly by Content-Length
  net/StreamingController.kt  keeps camera and link in step (start/stop/background/shutdown)
app/src/test/...           JVM unit tests (fake local servers, no emulator needed)
```
