# run_gateway.py
import argparse
import serial
from gateway.config import NOMINAL, OFFSET_DEADBAND, PMC_ADDR, MACRO_VAR, SORT_BIT, LATENCY_TARGET_MS
from gateway.line_framer import LineFramer
from gateway.parser import parse_record
from gateway.decision import classify_part
from gateway.fanuc_client import FanucClient, deliver

def main():
    parser = argparse.ArgumentParser(description="Edge-LoC System Runtime Gateway Engine")
    parser.add_argument("--serial", default="/dev/pts/1", help="Target serial port resource pathway")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--host", default="127.0.0.1", help="Target FANUC host node address")
    parser.add_argument("--tcp-port", type=int, default=8193, help="FANUC controller interface port")
    args = parser.parse_args()

    print("[Gateway Engine] Initiating core operational processing layers...")
    try:
        ser = serial.Serial(args.serial, args.baud, timeout=0.1)
    except serial.SerialException as e:
        print(f"[Gateway Core Fault] Serial connection initialization failed: {e}")
        return

    client = FanucClient(args.host, args.tcp_port)
    framer = LineFramer()

    try:
        while True:
            data = ser.read(ser.in_waiting or 1)
            if not data:
                continue
            for raw_line in framer.feed(data):
                try:
                    rec = parse_record(raw_line)
                except ValueError as e:
                    print(f"[Framer Warning] Discarding corrupted structure slice: {e}")
                    continue

                verdict = classify_part(rec["ch1"], rec["ch2"])
                commands = [f"pmc_wrrange({PMC_ADDR}, {SORT_BIT[verdict]})"]

                if verdict != "REJECT":
                    mean_dev = (rec["ch1"] + rec["ch2"]) / 2 - NOMINAL
                    if abs(mean_dev) >= OFFSET_DEADBAND:
                        commands.append(f"cnc_wrmacro(#{MACRO_VAR}, {mean_dev:+.4f})")

                latency = deliver(client, commands)
                print(f"\n[Telemetry Log] Dev {rec['device']} | Part {rec['part']} | Ch1 {rec['ch1']:+.4f} | Ch2 {rec['ch2']:+.4f}")
                if latency is None:
                    print(f"   [DROPPED PACKET] Unreachable infrastructure node.")
                else:
                    flag = " [LATENCY FAULT]" if latency >= LATENCY_TARGET_MS else ""
                    print(f"   [Routing Action] -> {verdict} | Latency: {latency:.2f}ms{flag}")
    except KeyboardInterrupt:
        print("\n[Gateway Engine] Interrupted. Powering down processing layers cleanly.")
    finally:
        ser.close()
        client.close()

if __name__ == "__main__":
    main()
