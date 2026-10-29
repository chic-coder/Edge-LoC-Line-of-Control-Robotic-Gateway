# gateway/fanuc_client.py
"""Implements robust, self-healing TCP sockets for controller interaction."""
import socket
import time
from .config import SOCK_TIMEOUT, MAX_RETRIES, BACKOFF_START, BACKOFF_MAX

class FanucClient:
    def __init__(self, host, port, timeout=SOCK_TIMEOUT):
        self.host, self.port, self.timeout = host, port, timeout
        self.sock = None
        self.rfile = None

    def connect(self):
        self.close()
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.settimeout(self.timeout)
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

def deliver(client: FanucClient, commands: list, max_retries=MAX_RETRIES,
            backoff_start=BACKOFF_START, backoff_max=BACKOFF_MAX):
    """Orchestrates backoffs and automated transport reconnection handling loops.

    Safe to resend: both commands write absolute values (idempotent).
    Returns latency in ms, or None if the cycle had to be dropped.
    """
    backoff = backoff_start
    for attempt in range(1, max_retries + 1):
        try:
            if client.sock is None:
                client.connect()
            return client.send(commands)
        except OSError as e:
            print(f"[Ethernet Error] Transport issue (Attempt {attempt}/{max_retries}): {e}")
            client.close()
            if attempt < max_retries:
                time.sleep(backoff)
                backoff = min(backoff * 2, backoff_max)
    return None