# mocks/gauge_transmitter.py
"""Simulated RS232 dimensional instrumentation telemetry module with frame distortion injection capabilities."""
import time
import random
from datetime import datetime

# Gauge "firmware" limits. Deliberately NOT imported from gateway.config: a real
# gauge has its own limits, and sharing them would hide configuration mistakes in
# the gateway (both sides would be wrong in the same way, so no mismatch is ever seen).
NOMINAL = 10.0
USL, LSL, REWORK_MAX = 0.015, -0.015, 0.030
PROBE_TOL = 0.010
SEV = {"OK": 0, "REWORK": 1, "REJECT": 2}

def _probe_verdict(ch):
    dev = round(ch - NOMINAL, 4)
    if dev < LSL or dev > REWORK_MAX:
        return "REJECT"
    return "REWORK" if dev > USL else "OK"

def calculate_verdict(ch1, ch2):
    verdict = max(_probe_verdict(ch1), _probe_verdict(ch2), key=SEV.get)
    if verdict == "OK" and abs(round(ch1 - ch2, 4)) > PROBE_TOL:
        verdict = "REWORK"
    return verdict

class MockGaugeTransmitter:
    def __init__(self, port, baud, lo, hi, mode="uniform", drift_step=0.002, noise=0.002,
                 fault_rate=0.0, lie_rate=0.0, seed=None):
        self.port, self.baud = port, baud
        self.lo, self.hi = lo, hi
        self.mode = mode
        self.drift_step = drift_step
        self.noise = noise
        self.fault_rate = fault_rate
        self.lie_rate = lie_rate
        self.seed = seed if seed is not None else random.randrange(10**6)  # 0 is a valid seed
        self.rng = random.Random(self.seed)

    def next_deviation(self, n):
        if self.mode == "uniform":
            return self.rng.uniform(self.lo, self.hi)
        return self.lo + (n * self.drift_step) % (self.hi - self.lo)

    def make_record(self, n, dev):
        """Builds one wire record (bytes, CRLF-terminated) for part number n."""
        ch1 = round(NOMINAL + dev + self.rng.gauss(0, self.noise), 4)
        ch2 = round(NOMINAL + dev + self.rng.gauss(0, self.noise), 4)
        verdict = calculate_verdict(ch1, ch2)
        if self.rng.random() < self.lie_rate:
            verdict = self.rng.choice([v for v in ("OK", "REWORK", "REJECT") if v != verdict])
        stamp = datetime.now().strftime("%y%m%d%H%M")
        return f"001 {stamp}_{n:05d} {ch1:+09.4f} {ch2:+09.4f} {verdict}\r\n".encode("ascii")

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
        import serial  # imported here so the record logic can be used and tested without pyserial
        print(f"[Gauge Mock] seed={self.seed} range=[{self.lo:+.3f}, {self.hi:+.3f}] "
              f"mode={self.mode} port={self.port}")
        try:
            ser = serial.Serial(self.port, self.baud, timeout=1)
        except Exception as e:
            print(f"[Gauge Mock Error] Critical port mapping assignment failure: {e}")
            return
        n = sent = 0
        try:
            while not count or sent < count:
                n += 1
                dev = self.next_deviation(n)
                record = self.make_record(n, dev)
                payload, fault = record, None
                if self.fault_rate and self.rng.random() < self.fault_rate:
                    payload, fault = self._corrupt(record)

                ser.write(payload)
                sent += 1
                text = payload.decode("ascii", "replace").strip()
                print(f"{text}   <-- FAULT: {fault}" if fault else text)
                time.sleep(interval)
        except KeyboardInterrupt:
            pass
        except serial.SerialException as e:
            print(f"\n[Gauge Mock Error] Serial link lost: {e}")
        finally:
            ser.close()
            print(f"\n[Gauge Mock] sent {sent} records (seed={self.seed})")