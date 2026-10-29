# gateway/config.py
"""Central configuration parameters and factory constants."""

NOMINAL = 10.0000
USL = 0.0150              # +0.015 mm -> Rework boundary
LSL = -0.0150             # -0.015 mm -> Scrap boundary
REWORK_MAX = 0.030       # Extreme upper tolerance limit
PROBE_TOL = 0.01000        # Maximum deviation delta across channels
OFFSET_DEADBAND = 0.0050  # Noise floor filter

MACRO_VAR = 500          # Target CNC macro variable (#500)
PMC_ADDR = "R0500"       # Target PMC address register

SORT_BIT = {"OK": "0x01", "REWORK": "0x02", "REJECT": "0x04"}
SEVERITY = {"OK": 0, "REWORK": 1, "REJECT": 2}

SOCK_TIMEOUT = 0.5       # Sockets network timeout (seconds)
LATENCY_TARGET_MS = 50   # Performance monitoring target
MAX_RETRIES = 5          # Resiliency attempt threshold
BACKOFF_START = 0.2      # Exponential backoff base interval
BACKOFF_MAX = 3.0        # Exponential backoff maximum ceiling
