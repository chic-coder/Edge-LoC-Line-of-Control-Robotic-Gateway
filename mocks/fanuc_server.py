# mocks/fanuc_server.py
"""Concurrent multi-threaded TCP automation test runner mimicking FANUC systems."""
import socket
import threading
import time
import re
from datetime import datetime

MACRO = re.compile(r"cnc_wrmacro\(#(\d+),\s*([+-]?\d+(?:\.\d+)?)\)")
PMC = re.compile(r"pmc_wrrange\((R\d{4}),\s*(0x[0-9A-Fa-f]{1,2}|\d{1,3})\)")

class MockFanucServer:
    def __init__(self, host, port, ack_delay=0, nak_rate=0, drop_every=0, seed=None):
        import random
        self.host, self.port = host, port
        self.ack_delay = ack_delay
        self.nak_rate = nak_rate
        self.drop_every = drop_every
        self.rng = random.Random(seed)
        self.macro_vars = {}
        self.pmc_bytes = {}
        self.lock = threading.Lock()
        self.cmd_count = 0
        self.server_sock = None

    def log(self, msg):
        print(f"{datetime.now():%H:%M:%S.%f}"[:-3] + f"  {msg}", flush=True)

    def _apply(self, command):
        """Parse and apply one command. Logs using exact assignment code formatting specs."""
        m = MACRO.fullmatch(command)
        if m:
            reg_num = int(m.group(1))
            val_float = float(m.group(2))
            with self.lock:
                self.macro_vars[reg_num] = m.group(2)
            
            # Format exactly as: cnc_wrmacro(#500, +0.013) // Dynamic offset
            self.log(f"cnc_wrmacro(#{reg_num}, {val_float:+.4f})")
            return None
            
        m = PMC.fullmatch(command)
        if m:
            reg_addr = m.group(1)
            value = int(m.group(2), 0)
            if not 0 <= value <= 255:
                return "BYTE_RANGE"
            with self.lock:
                self.pmc_bytes[reg_addr] = value
            
            # Format exactly as: pmc_wrrange(R0500, 0x01) // 0x01=OK, 0x02=Rew, 0x04=Rej
            self.log(f"pmc_wrrange({reg_addr}, 0x{value:02X})")
            return None
        return "BAD_CMD"

    def _client_handler(self, conn, addr):
        self.log(f"gateway connected from {addr[0]}:{addr[1]}")
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        f = conn.makefile("rb")
        try:
            conn.sendall(b"READY\r\n")
            while True:
                raw = f.readline(4096)
                if not raw:
                    break
                command = raw.decode("utf-8", errors="replace").strip()
                if not command:
                    continue
                with self.lock:
                    self.cmd_count += 1
                    n = self.cmd_count

                if self.ack_delay:
                    time.sleep(self.ack_delay / 1000)
                if self.rng.random() < self.nak_rate:
                    self.log(f"FAULT: NAK injected for {command}")
                    conn.sendall(b"NAK BUSY\r\n")
                    continue

                err = self._apply(command)
                if err:
                    self.log(f"rejected {command!r}: {err}")
                    conn.sendall(f"NAK {err}\r\n".encode())
                    continue

                if self.drop_every and n % self.drop_every == 0:
                    self.log("FAULT: command applied, dropping connection before ACK")
                    break
                conn.sendall(b"ACK\r\n")
        except OSError:
            pass
        finally:
            f.close()
            conn.close()
            self.log("gateway disconnected")

    def start(self):
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind((self.host, self.port))
        self.server_sock.listen(5)
        self.log(f"Mock FANUC listening on {self.host}:{self.port}")
        try:
            while True:
                conn, addr = self.server_sock.accept()
                threading.Thread(target=self._client_handler, args=(conn, addr), daemon=True).start()
        except KeyboardInterrupt:
            pass
        finally:
            self.server_sock.close()
            print(f"\nFinal state: macro={self.macro_vars}  "
                  f"pmc={ {k: hex(v) for k, v in self.pmc_bytes.items()} }  commands={self.cmd_count}")
