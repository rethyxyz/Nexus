# Nexus

Cross-platform remote access toolkit with a TCP client/server architecture and Fernet encryption.

The original write-up is available at [articles.rethy.xyz/articles/nexus.php](https://articles.rethy.xyz/articles/nexus.php). This repository is the current source of truth for the implementation; the article is background material and may lag behind the code.

> **Disclaimer:** This software is provided as-is, without support or warranty. It is intended for studying the operation of remote access tools and port scanners. Do not use it on systems you do not own or have explicit permission to access. The author does not condone illegal use.

## Overview

Nexus consists of a command-and-control server and a remote client. The server exposes an interactive REPL; the client connects back over TCP, authenticates, and executes commands sent by the operator.

- Fernet symmetric encryption between client and server
- Username and password authentication
- Direct TCP socket transport, default port `613`
- Multiple simultaneous clients
- Text, binary, and streaming frame types
- Shell execution, screenshots, webcam capture, audio recording, keylogging, LAN scanning, SMB mapping, file download, and piano mode

## Repository layout

```text
client.py                                      Remote client
server.py                                      Command-and-control server
icon.png                                       Generic icon used for builds
docs/code-review-findings.md                   Outstanding review findings
helpers-code-generation/build-client.sh        Client build helper
helpers-deployment/deploy_windows.py           Windows persistence helper
helpers-encoding/encode_py_base64.py           Base64 wrapper generator
helpers-encoding/obfuscate_py.py               Source obfuscator
helpers-encryption-and-auth/generate-fernet-key.py
helpers-encryption-and-auth/generate-username-password.py
```

## Requirements

Python 3.10 or newer is required. The client dependencies are:

```bash
python3 -m pip install cryptography pillow mss opencv-python numpy psutil sounddevice pynput
```

`pynput` is required for the keylogger. `numpy` is normally installed with `opencv-python`, but it is listed explicitly because `client.py` imports it directly.

On Linux, `sounddevice` requires PortAudio, and `mss` plus `pynput` require a graphical session. Screenshot, audio, webcam, and piano features do not work on a headless system. PyInstaller is optional and is only needed when producing a standalone executable.

## Configuration

Edit the constants at the top of `server.py`:

| Constant | Purpose |
|---|---|
| `HOST`, `PORT` | Listener address and port |
| `SECRET_KEY` | Fernet key shared with clients |
| `ACCOUNTS` | Usernames and passwords accepted by the server |

Edit the matching constants at the top of `client.py`:

| Constant | Purpose |
|---|---|
| `SERVER_PORT` | Port used to reach the server |
| `SECRET_KEY` | Fernet key shared with the server |
| `USERNAME`, `PASSWORD` | Credentials presented to the server |

The Fernet key must be identical on both sides. Generate a new key with:

```bash
python3 helpers-encryption-and-auth/generate-fernet-key.py
```

The default key and example accounts are committed to the repository. Replace them before using the program with any real client. The shared key is also embedded in client builds, so treat the client binary as untrusted.

Port `613` is below `1024` and therefore requires root or `CAP_NET_BIND_SERVICE` on Linux. Use a higher port if the server should run as an unprivileged user; remember to update `SERVER_PORT` in the client as well.

## Running the server

```bash
python3 server.py
```

At the `input>` prompt:

```text
--serve
--list
--send 1 1 whoami
```

- `--serve` starts the TCP listener. It can be called again if the listener has stopped.
- `--list` shows connected clients, their system user, operating system, public IP, and peer address.
- `--send <id> <cmd> [payload]` sends a command to a client.
- `--help` prints the full command reference.
- `exit` or `quit` terminates the server.

The server writes command history to `.server_hist` when `readline` is available.

## Running the client

```bash
python3 client.py <server-ip>
```

Example:

```bash
python3 client.py 192.168.1.20
```

The client retries the connection every five seconds after a failure. If the server sends an invalid encrypted frame, the client waits sixty seconds before retrying.

## Commands

Command IDs used by `--send`:

| ID | Command | Notes |
|---:|---|---|
| 1 | Execute shell command | Payload is passed to the shell; inner quoting is preserved |
| 2 | Binary output | Internal client-to-server frame |
| 3 | Stream frame | Internal client-to-server webcam frame |
| 4 | Screenshot | Captures the virtual desktop as a PNG |
| 5 | Webcam photo | Captures one image from the default camera |
| 6 | Audio recording | Five seconds by default; optional duration payload |
| 7 | Keylogger toggle | First call starts, second call stops and returns data |
| 8 | Shutdown | Requests immediate shutdown |
| 9 | Restart | Requests immediate restart |
| 10 | Webcam stream toggle | Starts or stops JPEG frame capture |
| 11 | LAN scan | Scans the local subnet for live hosts and common ports |
| 12 | LAN scan output | Internal client-to-server text frame |
| 13 | SMB mapping scan | Windows only; lists mapped SMB paths |
| 14 | Download file | Payload is the full path on the client |
| 15 | Piano mode | Interactive note mode for the selected client |
| 16 | Play piano note | Internal note frame |
| 99 | Self-delete | Attempts to delete the client file and exit |

Examples:

```text
--send 1 1 dir
--send 1 1 echo "hello; whoami"
--send 1 6 10
--send 1 14 C:\Users\user\file.txt
--send 1 14 "C:\Program Files\application\file.txt"
```

The payload after the command ID is preserved as typed. One matching pair of surrounding quotes is removed, so paths containing spaces can be quoted; inner quotes remain available to the shell.

## Hosting scenarios

### LAN

Run `server.py` on a machine reachable by the client and connect directly. This is the simplest option and is appropriate for isolated testing.

### Tailscale

Run both systems on the same Tailscale network. If the server must be reachable from outside that network, place a reverse proxy on a VPS and forward only the required port to the server over Tailscale.

### Public command and control

Forward a TCP port through the router to the server, or place the server behind a reverse proxy. Prefer an isolated virtual machine, restrict inbound traffic to the required port, and avoid giving the server unrestricted access to the local network. Fernet encrypts frame payloads but does not replace transport security, authentication of the server to the client, or network isolation.

## Building and deployment

### Standalone client

```bash
pyinstaller --onefile --noconsole --icon=icon.png client.py
```

`--noconsole` prevents a console window from appearing when the executable is launched. The resulting executable still contains the configured server address, port, key, and credentials.

### Windows persistence

On Windows, the deployment helper attempts registry, startup-folder, and scheduled-task persistence in that order:

```powershell
py helpers-deployment/deploy_windows.py <path-to-executable>
```

Review the script before running it. It modifies the current user's registry and startup configuration.

### Linux persistence

No deployment helper is included for Linux. Use cron, a systemd unit, or another mechanism appropriate to the environment.

### Base64 wrapper

```bash
python3 helpers-encoding/encode_py_base64.py client.py
```

This creates `client_b64.py`, a wrapper that stores the source as Base64 and executes it. It is an encoding layer, not an encryption or security boundary.

### Source obfuscation

```bash
python3 helpers-encoding/obfuscate_py.py client.py
```

This creates `client_obf.py` with renamed identifiers, stripped docstrings, and Base64-wrapped string literals.

## Known issues

The current review backlog is in [`docs/code-review-findings.md`](docs/code-review-findings.md). The critical items fixed so far are:

- Server history initialization on Linux and macOS
- Authentication bypass with missing or null credentials
- Command parsing crashes and payload corruption
- Client-controlled capture paths

Remaining high-priority items include serialized frame writes, webcam stream state handling, chunked file transfers, audio duration limits, connection timeouts, replay protection, and secret management.
