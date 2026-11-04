#!/usr/bin/env python3
"""serial_takeover.py — minimal on-demand serial take-over that never touches
flow control (DTR/RTS), so it never resets the MCU.

Design (see REQUIREMENTS.md):
  * Based on picocom's --noinit / --noreset termios+ioctl mechanism.
  * NOT based on pyserial (pyserial re-opens and flips modem lines -> reset).
  * No daemon, no socket, no modem-line control, no flash, no remote.
  * Each CLI invocation is a self-contained take-over -> act -> release cycle.

The single unavoidable flow-control event is the kernel driver asserting
DTR/RTS on open(); that is a hardware/OS fact, not something this tool does.
Everything this tool does at take-over/release is limited to:
  open(O_RDWR|O_NOCTTY|O_NONBLOCK) -> ioctl(TIOCEXCL) -> one tcsetattr that
  ONLY clears HUPCL (so close() will not drop DTR/RTS) [+ optional baud/raw],
  then close() (HUPCL=0 => no line drop).

Static guarantee: this module contains NO TIOCM* ioctl, i.e. it never writes
DTR/RTS. Enforced by `selftest`.
"""
import argparse
import ast
import fcntl
import os
import select
import sys
import termios
import threading
import time

# Any TIOCM* termios constant means modem-line control. We must never use one.
# `selftest` fails if such an identifier appears in the code (AST scan, so
# docstrings/comments are ignored).


def open_safe(port, baud=None, raw=False):
    """Take over `port` WITHOUT touching DTR/RTS. Returns an fd.

    Equals picocom --noinit (no modem-line dance) + --noreset (HUPCL=0).
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

    # ONE tcsetattr: applies HUPCL-clear (+ optional baud/raw). It does NOT
    # touch the DTR/RTS bits — they remain exactly as the driver left them.
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    return fd


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


def console(port, baud=None, raw=True):
    """Interactive console for a human. Attach = take over; Ctrl-] = release."""
    import tty
    fd = open_safe(port, baud=baud, raw=raw)
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
    import inspect
    src = inspect.getsource(sys.modules[__name__])
    tree = ast.parse(src)
    for node in ast.walk(tree):
        name = None
        if isinstance(node, ast.Attribute):
            name = node.attr
        elif isinstance(node, ast.Name):
            name = node.id
        if name and name.startswith("TIOCM"):
            print(f"FAIL: forbidden modem-control identifier {name!r} in code")
            return 1
    print("OK: static scan — no TIOCM* (no modem-line control) identifier in code")

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
        description="On-demand serial take-over without touching flow control.")
    p.add_argument("-p", "--port", help="serial port (e.g. /dev/cu.usbserial-*)")
    p.add_argument("-b", "--baud", type=int, default=None,
                   help="set baud rate (optional; default = inherit driver setting)")
    p.add_argument("-r", "--raw", action="store_true",
                   help="apply raw mode at take-over (single tcsetattr, no modem touch)")
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

    if args.cmd == "selftest":
        return selftest()

    if not args.port and args.cmd != "selftest":
        sys.stderr.write("error: -p/--port is required (except for selftest)\n")
        return 2
    if args.cmd is None:
        sys.stderr.write("error: no command given\n")
        return 2

    if args.cmd == "send":
        fd = open_safe(args.port, args.baud, args.raw)
        try:
            send(fd, args.data)
        finally:
            close_safe(fd)
        return 0

    if args.cmd == "recv":
        fd = open_safe(args.port, args.baud, args.raw)
        try:
            data = recv(fd, args.timeout)
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
        finally:
            close_safe(fd)
        return 0

    if args.cmd == "recv-until":
        fd = open_safe(args.port, args.baud, args.raw)
        try:
            data = recv_until(fd, args.pattern, args.timeout)
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
        finally:
            close_safe(fd)
        return 0

    if args.cmd == "status":
        print(f"port={args.port} baud={args.baud} raw={args.raw}")
        print("note: this tool never reads or writes DTR/RTS (no modem control).")
        return 0

    if args.cmd == "console":
        console(args.port, args.baud, args.raw)
        return 0

    sys.stderr.write(f"error: unknown command {args.cmd}\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
