"""
uart_client.py - AI-facing client for uart-gateway (SKELETON, no logic yet)

CRITICAL: this client uses ONLY plain sockets. It NEVER imports pyserial
and NEVER opens the serial port directly. All serial access goes through
the gateway daemon, which is the whole point of this project.

Intended API (to be implemented):
    c = UartClient(sock_path="/tmp/uart-gateway.sock")
    c.connect()
    c.send("AT\\r\\n")
    line = c.recv_line(timeout=2.0)
    c.recv_until("OK", timeout=5.0)
    c.set_dtr(1); c.set_rts(1)
    c.reset()          # toggle EN
    c.boot()           # enter download mode
    c.status()
    c.close()
"""
import socket
import time

DEFAULT_SOCK = "/tmp/uart-gateway.sock"


class UartClient:
    def __init__(self, sock_path=DEFAULT_SOCK, tcp_host=None, tcp_port=0, timeout=5.0):
        self.sock_path = sock_path
        self.tcp_host = tcp_host
        self.tcp_port = tcp_port
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

    def set_dtr(self, level: int):
        raise NotImplementedError("uart_client.set_dtr: skeleton not implemented")

    def set_rts(self, level: int):
        raise NotImplementedError("uart_client.set_rts: skeleton not implemented")

    def reset(self):
        raise NotImplementedError("uart_client.reset: skeleton not implemented")

    def boot(self):
        raise NotImplementedError("uart_client.boot: skeleton not implemented")

    def status(self):
        raise NotImplementedError("uart_client.status: skeleton not implemented")

    def close(self):
        if self._sock:
            self._sock.close()
            self._sock = None
