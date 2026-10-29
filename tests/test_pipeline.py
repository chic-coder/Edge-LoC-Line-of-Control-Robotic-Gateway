# tests/test_pipeline.py  (serial bytes -> controller commands, end to end)
import unittest

from fake_controller import FakeController, silence_stdout
from gateway.core import Gateway, p95
from gateway.fanuc_client import FanucClient

LINE = b"001 2608101430_00025 +010.0130 +010.0130 OK\r\n"


class TestPipeline(unittest.TestCase):
    def setUp(self):
        silence_stdout(self)
        self.ctl = FakeController().start()
        self.addCleanup(self.ctl.stop)
        client = FanucClient("127.0.0.1", self.ctl.port, timeout=0.5)
        self.addCleanup(client.close)
        self.gw = Gateway(client)

    def test_brief_example_end_to_end(self):
        self.gw.feed(LINE)
        self.assertEqual(self.ctl.received,
                         ["pmc_wrrange(R0500, 0x01)", "cnc_wrmacro(#500, +0.0130)"])

    def test_record_split_across_serial_reads(self):
        self.gw.feed(LINE[:20])
        self.assertEqual(self.ctl.received, [])
        self.gw.feed(LINE[20:])
        self.assertEqual(len(self.ctl.received), 2)

    def test_malformed_line_sends_nothing(self):
        self.gw.feed(b"001 2608101430_00025 +010.0130 +010.0130 MAYBE\r\n")
        self.assertEqual(self.ctl.received, [])

    def test_garbage_does_not_break_following_good_record(self):
        self.gw.feed(b"\xff\xfe\x80junk\r\n" + LINE)
        self.assertEqual(len(self.ctl.received), 2)

    def test_duplicate_part_processed_once(self):
        self.gw.feed(LINE + LINE)
        self.assertEqual(len(self.ctl.received), 2)       # one cycle = 2 commands

    def test_truncated_record_then_good_record_recovers_the_good_one(self):
        self.gw.feed(b"001 2608101430_00024 +010.01" + LINE)
        self.assertEqual(self.ctl.received,
                         ["pmc_wrrange(R0500, 0x01)", "cnc_wrmacro(#500, +0.0130)"])

    def test_gateway_verdict_overrides_a_lying_gauge(self):
        verdict = self.gw.handle_line(b"001 2608101430_00026 +010.0400 +010.0400 OK")
        self.assertEqual(verdict, "REJECT")
        self.assertEqual(self.ctl.received, ["pmc_wrrange(R0500, 0x04)"])

    def test_reject_part_sends_no_offset(self):
        self.gw.handle_line(b"001 2608101430_00027 +009.9700 +009.9700 REJECT")
        self.assertEqual(self.ctl.received, ["pmc_wrrange(R0500, 0x04)"])

    def test_turnaround_includes_send_to_ack_time(self):
        self.gw.feed(LINE)
        self.assertEqual(len(self.gw.turnaround_ms), 1)
        self.assertGreaterEqual(self.gw.turnaround_ms[0], self.gw.ack_ms[0])

    def test_summary_reports_cycles_and_percent_under_target(self):
        self.gw.feed(LINE)
        text = self.gw.summary()
        self.assertIn("cycles=1", text)
        self.assertIn("100.0%", text)

    def test_summary_with_no_cycles(self):
        self.assertIn("no cycles", self.gw.summary())


class TestP95(unittest.TestCase):
    def test_nearest_rank(self):
        self.assertEqual(p95([5]), 5)
        self.assertEqual(p95(list(range(1, 21))), 19)      # 20 values -> 19th
        self.assertEqual(p95(list(range(100, 0, -1))), 95)  # unsorted input


if __name__ == "__main__":
    unittest.main()