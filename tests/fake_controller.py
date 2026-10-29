"""Scripted fake FANUC controller + helpers for tests (real sockets, deterministic).

Each incoming connection consumes the next behaviour in the list; once the list
is used up, connections behave as "ok".

    ok            send READY, ACK every command line
    nak           send READY, answer every command with "NAK BUSY"
    drop_no_ack   send READY, read one command, close without answering
    silent        send READY, read commands, never answer (client must time out)
    bad_banner    send "HELLO" instead of READY
"""
import contextlib
import io
import socket
import threading


def silence_stdout(testcase):
    """Hide the gateway's print() output while a test runs."""
    cm = contextlib.redirect_stdout(io.StringIO())
    cm.__enter__()
    testcase.addCleanup(cm.__exit__, None, None, None)


class FakeController:
    def __init__(self, behaviours=(), port=0):
        self.behaviours = list(behaviours)
        self.received = []        # every command line received, in order
        self.connections = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._conns = []
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(("127.0.0.1", port))   # port 0: the OS picks a free port
        self.server.listen(5)
        self.server.settimeout(0.05)
        self.port = self.server.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=2)
        for conn in self._conns:
            try:
                conn.close()
            except OSError:
                pass
        self.server.close()

    def _next_behaviour(self):
        with self._lock:
            self.connections += 1
            return self.behaviours.pop(0) if self.behaviours else "ok"

    def _serve(self):
        while not self._stop.is_set():
            try:
                conn, _ = self.server.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)  # like the real mock server
            self._conns.append(conn)
            threading.Thread(target=self._handle,
                             args=(conn, self._next_behaviour()), daemon=True).start()

    def _handle(self, conn, behaviour):
        f = conn.makefile("rb")
        try:
            conn.sendall(b"HELLO\r\n" if behaviour == "bad_banner" else b"READY\r\n")
            while True:
                raw = f.readline(4096)
                if not raw:
                    break
                with self._lock:
                    self.received.append(raw.decode().strip())
                if behaviour == "drop_no_ack":
                    break
                if behaviour == "nak":
                    conn.sendall(b"NAK BUSY\r\n")
                elif behaviour == "ok":
                    conn.sendall(b"ACK\r\n")
        except OSError:
            pass
        finally:
            try:
                f.close()
                conn.close()
            except OSError:
                pass
