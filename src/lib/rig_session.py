#!/usr/bin/env python3
"""Reusable safe-session helpers for driving the CBC Duffing rig.

This module factors the persistent-connection, arm/disarm, health-check, and
harmonic-projection logic shared by the open-loop and (later) closed-loop
experiment scripts.  It deliberately mirrors the acceptance discipline proven in
``commission_safety_loopback.py``: every driving session arms only with a live
in-range laser, polls the firmware safety gate, and is expected to be wrapped in
a ``finally`` that calls :func:`force_safe`.

Rig limits, safe amplitudes, and the resting displacement are documented in
``AGENTS.md`` (the single source of truth); callers pass them in rather than
this library hard-coding them, except for decode helpers tied to the firmware
protocol.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

from helic_daq import Device


# Faults that must stay exactly zero in steady state (see AGENTS.md Health).
ZERO_FAULTS = [
    "overruns",
    "tick_timeouts",
    "clock_jitter",
    "laser_uart_errors",
    "laser_parse_errors",
    "laser_invalid_frames",
    "laser_unexpected_values",
    "laser_sync_errors",
]

DIAGNOSTICS = [
    *ZERO_FAULTS,
    "loop_time_last",
    "loop_time_max",
    "wake_phase_min",
    "wake_phase_max",
    "t_measure_max",
    "t_actuate_max",
    "t_rest_max",
    "cmd_backlog_max",
    "records_dropped",
    "safety",
    "arm",
    "laser",
]


class RigSafetyError(RuntimeError):
    """Raised when a safety or acceptance check fails; triggers abort-to-safe."""


def safety_flags(value: int) -> dict[str, bool]:
    """Decode the firmware safety bitfield (bit0 armed .. bit3 quieted)."""

    return {
        "armed": bool(value & 0b0001),
        "tripped": bool(value & 0b0010),
        "clamped_since_reset": bool(value & 0b0100),
        "quieted_since_reset": bool(value & 0b1000),
    }


def snapshot(dev: Device) -> dict[str, Any]:
    """Read the full health + safety snapshot in a single control request."""

    values = dev.get(*DIAGNOSTICS)
    result = dict(zip(DIAGNOSTICS, values, strict=True))
    result["safety_flags"] = safety_flags(int(result["safety"]))
    return result


def assert_healthy(dev: Device, health: dict[str, Any]) -> None:
    """Enforce the project health rules on a diagnostic snapshot."""

    nonzero = {name: health[name] for name in ZERO_FAULTS if health[name] != 0}
    if nonzero:
        raise RigSafetyError(f"non-zero fault counters: {nonzero}")
    tick_period_us = 1.0e6 / float(dev.status()["sample_rate"])
    if health["loop_time_max"] >= tick_period_us:
        raise RigSafetyError(
            f"loop_time_max={health['loop_time_max']} us reaches the "
            f"{tick_period_us:g} us tick period"
        )


def reset_diagnostics(dev: Device) -> dict[str, Any]:
    """Reset run-specific trackers, settle, and confirm a clean baseline."""

    dev.set("diag_reset", 1)
    time.sleep(0.05)
    health = snapshot(dev)
    assert_healthy(dev, health)
    return health


def zero_coefficients(dev: Device, name: str) -> None:
    parameter = dev.param(name)
    dev.set(name, [0.0] * parameter.count)


def force_safe(dev: Device) -> None:
    """Disarm first, then clear every output-producing path (idempotent)."""

    try:
        dev.set("arm", 0)
    finally:
        zero_coefficients(dev, "forcing_coeffs")
        zero_coefficients(dev, "target_coeffs")
        dev.set("table_mode", 0)
        dev.set("freq", 0.0)


def set_sine_forcing(dev: Device, frequency: float, amplitude: float) -> None:
    """Feed-forward a pure sine: single b1 (sine at the fundamental) coefficient.

    ``amplitude`` is the logical peak in volts (0.05 V = 0.1 V pp).  Note the
    firmware plays ``forcing`` at ``freq``; the response fundamental is at
    ``frequency``.
    """

    count = dev.param("forcing_coeffs").count
    harmonics = (count - 1) // 2
    coefficients = [0.0] * count
    coefficients[1 + harmonics] = float(amplitude)  # b1 (sine, fundamental)
    dev.set("freq", float(frequency))
    dev.set("forcing_coeffs", coefficients)


def require_armed_untripped(dev: Device) -> dict[str, Any]:
    """Arm and verify the gate reached armed+untripped with a healthy laser."""

    dev.set("arm", 1)
    time.sleep(0.05)
    health = snapshot(dev)
    assert_healthy(dev, health)
    flags = health["safety_flags"]
    if not flags["armed"] or flags["tripped"]:
        raise RigSafetyError(
            f"gate not armed/untripped: safety=0b{int(health['safety']):04b}, "
            f"laser={health['laser']} mm"
        )
    return health


@dataclass
class DisplacementGuard:
    """Host-side displacement envelope, tighter than the firmware trip.

    The firmware trips outside ``[10, 40] mm`` (rest ~25 mm).  This guard aborts
    the run before the firmware fires, keeping a margin so a sweep never relies
    on the hard trip in normal operation.
    """

    rest_mm: float = 25.0
    abort_excursion_mm: float = 10.0  # abort if |laser - rest| exceeds this
    warn_excursion_mm: float = 7.0    # flag (e.g. stop escalating amplitude)

    def check(self, laser_min: float, laser_max: float) -> str:
        """Return "ok" | "warn" | "abort" for an observed displacement span."""

        excursion = max(abs(laser_max - self.rest_mm), abs(laser_min - self.rest_mm))
        if excursion >= self.abort_excursion_mm:
            return "abort"
        if excursion >= self.warn_excursion_mm:
            return "warn"
        return "ok"


def project_harmonics(
    signal: np.ndarray,
    index: np.ndarray,
    freq: float,
    sample_rate: float,
    n_harmonics: int,
) -> dict[str, np.ndarray]:
    """Least-squares harmonic fit of ``signal`` at multiples of ``freq``.

    Fits ``mean + sum_{n=1..H} a_n cos(n w t) + b_n sin(n w t)`` where
    ``t = index / sample_rate`` and ``w = 2*pi*freq``.  Least squares (rather
    than a plain DFT) avoids spectral leakage from non-integer period counts.

    Returns ``mean`` (float), ``a`` and ``b`` (length-H arrays), the complex
    amplitude ``A_n = a_n - i b_n`` (so ``signal ~ Re[A_n exp(i n w t)]``),
    ``amp`` = |A_n|, ``phase`` = angle(A_n), and the RMS fit ``residual``.
    """

    t = np.asarray(index, dtype=float) / float(sample_rate)
    w = 2.0 * np.pi * float(freq)
    columns = [np.ones_like(t)]
    for n in range(1, n_harmonics + 1):
        columns.append(np.cos(n * w * t))
        columns.append(np.sin(n * w * t))
    design = np.column_stack(columns)
    coeffs, *_ = np.linalg.lstsq(design, np.asarray(signal, dtype=float), rcond=None)
    residual = float(np.sqrt(np.mean((design @ coeffs - signal) ** 2)))
    mean = float(coeffs[0])
    a = coeffs[1::2]
    b = coeffs[2::2]
    amplitude = a - 1j * b
    return {
        "mean": mean,
        "a": a,
        "b": b,
        "amplitude": amplitude,
        "amp": np.abs(amplitude),
        "phase": np.angle(amplitude),
        "residual": residual,
    }


def capture_checked(
    dev: Device,
    sources: Sequence[str],
    seconds: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Capture and reject UDP loss, new record drops, or unhealthy diagnostics.

    Returns ``(data, health_after)``.  Raises :class:`RigSafetyError` on any
    acceptance failure so the caller's ``finally`` drives the rig safe.
    """

    before = snapshot(dev)
    data = dev.capture(list(sources), seconds=seconds, port=0)
    after = snapshot(dev)
    assert_healthy(dev, after)
    if data["lost_packets"] != 0:
        raise RigSafetyError(f"lost {data['lost_packets']} UDP packets during capture")
    if after["records_dropped"] != before["records_dropped"]:
        raise RigSafetyError(
            f"records_dropped grew {before['records_dropped']} -> "
            f"{after['records_dropped']}"
        )
    return data, after
