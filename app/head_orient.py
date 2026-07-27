"""Head orientation — turn the Reachy Mini head toward the speaker on a wake fire.

Per the Reachy seam (design/w2_7_reachy_seam.md), motors/gaze are ROBOT-side. This
module is the PARAMETERIZED SEAM for "turn toward the voice": on a wake fire it
estimates the speaker's direction, gates on signal level (a "voice heard from a
certain distance" proxy), clamps to the neck's yaw range, and commands a head turn.

Nothing here needs a robot or a mic array to import/test. The direction and level are
HARD-CODED "signal inputs" for now (config §13); real direction-of-arrival (mic-array
GCC-PHAT) and the real Reachy SDK head-turn are HARDWARE-week drop-ins behind the two
protocols below — no rewiring of app/wake_word.run_hands_free_loop.

Layers:
  * DirectionEstimate — (azimuth_deg, level, source).
  * DirectionEstimator — FixedDirectionEstimator (default, hard-coded) | MicArrayDOAEstimator (stub).
  * HeadController     — LoggingHeadController (default, no hardware) | ReachyMiniHeadController (stub).
  * map_azimuth_to_yaw / gate_open — pure, unit-tested mapping + distance gate.
  * orient_to_wake()   — the glue; fully guarded (a head-orient failure never crashes a turn).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
import config  # noqa: E402


def _cfg(name, default):
    return getattr(config, name, default)


# ---------------------------------------------------------------- pure logic (tested)
def clamp(value: float, limit: float) -> float:
    """Clamp value to [-limit, +limit]."""
    return max(-abs(limit), min(abs(limit), value))


def map_azimuth_to_yaw(azimuth_deg: float, yaw_limit_deg: Optional[float] = None) -> float:
    """Map an estimated source azimuth (deg; 0=front, +=right, -=left) to a head-yaw
    command, clamped to the neck's mechanical range so a command never over-rotates."""
    limit = float(_cfg("HEAD_ORIENT_YAW_LIMIT_DEG", 90.0) if yaw_limit_deg is None else yaw_limit_deg)
    return round(clamp(float(azimuth_deg), limit), 2)


def gate_open(level: float, min_level: Optional[float] = None) -> bool:
    """Distance/level gate — the head only turns for a voice at/above this level ('heard
    from a certain distance'). A far/quiet wake stays below and the head holds position."""
    thr = float(_cfg("HEAD_ORIENT_MIN_LEVEL", 0.15) if min_level is None else min_level)
    return float(level) >= thr


# ---------------------------------------------------------------- direction estimators
@dataclass
class DirectionEstimate:
    azimuth_deg: float          # 0 = front, + = speaker to the robot's right, - = left
    level: float                # 0..1 signal loudness (distance proxy)
    source: str                 # "fixed" | "doa" | ...


class DirectionEstimator:
    def estimate(self, wav_path: Optional[str | Path] = None) -> DirectionEstimate:  # pragma: no cover
        raise NotImplementedError


class FixedDirectionEstimator(DirectionEstimator):
    """Default: the HARD-CODED signal inputs from config §13 (a fixed azimuth + level).
    Ignores the audio — a stand-in until real DOA lands. Re-parameterize via config/env."""
    def estimate(self, wav_path: Optional[str | Path] = None) -> DirectionEstimate:
        return DirectionEstimate(
            azimuth_deg=float(_cfg("HEAD_ORIENT_FIXED_AZIMUTH_DEG", 0.0)),
            level=float(_cfg("HEAD_ORIENT_FIXED_LEVEL", 1.0)),
            source="fixed")


class MicArrayDOAEstimator(DirectionEstimator):
    """HARDWARE-week stub: real direction-of-arrival from the robot's mic ARRAY
    (e.g. GCC-PHAT/TDOA over ≥2 channels with known geometry). Needs the array +
    multi-channel wake audio; unimplemented here on purpose."""
    def estimate(self, wav_path: Optional[str | Path] = None) -> DirectionEstimate:  # pragma: no cover
        raise NotImplementedError(
            "mic-array DOA needs the robot's microphone array (multi-channel) + a GCC-PHAT "
            "estimator. Use HEAD_ORIENT_BACKEND=fixed until the hardware is on the bench.")


def make_estimator(backend: Optional[str] = None) -> DirectionEstimator:
    backend = (backend or _cfg("HEAD_ORIENT_BACKEND", "fixed")).lower()
    if backend in ("fixed", "hardcoded", "config"):
        return FixedDirectionEstimator()
    if backend in ("doa", "mic_array", "micarray"):
        return MicArrayDOAEstimator()
    raise ValueError(f"unknown HEAD_ORIENT_BACKEND: {backend!r}")


# ---------------------------------------------------------------- head controllers
class HeadController:
    def turn_to(self, yaw_deg: float) -> None:  # pragma: no cover
        raise NotImplementedError


class LoggingHeadController(HeadController):
    """Default: no hardware — records/prints the target yaw so the seam is observable
    and testable off-robot. `last_yaw` lets tests assert what was commanded."""
    def __init__(self):
        self.last_yaw: Optional[float] = None

    def turn_to(self, yaw_deg: float) -> None:
        self.last_yaw = yaw_deg
        print(f"[head] -> turn to yaw {yaw_deg:+.1f}° (logging stub; no motor)")


class ReachyMiniHeadController(HeadController):
    """HARDWARE-week stub: the real Reachy Mini head-turn via its SDK
    (e.g. reachy.head.look_at / goto with the yaw). Unimplemented here on purpose."""
    def turn_to(self, yaw_deg: float) -> None:  # pragma: no cover
        raise NotImplementedError(
            "real head-turn needs the Reachy Mini SDK on the robot. Use "
            "HEAD_ORIENT_CONTROLLER=log off-robot.")


def make_controller(kind: Optional[str] = None) -> HeadController:
    kind = (kind or _cfg("HEAD_ORIENT_CONTROLLER", "log")).lower()
    if kind in ("log", "logging", "stub"):
        return LoggingHeadController()
    if kind in ("reachy", "reachy_mini", "sdk"):
        return ReachyMiniHeadController()
    raise ValueError(f"unknown HEAD_ORIENT_CONTROLLER: {kind!r}")


# ---------------------------------------------------------------- the glue
def orient_to_wake(estimator: Optional[DirectionEstimator] = None,
                   controller: Optional[HeadController] = None,
                   wav_path: Optional[str | Path] = None) -> dict:
    """On a wake fire: estimate direction -> gate on level -> clamp to yaw -> turn head.
    Returns a telemetry dict. FULLY GUARDED: a head-orient failure logs and returns
    turned=False; it must never crash the voice turn."""
    if not _cfg("HEAD_ORIENT_ENABLED", False):
        return {"enabled": False, "turned": False, "reason": "disabled"}
    out = {"enabled": True, "turned": False, "azimuth_deg": None, "level": None,
           "yaw_deg": None, "source": None, "reason": None}
    try:
        est = (estimator or make_estimator()).estimate(wav_path)
        out.update(azimuth_deg=est.azimuth_deg, level=est.level, source=est.source)
        if not gate_open(est.level):
            out["reason"] = "below_level_gate"      # voice too far/quiet — hold position
            return out
        yaw = map_azimuth_to_yaw(est.azimuth_deg)
        (controller or make_controller()).turn_to(yaw)
        out.update(turned=True, yaw_deg=yaw, reason="turned")
    except NotImplementedError as e:
        out["reason"] = f"stub_not_wired:{type(e).__name__}"
    except Exception as e:                           # never let head-orient break a turn
        out["reason"] = f"error:{type(e).__name__}: {e}"
    return out


__all__ = ["DirectionEstimate", "DirectionEstimator", "FixedDirectionEstimator",
           "MicArrayDOAEstimator", "HeadController", "LoggingHeadController",
           "ReachyMiniHeadController", "make_estimator", "make_controller",
           "map_azimuth_to_yaw", "gate_open", "clamp", "orient_to_wake"]
