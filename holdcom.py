#!/usr/bin/env python3
"""holdcom.py — minimal on-demand serial take-over that never resets
the MCU on take-over/release.

Design (see REQUIREMENTS.md):
  * Based on picocom's --noinit / --noreset termios+ioctl mechanism.
  * NOT based on pyserial (pyserial re-opens and flips modem lines -> reset).
  * No daemon, no socket, no flash, no remote, no deliberate modem control.
  * Each CLI invocation is a self-contained take-over -> act -> release cycle.

The one unavoidable flow-control event is the kernel driver asserting DTR/RTS
on open(); that is a hardware/OS fact, not something this tool does. By DEFAULT
this tool does NOT issue any modem-control ioctl at all — take-over leaves the
kernel's post-open line state untouched, fully honoring "never touch flow
control, never reset". The optional --idle-dtr/--idle-rts override sets DTR/RTS
exactly ONCE at take-over only, for boards whose reset circuit needs a specific
idle level (e.g. some ESP32-S3 native-USB firmware resets unless RTS is
deasserted). Release (close) and every send/recv never touch the modem lines.

Static guarantee: TIOCM* ioctls appear ONLY in `set_idle_state` (called at most
once from `open_safe`, and only when an override is requested). Enforced by
`selftest` (AST scan per function).

------------------------------------------------------------------------
TEXT vs BYTES (serial is a byte stream)
------------------------------------------------------------------------
  * Sending: `send`/`--send` take TEXT and encode it as UTF-8. Pass `--hex`
    (or `--send-hex`) to send raw bytes expressed as a hex string instead.
  * Matching: `recv-until`/`--until` are matched BYTE-WISE over the raw stream
    — the pattern is encoded as UTF-8 (or hex) and looked for as a byte
    sequence, never decoded as text. This is lossless for any byte, including
    multi-byte UTF-8 characters and binary payloads.
  * Output: captured serial bytes are written to stdout (and `--output`) as
    RAW BYTES, never decoded. Piping to a file gives the exact bytes on the
    wire. stdout stays pure serial data; status/diagnostics go to stderr.

------------------------------------------------------------------------
EXPLICIT OUTCOMES (so a non-match is never judged success)
------------------------------------------------------------------------
  recv-until / txn report `matched / timeout / disconnected / error`, and use
  distinct exit codes (see EXIT_*). A timeout, a device disconnect, an
  unsupported baud, a busy port, etc. are all reported SEPARATELY — never
  collapsed into one vague "error".
------------------------------------------------------------------------
"""
import argparse
import ast
import contextlib
import dataclasses
import enum
import errno
import fcntl
import os
import select
import struct
import sys
import termios
import threading
import time
import typing

__version__ = "0.1.8"

# TIOCM* constants mean modem-line control. They are permitted ONLY inside
# `set_idle_state` (called exactly once from `open_safe` at take-over).
# `selftest` enforces this confinement via an AST scan per function.

# Default cap on how many bytes recv-until will accumulate before giving up
# with an explicit ERROR (instead of growing memory without bound when the
# pattern never arrives). Override with --maxlen.
RECV_MAXLEN_DEFAULT = 16 * 1024 * 1024  # 16 MiB

# Exit codes — distinct so a caller can tell exactly what happened.
EXIT_OK = 0          # success / matched
EXIT_ERROR = 1       # unexpected serial I/O failure (runtime)
EXIT_TIMEOUT = 2     # pattern not found within -t
EXIT_DISCONNECT = 3  # device vanished (mid-wait) OR not present at open
EXIT_BUSY = 4        # another process holds the port (exclusive open)
EXIT_PERMISSION = 5  # permission denied
EXIT_UNSUPPORTED = 6 # baud / termios capability not available on this platform
EXIT_USAGE = 64      # bad arguments (timeout<=0, baud<=0, empty pattern, bad hex)


class PortErrorCategory(enum.Enum):
    NOTFOUND = "notfound"
    BUSY = "busy"
    PERMISSION = "permission"
    UNSUPPORTED = "unsupported"
    ERROR = "error"


class PortError(OSError):
    """A typed open/termios failure carrying a platform-independent category so
    the CLI can report 'not found' / 'busy' / 'permission' / 'unsupported'
    separately instead of a generic 'error'."""

    def __init__(self, errno_code, message, category):
        super().__init__(errno_code, message)
        self.category = category


class PortDisconnected(OSError):
    """Raised by recv/recv_until when the serial device is gone (e.g. USB
    unplugged). It subclasses OSError so the interactive console's generic
    OSError handler still catches it and exits gracefully."""


class RecvStatus(enum.Enum):
    MATCHED = "matched"
    TIMEOUT = "timeout"
    DISCONNECTED = "disconnected"
    ERROR = "error"


@dataclasses.dataclass
class RecvResult:
    status: RecvStatus
    data: bytes
    error: typing.Optional[str] = None

    @property
    def ok(self) -> bool:
        """True ONLY when the pattern actually matched. A timeout, a device
        disconnect, or any other I/O error is NOT success — callers must check
        `.ok` / `.status` and must not treat a non-match as a win."""
        return self.status is RecvStatus.MATCHED


# Map an errno from open()/tcgetattr() to a human category.
_OPEN_ERRNO_CATEGORY = {
    errno.ENOENT: PortErrorCategory.NOTFOUND,
    errno.ENXIO: PortErrorCategory.NOTFOUND,
    errno.ENODEV: PortErrorCategory.NOTFOUND,
    errno.EBUSY: PortErrorCategory.BUSY,
    errno.EACCES: PortErrorCategory.PERMISSION,
    errno.EPERM: PortErrorCategory.PERMISSION,
    errno.ENOTTY: PortErrorCategory.UNSUPPORTED,
    errno.EINVAL: PortErrorCategory.UNSUPPORTED,
    errno.EOPNOTSUPP: PortErrorCategory.UNSUPPORTED,
    errno.ENOSYS: PortErrorCategory.UNSUPPORTED,
}

_CATEGORY_MESSAGE = {
    PortErrorCategory.NOTFOUND: "device not found or unplugged",
    PortErrorCategory.BUSY: "device is busy (held by another process via exclusive open)",
    PortErrorCategory.PERMISSION: "permission denied (try sudo or fix device ownership)",
    PortErrorCategory.UNSUPPORTED: "not a usable serial terminal on this platform",
    PortErrorCategory.ERROR: "serial open failed",
}

# Map a PortError category to its CLI exit code.
CATEGORY_EXIT = {
    PortErrorCategory.NOTFOUND: EXIT_DISCONNECT,
    PortErrorCategory.BUSY: EXIT_BUSY,
    PortErrorCategory.PERMISSION: EXIT_PERMISSION,
    PortErrorCategory.UNSUPPORTED: EXIT_UNSUPPORTED,
    PortErrorCategory.ERROR: EXIT_ERROR,
}


def _raise_port_error(e, port):
    cat = _OPEN_ERRNO_CATEGORY.get(e.errno, PortErrorCategory.ERROR)
    msg = f"{port}: {e.strerror} — {_CATEGORY_MESSAGE[cat]}"
    raise PortError(e.errno, msg, cat)


def open_safe(port, baud=None, raw=False, dtr_high=None, rts_high=None):
    """Take over `port`. Returns an fd.

    Equals picocom --noinit (no modem-line dance) + --noreset (HUPCL=0).
    By DEFAULT no modem-control ioctl is issued at all (dtr_high/rts_high are
    None). If an idle level is requested via --idle-dtr/--idle-rts, it is
    applied exactly once, AFTER tcsetattr (which can reset the lines on some
    drivers), mirroring how picocom calls set_dtr_rts() after term_apply.

    Open/termios failures are raised as a typed `PortError` with a clear
    category (NOTFOUND / BUSY / PERMISSION / UNSUPPORTED / ERROR) so the caller
    can report the real cause instead of a vague error.
    """
    flags = os.O_RDWR | getattr(os, "O_NOCTTY", 0) | os.O_NONBLOCK
    try:
        fd = os.open(port, flags)
    except OSError as e:
        _raise_port_error(e, port)
    try:
        # Single holder: prevent a second process from opening the same port.
        # Non-fatal (just a warning) when the platform/fd doesn't support it;
        # but a hard error (e.g. EBUSY) means the port is already held -> we
        # surface that as a BUSY error rather than silently continuing.
        try:
            fcntl.ioctl(fd, termios.TIOCEXCL, 0)
        except (AttributeError, OSError, termios.error) as e:
            if getattr(e, "errno", None) in (errno.ENOTTY, errno.EOPNOTSUPP,
                                             errno.EINVAL):
                sys.stderr.write("warn: TIOCEXCL unsupported on this fd; "
                                 "continuing without exclusivity\n")
            else:
                _raise_port_error(e, port)

        try:
            attrs = termios.tcgetattr(fd)
        except (OSError, termios.error) as e:
            cat = _OPEN_ERRNO_CATEGORY.get(getattr(e, "errno", 0),
                                          PortErrorCategory.UNSUPPORTED)
            raise PortError(getattr(e, "errno", 0),
                            f"{port}: {getattr(e, 'strerror', str(e))} — "
                            f"{_CATEGORY_MESSAGE[cat]}",
                            cat)

        # Clear HUPCL so close() will NOT drop DTR/RTS (--noreset semantics).
        attrs[2] &= ~termios.HUPCL

        if raw:
            # cfmakeraw equivalent. This only changes line-discipline flags,
            # never the modem-control bits.
            attrs[0] &= ~(termios.IGNBRK | termios.BRKINT | termios.PARMRK
                          | termios.ISTRIP | termios.INLCR | termios.IGNCR
                          | termios.ICRNL | termios.IXON)
            attrs[1] &= ~termios.OPOST
            attrs[2] &= ~(termios.CSIZE | termios.PARENB)
            attrs[2] |= termios.CS8
            attrs[3] &= ~(termios.ECHO | termios.ECHONL | termios.ICANON
                          | termios.ISIG | termios.IEXTEN)
            attrs[6][termios.VMIN] = 1
            attrs[6][termios.VTIME] = 0

        baud_set_via_termios = False
        if baud is not None:
            bc = getattr(termios, f"B{baud}", None)
            if bc is not None:
                # Portable baud set: cfsetspeed is Linux-only. On macOS/BSD the
                # ispeed/ospeed fields live at indices 4/5 of the tcgetattr list.
                if hasattr(termios, "cfsetspeed"):
                    termios.cfsetspeed(attrs, bc)
                else:
                    attrs[4] = bc
                    attrs[5] = bc
                baud_set_via_termios = True
            # else: no named B-constant for this rate (e.g. macOS lacks
            # B2000000). Defer to the macOS IOSSIOSPEED ioctl below.

        # ONE tcsetattr: applies HUPCL-clear (+ optional baud/raw). On some
        # drivers tcsetattr (term_apply) resets DTR/RTS, so if an idle level
        # was requested we re-assert it immediately afterwards (picocom does
        # the same).
        termios.tcsetattr(fd, termios.TCSANOW, attrs)

        # macOS arbitrary baud: when there is no named B-constant, set the rate
        # via the Darwin-only IOSSIOSPEED ioctl. This MUST run after tcsetattr,
        # which would otherwise reset the speed to the value stored in the
        # termios struct. IOSSIOSPEED only changes the line speed — it does NOT
        # touch DTR/RTS, so the no-reset guarantee is preserved.
        if baud is not None and not baud_set_via_termios:
            if sys.platform == "darwin":
                try:
                    fcntl.ioctl(fd, 0x80045402, struct.pack("I", baud))
                except OSError as e:
                    cat = _OPEN_ERRNO_CATEGORY.get(e.errno,
                                                  PortErrorCategory.UNSUPPORTED)
                    raise PortError(
                        e.errno,
                        f"cannot set baud {baud} on this platform: "
                        f"{e.strerror} — {_CATEGORY_MESSAGE[cat]}",
                        cat)
            else:
                raise PortError(
                    0,
                    f"unsupported baud rate {baud} on this platform "
                    f"(no named B-constant and IOSSIOSPEED is macOS-only)",
                    PortErrorCategory.UNSUPPORTED)

        set_idle_state(fd, dtr_high=dtr_high, rts_high=rts_high)
        return fd
    except Exception:
        # Don't leak the fd if anything above fails.
        os.close(fd)
        raise


def set_idle_state(fd, dtr_high=None, rts_high=None):
    """Optionally assert/clear DTR and RTS to a chosen idle state, at most once
    at take-over. Passing None for either line leaves it untouched (the default
    — the tool then never issues any modem-control ioctl, fully honoring the
    "never touch flow control" guarantee). Use --idle-dtr/--idle-rts only when
    your board's reset circuit requires a specific idle level (e.g. some
    ESP32-S3 native-USB firmware resets unless RTS is deasserted). When used,
    TIOCMBIS/TIOCMBIC touch only DTR/RTS, leaving other modem bits alone.
    """
    if dtr_high is None and rts_high is None:
        return
    set_bits = 0
    clr_bits = 0
    if dtr_high is not None:
        if dtr_high:
            set_bits |= termios.TIOCM_DTR
        else:
            clr_bits |= termios.TIOCM_DTR
    if rts_high is not None:
        if rts_high:
            set_bits |= termios.TIOCM_RTS
        else:
            clr_bits |= termios.TIOCM_RTS
    if set_bits:
        try:
            fcntl.ioctl(fd, termios.TIOCMBIS, struct.pack("I", set_bits))
        except (OSError, termios.error) as e:
            if e.errno in (errno.ENOTTY, errno.EOPNOTSUPP, errno.EINVAL):
                sys.stderr.write("warn: modem-control ioctl unsupported on this "
                                 "device; idle-safe state skipped "
                                 "(expected for pty/virtual ports)\n")
            else:
                raise
    if clr_bits:
        try:
            fcntl.ioctl(fd, termios.TIOCMBIC, struct.pack("I", clr_bits))
        except (OSError, termios.error) as e:
            if e.errno in (errno.ENOTTY, errno.EOPNOTSUPP, errno.EINVAL):
                sys.stderr.write("warn: modem-control ioctl unsupported on this "
                                 "device; idle-safe state skipped "
                                 "(expected for pty/virtual ports)\n")
            else:
                raise


def close_safe(fd):
    """Release the port. HUPCL=0 => close() does NOT drop DTR/RTS."""
    os.close(fd)


def _readable(fd, timeout):
    r, _, _ = select.select([fd], [], [], timeout)
    return bool(r)


def _writable(fd, timeout):
    _, w, _ = select.select([], [fd], [], timeout)
    return bool(w)


def send(fd, data, timeout=5.0):
    """Write `data` to the port. `data` may be `bytes` or `str`; a `str` is
    encoded as UTF-8 (the single, documented text encoding for holdcom)."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    view = memoryview(data)
    while view:
        if not _writable(fd, timeout):
            raise TimeoutError("send timed out")
        try:
            n = os.write(fd, view)
            view = view[n:]
        except BlockingIOError:
            continue
        except OSError:
            raise


def recv(fd, timeout=1.0, n=4096):
    """Read up to `n` bytes, waiting at most `timeout` seconds. Returns b"" on
    timeout (no data). Raises `PortDisconnected` if the device vanished
    (ENXIO/ENODEV/EIO), or a generic OSError for any other failure."""
    if _readable(fd, timeout):
        try:
            return os.read(fd, n)
        except BlockingIOError:
            return b""
        except OSError as e:
            # Device gone (e.g. USB unplugged -> ENXIO/EIO on macOS/Linux) or
            # some other serial failure. Surface a typed disconnect so callers
            # can tell it apart from a plain (data-empty) timeout.
            if e.errno in (errno.ENXIO, errno.ENODEV, errno.EIO):
                raise PortDisconnected(e.errno, str(e)) from e
            raise
    return b""


def recv_until(fd, pattern, timeout=5.0, n=4096, maxlen=RECV_MAXLEN_DEFAULT):
    """Wait until `pattern` appears in the received byte stream, or until
    `timeout` seconds elapse, or until `maxlen` bytes accumulate without a
    match. Returns a RecvResult whose `.status` is one of MATCHED / TIMEOUT /
    DISCONNECTED / ERROR.

    `pattern` is matched BYTE-WISE over the raw stream (encoded as UTF-8 if it
    is a str, or left as-is if bytes). No text decoding happens.

    DISCONNECTED: device vanished mid-wait (e.g. USB unplugged; ENXIO/EIO).
    ERROR: other I/O failure, OR the buffer exceeded `maxlen` without a match
           (so a runaway stream can't silently eat all memory).
    The captured bytes-so-far always travel along in `.data` for logging.
    """
    if isinstance(pattern, str):
        pattern = pattern.encode("utf-8")
    buf = bytearray()
    end = time.monotonic() + timeout
    while True:
        remaining = end - time.monotonic()
        if remaining <= 0:
            return RecvResult(RecvStatus.TIMEOUT, bytes(buf))
        try:
            chunk = recv(fd, remaining, n)
        except PortDisconnected as e:
            return RecvResult(RecvStatus.DISCONNECTED, bytes(buf), str(e))
        except OSError as e:
            return RecvResult(RecvStatus.ERROR, bytes(buf), str(e))
        if chunk:
            buf.extend(chunk)
            if len(buf) > maxlen:
                return RecvResult(
                    RecvStatus.ERROR, bytes(buf),
                    f"maxlen {maxlen} exceeded without a match "
                    f"(stream never produced the pattern)")
            if pattern in buf:
                return RecvResult(RecvStatus.MATCHED, bytes(buf))


class Session:
    """A single serial take-over held open for a transaction: open once, send /
    recv / recv_until as many times as needed, then close once.

    This removes the timing ambiguity of firing separate `holdcom send` /
    `holdcom recv-until` CLI invocations (each opens and closes the port, with
    an uncontrolled gap in between). Within one Session the caller controls the
    exact send -> wait -> release sequence.

    Text passed to send()/recv_until() is encoded as UTF-8; to send or match
    raw bytes, pass `bytes` directly (e.g. bytes.fromhex("de ad be ef")).

    Usage:
        with Session("/dev/cu.usbmodem1101", baud=115200, raw=True) as s:
            s.send("AT\\r\\n")                      # UTF-8 text
            res = s.recv_until("OK", timeout=2.0)
            if res.ok:
                print("got response:", res.data)
        # close() runs automatically on __exit__ (release, no reset).

    Like every holdcom entry point, the only modem-line touch is the optional
    one-time idle set in open_safe (only if idle_dtr/idle_rts are given);
    opening, sending, and closing never flip DTR/RTS.
    """

    def __init__(self, port, baud=None, raw=False, idle_dtr=None, idle_rts=None):
        self.fd = open_safe(port, baud=baud, raw=raw,
                            dtr_high=idle_dtr, rts_high=idle_rts)

    def send(self, data, timeout=5.0):
        send(self.fd, data, timeout)

    def recv(self, timeout=1.0, n=4096):
        return recv(self.fd, timeout, n)

    def recv_until(self, pattern, timeout=5.0, n=4096,
                   maxlen=RECV_MAXLEN_DEFAULT):
        return recv_until(self.fd, pattern, timeout, n, maxlen)

    def close(self):
        if self.fd is not None:
            close_safe(self.fd)
            self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


class _Tee:
    """Write serial bytes to stdout AND (optionally) a file. Used by --output
    so the default always stays stdout and holdcom never writes to /tmp unless
    the caller points --output there explicitly. Bytes are written as-is
    (lossless); nothing is ever decoded."""

    def __init__(self, path=None):
        self._f = open(path, "wb") if path else None

    def write(self, b):
        sys.stdout.buffer.write(b)
        sys.stdout.buffer.flush()
        if self._f is not None:
            self._f.write(b)
            self._f.flush()

    def close(self):
        if self._f is not None:
            self._f.close()
            self._f = None


def _emit_recv_result(res, tee):
    """Write the captured serial bytes (stdout + optional file) and print a
    machine-readable status line on stderr so stdout stays pure serial data
    for piping."""
    tee.write(res.data)
    line = f"[recv] status={res.status.value} bytes={len(res.data)}"
    if res.error:
        line += f" error={res.error}"
    sys.stderr.write(line + "\n")


def _exit_for_status(status):
    return {
        RecvStatus.MATCHED: EXIT_OK,
        RecvStatus.TIMEOUT: EXIT_TIMEOUT,
        RecvStatus.DISCONNECTED: EXIT_DISCONNECT,
        RecvStatus.ERROR: EXIT_ERROR,
    }[status]


def _to_bytes(text, hex_flag):
    """Resolve a CLI argument to the bytes that will be sent / matched.
    With `hex_flag`, `text` is parsed as a hex string (spaces ignored) into
    raw bytes. Otherwise `text` stays a str and is UTF-8 encoded later by
    send()/recv_until()."""
    if hex_flag:
        try:
            return bytes.fromhex(text.replace(" ", ""))
        except ValueError as e:
            raise ValueError(f"invalid hex value {text!r}: {e}")
    return text


def _cmd_config(port, args):
    """Report the resolved take-over configuration. Honest about what it does
    and does NOT do: it never opens the port and never queries live modem-line
    levels, because opening would assert DTR on some drivers and could reset
    the MCU — the very thing this tool exists to avoid."""
    idle_dtr = args.idle_dtr if args.idle_dtr else "untouched (no modem ioctl)"
    idle_rts = args.idle_rts if args.idle_rts else "untouched (no modem ioctl)"
    print("holdcom configuration (resolved take-over settings):")
    print(f"  port      : {port if port else '(auto-detect when omitted)'}")
    print(f"  baud      : {args.baud if args.baud is not None else 'inherit driver setting'}")
    print(f"  raw       : {args.raw}")
    print(f"  idle DTR  : {idle_dtr}")
    print(f"  idle RTS  : {idle_rts}")
    print()
    print("NOTE: this reports the configuration holdcom WILL apply at take-over.")
    print("It does NOT open the port and does NOT query live modem-line levels")
    print("(opening would assert DTR on some drivers and could reset the MCU).")
    print("To read real-time line state, open the port with another tool (which")
    print("accepts the DTR assertion) or call ioctl(TIOCMGET) yourself.")


def selftest():
    """Phase 0 verification, no real device needed."""
    src = open(__file__, "r", encoding="utf-8").read()
    tree = ast.parse(src)

    ALLOWED = {"open_safe", "set_idle_state"}   # the one sanctioned place
    FORBIDDEN = {"close_safe", "send", "recv", "recv_until", "console",
                 "status", "main", "selftest", "build_parser",
                 "_readable", "_writable", "Session", "_emit_recv_result",
                 "_cmd_config"}

    def idents_in(fn):
        s = set()
        for n in ast.walk(fn):
            if isinstance(n, ast.Attribute):
                s.add(n.attr)
            elif isinstance(n, ast.Name):
                s.add(n.id)
        return s

    violations = []
    has_sanctioned = False
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        toks = {i for i in idents_in(node) if "TIOCM" in i}
        if node.name in ALLOWED and toks:
            has_sanctioned = True
        if toks and node.name not in ALLOWED:
            violations.append((node.name, sorted(toks)))

    if not has_sanctioned:
        print("FAIL: no sanctioned TIOCM usage in open_safe/set_idle_state")
        return 1
    if violations:
        for fn, toks in violations:
            print(f"FAIL: modem-control {toks} in {fn!r} "
                  f"(must live only in open_safe/set_idle_state)")
        return 1
    print("OK: static scan — TIOCM* confined to set_idle_state (one-time "
          "idle-safe set at take-over); no other function touches modem lines")

    # Dynamic pty loopback: proves the byte path + open/close run cleanly.
    try:
        master, slave = os.openpty()
    except Exception as e:
        print(f"SKIP dynamic pty test: {e}")
        return 0
    fd = open_safe(os.ttyname(slave), raw=True)
    try:
        send(fd, b"hello")
        got = os.read(master, 64) if _readable(master, 2.0) else b""
        assert got == b"hello", got
        os.write(master, b"world")
        back = recv(fd, 2.0)
        assert back == b"world", back
    finally:
        close_safe(fd)
        os.close(master)
    print("OK: pty loopback — send/recv byte path verified, open/close clean")

    # RecvResult logic (no real device): stub recv() and exercise the
    # matched / timeout / maxlen-overflow branches.
    import importlib
    hc = importlib.import_module("holdcom")
    orig_recv = hc.recv
    try:
        hc.recv = lambda fd, timeout=1.0, n=4096: b"abc MATCH def"
        r = hc.recv_until(0, "MATCH", timeout=2.0)
        assert r.status is hc.RecvStatus.MATCHED and r.ok, r

        hc.recv = lambda fd, timeout=1.0, n=4096: b"nope"
        r = hc.recv_until(0, "ZZZ", timeout=0.3)
        assert r.status is hc.RecvStatus.TIMEOUT, r

        hc.recv = lambda fd, timeout=1.0, n=4096: b"xxxxxxxxxx"
        r = hc.recv_until(0, "NEVER", timeout=2.0, maxlen=25)
        assert r.status is hc.RecvStatus.ERROR and "maxlen" in (r.error or ""), r
    finally:
        hc.recv = orig_recv
    print("OK: recv_until logic — matched / timeout / maxlen-overflow verified")
    return 0


# Known subcommands. A bare token that is NOT one of these is treated as the
# serial device (picocom-style positional), so `holdcom /dev/ttyX` just works.
SUBCOMMANDS = {"send", "recv", "recv-until", "status", "config", "txn",
               "console", "selftest"}


class _HelpFormatter(argparse.RawDescriptionHelpFormatter):
    """Keep our explicit line breaks in the description/epilog, and print a
    fixed usage block instead of argparse's auto-wrapped one (which dangles the
    subcommand metavar on its own line and hard-breaks sentences mid-word)."""

    def _format_usage(self, usage, actions, groups, prefix):
        return (
            "usage: holdcom [options] [device] [command [args]]\n"
            "       holdcom /dev/ttyX -b 115200   (interactive console)\n"
        )


DESCRIPTION = (
    "On-demand serial take-over that NEVER resets the MCU:\n"
    "DTR/RTS are left untouched unless you set --idle-dtr/--idle-rts explicitly.\n"
    "\n"
    "Name the port any of three ways:\n"
    "  holdcom /dev/ttyX -b 115200       picocom-style positional\n"
    "  holdcom -p /dev/ttyX -b 115200     explicit -p\n"
    "  holdcom -b 115200                 omit it -> auto-use the only device\n"
    "Omit the command to drop into an interactive console.\n"
    "\n"
    "TEXT vs BYTES: send / --send take TEXT (UTF-8). Use --hex (or --send-hex /\n"
    "--until-hex) to send/match RAW BYTES (hex string). Matching is byte-wise\n"
    "over the raw stream. Raw serial output to stdout is ALWAYS lossless bytes\n"
    "(never decoded).\n"
    "\n"
    "recv-until / txn report an explicit status (matched / timeout /\n"
    "disconnected / error) and use distinct exit codes, so a non-match is\n"
    "never mistaken for success. Open failures are reported separately as\n"
    "not-found / busy / permission / unsupported."
)

OUTPUT_HELP = ("write captured serial data to this file as well as stdout "
               "(audit log). Default: stdout only; holdcom never writes to "
               "/tmp unless you point --output there.")

EXIT_HELP = (
    "exit codes: 0=ok/matched 1=error 2=timeout 3=disconnected/not-found "
    "4=busy 5=permission 6=unsupported 64=usage(bad timeout/baud/pattern/hex)"
)

EPILOG = (
    "examples:\n"
    "  holdcom /dev/tty.usbmodem1101 -b 2000000\n"
    "  holdcom -p /dev/ttyUSB0 -b 115200 send \"AT\\r\\n\"\n"
    "  holdcom -p /dev/ttyUSB0 recv -t 2\n"
    "  holdcom -p /dev/ttyUSB0 recv-until \"OK\" -t 5        # exit 0=matched 2=timeout 3=disconnected 1=error\n"
    "  holdcom -p /dev/ttyUSB0 txn --send $'AT\\r\\n' --until \"OK\" -t 5   # one takeover: send+wait+release\n"
    "  holdcom -p /dev/ttyUSB0 config                    # show resolved config (no port open)\n"
    "  holdcom -p /dev/ttyUSB0 recv-until \"OK\" -t 5 --output session.log   # also save to file\n"
    "  holdcom selftest\n"
    "\n"
    "console: Ctrl-] or Ctrl-C quits; -I passes Ctrl-C through to the device\n"
    "(e.g. for a MicroPython REPL that needs Ctrl-C).\n"
    "\n"
    f"{EXIT_HELP}\n"
    "\n"
    "Library: `from holdcom import Session, recv_until, RecvResult, RecvStatus`\n"
    "for scripted send -> wait -> release without subprocess gaps.\n"
    "\n"
    "Encoding: send/--send are UTF-8 text unless --hex/--send-hex given; "
    "recv-until/--until match byte-wise. Output is raw bytes (lossless)."
)


def build_parser():
    p = argparse.ArgumentParser(
        prog="holdcom",
        formatter_class=_HelpFormatter,
        description=DESCRIPTION,
        epilog=EPILOG)
    p.add_argument("-v", "--version", action="version",
                   version=f"holdcom {__version__}")
    p.add_argument("-p", "--port",
                   help="serial port, e.g. /dev/cu.usbmodem1101 "
                        "(positional also works; omit to auto-pick the only device)")
    p.add_argument("-b", "--baud", type=int, default=None,
                   help="baud rate (must be > 0; default: inherit driver setting)")
    p.add_argument("-r", "--raw", action="store_true",
                   help="raw mode: disable echo/line editing at take-over "
                        "(no modem touch)")
    p.add_argument("--idle-dtr", choices=["high", "low"], default=None,
                   help="DTR level at take-over (default: don't touch). "
                        "Set only if your board needs a specific idle level")
    p.add_argument("--idle-rts", choices=["high", "low"], default=None,
                   help="RTS level at take-over (default: don't touch). "
                        "Set only if your board needs a specific idle level")
    p.add_argument("-I", "--int-passthrough", action="store_true",
                   help="pass Ctrl-C through to the device instead of quitting "
                        "(use when the target needs Ctrl-C, e.g. a MicroPython "
                        "REPL); by default Ctrl-C also quits holdcom")
    p.add_argument("--output", default=None, help=OUTPUT_HELP)
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("send",
                       help="send TEXT (UTF-8) to the port; --hex to send raw bytes")
    s.add_argument("data", help="text to send (UTF-8). Use --hex for raw bytes.")
    s.add_argument("--hex", action="store_true",
                   help="interpret `data` as a hex string (raw bytes)")
    ru = sub.add_parser("recv-until",
                        help="read until PATTERN appears, or timeout/maxlen")
    ru.add_argument("pattern",
                    help="byte/UTF-8 pattern to wait for (--hex for raw bytes)")
    ru.add_argument("-t", "--timeout", type=float, default=5.0,
                    help="max seconds to wait (must be > 0)")
    ru.add_argument("--maxlen", type=int, default=RECV_MAXLEN_DEFAULT,
                    help=f"max bytes to accumulate before giving up "
                         f"(default {RECV_MAXLEN_DEFAULT})")
    ru.add_argument("--hex", action="store_true",
                   help="interpret `pattern` as a hex string (raw bytes)")
    ru.add_argument("--output", default=None, help=OUTPUT_HELP)
    rr = sub.add_parser("recv", help="read once, up to -t seconds")
    rr.add_argument("-t", "--timeout", type=float, default=1.0,
                    help="max seconds to wait (must be > 0)")
    rr.add_argument("--output", default=None, help=OUTPUT_HELP)
    cfg = sub.add_parser("config",
                         help="show the resolved take-over configuration "
                              "(does NOT open the port or query live line state)")
    sub.add_parser("status", help="DEPRECATED alias for 'config'")
    txn = sub.add_parser("txn",
                         help="transaction: open once, optionally send, wait "
                              "for a pattern (or time out), then release")
    txn.add_argument("--send", default=None,
                     help="TEXT to send at take-over (UTF-8). Use --send-hex "
                          "for raw bytes. Shell $'...' for control chars")
    txn.add_argument("--send-hex", default=None,
                     help="hex string to send at take-over (raw bytes)")
    txn.add_argument("--until", default=None,
                     help="wait until this PATTERN appears in the response "
                          "(--until-hex for raw bytes)")
    txn.add_argument("--until-hex", default=None,
                     help="hex string pattern to wait for (raw bytes)")
    txn.add_argument("-t", "--timeout", type=float, default=5.0,
                     help="max seconds to wait for --until (must be > 0)")
    txn.add_argument("--maxlen", type=int, default=RECV_MAXLEN_DEFAULT,
                     help=f"max bytes to accumulate before giving up "
                          f"(default {RECV_MAXLEN_DEFAULT})")
    txn.add_argument("--output", default=None, help=OUTPUT_HELP)
    con = sub.add_parser("console",
                         help="interactive console (default when no command given)")
    con.add_argument("--output", default=None, help=OUTPUT_HELP)
    sub.add_parser("selftest")
    return p


def _find_device(argv):
    """Index of the first token that is a standalone (non-option, non-option-
    value) positional, or None. Used to detect a picocom-style leading device
    path while ignoring option values such as the argument of `-p`/`-b`."""
    opts_with_val = {"-p", "--port", "-b", "--baud", "--idle-dtr",
                     "--idle-rts", "--output"}
    i, n = 0, len(argv)
    while i < n:
        a = argv[i]
        if a.startswith("-"):
            if a in opts_with_val and i + 1 < n:
                i += 2
                continue
            i += 1
            continue
        return i
    return None


def _auto_detect_port():
    """Scan for serial devices and return them sorted. Used when neither a
    positional device nor `-p/--port` is given, so `holdcom` with no port just
    works when exactly one device is attached.

    Returns a sorted list of candidate device paths (may be empty)."""
    import glob
    if sys.platform == "darwin":
        # Only real USB-serial adapters (CP210x/CDC/FTDI). macOS also exposes
        # paired-Bluetooth, debug-console and wlan-debug as /dev/cu.* which are
        # never the target, so we do NOT scan the bare /dev/cu.* glob.
        patterns = ["/dev/cu.usbmodem*", "/dev/cu.usbserial*"]
        skip = ()
    elif sys.platform.startswith("linux"):
        patterns = ["/dev/ttyUSB*", "/dev/ttyACM*"]
        skip = ()
    else:
        patterns = ["/dev/cu.*", "/dev/ttyUSB*", "/dev/ttyACM*"]
        skip = ()
    found = set()
    for pat in patterns:
        for dev in glob.glob(pat):
            if not any(s in dev for s in skip):
                found.add(dev)
    return sorted(found)


def _try_open(port, baud, raw, idle_dtr, idle_rts):
    """Open the port, turning platform errors into a clear message + exit code.
    Returns (fd, None) on success or (None, exit_code) on error."""
    try:
        return open_safe(port, baud=baud, raw=raw,
                         dtr_high=idle_dtr, rts_high=idle_rts), None
    except PortError as e:
        sys.stderr.write(f"error: {e}\n")
        return None, CATEGORY_EXIT[e.category]


def _usage_error(msg):
    sys.stderr.write(f"error: {msg}\n")
    return EXIT_USAGE


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    argv = list(argv)

    # picocom-style: if the first standalone (non-option) token is NOT a known
    # subcommand, treat it as the serial device and rewrite it as `-p <device>`
    # before parsing. This keeps `holdcom /dev/ttyX -b 2000000` working exactly
    # like `picocom /dev/ttyX -b 2000000`, while `-p` / subcommands keep working.
    idx = _find_device(argv)
    if idx is not None and argv[idx] not in SUBCOMMANDS:
        dev = argv[idx]
        has_port_opt = any(a in ("-p", "--port") for a in argv)
        if has_port_opt:
            # `-p` already given; just drop the redundant positional device.
            argv = argv[:idx] + argv[idx + 1:]
        else:
            argv = argv[:idx] + ["-p", dev] + argv[idx + 1:]

    args = build_parser().parse_args(argv)
    port = args.port

    idle_dtr = {"high": True, "low": False}.get(args.idle_dtr)
    idle_rts = {"high": True, "low": False}.get(args.idle_rts)

    if args.cmd == "selftest":
        return selftest()

    # picocom-like: no subcommand given => default to interactive console.
    if args.cmd is None:
        args.cmd = "console"

    # Commands that need a real port: auto-detect when none was named.
    # `config`/`status` only report the intended configuration and must NOT
    # open a port (opening would assert DTR and could reset the MCU).
    NEEDS_PORT = {"send", "recv", "recv-until", "txn", "console"}
    if not port and args.cmd in NEEDS_PORT:
        candidates = _auto_detect_port()
        if len(candidates) == 1:
            port = candidates[0]
            sys.stderr.write(f"[holdcom] no port given; auto-selected {port}\n")
        elif not candidates:
            sys.stderr.write("error: no serial port found. Plug in a device or "
                             "name one explicitly:\n"
                             "  holdcom /dev/cu.usbmodem1101 -b 115200\n")
            return 2
        else:
            sys.stderr.write("error: multiple serial ports found; name one with "
                             "-p/device:\n")
            for c in candidates:
                sys.stderr.write(f"  {c}\n")
            return 2

    # ---- parameter-boundary validation (before any port open) ----
    if args.baud is not None and args.baud <= 0:
        return _usage_error("baud must be > 0")

    if args.cmd in ("recv", "recv-until", "txn"):
        if args.timeout is not None and args.timeout <= 0:
            return _usage_error(f"timeout must be > 0 (got {args.timeout})")

    if args.cmd == "send":
        try:
            payload = _to_bytes(args.data, args.hex)
        except ValueError as e:
            return _usage_error(str(e))
        fd, rc = _try_open(port, args.baud, args.raw, idle_dtr, idle_rts)
        if fd is None:
            return rc
        try:
            send(fd, payload)
        finally:
            close_safe(fd)
        return 0

    if args.cmd == "recv":
        fd, rc = _try_open(port, args.baud, args.raw, idle_dtr, idle_rts)
        if fd is None:
            return rc
        tee = _Tee(args.output)
        try:
            data = recv(fd, args.timeout)
            tee.write(data)
        finally:
            tee.close()
            close_safe(fd)
        return 0

    if args.cmd == "recv-until":
        try:
            pattern = _to_bytes(args.pattern, args.hex)
        except ValueError as e:
            return _usage_error(str(e))
        if len(pattern) == 0:
            return _usage_error("empty pattern (use a non-empty string or hex)")
        if args.maxlen is not None and args.maxlen <= 0:
            return _usage_error("maxlen must be > 0")
        fd, rc = _try_open(port, args.baud, args.raw, idle_dtr, idle_rts)
        if fd is None:
            return rc
        tee = _Tee(args.output)
        try:
            res = recv_until(fd, pattern, args.timeout, maxlen=args.maxlen)
            _emit_recv_result(res, tee)
        finally:
            tee.close()
            close_safe(fd)
        return _exit_for_status(res.status)

    if args.cmd == "txn":
        send_bytes = None
        if args.send is not None:
            try:
                send_bytes = _to_bytes(args.send, False)
            except ValueError as e:
                return _usage_error(str(e))
        elif args.send_hex is not None:
            try:
                send_bytes = _to_bytes(args.send_hex, True)
            except ValueError as e:
                return _usage_error(str(e))
        if send_bytes is not None and len(send_bytes) == 0:
            return _usage_error("empty --send/--send-hex payload")

        until = None
        if args.until is not None:
            try:
                until = _to_bytes(args.until, False)
            except ValueError as e:
                return _usage_error(str(e))
        elif args.until_hex is not None:
            try:
                until = _to_bytes(args.until_hex, True)
            except ValueError as e:
                return _usage_error(str(e))
        if until is not None and len(until) == 0:
            return _usage_error("empty --until/--until-hex pattern")
        if args.maxlen is not None and args.maxlen <= 0:
            return _usage_error("maxlen must be > 0")

        fd, rc = _try_open(port, args.baud, args.raw, idle_dtr, idle_rts)
        if fd is None:
            return rc
        tee = _Tee(args.output)
        try:
            if send_bytes is not None:
                send(fd, send_bytes)
                sys.stderr.write(f"[txn] sent {len(send_bytes)} bytes\n")
            if until is not None:
                res = recv_until(fd, until, args.timeout, maxlen=args.maxlen)
                _emit_recv_result(res, tee)
                return _exit_for_status(res.status)
            # No --until: just capture whatever arrives within the timeout.
            data = recv(fd, args.timeout)
            tee.write(data)
            sys.stderr.write(f"[txn] captured {len(data)} bytes (no --until)\n")
            return 0
        finally:
            tee.close()
            close_safe(fd)

    if args.cmd in ("status", "config"):
        if args.cmd == "status":
            sys.stderr.write("warning: 'status' is deprecated; use 'config'\n")
        _cmd_config(port, args)
        return 0

    if args.cmd == "console":
        fd, rc = _try_open(port, args.baud, args.raw, idle_dtr, idle_rts)
        if fd is None:
            return rc
        try:
            _run_console_on_fd(fd, args)
        finally:
            close_safe(fd)
        return 0

    sys.stderr.write(f"error: unknown command {args.cmd}\n")
    return 2


def _run_console_on_fd(fd, args):
    """Drive the interactive console over an already-open fd (so the explicit
    open-error handling in main applies consistently)."""
    import tty
    tee = _Tee(args.output)
    try:
        stdin_fd = sys.stdin.fileno()
        old = termios.tcgetattr(stdin_fd)
        tty.setraw(stdin_fd)
    except Exception:
        old = None

    stop = threading.Event()

    def reader():
        while not stop.is_set():
            if _readable(sys.stdin.fileno(), 0.1):
                try:
                    ch = os.read(sys.stdin.fileno(), 1)
                except OSError:
                    break
                if ch == b"\x1d":  # Ctrl-]
                    stop.set()
                    break
                if not args.int_passthrough and ch == b"\x03":  # Ctrl-C
                    stop.set()
                    break
                try:
                    send(fd, ch, timeout=1.0)
                except Exception:
                    stop.set()
                    break

    def writer():
        while not stop.is_set():
            try:
                data = recv(fd, 0.1, 1024)
            except PortDisconnected as e:
                sys.stderr.write(f"\n[console] device disconnected: {e}\n")
                stop.set()
                break
            except OSError as e:
                sys.stderr.write(f"\n[console] serial I/O error: {e}\n")
                stop.set()
                break
            if data:
                tee.write(data)

    t_r = threading.Thread(target=reader, daemon=True)
    t_w = threading.Thread(target=writer, daemon=True)
    t_r.start()
    t_w.start()
    sys.stderr.write(f"[console] attached to {args.port or '(auto)'} via open fd; "
                     f"Ctrl-] or Ctrl-C to quit (Ctrl-C passthrough: -I)\n")
    try:
        while not stop.is_set():
            t_r.join(0.2)
    finally:
        stop.set()
        t_r.join(0.5)
        t_w.join(0.5)
        if old is not None:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old)
        tee.close()
        sys.stderr.write("[console] released\n")


if __name__ == "__main__":
    sys.exit(main())
