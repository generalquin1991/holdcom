"""
uart_client.py - AI-facing client for uart-gateway (SKELETON, no logic yet)

CRITICAL: this client uses ONLY plain sockets. It NEVER imports pyserial
and NEVER opens the serial port directly. All serial access goes through
the gateway daemon, which is the whole point of this project.

Intended API (to be implemented):
    c = UartClient(sock_path="/tmp/uart-gateway.sock")
    c.connect()           # occupy entry point
    c.send("AT\\r\\n")
    line = c.recv_line(timeout=2.0)
    c.recv_until("OK", timeout=5.0)
    c.status()
    c.close()             # release entry point
"""
import socket
import time

DEFAULT_SOCK = "/tmp/uart-gateway.sock"


class UartClient:
    def __init__(self, sock_path=DEFAULT_SOCK, timeout=5.0):
        self.sock_path = sock_path
        self.timeout = timeout
        self._sock = None

    def connect(self):
        raise NotImplementedError("uart_client.connect: skeleton not implemented")

    def send(self, data: str, hex_mode=False):
        raise NotImplementedError("uart_client.send: skeleton not implemented")

    def recv_line(self, timeout=None):
        raise NotImplementedError("uart_client.recv_line: skeleton not implemented")

    def recv_until(self, pattern: str, timeout=None):
        raise NotImplementedError("uart_client.recv_until: skeleton not implemented")

    def status(self):
        raise NotImplementedError("uart_client.status: skeleton not implemented")

    def close(self):
        if self._sock:
            self._sock.close()
            self._sock = None
