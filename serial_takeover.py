#!/usr/bin/env python3
"""serial_takeover.py — minimal on-demand serial take-over that never resets
the MCU on take-over/release.

Design (see REQUIREMENTS.md):
  * Based on picocom's --noinit / --noreset termios+ioctl mechanism.
  * NOT based on pyserial (pyserial re-opens and flips modem lines -> reset).
  * No daemon, no socket, no flash, no remote, no deliberate modem control.
  * Each CLI invocation is a self-contained take-over -> act -> release cycle.

The one unavoidable flow-control event is the kernel driver asserting DTR/RTS
on open(); that is a hardware/OS fact, not something this tool does. On
take-over we additionally set DTR/RTS exactly ONCE to the idle-safe state
(default: both asserted/high, which for the common low-active reset circuit
= released = safe), mirroring how picocom calls set_dtr_rts() after tcsetattr
(term_apply can reset the lines on some drivers). This happens only at open();
release (close) and every send/recv never touch the modem lines.

Static guarantee: TIOCM* ioctls appear ONLY in `set_idle_state` (called once
from `open_safe`). Enforced by `selftest` (AST scan per function).
"""
import argparse
import ast
import errno
import fcntl
import os
import select
import struct
import sys
import termios
import threading
import time

# TIOCM* constants mean modem-line control. They are permitted ONLY inside
# `set_idle_state` (called exactly once from `open_safe` at take-over).
# `selftest` enforces this confinement via an AST scan per function.


def open_safe(port, baud=None, raw=False, dtr_high=True, rts_high=True):
    """Take over `port`. Returns an fd.

    Equals picocom --noinit (no modem-line dance beyond the idle-safe set)
    + --noreset (HUPCL=0). DTR/RTS are set to the idle-safe state exactly
    once, AFTER tcsetattr (which can reset them on some drivers).
    """
    flags = os.O_RDWR | getattr(os, "O_NOCTTY", 0) | os.O_NONBLOCK
    fd = os.open(port, flags)

    # Single holder: prevent a second process from opening the same port.
    try:
        fcntl.ioctl(fd, termios.TIOCEXCL, 0)
    except (AttributeError, OSError) as e:
        sys.stderr.write(f"warn: TIOCEXCL unavailable ({e}); continuing without exclusivity\n")

    attrs = termios.tcgetattr(fd)
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

    if baud is not None:
        bc = getattr(termios, f"B{baud}", None)
        if bc is None:
            raise ValueError(f"unsupported baud rate: {baud}")
        termios.cfsetspeed(attrs, bc)

    # ONE tcsetattr: applies HUPCL-clear (+ optional baud/raw). On some
    # drivers tcsetattr (term_apply) resets DTR/RTS, so we re-assert the
    # idle-safe state immediately afterwards (picocom does the same).
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    set_idle_state(fd, dtr_high=dtr_high, rts_high=rts_high)
    return fd


def set_idle_state(fd, dtr_high=True, rts_high=True):
    """Assert/clear DTR and RTS to the chosen idle-safe levels, exactly once
    at take-over. Uses TIOCMBIS/TIOCMBIC so only DTR/RTS are affected and
    other modem bits are left untouched.

    Default (both high/asserted) is the safe state for the common
    low-active reset circuit (e.g. ESP32: EN/IO0 pulled up, high = released).
    Pass high/low via --idle-dtr / --idle-rts for non-standard polarities.
    """
    set_bits = 0
    clr_bits = 0
    if dtr_high:
        set_bits |= termios.TIOCM_DTR
    else:
        clr_bits |= termios.TIOCM_DTR
    if rts_high:
        set_bits |= termios.TIOCM_RTS
    else:
        clr_bits |= termios.TIOCM_RTS
    if set_bits:
        try:
            fcntl.ioctl(fd, termios.TIOCMBIS, struct.pack("I", set_bits))
        except OSError as e:
            if e.errno in (errno.ENOTTY, errno.EOPNOTSUPP, errno.EINVAL):
                sys.stderr.write("warn: modem-control ioctl unsupported on this "
                                 "device; idle-safe state skipped "
                                 "(expected for pty/virtual ports)\n")
            else:
                raise
    if clr_bits:
        try:
            fcntl.ioctl(fd, termios.TIOCMBIC, struct.pack("I", clr_bits))
        except OSError as e:
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
    if isinstance(data, str):
        data = data.encode()
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
    if _readable(fd, timeout):
        try:
            return os.read(fd, n)
        except BlockingIOError:
            return b""
    return b""


def recv_until(fd, pattern, timeout=5.0, n=4096):
    if isinstance(pattern, str):
        pattern = pattern.encode()
    buf = bytearray()
    end = time.monotonic() + timeout
    while True:
        remaining = end - time.monotonic()
        chunk = recv(fd, max(0.0, remaining), n) if remaining > 0 else b""
        if chunk:
            buf.extend(chunk)
            if pattern in buf:
                return bytes(buf)
        if time.monotonic() >= end:
            return bytes(buf)


def console(port, baud=None, raw=True, dtr_high=True, rts_high=True):
    """Interactive console for a human. Attach = take over; Ctrl-] = release."""
    import tty
    fd = open_safe(port, baud=baud, raw=raw, dtr_high=dtr_high, rts_high=rts_high)
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
                try:
                    send(fd, ch, timeout=1.0)
                except Exception:
                    stop.set()
                    break

    def writer():
        while not stop.is_set():
            data = recv(fd, 0.1, 1024)
            if data:
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()

    t_r = threading.Thread(target=reader, daemon=True)
    t_w = threading.Thread(target=writer, daemon=True)
    t_r.start()
    t_w.start()
    sys.stderr.write(f"[console] attached to {port}; Ctrl-] to quit\n")
    try:
        while not stop.is_set():
            t_r.join(0.2)
    finally:
        stop.set()
        t_r.join(0.5)
        t_w.join(0.5)
        if old is not None:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old)
        close_safe(fd)
        sys.stderr.write("[console] released\n")


def selftest():
    """Phase 0 verification, no real device needed."""
    src = open(__file__, "r", encoding="utf-8").read()
    tree = ast.parse(src)

    ALLOWED = {"open_safe", "set_idle_state"}   # the one sanctioned place
    FORBIDDEN = {"close_safe", "send", "recv", "recv_until", "console",
                 "status", "main", "selftest", "build_parser",
                 "_readable", "_writable"}

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
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        prog="serial_takeover.py",
        description="On-demand serial take-over without resetting the MCU.")
    p.add_argument("-p", "--port", help="serial port (e.g. /dev/cu.usbserial-*)")
    p.add_argument("-b", "--baud", type=int, default=None,
                   help="set baud rate (optional; default = inherit driver setting)")
    p.add_argument("-r", "--raw", action="store_true",
                   help="apply raw mode at take-over (single tcsetattr, no modem touch)")
    p.add_argument("--idle-dtr", choices=["high", "low"], default="high",
                   help="DTR idle level at take-over (default high = safe for "
                        "low-active reset circuits)")
    p.add_argument("--idle-rts", choices=["high", "low"], default="high",
                   help="RTS idle level at take-over (default high = safe for "
                        "low-active reset circuits)")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("send").add_argument("data")
    ru = sub.add_parser("recv-until")
    ru.add_argument("pattern")
    ru.add_argument("-t", "--timeout", type=float, default=5.0)
    rr = sub.add_parser("recv")
    rr.add_argument("-t", "--timeout", type=float, default=1.0)
    sub.add_parser("status")
    sub.add_parser("console")
    sub.add_parser("selftest")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)

    idle_dtr = args.idle_dtr == "high"
    idle_rts = args.idle_rts == "high"

    if args.cmd == "selftest":
        return selftest()

    if not args.port and args.cmd != "selftest":
        sys.stderr.write("error: -p/--port is required (except for selftest)\n")
        return 2
    if args.cmd is None:
        sys.stderr.write("error: no command given\n")
        return 2

    if args.cmd == "send":
        fd = open_safe(args.port, args.baud, args.raw, idle_dtr, idle_rts)
        try:
            send(fd, args.data)
        finally:
            close_safe(fd)
        return 0

    if args.cmd == "recv":
        fd = open_safe(args.port, args.baud, args.raw, idle_dtr, idle_rts)
        try:
            data = recv(fd, args.timeout)
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
        finally:
            close_safe(fd)
        return 0

    if args.cmd == "recv-until":
        fd = open_safe(args.port, args.baud, args.raw, idle_dtr, idle_rts)
        try:
            data = recv_until(fd, args.pattern, args.timeout)
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
        finally:
            close_safe(fd)
        return 0

    if args.cmd == "status":
        print(f"port={args.port} baud={args.baud} raw={args.raw} "
              f"idle_dtr={args.idle_dtr} idle_rts={args.idle_rts}")
        print("note: DTR/RTS are set to the idle-safe level exactly once at "
              "take-over; release and all I/O never touch the modem lines.")
        return 0

    if args.cmd == "console":
        console(args.port, args.baud, args.raw, idle_dtr, idle_rts)
        return 0

    sys.stderr.write(f"error: unknown command {args.cmd}\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
