# gateway/fanuc_client.py
"""Implements robust, self-healing TCP sockets for controller interaction."""
import socket
import time
from .config import SOCK_TIMEOUT, MAX_RETRIES, BACKOFF_START, BACKOFF_MAX

class FanucClient:
    def __init__(self, host, port):
        self.host, self.port = host, port
        self.sock = None
        self.rfile = None

    def connect(self):
        self.close()
        sock = socket.create_connection((self.host, self.port), timeout=SOCK_TIMEOUT)
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.settimeout(SOCK_TIMEOUT)
            rfile = sock.makefile("rb")
            banner = rfile.readline(64).strip()
            if banner != b"READY":
                raise ConnectionError(f"Expected READY banner, got: {banner!r}")
        except OSError:
            sock.close()
            raise
        self.sock, self.rfile = sock, rfile
        print(f"[Ethernet] Link established with FANUC server at {self.host}:{self.port}")

    def close(self):
        for resource in (self.rfile, self.sock):
            if resource:
                try:
                    resource.close()
                except OSError:
                    pass
        self.sock = self.rfile = None

    def send(self, commands: list) -> float:
        """Sends operational batches across sockets. Evaluates latency."""
        t0 = time.perf_counter_ns()
        payload = "".join(cmd + "\r\n" for cmd in commands)
        self.sock.sendall(payload.encode("ascii"))
        for cmd in commands:
            reply = self.rfile.readline(64)
            if not reply:
                raise ConnectionError("Link dropped by controller during payload transfer")
            reply = reply.decode("ascii", "replace").strip()
            if not reply.startswith("ACK"):
                raise ConnectionError(f"Command execution error: {cmd} -> {reply}")
        return (time.perf_counter_ns() - t0) / 1e6

def deliver(client: FanucClient, commands: list):
    """Orchestrates backoffs and automated transport reconnection handling loops."""
    backoff = BACKOFF_START
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if client.sock is None:
                client.connect()
            return client.send(commands)
        except OSError as e:
            print(f"[Ethernet Error] Transport issue (Attempt {attempt}/{MAX_RETRIES}): {e}")
            client.close()
            if attempt < MAX_RETRIES:
                time.sleep(backoff)
                backoff = min(backoff * 2, BACKOFF_MAX)
    return None
