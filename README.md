# Edge-LoC: Line-of-Control Robotic Gateway

A Python edge gateway that bridges a precision RS232 gauge and a FANUC CNC controller (FOCAS-style commands over TCP/IP). It ingests inspection records, decides **OK / REWORK / REJECT** at the edge, then sorts the part (PMC register) and, when the tool is drifting, corrects the tool-wear offset (CNC macro variable).

Because no physical machinery is available, the repo includes its own **mock gauge** (virtual serial transmitter) and **mock FANUC controller** (TCP server), so the whole chain runs on one laptop under WSL or Linux.

```
 run_mock_gauge.py ──RS232 (socat PTY pair)──▶ run_gateway.py ──TCP :8193──▶ run_mock_fanuc.py
 (random parts,                                (frame, parse,                (READY / ACK / NAK,
  drift, faults)                                classify, actuate)            fault injection)
```

**Demo video:** see [`video_link.md`](video_link.md).

---

## 1. Why Linux (WSL) and Python

- **Same platform as the target.** The brief targets a Raspberry Pi 3 or 5, and Raspberry Pi OS is Linux. WSL2 (Ubuntu) is also Linux, so the commands, device paths (`/dev/tty*`), tools (`socat`) and libraries (`pyserial`) behave the same on the laptop and on the Pi. Nothing in the code is tied to Windows.
- **Python is the natural language for the Pi.** Python 3 ships with Raspberry Pi OS, it is the language the Pi ecosystem is documented in, and `pyserial` and the standard `socket` module cover everything this gateway needs. There is nothing to compile, so the same source files run unchanged on both machines.

---

## 2. Project Structure

```
.
├── gateway/                 core service package
│   ├── config.py            tolerances, timeouts and other constants
│   ├── line_framer.py       turns the serial byte stream into complete lines
│   ├── parser.py            strict parsing of one gauge record
│   ├── decision.py          verdict, tool-wear offset, command building
│   ├── fanuc_client.py      TCP client: handshake, ACKs, timeouts, reconnect
│   └── core.py              pipeline: bytes -> lines -> records -> decision -> controller
├── mocks/                   test fixtures
│   ├── fanuc_server.py      mock FANUC controller with fault injection
│   └── gauge_transmitter.py mock gauge with drift mode and fault injection
├── tests/                   unit and integration tests (unittest)
├── run_gateway.py           entry point: the gateway
├── run_mock_fanuc.py        entry point: mock controller
├── run_mock_gauge.py        entry point: mock gauge
├── requirements.txt
└── video_link.md
```

---

## 3. Protocol Reference

### Inbound: gauge to gateway (RS232, 115200 baud, 8-N-1, ASCII)

```
001 2608101430_00025 +010.0130 +010.0130 OK\r\n
```

| Field | Meaning |
|---|---|
| `001` | 3-digit device (gauge station) ID |
| `2608101430_00025` | Part serial: timestamp + serial number |
| `+010.0130` `+010.0130` | Channel 1 and Channel 2 probe readings, mm |
| `OK` | Gauge verdict: `OK`, `REWORK` or `REJECT` |

### Outbound: gateway to controller (TCP, port 8193, one command per `\r\n` line)

```
cnc_wrmacro(#500, +0.0130)     write tool-wear offset to macro variable #500
pmc_wrrange(R0500, 0x01)       write sorting bits: 0x01 OK, 0x02 REWORK, 0x04 REJECT
```

**Handshake:** on connect the controller sends `READY` and the gateway validates it. Every command is answered with `ACK` (or `NAK <reason>`), and the gateway checks one reply per command.

---

## 4. Decision Logic

### Tolerances

These values are assumptions, because the brief does not specify them. They all live in `gateway/config.py`.

| Constant | Value | Meaning |
|---|---|---|
| `NOMINAL` | 10.000 mm | Target size |
| `USL` | +0.015 mm | Above this, the probe reading is **REWORK** |
| `LSL` | -0.015 mm | Below this, **REJECT** (material cannot be added back) |
| `REWORK_MAX` | +0.030 mm | Above this, **REJECT** (too much to recover) |
| `PROBE_TOL` | 0.010 mm | Max allowed `abs(ch1 - ch2)` before the part is flagged **REWORK** |
| `OFFSET_DEADBAND` | 0.005 mm | Mean deviations below this are treated as probe noise |

### Verdict

1. Each probe is classified on its own (deviation = reading minus nominal, rounded to the gauge's 4 decimals so that a reading exactly on a limit is not pushed over it by float error).
2. The **worse probe sets the decision** (`REJECT > REWORK > OK`).
3. If the result is **OK** but the probes disagree by more than `PROBE_TOL`, the part becomes **REWORK**, because the measurement itself is not reliable.
4. The gateway **recomputes** the verdict and does not trust the gauge's own. A disagreement is logged as `[Mismatch]`.

### Actions

| Action | When it is sent |
|---|---|
| `pmc_wrrange(R0500, bit)` | **Every valid record.** The bit follows the verdict: OK `0x01`, REWORK `0x02`, REJECT `0x04` |
| `cnc_wrmacro(#500, offset)` | Only if the verdict is **not REJECT** and `abs(mean deviation) >= OFFSET_DEADBAND`. `offset = mean(ch1, ch2) - nominal` |

**Why a deadband:** probe noise would otherwise trigger a correction on nearly every part, and constantly nudging the tool in response to noise can make variation worse. **Why exclude REJECT:** one scrapped outlier must not push a bad correction into the machine.

> **Sign convention:** the offset equals the measured deviation, which matches the brief's example (10.013 gives `+0.013`). A real controller may need the opposite sign to compensate; that is a one-line change in `decision.py`.

| Ch1 / Ch2 | Verdict | `pmc_wrrange` | `cnc_wrmacro` |
|---|---|---|---|
| 10.0130 / 10.0130 | OK | `0x01` | `+0.0130` |
| 10.0020 / 10.0010 | OK | `0x01` | none (inside deadband) |
| 10.0200 / 10.0220 | REWORK | `0x02` | `+0.0210` |
| 10.0000 / 10.0120 | REWORK (probes disagree) | `0x02` | `+0.0060` |
| 10.0400 / 10.0400 | REJECT | `0x04` | none |

---

## 5. Resilience Features

- **Framing:** `LineFramer` handles partial reads, merged lines and over-long junk without crashing.
- **Strict parsing:** non-ASCII bytes, missing fields, wrong field widths and invalid verdicts (for example `MAYBE`) are rejected with a warning, and the loop keeps running.
- **Truncation recovery:** a truncated record has no terminator, so the next record is glued onto it. The parser finds the complete record at the end of the line, so the good record is kept and only the broken fragment is lost.
- **Duplicate records** (same part serial twice in a row) are skipped, so an offset is never written twice for one part.
- **Timeouts:** connect and every read use a 500 ms socket timeout. This is a *failure detector*, not the latency goal.
- **Auto-reconnect:** on any socket error, timeout or NAK the gateway closes the socket, reconnects with exponential backoff (0.2 s up to 3 s) and resends the cycle, up to 5 attempts. If the controller stays unreachable, that cycle is dropped and the service keeps running.
- **Idempotent resend:** both commands write absolute values, so a resend after a lost ACK is safe.
- **Handshake:** the `READY` banner is validated on every (re)connect, and one `ACK` is checked per command.

### Latency

The target is a sub-50 ms edge turnaround (`LATENCY_TARGET_MS = 50`).

- **Turnaround** is measured from the moment a complete line is available to the final ACK, so it covers parsing, the decision, building the commands, the send and any retries. Cycles at or above the target are flagged `[LATENCY FAULT]`.
- **send->ACK** is the time of the last successful send to its last ACK, reported next to it.
- `TCP_NODELAY` is enabled on the socket, so small writes are not held back by Nagle's algorithm.
- On exit (Ctrl+C) the gateway prints a summary:

```
[Latency Summary] cycles=<N> dropped=<D>
   turnaround (rx->ACK) ms: min <a> | avg <b> | p95 <c> | max <d>
   send->ACK            ms: min <a> | avg <b> | p95 <c> | max <d>
   under 50 ms target: <pct>%
```

In development runs on WSL2 over loopback, send->ACK was typically 1 to 8 ms. Serial wire time (about 3.9 ms for a 45-byte record at 115200 baud) is outside the gateway's control and is not included.

---

## 6. Setup (step by step)

### Requirements

| Requirement | Needed for | How to install |
|---|---|---|
| Linux (WSL2 Ubuntu on Windows, or Raspberry Pi OS) | running everything | WSL2: `wsl --install` in PowerShell. Raspberry Pi OS is already Linux |
| Python 3.8 or newer | gateway, mocks and tests | `sudo apt install python3 python3-pip` |
| `pyserial` | serial port access | `pip install -r requirements.txt` |
| `socat` | the virtual serial cable, for the simulation only | `sudo apt install socat` |

`requirements.txt` lists only Python packages, because that is all `pip` can install. The operating system, Python itself and `socat` are system-level requirements, so they are listed here and installed with `apt` in Step 0. `socat` is not needed on a real Pi with a real serial adapter.

You also need four terminal windows, all opened in the project folder inside WSL.

### Step 0: Install dependencies (once)

```bash
sudo apt update
sudo apt install -y socat python3 python3-pip
pip install -r requirements.txt
```

If `pip` refuses to install system-wide, use the apt package instead: `sudo apt install -y python3-serial`.

### Step 1: Create the virtual serial cable (Terminal 1)

```bash
socat -d -d pty,raw,echo=0,link=/tmp/ttyGAUGE pty,raw,echo=0,link=/tmp/ttyGATEWAY
```

Leave it running. Whatever is written to `/tmp/ttyGAUGE` comes out of `/tmp/ttyGATEWAY`, like an RS232 cable.

### Step 2: Start the mock FANUC controller (Terminal 2)

```bash
python3 run_mock_fanuc.py
```

Expected: a line saying the mock FANUC is listening on `127.0.0.1:8193`.

### Step 3: Start the gateway (Terminal 3)

```bash
python3 run_gateway.py --serial /tmp/ttyGATEWAY
```

Expected: `[Gateway Engine] Initiating core operational processing layers...`

### Step 4: Start the mock gauge (Terminal 4)

```bash
python3 run_mock_gauge.py --port /tmp/ttyGAUGE --mode drift --interval 1.0
```

The gauge prints each record exactly as it is sent, for example `001 2610290401_00004 +010.0067 +010.0037 OK`. The gateway connects to the controller on the first record and prints a decision for every part.

### Stopping

Stop in this order: gauge, gateway (prints the latency summary), controller, then socat last.

### Command-line options

| Script | Options |
|---|---|
| `run_gateway.py` | `--serial`, `--baud` (115200), `--host` (127.0.0.1), `--tcp-port` (8193) |
| `run_mock_gauge.py` | `--port`, `--baud`, `--lo`, `--hi` (deviation range, mm), `--mode` (`uniform` or `drift`), `--drift-step`, `--noise`, `--interval`, `--count` (0 = forever), `--fault-rate`, `--lie-rate`, `--seed` |
| `run_mock_fanuc.py` | `--host`, `--port` (8193), `--ack-delay-ms`, `--nak-rate`, `--drop-every` (must be 3 or more), `--seed` |

---

## 7. Running the Automated Tests

```bash
python3 -m unittest discover -s tests
```

Add `-v` to list each test. The suite uses only the standard library and needs no hardware. It covers:

- **Framer:** split reads, merged lines, `\r\n` handling, overflow junk.
- **Parser:** the brief's example, malformed and non-ASCII input, wrong widths, truncation recovery.
- **Decision logic:** every tolerance boundary, probe disagreement, the deadband, negative drift, REJECT never correcting, exact command strings.
- **Controller client:** against a scripted fake controller over real sockets: normal cycle, NAK, dropped connection, silent controller (timeout), bad banner, retries exhausted, unreachable controller, a controller that starts late.
- **Pipeline:** serial bytes to controller commands end to end, duplicates, garbage, truncated-then-good records.
- **Mock gauge:** thousands of generated records parse correctly and agree with the gateway's classifier (the mock has its own independent limits, so this is a real cross-check), and corrupted frames are never accepted as a different record.

---

## 8. Fault Injection & Edge Resilience Testing

The simulation tools replicate hostile factory conditions: slow controllers, dropped sockets, rejected commands and electrical noise on the serial line. Run the gateway and the gauge as in Section 6, and restart the mock controller or gauge with these flags.

### Scenario A: Dropped sockets and reconnection

The controller applies a command, then drops the connection before sending its ACK.

* **Terminal 2:** `python3 run_mock_fanuc.py --drop-every 3`
* **Expected:** every third command, the gateway logs `[Ethernet Error] Transport issue...`, closes the dead socket, waits for the backoff, reconnects, and resends. No data is lost and the gateway never crashes. The resend is safe because the commands write absolute values.

### Scenario B: Controller latency violations

A slow controller, to test the 50 ms warning.

* **Terminal 2:** `python3 run_mock_fanuc.py --ack-delay-ms 30`
* **Expected:** the mock waits 30 ms before **each** ACK. A cycle with only the sorting command takes about 30 ms and passes. A cycle that also writes a tool offset sends two commands and takes about 60 ms, so it exceeds the target and is flagged. Illustrative output:

```text
[Routing Action] -> OK | TX pmc_wrrange(R0500, 0x01) ; cnc_wrmacro(#500, +0.0130) | Turnaround: 61.45ms (send->ACK 60.80ms) [LATENCY FAULT >= 50 ms]
```

### Scenario C: Command rejections (NAK)

The controller refuses some commands because it is busy.

* **Terminal 2:** `python3 run_mock_fanuc.py --nak-rate 0.30`
* **Expected:** about 30% of commands get `NAK BUSY`. The gateway treats it as a transport failure, reconnects, and retries up to 5 times until the cycle succeeds.

### Scenario D: Serial framing errors and cable noise

Broken ASCII fragments, dropped fields, bad verdicts and duplicated records.

* **Terminal 4:** `python3 run_mock_gauge.py --port /tmp/ttyGAUGE --fault-rate 0.15`
* **Expected:** the gauge distorts about 15% of the stream and marks each corrupted line with `<-- FAULT: <kind>`. The gateway discards bad lines without crashing:

```text
[Framer Warning] Discarding corrupted structure slice: bad format or field count mismatch
```

A truncated record glued to its successor does not lose the good record, and a duplicated record is skipped (`Duplicate record ... skipped`).

### Scenario E: Fast drift stream for latency statistics

A quick burst of 30 parts to collect latency numbers.

* **Terminal 4:** `python3 run_mock_gauge.py --port /tmp/ttyGAUGE --mode drift --interval 0.05 --count 30`
* **Expected:** the gauge sends a part every 50 ms and stops after 30. The tool-wear drift sweeps from undersize parts (REJECT), through good parts that trigger small offsets, into REWORK as the wear grows. Press Ctrl+C in the gateway terminal afterwards to print the latency summary.

To see both scenarios together, run the controller with `--ack-delay-ms 30` while running Scenario E.

### Scenario F: A gauge that reports the wrong verdict

* **Terminal 4:** `python3 run_mock_gauge.py --port /tmp/ttyGAUGE --lie-rate 0.2`
* **Expected:** about 20% of records carry a verdict that contradicts their own readings. The gateway sorts by its own computed verdict and logs `[Mismatch] gauge said X, gateway computed Y`.

---

## 9. Example Output

### Gateway console

```text
[Ethernet] Link established with FANUC server at 127.0.0.1:8193

[Telemetry Log] Dev 001 | Part 2608101430_00025 | Ch1 +10.0130 | Ch2 +10.0130
   [Routing Action] -> OK | TX pmc_wrrange(R0500, 0x01) ; cnc_wrmacro(#500, +0.0130) | Turnaround: 1.20ms (send->ACK 0.90ms)
```

### Mock FANUC controller console

```text
21:47:32.655  pmc_wrrange(R0500, 0x01)
21:47:32.656  cnc_wrmacro(#500, +0.0130)
```

## 10. Assumptions and Limitations
- The mock controller speaks a simplified text protocol (`READY`, `ACK`, `NAK`), not binary FOCAS. `FanucClient` is the single place to swap in a real FOCAS library.
- The system was developed and tested on WSL2 with virtual serial ports. It has not been run against a physical gauge or a physical Raspberry Pi.
- When the gauge's verdict and the gateway's disagree, the gateway's own verdict is used for sorting. A stricter policy (take the more severe of the two) is a small change in `core.py`.
