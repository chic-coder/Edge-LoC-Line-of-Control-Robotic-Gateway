# tests/test_mock_gauge.py  (mock output is valid and consistent with the gateway rules)
import unittest

from gateway.decision import classify_part
from gateway.line_framer import LineFramer
from gateway.parser import parse_record
from mocks.gauge_transmitter import MockGaugeTransmitter
#text = payload.decode("ascii", "replace").strip()

def make(**kw):
    kw.setdefault("seed", 1)
    return MockGaugeTransmitter("unused", 115200, -0.030, 0.045, **kw)


class TestMockGauge(unittest.TestCase):
    def test_every_record_parses_and_verdict_agrees_with_gateway(self):
        # The mock has its own independent limits, so agreement here is a real cross-check.
        for mode in ("uniform", "drift"):
            g = make(mode=mode)
            for n in range(1, 3001):
                rec = parse_record(g.make_record(n, g.next_deviation(n)).strip())
                with self.subTest(mode=mode, n=n):
                    self.assertEqual(rec["gauge"], classify_part(rec["ch1"], rec["ch2"]))

    def test_lie_rate_one_always_disagrees_with_the_gateway(self):
        g = make(lie_rate=1.0)
        for n in range(1, 200):
            rec = parse_record(g.make_record(n, g.next_deviation(n)).strip())
            self.assertNotEqual(rec["gauge"], classify_part(rec["ch1"], rec["ch2"]))

    def test_seed_zero_is_reproducible(self):
        a, b = make(seed=0), make(seed=0)
        self.assertEqual(a.seed, 0)
        ra = [a.make_record(n, a.next_deviation(n)).split(b" ", 2)[2] for n in range(1, 50)]
        rb = [b.make_record(n, b.next_deviation(n)).split(b" ", 2)[2] for n in range(1, 50)]
        self.assertEqual(ra, rb)

    def test_corrupted_frames_are_never_accepted_as_a_different_record(self):
        g = make()
        for n in range(1, 2001):
            original = g.make_record(n, g.next_deviation(n))
            expected = parse_record(original.strip())
            payload, _ = g._corrupt(original)
            for line in LineFramer().feed(payload):
                try:
                    got = parse_record(line)
                except ValueError:
                    continue                      # rejected: fine
                self.assertEqual(got, expected)   # accepted: must be the true record


if __name__ == "__main__":
    unittest.main()