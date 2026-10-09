# Network setup and troubleshooting

All three devices (PC running the server, input phone, output phone) must be on the **same local network**.
The phones connect *to the PC*, so only the PC needs an open port. No internet is required.

## Finding the address

`python -m babycue_server` prints the PC's LAN address and port (default `8080`), e.g. `192.168.1.20:8080`.
Type exactly that into both phones. Check it from a phone's browser first: `http://192.168.1.20:8080/status`
should show JSON.

## Windows Firewall

The first run shows a prompt: allow **Private networks**. To add the rule manually (admin PowerShell):

```powershell
New-NetFirewallRule -DisplayName "BabyCue server" -Direction Inbound -Protocol TCP -LocalPort 8080 -Profile Private -Action Allow
```

## Symptoms

| Phone says | Likely cause |
|---|---|
| Cannot connect to the server | Wrong IP/port, server not running, firewall blocking, VPN active on the PC |
| The server did not respond in time | Guest Wi-Fi or AP/client isolation on the router; PC and phone on different networks |
| Unknown server address | Typo in the address |
| Another phone is already sending video | A second Input phone; stop the first, or the old connection is still timing out (up to ~10 s) |
| The server already has the maximum number of viewers | More than 4 Output viewers (including browser tabs on `/view`) |
| Waiting for the input phone to start sending | Output is connected but no Input is streaming |

## Notes

- Plain HTTP, no encryption or login: trusted network only. Never port-forward the server port.
- Several Wi-Fi bands/mesh nodes are fine as long as they bridge clients to each other.
- USB tethering or a phone hotspot also works if the PC and phones share that network.
