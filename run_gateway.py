# run_gateway.py
import argparse
import serial
from gateway.core import Gateway
from gateway.fanuc_client import FanucClient

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

    gateway = Gateway(FanucClient(args.host, args.tcp_port))

    try:
        while True:
            data = ser.read(ser.in_waiting or 1)
            if data:
                gateway.feed(data)
    except KeyboardInterrupt:
        print("\n[Gateway Engine] Interrupted. Powering down processing layers cleanly.")
    except serial.SerialException as e:
        print(f"\n[Gateway Core Fault] Serial link lost: {e}")
    finally:
        ser.close()
        gateway.client.close()
        print("\n" + gateway.summary())

if __name__ == "__main__":
    main()