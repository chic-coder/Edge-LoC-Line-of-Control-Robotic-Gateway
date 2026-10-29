# tests/test_fanuc_client.py  (socket handshake, ACKs, retry, reconnect, timeouts)
import socket
import unittest

from fake_controller import FakeController, silence_stdout
from gateway.fanuc_client import FanucClient, deliver

CMDS = ["pmc_wrrange(R0500, 0x01)", "cnc_wrmacro(#500, +0.0130)"]
FAST = dict(max_retries=3, backoff_start=0.01, backoff_max=0.02)   # keep tests quick


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TestFanucClient(unittest.TestCase):
    def setUp(self):
        silence_stdout(self)
        self._controllers = []

    def tearDown(self):
        for c in self._controllers:
            c.stop()

    def controller(self, *behaviours, port=0):
        c = FakeController(behaviours, port=port).start()
        self._controllers.append(c)
        return c

    def client(self, ctl, timeout=0.5):
        c = FanucClient("127.0.0.1", ctl.port, timeout=timeout)
        self.addCleanup(c.close)
        return c

    def test_normal_cycle(self):
        ctl = self.controller()
        latency = deliver(self.client(ctl), CMDS, **FAST)
        self.assertGreater(latency, 0)
        self.assertEqual(ctl.received, CMDS)

    def test_connection_reused_between_cycles(self):
        ctl = self.controller()
        client = self.client(ctl)
        deliver(client, CMDS[:1], **FAST)
        deliver(client, CMDS[:1], **FAST)
        self.assertEqual(ctl.connections, 1)

    def test_nak_triggers_reconnect_and_resend(self):
        ctl = self.controller("nak", "ok")
        self.assertIsNotNone(deliver(self.client(ctl), CMDS, **FAST))
        self.assertEqual(ctl.connections, 2)

    def test_drop_before_ack_is_resent(self):
        ctl = self.controller("drop_no_ack", "ok")
        self.assertIsNotNone(deliver(self.client(ctl), CMDS, **FAST))
        self.assertEqual(ctl.connections, 2)

    def test_silent_controller_times_out_then_recovers(self):
        ctl = self.controller("silent", "ok")
        self.assertIsNotNone(deliver(self.client(ctl, timeout=0.15), CMDS, **FAST))
        self.assertEqual(ctl.connections, 2)

    def test_bad_banner_rejected_then_recovers(self):
        ctl = self.controller("bad_banner", "ok")
        self.assertIsNotNone(deliver(self.client(ctl, timeout=0.15), CMDS, **FAST))
        self.assertEqual(ctl.connections, 2)

    def test_gives_up_after_max_retries(self):
        ctl = self.controller("nak", "nak", "nak", "ok")
        self.assertIsNone(deliver(self.client(ctl), CMDS, **FAST))
        self.assertEqual(ctl.connections, 3)

    def test_unreachable_controller_returns_none(self):
        client = FanucClient("127.0.0.1", free_port(), timeout=0.2)
        self.assertIsNone(deliver(client, CMDS, max_retries=2,
                                  backoff_start=0.01, backoff_max=0.02))

    def test_recovers_when_controller_starts_late(self):
        port = free_port()
        client = FanucClient("127.0.0.1", port, timeout=0.2)
        self.addCleanup(client.close)
        self.assertIsNone(deliver(client, CMDS, max_retries=1))      # nothing listening yet
        ctl = self.controller(port=port)                             # controller appears
        self.assertIsNotNone(deliver(client, CMDS, **FAST))
        self.assertEqual(ctl.received, CMDS)


if __name__ == "__main__":
    unittest.main()