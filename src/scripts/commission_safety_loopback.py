#!/usr/bin/env python3
"""Commission the CBC firmware safety gate through the DAC-to-ADC loopback.

This script deliberately separates the commissioning phases so a failed check
cannot silently advance to a more demanding test.  Every ordinary phase uses a
persistent host connection and disarms before clearing signal generators in a
``finally`` block.  The disconnect phase is the sole exception: it closes an
armed connection intentionally, then verifies that a fresh connection sees a
quiet, disarmed device.

Rig limits and test amplitudes are intentionally supplied on the command line;
``AGENTS.md`` remains their single source of truth.
"""

from __future__ import annotations

import argparse
import json
import math
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np

from helic_daq import Device, protocol


CAPTURE_SOURCES = ["adc0", "laser", "target", "forcing", "table", "out", "cmd_epoch"]
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


class CommissioningError(RuntimeError):
    """Raised when a commissioning acceptance check fails."""


def json_value(value: Any) -> Any:
    """Convert NumPy scalars and paths into JSON-compatible values."""

    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    return value


def safety_flags(value: int) -> dict[str, bool]:
    """Decode the host-visible safety bitfield."""

    return {
        "armed": bool(value & 0b0001),
        "tripped": bool(value & 0b0010),
        "clamped_since_reset": bool(value & 0b0100),
        "quieted_since_reset": bool(value & 0b1000),
    }


def snapshot(dev: Device) -> dict[str, Any]:
    """Read the complete health and safety snapshot in one control request."""

    values = dev.get(*DIAGNOSTICS)
    result = dict(zip(DIAGNOSTICS, values, strict=True))
    result["safety_flags"] = safety_flags(int(result["safety"]))
    return result


def assert_healthy(dev: Device, health: dict[str, Any]) -> None:
    """Apply the project health rules to a diagnostic snapshot."""

    nonzero = {name: health[name] for name in ZERO_FAULTS if health[name] != 0}
    if nonzero:
        raise CommissioningError(f"non-zero real-time or sensor fault counters: {nonzero}")

    tick_period_us = 1.0e6 / float(dev.status()["sample_rate"])
    if health["loop_time_max"] >= tick_period_us:
        raise CommissioningError(
            f"loop_time_max={health['loop_time_max']} us reaches the "
            f"{tick_period_us:g} us tick period"
        )


def reset_diagnostics(dev: Device) -> dict[str, Any]:
    """Reset run-specific trackers, allow fresh ticks, and check health."""

    dev.set("diag_reset", 1)
    time.sleep(0.05)
    health = snapshot(dev)
    assert_healthy(dev, health)
    return health


def zero_coefficients(dev: Device, name: str) -> None:
    parameter = dev.param(name)
    dev.set(name, [0.0] * parameter.count)


def force_safe(dev: Device) -> None:
    """Disarm first, then clear every output-producing path."""

    dev.set("arm", 0)
    zero_coefficients(dev, "forcing_coeffs")
    zero_coefficients(dev, "target_coeffs")
    dev.set("table_mode", 0)
    dev.set("freq", 0.0)


def set_constant_forcing(dev: Device, value: float) -> None:
    coefficients = [0.0] * dev.param("forcing_coeffs").count
    coefficients[0] = float(value)
    dev.set("forcing_coeffs", coefficients)


def set_sine_forcing(dev: Device, frequency: float, amplitude: float) -> None:
    coefficients = [0.0] * dev.param("forcing_coeffs").count
    harmonics = (len(coefficients) - 1) // 2
    coefficients[1 + harmonics] = float(amplitude)
    dev.set("freq", float(frequency))
    dev.set("forcing_coeffs", coefficients)


def save_capture(output_dir: Path, label: str, data: dict[str, Any]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{label}.npz"
    np.savez(path, **data)
    return path


def capture_checked(
    dev: Device,
    output_dir: Path,
    label: str,
    seconds: float,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    """Capture evidence and reject loss, new drops, or unhealthy diagnostics."""

    before = snapshot(dev)
    data = dev.capture(CAPTURE_SOURCES, seconds=seconds, port=0)
    after = snapshot(dev)
    assert_healthy(dev, after)
    if data["lost_packets"] != 0:
        raise CommissioningError(f"{label}: lost {data['lost_packets']} UDP packets")
    if after["records_dropped"] != before["records_dropped"]:
        raise CommissioningError(
            f"{label}: records_dropped grew from {before['records_dropped']} "
            f"to {after['records_dropped']}"
        )
    return data, after, save_capture(output_dir, label, data)


def basic_stats(data: dict[str, Any]) -> dict[str, float]:
    return {
        "records": int(len(data["index"])),
        "adc0_mean_v": float(np.mean(data["adc0"])),
        "adc0_std_v": float(np.std(data["adc0"])),
        "adc0_min_v": float(np.min(data["adc0"])),
        "adc0_max_v": float(np.max(data["adc0"])),
        "out_mean_v": float(np.mean(data["out"])),
        "out_min_v": float(np.min(data["out"])),
        "out_max_v": float(np.max(data["out"])),
        "laser_min_mm": float(np.min(data["laser"])),
        "laser_max_mm": float(np.max(data["laser"])),
    }


def write_summary(output_dir: Path, phase: str, summary: dict[str, Any]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{phase}.json"
    path.write_text(
        json.dumps(summary, indent=2, sort_keys=True, default=json_value) + "\n",
        encoding="utf-8",
    )
    return path


def require_armed_untripped(dev: Device) -> dict[str, Any]:
    """Arm only with a currently healthy laser and verify the gate accepted it."""

    dev.set("arm", 1)
    time.sleep(0.05)
    health = snapshot(dev)
    assert_healthy(dev, health)
    flags = health["safety_flags"]
    if not flags["armed"] or flags["tripped"]:
        raise CommissioningError(
            f"gate did not reach armed/untripped state: safety=0b{health['safety']:04b}, "
            f"laser={health['laser']} mm"
        )
    return health


def run_baseline(args: argparse.Namespace) -> dict[str, Any]:
    with Device(args.host, args.port) as dev:
        try:
            force_safe(dev)
            initial = reset_diagnostics(dev)
            data, final, path = capture_checked(
                dev, args.output_dir, "baseline_disarmed", args.seconds
            )
            if int(final["arm"]) != 0 or final["safety_flags"]["armed"]:
                raise CommissioningError("baseline ended armed")
            if np.max(np.abs(data["out"])) > args.zero_tolerance:
                raise CommissioningError("disarmed applied output is not near zero")
            if abs(float(np.mean(data["adc0"]))) > args.zero_tolerance:
                raise CommissioningError("disarmed ADC0 differential baseline is not near zero")
            return {
                "phase": "baseline",
                "firmware": dev.get("firmware"),
                "initial_health": initial,
                "final_health": final,
                "capture": path,
                "stats": basic_stats(data),
            }
        finally:
            force_safe(dev)


def run_mapping(args: argparse.Namespace) -> dict[str, Any]:
    if args.small_level is None or args.sine_frequency is None:
        raise CommissioningError("mapping requires --small-level and --sine-frequency")
    if not math.isfinite(args.small_level) or args.small_level <= 0.0:
        raise CommissioningError("--small-level must be finite and positive")

    with Device(args.host, args.port) as dev:
        try:
            force_safe(dev)
            reset_diagnostics(dev)
            armed = require_armed_untripped(dev)
            captures: dict[str, dict[str, Any]] = {}
            raw: list[dict[str, Any]] = []
            for label, command in (("mapping_positive", args.small_level),
                                   ("mapping_negative", -args.small_level)):
                set_constant_forcing(dev, command)
                data, health, path = capture_checked(
                    dev, args.output_dir, label, args.seconds
                )
                captures[label] = {
                    "command_v": command,
                    "capture": path,
                    "health": health,
                    "stats": basic_stats(data),
                }
                raw.append(data)

            set_sine_forcing(dev, args.sine_frequency, args.small_level)
            sine, sine_health, sine_path = capture_checked(
                dev, args.output_dir, "mapping_sine", args.seconds
            )
            captures["mapping_sine"] = {
                "frequency_hz": args.sine_frequency,
                "amplitude_v": args.small_level,
                "capture": sine_path,
                "health": sine_health,
                "stats": basic_stats(sine),
            }

            out = np.concatenate([item["out"] for item in raw])
            adc = np.concatenate([item["adc0"] for item in raw])
            gain, offset = np.polyfit(out, adc, 1)
            residual = adc - (gain * out + offset)
            if gain <= 0:
                raise CommissioningError(f"ADC0 polarity is inverted: fitted gain={gain:g}")
            if abs(gain - 1.0) > args.gain_tolerance:
                raise CommissioningError(
                    f"ADC0/out gain {gain:g} differs from unity by more than "
                    f"{args.gain_tolerance:g}"
                )
            return {
                "phase": "mapping",
                "firmware": dev.get("firmware"),
                "armed_health": armed,
                "captures": captures,
                "fit": {
                    "adc0_per_out_gain": float(gain),
                    "adc0_offset_v": float(offset),
                    "residual_rms_v": float(np.sqrt(np.mean(residual**2))),
                },
            }
        finally:
            force_safe(dev)


def run_disconnect(args: argparse.Namespace) -> dict[str, Any]:
    if args.small_level is None:
        raise CommissioningError("disconnect requires --small-level")

    dev = Device(args.host, args.port)
    try:
        force_safe(dev)
        reset_diagnostics(dev)
        require_armed_untripped(dev)
        set_constant_forcing(dev, args.small_level)
        active, active_health, active_path = capture_checked(
            dev, args.output_dir, "explicit_disarm_before", args.seconds
        )
        if abs(float(np.mean(active["out"])) - args.small_level) > args.output_tolerance:
            raise CommissioningError("pre-disarm applied output does not match the command")

        dev.set("arm", 0)
        explicitly_quiet, explicit_health, explicit_path = capture_checked(
            dev, args.output_dir, "explicit_disarm_after", args.seconds
        )
        if int(explicit_health["arm"]) != 0 or explicit_health["safety_flags"]["armed"]:
            raise CommissioningError("explicit disarm did not clear the armed state")
        if np.max(np.abs(explicitly_quiet["out"])) > args.zero_tolerance:
            raise CommissioningError("explicit disarm did not quiet applied output")
        if (
            abs(float(np.mean(explicitly_quiet["forcing"])) - args.small_level)
            > args.output_tolerance
        ):
            raise CommissioningError("explicit-disarm test lost its configured forcing command")

        require_armed_untripped(dev)
        rearmed, rearmed_health, rearmed_path = capture_checked(
            dev, args.output_dir, "disconnect_before_close", args.seconds
        )
        if abs(float(np.mean(rearmed["out"])) - args.small_level) > args.output_tolerance:
            raise CommissioningError("re-armed output does not match the command")
    except BaseException:
        try:
            force_safe(dev)
        finally:
            dev.close()
        raise
    else:
        # Intentional unclean control close: firmware must disarm before the
        # next connection.  The configured forcing remains nonzero as a strong
        # test that quieting is caused by the safety gate, not command cleanup.
        dev.close()

    time.sleep(0.1)
    with Device(args.host, args.port) as verify:
        try:
            quiet, quiet_health, quiet_path = capture_checked(
                verify, args.output_dir, "disconnect_after_close", args.seconds
            )
            if int(quiet_health["arm"]) != 0 or quiet_health["safety_flags"]["armed"]:
                raise CommissioningError("control disconnect did not clear the armed state")
            if np.max(np.abs(quiet["out"])) > args.zero_tolerance:
                raise CommissioningError("control disconnect did not quiet applied output")
            if abs(float(np.mean(quiet["forcing"])) - args.small_level) > args.output_tolerance:
                raise CommissioningError("disconnect test lost its configured forcing command")
            return {
                "phase": "disconnect",
                "firmware": verify.get("firmware"),
                "before": {
                    "capture": active_path,
                    "health": active_health,
                    "stats": basic_stats(active),
                },
                "explicit_disarm": {
                    "capture": explicit_path,
                    "health": explicit_health,
                    "stats": basic_stats(explicitly_quiet),
                },
                "rearmed_before_disconnect": {
                    "capture": rearmed_path,
                    "health": rearmed_health,
                    "stats": basic_stats(rearmed),
                },
                "after": {
                    "capture": quiet_path,
                    "health": quiet_health,
                    "stats": basic_stats(quiet),
                },
            }
        finally:
            force_safe(verify)


def run_clamp(args: argparse.Namespace) -> dict[str, Any]:
    if args.clamp_request is None or args.clamp_request <= 0:
        raise CommissioningError("clamp requires a positive --clamp-request")

    with Device(args.host, args.port) as dev:
        try:
            force_safe(dev)
            reset_diagnostics(dev)
            require_armed_untripped(dev)
            results: dict[str, Any] = {}
            plateaus: list[float] = []
            for label, command in (("clamp_positive", args.clamp_request),
                                   ("clamp_negative", -args.clamp_request)):
                set_constant_forcing(dev, command)
                data, health, path = capture_checked(
                    dev, args.output_dir, label, args.seconds
                )
                plateau = float(np.mean(data["out"]))
                forcing = float(np.mean(data["forcing"]))
                adc_plateau = float(np.mean(data["adc0"]))
                plateaus.append(plateau)
                if abs(forcing - command) > args.output_tolerance:
                    raise CommissioningError(
                        f"{label}: forcing telemetry {forcing:g} V does not retain "
                        f"request {command:g} V"
                    )
                if abs(plateau) >= abs(command) - args.clamp_min_gap:
                    raise CommissioningError(
                        f"{label}: output {plateau:g} V was not detectably clamped "
                        f"below request {command:g} V"
                    )
                if abs(adc_plateau - plateau) > args.output_tolerance:
                    raise CommissioningError(
                        f"{label}: ADC0 plateau {adc_plateau:g} V does not track "
                        f"applied output {plateau:g} V"
                    )
                if not health["safety_flags"]["clamped_since_reset"]:
                    raise CommissioningError(f"{label}: clamp safety flag was not set")
                results[label] = {
                    "request_v": command,
                    "capture": path,
                    "health": health,
                    "stats": basic_stats(data),
                }
            if abs(plateaus[0] + plateaus[1]) > args.output_tolerance:
                raise CommissioningError(
                    f"clamp plateaus are not symmetric: {plateaus[0]:g}, {plateaus[1]:g} V"
                )
            if plateaus[0] <= 0 or plateaus[1] >= 0:
                raise CommissioningError("clamp directions have incorrect signs")
            return {
                "phase": "clamp",
                "firmware": dev.get("firmware"),
                "captures": results,
                "positive_plateau_v": plateaus[0],
                "negative_plateau_v": plateaus[1],
            }
        finally:
            force_safe(dev)


def run_final(args: argparse.Namespace) -> dict[str, Any]:
    with Device(args.host, args.port) as dev:
        force_safe(dev)
        initial = reset_diagnostics(dev)
        data, final, path = capture_checked(dev, args.output_dir, "final_quiet", args.seconds)
        if int(final["arm"]) != 0 or final["safety_flags"]["armed"]:
            raise CommissioningError("final state is armed")
        if np.max(np.abs(data["out"])) > args.zero_tolerance:
            raise CommissioningError("final applied output is not near zero")
        if abs(float(np.mean(data["adc0"]))) > args.zero_tolerance:
            raise CommissioningError("final ADC0 differential reading is not near zero")
        return {
            "phase": "final",
            "firmware": dev.get("firmware"),
            "initial_health": initial,
            "final_health": final,
            "capture": path,
            "stats": basic_stats(data),
        }


def run_self_test() -> dict[str, Any]:
    """Exercise persistent control, streaming, and cleanup against the simulator."""

    from helic_daq.sim import Simulator

    with tempfile.TemporaryDirectory() as temporary, Simulator(noise=0.0) as simulator:
        output_dir = Path(temporary)
        with Device(simulator.host, simulator.port) as dev:
            force_safe(dev)
            dev.set("arm", 1)
            set_constant_forcing(dev, 0.025)
            data, health, path = capture_checked(dev, output_dir, "self_test", 0.02)
            if not np.allclose(data["out"], 0.025, atol=1e-6):
                raise CommissioningError("simulator constant forcing did not stream")
            if not np.allclose(data["adc0"], data["out"], atol=1e-6):
                raise CommissioningError("simulator loopback did not track output")
            force_safe(dev)
            if dev.get("arm") != 0:
                raise CommissioningError("cleanup did not disarm simulator")
            if not path.exists():
                raise CommissioningError("self-test capture was not saved")

        with Device(simulator.host, simulator.port) as verify:
            if verify.get("arm") != 0:
                raise CommissioningError("disconnect did not preserve disarmed state")
        return {"phase": "self-test", "health": health, "records": len(data["index"])}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "phase", choices=["self-test", "baseline", "mapping", "disconnect", "clamp", "final"]
    )
    parser.add_argument("--host", default="192.168.1.235")
    parser.add_argument("--port", type=int, default=protocol.CONTROL_PORT)
    parser.add_argument("--output-dir", type=Path, default=Path("data/safety-loopback"))
    parser.add_argument("--seconds", type=float, default=0.5)
    parser.add_argument("--small-level", type=float)
    parser.add_argument("--sine-frequency", type=float)
    parser.add_argument("--clamp-request", type=float)
    parser.add_argument("--zero-tolerance", type=float, default=0.02)
    parser.add_argument("--gain-tolerance", type=float, default=0.05)
    parser.add_argument("--output-tolerance", type=float, default=0.01)
    parser.add_argument("--clamp-min-gap", type=float, default=0.01)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.seconds <= 0 or not math.isfinite(args.seconds):
        raise CommissioningError("--seconds must be finite and positive")

    if args.phase == "self-test":
        summary = run_self_test()
        print(json.dumps(summary, indent=2, sort_keys=True, default=json_value))
        return 0

    runners = {
        "baseline": run_baseline,
        "mapping": run_mapping,
        "disconnect": run_disconnect,
        "clamp": run_clamp,
        "final": run_final,
    }
    summary = runners[args.phase](args)
    summary_path = write_summary(args.output_dir, args.phase, summary)
    summary["summary"] = summary_path
    print(json.dumps(summary, indent=2, sort_keys=True, default=json_value))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
