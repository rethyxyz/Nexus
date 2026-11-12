# Nexus Code Review Findings

**Review date:** 2026-11-12

**Scope:** `client.py`, `server.py`, and the helper scripts referenced by the article.

**Status values:** Fixed, Open, Deferred.

## Fixed During This Review

### C1 — Server history initialization crashed at import

- **Location:** `server.py`, history initialization block.
- **Problem:** `HIST_FILE` was a string, so `hfile.exists()` raised `AttributeError` during module import on any platform where `readline` imports.
- **Fix:** `HIST_FILE` is now a `pathlib.Path`; missing or unreadable history files are handled without preventing startup.
- **Commit:** `7ffdba6`

### C2 — Missing credentials bypassed authentication

- **Location:** `server.py`, `_client_thread` and `_credentials_valid`.
- **Problem:** `ACCOUNTS.get(user) != pw` treated an unknown user and a missing or null password as equal because both sides were `None`.
- **Fix:** Authentication now requires a known string user, a string password, and a constant-time comparison. Authentication and metadata payloads must also be JSON objects.
- **Commit:** `1c2d2c2`

### C3 — Command parsing could crash the REPL and damage payloads

- **Location:** `server.py`, `_parse_send_command`, `_send_cmd_cli`, and `main`.
- **Problem:** `shlex.split()` raised uncaught `ValueError` for unmatched quotes and trailing backslashes. `str.isdigit()` accepted characters that `int()` rejects. Rejoining tokenized arguments removed quotes and backslashes, which mangled Windows paths and changed shell command semantics.
- **Fix:** `--send` is parsed with a dedicated parser that preserves the raw payload text. Integer conversion and command range checks are handled without terminating the REPL.
- **Commit:** `38ec1b8`

### C4 — Client-controlled metadata could write outside the working directory

- **Location:** `server.py`, `save_binary`.
- **Problem:** `kind`, `ext`, and `name` were interpolated into filesystem paths without validation. A client could supply an absolute `kind` or path components to write outside the intended directory.
- **Fix:** `kind` and `ext` are restricted to safe character sets, both path separator styles are normalized before the file name is reduced to a single component, control characters are replaced, and binary capture timestamps include microseconds.
- **Commit:** `e43f496`

## High-Priority Backlog

- [ ] **H1 — Serialize encrypted frame writes.**
  - **Location:** `client.py`, `_send_enc`, `_stream_worker`, `_toggle_stream`; `server.py`, `send_encrypted_frame`.
  - **Problem:** The main command loop and the webcam worker can call `sendall()` on the same socket concurrently. Interleaved writes can corrupt the length prefix or token.
  - **Action:** Protect each complete frame write with a per-socket `threading.Lock`.

- [ ] **H2 — Correct the webcam stream state machine.**
  - **Location:** `client.py`, `_stream_worker`, `_toggle_stream`.
  - **Problem:** The worker does not clear `_stream_on` when it exits. Stopping uses a one-second join and then permits a new worker, so an old worker blocked in `cap.read()` can resume and create duplicate streams.
  - **Action:** Use a stop event, clear state in `finally`, and confirm the previous worker has terminated before starting another.

- [ ] **H3 — Replace single-frame file downloads with chunked transfers.**
  - **Location:** `client.py`, `GET_FILE_CMD`; `server.py`, `receive_encrypted_frame`, `MAX_CIPHER`.
  - **Problem:** The client reads the entire file into memory and sends one frame. The server rejects ciphertext above 100 MB, which limits files to roughly 75 MiB and disconnects the client when exceeded.
  - **Action:** Add a transfer ID, offset, and chunk size; assemble the file on the server; enforce limits before reading.

- [ ] **H4 — Cap audio recording duration.**
  - **Location:** `client.py`, `_record_audio`, `AUDIO_CMD` handler.
  - **Problem:** The duration is only checked for values less than or equal to zero. A large duration causes a large allocation and a long blocking recording.
  - **Action:** Enforce a maximum duration on both client and server, or stream long recordings to disk.

- [ ] **H5 — Isolate command failures from the connection loop.**
  - **Location:** `client.py`, command dispatch in `run`.
  - **Problem:** Screenshot, webcam, audio, and LAN-scan failures reach the outer reconnect handler, so a missing display, camera, audio device, or `arp` binary disconnects the client instead of returning an error.
  - **Action:** Wrap each command handler and send a `SHELL_OUT` error frame; consider running long commands in a worker queue.

- [ ] **H6 — Add connect, authentication, and read deadlines plus a heartbeat.**
  - **Location:** `client.py`, `run`; `server.py`, `_client_thread`.
  - **Problem:** The client connect call has no timeout, and both sides block indefinitely after authentication. Half-open connections leave stale clients in `--list` and can block server sends.
  - **Action:** Add connect and authentication timeouts, then an application-level heartbeat or read deadline with stale-client reaping.

- [ ] **H7 — Bound server connection and send resources.**
  - **Location:** `server.py`, `_listener`, `_client_thread`, `_send_cmd_cli`.
  - **Problem:** `conn.settimeout(3.0)` is a per-receive timeout, not a total authentication deadline. The listener starts an unbounded number of threads, and `sendall()` to a non-reading client can block the CLI.
  - **Action:** Enforce a monotonic total authentication deadline, cap concurrent clients, and set a send timeout or use a dedicated sender.

- [ ] **H8 — Make self-deletion reliable or document it as best-effort.**
  - **Location:** `client.py`, `DEATH_CMD`.
  - **Problem:** `os.remove(sys.argv[0])` may use a relative path. A running PyInstaller executable is locked on Windows. Persistence entries created by the deployment helper are not removed, so the client can return.
  - **Action:** Resolve the executable path, remove persistence entries first, and use a detached cleanup helper where supported.

- [ ] **H9 — Add replay protection to the frame protocol.**
  - **Location:** `client.py`, `_recv_enc`; `server.py`, `receive_encrypted_frame`.
  - **Problem:** Fernet tokens are decrypted without a TTL, and frames have no session ID or sequence number. Captured command or authentication frames can be replayed.
  - **Action:** Add a session nonce and monotonically increasing sequence number, reject duplicates, and pass a short `ttl` to `decrypt()` as defense in depth.

- [ ] **H10 — Replace embedded default secrets and add server authentication.**
  - **Location:** `client.py`, `SECRET_KEY`, `USERNAME`, `PASSWORD`; `server.py`, `SECRET_KEY`, `ACCOUNTS`.
  - **Problem:** The shared key and example credentials are committed to the repository and embedded in client builds. The shared key does not prove the server's identity to the client.
  - **Action:** Generate per-deployment keys, load them from the environment or a protected file with no defaults, fail closed when defaults remain, and consider challenge-response or public-key authentication.

- [ ] **H11 — Sanitize terminal output.**
  - **Location:** `server.py`, command output and `_print_clients`.
  - **Problem:** Client output and metadata are printed directly. ANSI/OSC escape sequences can alter the operator's terminal title, clipboard, or display.
  - **Action:** Strip C0/C1 control characters except newline and tab, and cap displayed output length.

- [ ] **H12 — Eliminate remaining filename collisions.**
  - **Location:** `server.py`, `STREAM_FRAME`.
  - **Status:** Partially fixed. Binary captures now use microsecond timestamps, but stream frames still use `stream_<cid>_<frame>.jpg`; frame counters restart per stream and client IDs are reused.
  - **Action:** Include a session identifier and timestamp in stream frame names, or write each stream to its own directory.

- [ ] **H13 — Stop trusting client metadata in the registry and listing.**
  - **Location:** `server.py`, `_client_thread`, `_print_clients`.
  - **Status:** Partially fixed. Authentication metadata must now be an object, but `**meta` can still overwrite registry fields, and non-string values can still raise `TypeError` in `--list`.
  - **Action:** Nest metadata under a `meta` key, validate value types and lengths, and display the authenticated `username` rather than client-supplied `auth_user`.

## Medium and Low-Priority Backlog

- [ ] **M1 — Harden LAN scanning.**
  - `client.py`, `_primary_subnet`, `_ping_ok`, `_arp_table`, `_scan_lan`.
  - macOS/BSD `ping -W 1` means one millisecond, not one second. The subnet is forced to `/24`, the first private address may belong to Docker or a VPN, reverse DNS can block, and `arp -n` is unavailable or formatted differently on some systems. Per-host debug prints remain.
  - Action: select the interface deliberately, use platform-correct timeout units, bound reverse lookups, and run the scan asynchronously.

- [ ] **M2 — Correct piano mode.**
  - `server.py`, `_piano_mode_via_send`; `client.py`, `_toggle_piano_mode`.
  - `u` and `o` both map to A-sharp, `p` maps to B, and several white keys repeat the same one-octave pitches. End-of-file on `sys.stdin.read(1)` causes a busy loop. Toggle commands are not idempotent.
  - Action: define a consistent key map across octaves, handle EOF, and make the command explicitly activate or deactivate.

- [ ] **M3 — Move `META` construction out of module import.**
  - `client.py`, `META`.
  - Importing the client calls `api.ipify.org` and caches the public IP. This delays startup, creates an external dependency, and becomes stale after a network change.
  - Action: build metadata inside `run()` or refresh it on reconnect.

- [ ] **M4 — Align features with documentation.**
  - Screenshots capture the virtual desktop bounding box rather than one image per display.
  - Command 13 lists SMB mappings, not SMB shares.
  - Webcam streaming writes JPEG files; there is no live viewer.
  - The article and help text describe these features more broadly than the implementation supports.

- [ ] **M5 — Remove dead and misleading code.**
  - `client.py`, `_read` is unused and does not return the accumulated buffer correctly.
  - `client.py`, `_gateway` is unused.
  - `client.py` imports `numpy` and `json` more than once.
  - `server.py`, `_next_id` is unused.
  - Comments in both files describe Fernet as AES-CTR; Fernet uses AES-128-CBC with PKCS7 padding and HMAC-SHA256.

- [ ] **M6 — Protect the command history file.**
  - `server.py`, history initialization; `.gitignore`.
  - `.server_hist` records commands in plain text and is not ignored by Git. It may contain sensitive paths or credentials.
  - Action: restrict permissions or disable history, and add `.server_hist` and capture artifacts to `.gitignore`.

- [ ] **M7 — Document the privileged port requirement.**
  - `server.py`, `HOST`, `PORT`.
  - TCP/613 requires root or `CAP_NET_BIND_SERVICE` on Linux. The listener thread fails with a traceback if binding is not permitted.
  - Action: document the requirement or default to a high port.

- [ ] **M8 — Add a dependency manifest and regression tests.**
  - The repository has no `requirements.txt`, `pyproject.toml`, or test suite.
  - The article's dependency command omits `pynput`.
  - Action: add a manifest and tests for frame handling, authentication, command parsing, and filename sanitization.

- [ ] **M9 — Correct the helper scripts.**
  - `helpers-code-generation/build-client.sh` searches for `USERNAME = "exampleusername"` while `client.py` defines `exampleuser`, so the username replacement does nothing.
  - The script invokes `encode_py_base64.py` by bare name although it lives in `helpers-encoding/`.
  - The opening `'''` is Python-style, not a shell comment, and is executed as a command.
  - `helpers-encryption-and-auth/generate-username-password.py` uses `random` rather than `secrets`.

- [ ] **M10 — Restrict saved-file permissions and location.**
  - `server.py`, `save_binary`.
  - Captures are written to the current directory with default permissions. Consider a dedicated output directory and `0o600` permissions.

- [ ] **M11 — Reduce byte-copy overhead in frame readers.**
  - `client.py`, `_read_exact`; `server.py`, `read_exact_bytes`.
  - Repeated `buf += chunk` can become quadratic for large frames. Use `bytearray` and validate the declared payload length against the decrypted plaintext.

- [ ] **M12 — Bound memory use for unauthenticated frames.**
  - Both files, `MAX_CIPHER` handling.
  - A peer can declare a ciphertext close to 100 MB before authentication, causing a large allocation. Consider a lower pre-authentication limit and explicit connection limits.

## Article and Helper-Script Drift

- The article references helper scripts at the repository root; they are under `helpers-deployment/`, `helpers-encoding/`, and `helpers-encryption-and-auth/`.
- The article's dependency list omits `pynput`; the keylogger imports it lazily and reports an error when it is unavailable.
- The article's example file listing and byte sizes do not match the current repository.
- The article's statement that the server works as of Python 3.13.5 was not true for this checkout before commit `7ffdba6`.

## Verification Performed

- `python3 -m py_compile server.py client.py`
- Imported `server.py` with a real `cryptography` installation in a temporary environment.
- Tested authentication with valid, invalid, missing, null, and non-string credentials.
- Tested command parsing with Windows paths, shell metacharacters, unmatched quotes, trailing backslashes, Unicode digits, missing payloads, and out-of-range command IDs.
- Tested filename sanitization with absolute paths, parent traversal, control characters, empty values, and rapid duplicate captures.
- No end-to-end client/server session was run because the client's full dependency set is not installed in this environment.
- No subagents were used.

## Suggested Next Order

1. H1 and H2: serialize frame writes and correct stream state.
2. H5, H6, and H7: isolate command failures, add deadlines and heartbeats, and bound server resources.
3. H3 and H4: chunk file transfers and cap audio duration.
4. H9, H10, and H11: add replay protection, replace default secrets, and sanitize terminal output.
5. H8, H12, and H13: improve self-deletion, remove remaining filename collisions, and stop trusting client metadata.
6. Medium and low-priority items, followed by a dependency manifest and test suite.
