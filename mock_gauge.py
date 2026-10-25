"""Mock RS232 gauge that generates RANDOM records from a deviation range.
Instead of fixed test records, you give a range of deviation from nominal (mm):
    python mock_gauge.py --port /dev/pts/0 --lo -0.030 --hi 0.045

Each part gets a random deviation in [lo, hi]; channel 1 and 2 are that value plus
small probe noise; the gauge verdict is computed from the spec limits below.

Modes:
    uniform  every part: deviation = random.uniform(lo, hi)           (default)
    drift    simulated tool wear: deviation climbs by --drift-step per part from
             lo up to hi, then wraps (tool change), plus noise

"""
import argparse
import random
import time
from datetime import datetime

import serial

NOMINAL = 10.000
USL, LSL, REWORK_MAX = 0.015, -0.015, 0.030    #upper tolerance (010.0150mm), lower tolerance(009.9850mm), max rework limit
PROBE_TOL = 0.010   #difference between channel 1 and channel 2 values          

def probe_verdict(ch):
    dev = ch - NOMINAL
    if dev < LSL or dev > REWORK_MAX:
        return "REJECT"
    if dev > USL:
        return "REWORK"
    return "OK"

def gauge_verdict(ch1, ch2):
    """Same rule as the gateway: worst probe wins; probes that disagree -> REWORK."""
    sev = {"OK": 0, "REWORK": 1, "REJECT": 2}
    verdict = max(probe_verdict(ch1), probe_verdict(ch2), key=sev.get)
    if verdict == "OK" and abs(ch1 - ch2) > PROBE_TOL + 1e-9:
        verdict = "REWORK"
    return verdict

def make_record(n, dev, rng, noise, lie_rate):
    ch1 = NOMINAL + dev + rng.gauss(0, noise)
    ch2 = NOMINAL + dev + rng.gauss(0, noise)
    verdict = gauge_verdict(round(ch1, 4), round(ch2, 4))
    if rng.random() < lie_rate:
        verdict = rng.choice([v for v in ("OK", "REWORK", "REJECT") if v != verdict])
    stamp = datetime.now().strftime("%y%m%d%H%M")
    return f"001 {stamp}_{n:05d} {ch1:+09.4f} {ch2:+09.4f} {verdict}\r\n".encode("ascii")

def corrupt(record, rng):
    """Return (bytes_to_send, fault_name)."""
    body = record.rstrip(b"\r\n")
    kind = rng.choice(["truncate", "garbage", "missing_field", "bad_verdict", "duplicate"])
    if kind == "truncate":
        return body[: rng.randint(5, len(body) - 3)], kind          # no terminator
    if kind == "garbage":
        pos = rng.randint(1, len(body) - 1)
        junk = bytes(rng.randint(0x80, 0xFF) for _ in range(rng.randint(1, 4)))
        return body[:pos] + junk + body[pos:] + b"\r\n", kind
    if kind == "missing_field":
        parts = body.split(b" ")
        return b" ".join(parts[:3] + parts[4:]) + b"\r\n", kind
    if kind == "bad_verdict":
        return body.rsplit(b" ", 1)[0] + b" MAYBE\r\n", kind
    return record + record, kind

def main():
    p = argparse.ArgumentParser(description="Random mock gauge")
    p.add_argument("--port", default="/dev/pts/0", help="serial device (the gauge end of the socat pair)")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--lo", type=float, default=-0.030, help="lowest deviation from nominal, mm")
    p.add_argument("--hi", type=float, default=0.045, help="highest deviation from nominal, mm")
    p.add_argument("--mode", choices=["uniform", "drift"], default="uniform")
    p.add_argument("--drift-step", type=float, default=0.002, help="mm of wear per part (drift mode)")
    p.add_argument("--noise", type=float, default=0.002, help="probe noise sigma, mm")
    p.add_argument("--interval", type=float, default=1.0, help="seconds between parts")
    p.add_argument("--count", type=int, default=0, help="stop after N parts (0 = forever)")
    p.add_argument("--fault-rate", type=float, default=0.0)
    p.add_argument("--lie-rate", type=float, default=0.0)
    p.add_argument("--seed", type=int, default=None)
    a = p.parse_args()
    if a.lo >= a.hi:
        p.error("--lo must be smaller than --hi")

    seed = a.seed if a.seed is not None else random.randrange(10**6)
    rng = random.Random(seed)
    print(f"[Mock Gauge] seed={seed} range=[{a.lo:+.3f}, {a.hi:+.3f}] mode={a.mode} port={a.port}")
    try:
        ser = serial.Serial(a.port, a.baud, timeout=1)
    except Exception as e:
        print(f"[Mock Gauge Error] Failed to open port: {e}")
        return
    n = 0
    try:
        while not a.count or n < a.count:
            n += 1
            if a.mode == "uniform":
                dev = rng.uniform(a.lo, a.hi)
            else:
                dev = a.lo + (n * a.drift_step) % (a.hi - a.lo)
            record = make_record(n, dev, rng, a.noise, a.lie_rate)
            payload, fault = record, None
            if a.fault_rate and rng.random() < a.fault_rate:
                payload, fault = corrupt(record, rng)
            ser.write(payload)
            tag = f"   <-- FAULT: {fault}" if fault else ""
            print(f"[Mock Gauge Sent] dev={dev:+.4f}  {payload.decode('ascii', 'replace').strip()!r}{tag}")
            time.sleep(a.interval)
    except KeyboardInterrupt:
        pass
    finally:
        ser.close()
        print(f"\n[Mock Gauge] sent {n} records (seed={seed})")

if __name__ == "__main__":
    main()
