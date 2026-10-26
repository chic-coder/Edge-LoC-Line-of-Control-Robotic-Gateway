# Edge-LoC-Line-of-Control-Robotic-Gateway

A Python edge gateway that bridges a precision RS232 gauge and a FANUC CNC controller (FOCAS-style commands over TCP/IP). It ingests inspection records, decides OK / REWORK / REJECT at the edge, then sorts the part (PMC register) and, when the tool is drifting, corrects the tool-wear offset (CNC macro variable).

Since no physical machinery is available, the repo includes its own **mock gauge** (virtual serial transmitter) and **mock FANUC controller** (TCP server) so the whole chain runs on one laptop, under WSL or Linux.

Use code with caution.
mock_gauge.py ──RS232 (socat PTY pair)──▶ run_gateway.py ──TCP :8193──▶ run_mock_fanuc.py
(random parts,                          (frame, parse,                  (READY / ACK / NAK,
drift, faults)                          classify, actuate)              fault injection)

---

## 1. Components

| File / Package | Role |
|---|---|
| `gateway/` | The core service package containing parameters (`config.py`), serial slicing (`line_framer.py`), data decoding (`parser.py`), matrix sorting (`decision.py`), and transport mechanics (`fanuc_client.py`). |
| `mocks/` | The infrastructure validation test fixtures containing the multi-threaded automation receiver (`fanuc_server.py`) and loop simulator transmitter (`gauge_transmitter.py`). |
| `run_gateway.py` | Main application system entry point runtime dashboard logic. |
| `run_mock_fanuc.py` | Executable launcher entry point initialization interface for the mock server node. |
| `run_mock_gauge.py` | Executable launcher entry point initialization interface for the mock serial pipeline transmitter. |
| `tests/` | Automated unit verification suites checking framing buffers, boundary checks, and consensus fallback matrix states. |

---

## 2. Protocol Reference

### Inbound: gauge to gateway (RS232, 115200 baud, 8-N-1, ASCII)

001 2608101430_00025 +010.0130 +010.0130 OK\r\n

| Field | Meaning |
|---|---|
| `001` | 3-digit device (gauge station) ID |
| `2608101430_00025` | Part serial: timestamp + serial number |
| `+010.0130` `+010.0130` | Channel 1 and Channel 2 probe readings, mm |
| `OK` | Gauge verdict: `OK`, `REWORK` or `REJECT` |

### Outbound: gateway to controller (TCP, port 8193, one command per `\r\n` line)

cnc_wrmacro(#500, +0.0130)     write tool-wear offset to macro variable #500
pmc_wrrange(R0500, 0x01)       write sorting bits: 0x01 OK, 0x02 REWORK, 0x04 REJECT

**Handshake:** on connect the controller sends `READY`; the gateway validates it. Every command is answered with `ACK` (or `NAK <reason>`), and the gateway checks one reply per command.

---

## 3. Decision Logic

### Tolerances

| Constant | Value | Meaning |
|---|---|---|
| `NOMINAL` | 10.000 mm | Target size |
| `USL` | +0.015 mm | Above this, the probe reading is REWORK |
| `LSL` | -0.015 mm | Below this, REJECT (cannot add material back) |
| `REWORK_MAX` | +0.030 mm | Above this, REJECT (too much to recover) |
| `PROBE_TOL` | 0.0010 mm | Max allowed `|ch1 - ch2|` deviation before flagging REWORK |
| `OFFSET_DEADBAND` | 0.005 mm | Mean deviations below this are treated as noise |

### Verdict
1. Each probe is classified on its own (deviation = reading minus nominal).
2. The **worse probe reading sets the decision** (REJECT > REWORK > OK).
3. If the result is OK but the probes disagree by more than `PROBE_TOL` (`0.0010 mm`), the part becomes **REWORK**, because the measurement itself is suspect.
4. The gateway **recomputes** the verdict and does not trust the gauge's own. A disagreement is logged as `[Mismatch]`.

### Actions

| Action | When it is sent |
|---|---|
| `pmc_wrrange(R0500, bit)` | **Every valid record.** The bit follows the verdict: OK `0x01`, REWORK `0x02`, REJECT `0x04` |
| `cnc_wrmacro(#500, offset)` | Only if the verdict is **not REJECT** and `|mean deviation| >= OFFSET_DEADBAND`. `offset = mean(ch1, ch2) - nominal` |

---

## 4. Resilience Features
- **Framing:** `LineFramer` handles partial reads, merged lines and over-long junk without crashing.
- **Strict parsing:** non-ASCII bytes, missing fields and invalid verdicts (for example `MAYBE`) are rejected with a warning, and the loop keeps running.
- **Timeouts:** connect and every read use a 500ms network timeout.
- **Auto-reconnect:** on any socket error, timeout or NAK the gateway closes the socket, reconnects with exponential backoff (0.2 s up to 3 s) and resends the cycle, up to 5 attempts. If the controller stays unreachable, that cycle is dropped and the service keeps running.
- **Idempotent resend:** both commands write absolute values, so a resend after a lost ACK is safe.
- **Latency:** measured per cycle from `sendall` to the last ACK, in `perf_counter_ns`, and printed with each decision. `TCP_NODELAY` is enabled.

---

## 5. Setup (step by step)

### Prerequisites

- Windows with **WSL2** (Ubuntu), or any Linux
- Python 3.8+
- Four terminal windows, all opened in the project folder inside WSL

### Step 0: Install dependencies (once)

```bash
sudo apt update
sudo apt install -y socat python3
pip install -r requirements.txt
```

### Step 1: Create the virtual serial cable (Terminal 1)

```bash
socat -d -d pty,raw,echo=0,link=/tmp/ttyGAUGE pty,raw,echo=0,link=/tmp/ttyGATEWAY
```

Leave it running. Whatever is written to `/tmp/ttyGAUGE` comes out of `/tmp/ttyGATEWAY`, acting like an RS232 cable link.

### Step 2: Start the mock FANUC controller (Terminal 2)

```bash
python3 run_mock_fanuc.py
```

Expected: `[FANUC Mock] Mock FANUC listening on 127.0.0.1:8193`

### Step 3: Start the gateway (Terminal 3)

```bash
python3 run_gateway.py --serial /tmp/ttyGATEWAY --host 127.0.0.1 --tcp-port 8193
```

Expected:
[Gateway Engine] Initiating core operational processing layers...
[Gateway] Listening for gauge telemetry on /tmp/ttyGATEWAY...

### Step 4: Start the mock gauge (Terminal 4)

```bash
python3 run_mock_gauge.py --port /tmp/ttyGAUGE --mode drift --interval 1.0
```

---

## 6. Execution Verification Logs

### Gateway Console Interface
[Ethernet] Link established with FANUC server at 127.0.0.1:8193
[Telemetry Log] Dev 001 | Part 2608101430_00025 | Ch1 +10.0130 | Ch2 +10.0130
[Routing Action] -> OK | Latency: 1.20ms

### Mock FANUC Controller Interface
21:47:32.655  cnc_wrmacro  #500 = -0.0095
21:47:33.658  pmc_wrrange  R0500 = 0x01

### Running Automated Test Verification Suites
To confirm the integrity of modular parameters, framing checks, and boundary logic configurations at any point, execute:
```bash
python -m unittest discover -s tests
```
