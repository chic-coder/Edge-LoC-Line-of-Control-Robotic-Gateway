# run_mock_gauge.py
import argparse
from mocks.gauge_transmitter import MockGaugeTransmitter

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Dimensional Gauge Instrument Serial Pipeline Hardware Simulation")
    p.add_argument("--port", default="/dev/pts/0")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--lo", type=float, default=-0.030)
    p.add_argument("--hi", type=float, default=0.045)
    p.add_argument("--mode", choices=["uniform", "drift"], default="uniform")
    p.add_argument("--drift-step", type=float, default=0.002)
    p.add_argument("--noise", type=float, default=0.002)
    p.add_argument("--interval", type=float, default=1.0)
    p.add_argument("--count", type=int, default=0)
    p.add_argument("--fault-rate", type=float, default=0.0)
    p.add_argument("--lie-rate", type=float, default=0.0)
    p.add_argument("--seed", type=int, default=None)
    a = p.parse_args()

    if a.lo >= a.hi:
        p.error("Configuration evaluation validation bounds constraint failure: --lo must be < --hi")

    gauge = MockGaugeTransmitter(a.port, a.baud, a.lo, a.hi, a.mode, a.drift_step, a.noise, a.fault_rate, a.lie_rate, a.seed)
    gauge.execute(count=a.count, interval=a.interval)
