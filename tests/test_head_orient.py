"""Head-orientation seam test (offline, $0) — the pure mapping/gate logic + the guarded
orient_to_wake glue. No robot, no mic array, no audio needed.

Standalone (exits non-zero on failure): .venv/Scripts/python.exe tests/test_head_orient.py
Pytest-compatible.
"""
from __future__ import annotations

import sys
from pathlib import Path

try:                                    # console-safe unicode (Windows cp1252 chokes on ->/°)
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))

import config          # noqa: E402
import head_orient     # noqa: E402
from head_orient import (DirectionEstimate, DirectionEstimator, FixedDirectionEstimator,  # noqa: E402
                         MicArrayDOAEstimator, LoggingHeadController, ReachyMiniHeadController,
                         map_azimuth_to_yaw, gate_open, clamp, orient_to_wake)


class StubEstimator(DirectionEstimator):
    def __init__(self, az, level): self._az, self._level = az, level
    def estimate(self, wav_path=None): return DirectionEstimate(self._az, self._level, "stub")


class ThrowingEstimator(DirectionEstimator):
    def estimate(self, wav_path=None): raise RuntimeError("estimator boom")


def _enabled(v: bool):
    config.HEAD_ORIENT_ENABLED = v


# ---- pure logic (no config coupling — explicit args) ----
def test_clamp_and_yaw_mapping():
    assert clamp(5, 3) == 3 and clamp(-5, 3) == -3 and clamp(2, 3) == 2
    assert map_azimuth_to_yaw(45, 90) == 45.0          # within range: unchanged
    assert map_azimuth_to_yaw(120, 90) == 90.0         # beyond +limit: clamped
    assert map_azimuth_to_yaw(-140, 90) == -90.0       # beyond -limit: clamped
    assert map_azimuth_to_yaw(-30, 90) == -30.0        # left, within range


def test_level_gate():
    assert gate_open(0.5, 0.15) is True
    assert gate_open(0.15, 0.15) is True               # boundary is inclusive
    assert gate_open(0.10, 0.15) is False              # too far/quiet


# ---- orient_to_wake glue ----
def test_disabled_by_default_no_turn():
    _enabled(False)
    r = orient_to_wake()
    assert r["enabled"] is False and r["turned"] is False and r["reason"] == "disabled"


def test_turns_when_enabled_and_loud_enough():
    _enabled(True)
    try:
        ctrl = LoggingHeadController()
        r = orient_to_wake(StubEstimator(az=40, level=0.9), ctrl)
        assert r["turned"] is True and r["yaw_deg"] == 40.0 and r["reason"] == "turned"
        assert ctrl.last_yaw == 40.0                   # the controller actually got the command
    finally:
        _enabled(False)


def test_gated_when_too_far():
    _enabled(True)
    try:
        ctrl = LoggingHeadController()
        r = orient_to_wake(StubEstimator(az=40, level=0.05), ctrl)   # below default MIN_LEVEL 0.15
        assert r["turned"] is False and r["reason"] == "below_level_gate"
        assert ctrl.last_yaw is None                   # head must NOT move
    finally:
        _enabled(False)


def test_azimuth_is_clamped_to_yaw_limit():
    _enabled(True)
    try:
        ctrl = LoggingHeadController()
        r = orient_to_wake(StubEstimator(az=140, level=0.9), ctrl)   # > default 90° limit
        assert r["turned"] is True and r["yaw_deg"] == 90.0 and ctrl.last_yaw == 90.0
    finally:
        _enabled(False)


def test_guarded_on_estimator_error():
    _enabled(True)
    try:
        r = orient_to_wake(ThrowingEstimator(), LoggingHeadController())
        assert r["turned"] is False and r["reason"].startswith("error:")   # caught, not raised
    finally:
        _enabled(False)


def test_hardware_stubs_raise_and_are_caught():
    # the stubs themselves raise NotImplementedError...
    raised = False
    try:
        MicArrayDOAEstimator().estimate()
    except NotImplementedError:
        raised = True
    assert raised
    raised = False
    try:
        ReachyMiniHeadController().turn_to(0)
    except NotImplementedError:
        raised = True
    assert raised
    # ...and orient_to_wake catches a stub cleanly (reason=stub_not_wired), never crashes
    _enabled(True)
    try:
        r = orient_to_wake(MicArrayDOAEstimator(), LoggingHeadController())
        assert r["turned"] is False and r["reason"].startswith("stub_not_wired")
    finally:
        _enabled(False)


CASES = [
    ("clamp + azimuth->yaw mapping", test_clamp_and_yaw_mapping),
    ("level/distance gate", test_level_gate),
    ("disabled by default → no turn", test_disabled_by_default_no_turn),
    ("turns when enabled and loud enough", test_turns_when_enabled_and_loud_enough),
    ("gated when too far/quiet", test_gated_when_too_far),
    ("azimuth clamped to yaw limit", test_azimuth_is_clamped_to_yaw_limit),
    ("guarded on estimator error", test_guarded_on_estimator_error),
    ("hardware stubs raise + are caught", test_hardware_stubs_raise_and_are_caught),
]


def main() -> int:
    print(f"=== head-orient test (HEAD_ORIENT default enabled={config.HEAD_ORIENT_ENABLED}) ===")
    ok = True
    for name, fn in CASES:
        try:
            fn()
            print(f"  PASS  {name}")
        except AssertionError as e:
            ok = False
            print(f"  FAIL  {name}: {e}")
    print(f"\n{'ALL PASS' if ok else 'FAILURES'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
