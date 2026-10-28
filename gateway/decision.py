# gateway/decision.py
"""Encapsulates telemetry processing business constraints and categorization matrix logic."""
from .config import NOMINAL, LSL, REWORK_MAX, USL, PROBE_TOL, SEVERITY

def probe_verdict(ch: float) -> str:
    dev = round(ch - NOMINAL, 4)
    if dev < LSL or dev > REWORK_MAX:
        return "REJECT"
    if dev > USL:
        return "REWORK"
    return "OK"
   
def classify_part(ch1: float, ch2: float) -> str:
    """Calculates classifications and guarantees dual-probe consensus fallback."""
    verdict = max(probe_verdict(ch1), probe_verdict(ch2), key=SEVERITY.get)
    if verdict == "OK" and abs(round(ch1 - ch2, 4)) > PROBE_TOL:   
        verdict = "REWORK"
    return verdict
