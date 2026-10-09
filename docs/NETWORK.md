# Network setup and troubleshooting

All three devices (PC running the server, baby phone, parent phone) must be on the **same local network**.
The phones connect *to the PC*, so only the PC needs an open port. No internet is required.

## Finding the address

`python -m babycue_server` prints the PC's LAN address, e.g. `https://192.168.1.20:8080/`. Open exactly that in the
phone's browser (Chrome or Safari); the website itself is served from the PC. The first visit shows a certificate
warning: choose **Advanced, Proceed** (see the root README for installing the certificate so the browser trusts it
and the site installs as an app). Check first with `https://192.168.1.20:8080/status`, which should show JSON.

## Windows Firewall

The first run shows a prompt: allow **Private networks**. To add the rule manually (admin PowerShell):

```powershell
New-NetFirewallRule -DisplayName "BabyCue server" -Direction Inbound -Protocol TCP -LocalPort 8080 -Profile Private -Action Allow
```

## Symptoms

| You see | Likely cause |
|---|---|
| The page does not load | Wrong IP/port, server not running, firewall blocking, VPN active on the PC; or you typed `http://` instead of `https://` |
| "Your connection is not private" | Expected the first time: choose Advanced, Proceed. Install `/ca.crt` to stop it |
| The camera is blocked / "isn't secure" | The page was opened over `http://` or by another address than the server printed; or camera access was denied (lock icon next to the address) |
| No "Install app" in the browser menu | The certificate is not trusted yet (install `/ca.crt`), or it is installed already (look for the app icon) |
| The page loads but never connects | Guest Wi-Fi or AP/client isolation on the router; PC and phone on different networks |
| Another phone is already sending video | A second baby phone; stop the first, or the old one is still timing out (up to ~5 s) |
| Video does not show (4 viewers) | More than 4 parent phones or browser tabs on `/view` |
| Can't see {name}: waiting for the baby phone | The parent phone is connected but no baby phone is streaming |
| The PC's address changed | The certificate is renewed automatically on the next start; phones that trust the CA keep working |

## Notes

- The connection is encrypted (HTTPS) but there is no login: trusted network only. Never port-forward the server port.
- Several Wi-Fi bands/mesh nodes are fine as long as they bridge clients to each other.
- USB tethering or a phone hotspot also works if the PC and phones share that network.
