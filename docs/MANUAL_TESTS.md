# Manual test plan (real phones)

Automated tests use localhost sockets and fake servers. Everything below needs real phones and a real
network and has **not yet been performed** (mark each NOT TESTED until run). Record the date, phone models,
app version and network when you run them.

Setup: the server running on the Windows PC (`python -m babycue_server`), two Android phones with the debug APK,
all on the same trusted Wi-Fi, port 8080 allowed in Windows Firewall.

| # | Test | Steps | Expected |
|---|------|-------|----------|
| M1 | Basic relay | Phone A: Input + server address, Start. Phone B: Output + same address, Start | B shows A's live picture; A shows frames/fps rising; `http://PC:8080/status` shows input_connected, viewers 1 |
| M2 | Latency | Wave a hand in front of A | Delay noticeable but short |
| M3 | Browser viewer | Open `http://PC:8080/` on the PC | Same picture; viewers count +1 |
| M4 | Bad address | Enter garbage / wrong IP | Clear message; no crash; Start works after fixing |
| M5 | Second input | Start a second Input phone | Rejected with "Another phone is already sending video", keeps retrying; first unaffected |
| M6 | Input stop/start | Tap Stop on A, then Start | B stops updating (no frozen live claim), resumes by itself |
| M7 | Server restart | Stop and restart the server | Both phones show Retrying, then reconnect without touching them |
| M8 | Wi-Fi drop | Switch A's Wi-Fi off 10 s, then on | A retries and resumes |
| M9 | Permission | Deny camera on A, then allow via the button/settings | Clear messages; works after allowing |
| M10 | Rotation | Rotate both phones | No crash; picture orientation correct |
| M11 | Background/lock | Press Home or lock A, then return and tap Start | Streaming stops while away, resumes on return |
| M12 | Output without camera | Run Output on a device with no camera | Installs and works |
| M13 | Firewall/isolation | Block port 8080, or use a guest network | Phones show "Cannot connect"/"did not respond", never hang |
| M14 | No internet | Disconnect the router from the internet | Relay still works |
| M15 | Many viewers | Open 5 viewers | 5th gets the "maximum viewers" message |
| M16 | Long run | Stream for 1 hour | No crash; steady fps; flat memory on PC and phones |
