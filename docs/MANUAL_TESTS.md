# Manual test plan (real phones)

Automated tests use localhost sockets and fake servers. Everything below needs real phones and a real
network and has **not yet been performed** (mark each NOT TESTED until run). Record the date, phone models,
app version and network when you run them.

Setup: the server running on the Windows PC (`python -m babycue_server`), two phones with Chrome (Android) or Safari (iPhone), the website built (`cd web; npm run build`),
all on the same trusted Wi-Fi, port 8080 allowed in Windows Firewall.

| # | Test | Steps | Expected |
|---|------|-------|----------|
| M1 | Basic relay | Phone A opens https://PC:8080/, accepts the certificate warning, chooses Baby phone, Connect. Phone B the same with Watch | B shows A's live picture and "camera is live"; A shows Streaming; `http://PC:8080/status` shows input_connected, viewers 1 |
| M2 | Latency | Wave a hand in front of A | Delay noticeable but short |
| M3 | Browser viewer | Open `http://PC:8080/` on the PC | Same picture; viewers count +1 |
| M4 | Wrong address | Open `http://PC:8080/` (http) and a wrong IP | Clear message; no crash; works after fixing |
| M5 | Second input | Connect a second Baby phone | Rejected with "Another phone is already sending video", keeps retrying; first unaffected |
| M6 | Input stop/start | Hold-to-stop on A for 2 s (a short tap must not stop it), then connect again | B shows "Can't see ..." / "Waiting for the baby phone", never a frozen live claim, and resumes by itself |
| M7 | Server restart | Stop and restart the server | A shows "Trying again", B shows Reconnecting, then both reconnect without touching them |
| M8 | Wi-Fi drop | Switch A's Wi-Fi off 10 s, then on | A retries and resumes |
| M9 | Permission | Deny the camera on A, then allow it from the lock icon next to the address | Clear messages; works after allowing |
| M10 | Rotation | Rotate both phones | No crash; picture orientation correct |
| M11 | Background/lock | Press Home or lock A, then return | A stops sending while away (expected); on return the camera restarts by itself and streaming resumes |
| M12 | Watch without camera | Run Watch on a device with no camera | Works |
| M13 | Firewall/isolation | Block port 8080, or use a guest network | Setup/Live shows Reconnecting or "Cannot reach the home PC", never hangs |
| M14 | No internet | Disconnect the router from the internet | Relay still works |
| M15 | Many viewers | Open 5 viewers | 5th gets the "maximum viewers" message |
| M16 | Long run | Stream for 1 hour | No crash; steady fps; flat memory on PC and phones |
| M17 | Frame rate | Watch B while A streams a moving object | Note the fps shown on B; expect a few frames a second (one picture per upload). Record it |
| M18 | Picture orientation | Hold A upright and sideways | Picture on B is upright |
| M19 | Hold to stop | Tap the stop button, then hold it 2 s | Tap does nothing; hold fills and returns to setup |
| M20 | Design preview | Long-press the title on the first screen | Preview of Heads-up, Critical, Connection lost and No camera; labelled as examples |
| M21 | Reduce motion | Turn on "Remove animations" in the phone's accessibility settings | Screens appear without motion; everything still readable |
| M22 | Install as app | In Chrome use Install app (after installing `/ca.crt`) and on iPhone Add to Home Screen | Own icon and window, opens at the setup screen |
| M23 | Offline shell | Turn the server off, open the installed app | The app opens and says it cannot reach the PC; no crash |
| M24 | Wake lock | Leave A streaming for 10 min untouched | The screen stays on and streaming continues |
| M25 | Certificate | Install `/ca.crt` on a phone | No warning on `https://PC:8080/`; the install prompt appears |
