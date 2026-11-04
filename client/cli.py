#!/usr/bin/env python3
"""
cli.py - command-line client for uart-gateway (SKELETON, no logic yet)

Planned usage:
    python3 cli.py send "AT\\r\\n"
    python3 cli.py recv 2000
    python3 cli.py recv_until OK 5000
    python3 cli.py reset
    python3 cli.py boot
    python3 cli.py status
"""
import argparse
import sys
from uart_client import UartClient, DEFAULT_SOCK


def main():
    p = argparse.ArgumentParser(prog="cli", description="uart-gateway client (skeleton)")
    p.add_argument("-s", "--sock", default=DEFAULT_SOCK, help="Unix socket path")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("send").add_argument("data")
    sub.add_parser("recv").add_argument("timeout_ms", type=int)
    ru = sub.add_parser("recv_until")
    ru.add_argument("pattern"); ru.add_argument("timeout_ms", type=int)
    sub.add_parser("reset")
    sub.add_parser("boot")
    sub.add_parser("status")

    args = p.parse_args()
    print("cli: NOT IMPLEMENTED (skeleton) - would dispatch:", args.cmd, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
