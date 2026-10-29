# gateway/core.py
"""Gateway pipeline: bytes -> lines -> records -> decision -> controller.
Has no serial dependency, so it can be unit-tested without hardware."""
import math
import time
from .config import LATENCY_TARGET_MS
from .decision import classify_part, build_commands
from .fanuc_client import deliver
from .line_framer import LineFramer
from .parser import parse_record

def p95(values):
    """95th percentile, nearest-rank method (needs at least one value)."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]

class Gateway:
    def __init__(self, client):
        self.client = client
        self.framer = LineFramer()
        self.last_part = None
        self.turnaround_ms = []   # line received -> final ACK (parse + decide + send, incl. retries)
        self.ack_ms = []          # last send -> final ACK only
        self.dropped = 0

    def feed(self, data: bytes):
        for raw_line in self.framer.feed(data):
            self.handle_line(raw_line)

    def handle_line(self, raw_line: bytes):
        """Processes one framed line. Returns the verdict, or None if skipped."""
        t_rx = time.perf_counter_ns()      # complete line is available: turnaround clock starts
        try:
            rec = parse_record(raw_line)
        except ValueError as e:
            print(f"[Framer Warning] Discarding corrupted structure slice: {e}")
            return None

        if rec["part"] == self.last_part:
            print(f"[Framer Warning] Duplicate record for part {rec['part']} skipped")
            return None
        self.last_part = rec["part"]

        verdict = classify_part(rec["ch1"], rec["ch2"])
        commands = build_commands(verdict, rec["ch1"], rec["ch2"])
        latency = deliver(self.client, commands)
        turnaround = (time.perf_counter_ns() - t_rx) / 1e6   # stops at the final ACK

        print(f"\n[Telemetry Log] Dev {rec['device']} | Part {rec['part']} | "
              f"Ch1 {rec['ch1']:+.4f} | Ch2 {rec['ch2']:+.4f}")
        if verdict != rec["gauge"]:
            print(f"   [Mismatch] gauge said {rec['gauge']}, gateway computed {verdict}")
        if latency is None:
            self.dropped += 1
            print("   [DROPPED PACKET] Unreachable infrastructure node.")
        else:
            self.turnaround_ms.append(turnaround)
            self.ack_ms.append(latency)
            flag = f" [LATENCY FAULT >= {LATENCY_TARGET_MS} ms]" if turnaround >= LATENCY_TARGET_MS else ""
            print(f"   [Routing Action] -> {verdict} | TX {' ; '.join(commands)} | "
                  f"Turnaround: {turnaround:.2f}ms (send->ACK {latency:.2f}ms){flag}")
        return verdict

    def summary(self):
        """Latency statistics for the whole run, for the end of the demo."""
        n = len(self.turnaround_ms)
        if n == 0:
            return "[Latency Summary] no cycles completed"
        t, a = self.turnaround_ms, self.ack_ms
        under = 100.0 * sum(x < LATENCY_TARGET_MS for x in t) / n
        return (f"[Latency Summary] cycles={n} dropped={self.dropped}\n"
                f"   turnaround (rx->ACK) ms: min {min(t):.2f} | avg {sum(t)/n:.2f} | "
                f"p95 {p95(t):.2f} | max {max(t):.2f}\n"
                f"   send->ACK            ms: min {min(a):.2f} | avg {sum(a)/n:.2f} | "
                f"p95 {p95(a):.2f} | max {max(a):.2f}\n"
                f"   under {LATENCY_TARGET_MS} ms target: {under:.1f}%")