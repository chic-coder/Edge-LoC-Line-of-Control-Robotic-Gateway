# mocks/gauge_transmitter.py
"""Simulated RS232 dimensional instrumentation telemetry module with frame distortion injection capabilities."""
import time
import random
from datetime import datetime
import serial
from gateway.config import NOMINAL, USL, LSL, REWORK_MAX, PROBE_TOL

def calculate_verdict(ch1, ch2):
    sev = {"OK": 0, "REWORK": 1, "REJECT": 2}
    p1 = "REJECT" if (ch1 - NOMINAL < LSL or ch1 - NOMINAL > REWORK_MAX) else ("REWORK" if ch1 - NOMINAL > USL else "OK")
    p2 = "REJECT" if (ch2 - NOMINAL < LSL or ch2 - NOMINAL > REWORK_MAX) else ("REWORK" if ch2 - NOMINAL > USL else "OK")
    verdict = max(p1, p2, key=sev.get)
    if verdict == "OK" and abs(ch1 - ch2) > PROBE_TOL + 1e-9:
        verdict = "REWORK"
    return verdict

class MockGaugeTransmitter:
    def __init__(self, port, baud, lo, hi, mode="uniform", drift_step=0.002, noise=0.002, fault_rate=0.0, lie_rate=0.0, seed=None):
        self.port, self.baud = port, baud
        self.lo, self.hi = lo, hi
        self.mode = mode
        self.drift_step = drift_step
        self.noise = noise
        self.fault_rate = fault_rate
        self.lie_rate = lie_rate
        self.rng = random.Random(seed or random.randrange(10**6))

    def _corrupt(self, record):
        body = record.rstrip(b"\r\n")
        kind = self.rng.choice(["truncate", "garbage", "missing_field", "bad_verdict", "duplicate"])
        if kind == "truncate":
            return body[: self.rng.randint(5, len(body) - 3)], kind
        if kind == "garbage":
            pos = self.rng.randint(1, len(body) - 1)
            junk = bytes(self.rng.randint(0x80, 0xFF) for _ in range(self.rng.randint(1, 4)))
            return body[:pos] + junk + body[pos:] + b"\r\n", kind
        if kind == "missing_field":
            parts = body.split(b" ")
            return b" ".join(parts[:3] + parts[4:]) + b"\r\n", kind
        if kind == "bad_verdict":
            return body.rsplit(b" ", 1)[0] + b" MAYBE\r\n", kind
        return record + record, kind

    def execute(self, count=0, interval=1.0):
        print(f"[Gauge Mock] Opening port={self.port} Mode={self.mode}")
        try:
            ser = serial.Serial(self.port, self.baud, timeout=1)
        except Exception as e:
            print(f"[Gauge Mock Error] Critical port mapping assignment failure: {e}")
            return
        n = 0
        try:
            while not count or n < count:
                n += 1
                dev = self.rng.uniform(self.lo, self.hi) if self.mode == "uniform" else self.lo + (n * self.drift_step) % (self.hi - self.lo)
                ch1 = NOMINAL + dev + self.rng.gauss(0, self.noise)
                ch2 = NOMINAL + dev + self.rng.gauss(0, self.noise)
                verdict = calculate_verdict(round(ch1, 4), round(ch2, 4))
                if self.rng.random() < self.lie_rate:
                    verdict = self.rng.choice([v for v in ("OK", "REWORK", "REJECT") if v != verdict])
                
                stamp = datetime.now().strftime("%y%m%d%H%M")
                record = f"001 {stamp}_{n:05d} {ch1:+09.4f} {ch2:+09.4f} {verdict}\r\n".encode("ascii")
                payload, fault = record, None
                if self.fault_rate and self.rng.random() < self.fault_rate:
                    payload, fault = self._corrupt(record)
                
                ser.write(payload)
                tag = f"   <-- FAULT: {fault}" if fault else ""
                print(f"[Gauge Mock TX] data={payload.decode('ascii', 'replace').strip()!r}{tag}")
                time.sleep(interval)
        except KeyboardInterrupt:
            pass
        finally:
            ser.close()
