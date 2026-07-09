# RUNBOOK — Service-host native-TLS transport profile

The pipeline's composer needs **native Python TLS** (`transport=native_sdk`) for
streaming and valid TTFA. On Windows dev/Service hosts running **Avast**, HTTPS
scanning injects an applink-less OpenSSL that **hard-aborts native outbound
HTTPS**, so the pipeline silently degrades to `schannel_curl` (works for
fabrication-only evals — transport-independent — but **no streaming, invalid
TTFA**). This regressed repeatedly across W2.x/W3.x runs and must be made durable.

## 1. Preflight (run before ANY streaming / latency / paid run)

```
python scripts/preflight_transport.py
```

- exit 0 + `native TLS OK` → safe to run.
- exit 2 + loud banner → native TLS broken; apply the profile below, **reboot**, re-run the preflight.

Import form for harness startup: `from preflight_transport import require_native_tls; require_native_tls()`.
(Fabrication-only / Section-B curl runs may skip it — those are transport-independent.)

## 2. Service-host security profile (apply once; survives if not changed)

**Goal:** the minimum-off that keeps native TLS working — only HTTPS scanning OFF, everything else ON.

Avast One → **Protection → Core Shields → Web Guard**:
- **Enable HTTPS scanning = OFF**  ← the single required change (the OpenSSL applink injector).
- Web Guard itself = ON; "Scan web traffic of uncommon applications" = ON (default).
- **AI Browsing Protection = ON** (verified not to break native TLS).
- **All other shields ON:** File / Behavior / Mail Shields, Anti-Rootkit, Anti-Exploit, Ransomware Shield (Smart Mode), Firewall (Smart Mode).

**Then REBOOT** — Avast applies the change to new processes only after the injected hooks clear; a running session stays broken until restart.

> Known good = the documented "Avast Service-host profile": HTTPS scanning OFF, all other shields ON.

## 3. Why not auto-applied

This is an **OS/GUI change (Avast) + reboot** — it cannot be applied from the repo
or a script. Dev0/Pao apply steps in §2 manually on each Service host. The repo's
contribution is the **preflight self-check** (`scripts/preflight_transport.py`)
that fails loudly if the profile is not in effect, so a broken transport is caught
**before** a run rather than discovered mid-run.

## 4. Durability

- Re-verify with the preflight after any OS update / Avast update / reboot (the regression has recurred).
- If native TLS cannot be restored on a given host, latency/streaming runs are invalid there; only
  transport-independent evals (retrieval-only, fabrication) may proceed on `schannel_curl` — and must be
  **labeled** as curl/provisional.
