"""
Startup native-TLS PREFLIGHT — fail LOUDLY before any composition/latency run.

The Service host must have working native Python TLS (native_sdk transport) for
streaming/TTFA. On Windows dev boxes with Avast, HTTPS scanning injects an
applink-less OpenSSL that hard-aborts native TLS -> the pipeline silently falls
back to schannel_curl (no streaming, invalid TTFA). This check surfaces that
BEFORE a run instead of mid-run.

Probes native TLS in an isolated subprocess (the failure is a hard process abort,
so it can't be caught in-process). Exits 0 if native_sdk; exits 2 with a loud
banner + the fix (see docs/RUNBOOK_transport.md) if broken. NO API key, NO LLM
call — just a TLS handshake to the API root (404/401 = reachable).

Usage (Dev0, before any paid/latency run):  python scripts/preflight_transport.py
Import form:                                 from preflight_transport import require_native_tls
"""
from __future__ import annotations
import subprocess
import sys

_PROBE = ("import truststore; truststore.inject_into_ssl(); import httpx; "
          "httpx.get('https://api.anthropic.com/', timeout=10)")


def native_tls_ok(timeout: float = 30.0) -> bool:
    try:
        r = subprocess.run([sys.executable, "-c", _PROBE], capture_output=True, timeout=timeout)
        return r.returncode == 0
    except Exception:
        return False


def require_native_tls() -> None:
    """Raise loudly if native TLS is broken. Call at startup of any run that needs
    streaming/TTFA (fabrication-only/curl runs may skip)."""
    if not native_tls_ok():
        raise SystemExit(
            "\n" + "=" * 72 +
            "\n  PREFLIGHT FAIL: native Python TLS is BROKEN (transport -> schannel_curl)."
            "\n  Streaming / TTFA are INVALID on this host until fixed."
            "\n  FIX (Service-host profile): Avast One -> Protection -> Core Shields ->"
            "\n    Web Guard -> 'Enable HTTPS scanning' = OFF (all other shields ON), then"
            "\n    REBOOT. See docs/RUNBOOK_transport.md. Re-run this preflight to confirm."
            "\n" + "=" * 72)


if __name__ == "__main__":
    if native_tls_ok():
        print("[preflight] native TLS OK -> transport=native_sdk. Safe to run streaming/latency.")
        raise SystemExit(0)
    print("[preflight] native TLS BROKEN -> transport would be schannel_curl (no streaming).",
          file=sys.stderr)
    require_native_tls()   # emits the loud banner + exits 2
