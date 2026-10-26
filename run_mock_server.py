# run_mock_fanuc.py
import argparse
from mocks.fanuc_server import MockFanucServer

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="FANUC Device Driver Simulation Environment Setup")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8193)
    p.add_argument("--ack-delay-ms", type=float, default=0)
    p.add_argument("--nak-rate", type=float, default=0)
    p.add_argument("--drop-every", type=int, default=0)
    p.add_argument("--seed", type=int, default=None)
    args = p.parse_args()
    
    if args.drop_every and args.drop_every < 3:
        p.error("--drop-every threshold configuration requires an evaluation value >= 3")

    server = MockFanucServer(args.host, args.port, args.ack_delay_ms, args.nak_rate, args.drop_every, args.seed)
    server.start()
