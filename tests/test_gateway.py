# tests/test_gateway.py
import unittest
from gateway.line_framer import LineFramer
from gateway.parser import parse_record
from gateway.decision import classify_part

class TestGatewayLogic(unittest.TestCase):

    def setUp(self):
        self.framer = LineFramer()

    def test_line_framer_complete_line(self):
        """Verify that the framer processes a clean, complete line ending in newline."""
        raw_data = b"001 PART_A +10.0010 +10.0020 OK\n"
        result = self.framer.feed(raw_data)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], b"001 PART_A +10.0010 +10.0020 OK")

    def test_line_framer_fragmented_stream(self):
        """Verify the framer handles chunks split across network/serial reads."""
        self.assertEqual(self.framer.feed(b"001 PART_"), [])
        result = self.framer.feed(b"B +10.0000 +10.0000 OK\n")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], b"001 PART_B +10.0000 +10.0000 OK")

    def test_strict_parser_valid(self):
        """Verify clean telemetry fields translate properly into structured dictionaries."""
        raw_line = b"001 2608101430_00025 +010.0050 +009.9950 REWORK"
        parsed = parse_record(raw_line)
        self.assertEqual(parsed["device"], "001")
        self.assertEqual(parsed["part"], "2608101430_00025")
        self.assertEqual(parsed["ch1"], 10.0050)
        self.assertEqual(parsed["ch2"], 9.9950)
        self.assertEqual(parsed["gauge"], "REWORK")

    def test_strict_parser_corrupted(self):
        """Ensure malformed or unaligned payloads raise a clear ValueError exception."""
        with self.assertRaises(ValueError):
            parse_record(b"BAD_DATA_STREAM")

    def test_classification_matrix_ok(self):
        """Check nominal specs classify safely as OK."""
        self.assertEqual(classify_part(10.001, 10.002), "OK")

    def test_classification_matrix_rework(self):
        """Verify parts exceeding tolerance trigger REWORK states."""
        self.assertEqual(classify_part(10.016, 10.000), "REWORK")

    def test_classification_matrix_reject(self):
        """Verify extreme deviations drop explicitly into structural REJECT states."""
        self.assertEqual(classify_part(10.035, 10.000), "REJECT")
        self.assertEqual(classify_part(9.980, 10.000), "REJECT")

    def test_probe_mismatch_fallback(self):
        """Ensure probes that disagree by more than PROBE_TOL flag REWORK even if nominal."""
        # Both channels are within OK bounds, but their difference is 0.012 (Limit is 0.010)
        self.assertEqual(classify_part(10.006, 9.994), "REWORK")

if __name__ == "__main__":
    unittest.main()
