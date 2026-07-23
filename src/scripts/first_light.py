#!/usr/bin/env python3
"""Phase 0 first-light check for the CBC Duffing rig.

Purpose: the first energised actuation of the physical beam after exciter
power-on.  It arms the safety gate (confirming any historical latched trip
clears with a live in-range laser), captures a quiet armed baseline, then drives
a small sub-resonance sine and confirms the beam actually responds (laser
deflection and adc0 current), the safety gate holds with a moving beam, and the
displacement stays well inside the host guard band.

Deliberately conservative: single low frequency, small amplitude (default
0.1 V pp), short.  Always disarms and clears every output path in ``finally``.
Amplitudes/limits are CLI inputs; ``AGENTS.md`` remains their source of truth.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from helic_daq import Device, protocol  # noqa: E402
from rig_session import (  # noqa: E402
    DisplacementGuard,
    RigSafetyError,
    capture_checked,
    force_safe,
    project_harmonics,
    reset_diagnostics,
    require_armed_untripped,
    set_sine_forcing,
    snapshot,
)

SOURCES = ["adc0", "laser", "forcing", "out", "cmd_epoch"]


def jsonable(value):
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, Path):
        return str(value)
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="192.168.1.235")
    parser.add_argument("--port", type=int, default=protocol.CONTROL_PORT)
    parser.add_argument("--freq", type=float, default=3.0, help="drive frequency (Hz)")
    parser.add_argument("--amp", type=float, default=0.05, help="logical peak volts (0.05 = 0.1 Vpp)")
    parser.add_argument("--settle", type=float, default=2.0, help="settle seconds before capture")
    parser.add_argument("--capture", type=float, default=2.0, help="capture seconds")
    parser.add_argument("--rest-mm", type=float, default=25.0)
    parser.add_argument("--abort-mm", type=float, default=10.0, help="abort excursion from rest")
    parser.add_argument("--output", default="data/2026-07-22-first-light")
    args = parser.parse_args()

    guard = DisplacementGuard(rest_mm=args.rest_mm, abort_excursion_mm=args.abort_mm)
    outdir = Path(args.output)
    outdir.mkdir(parents=True, exist_ok=True)
    report: dict = {"args": {k: jsonable(v) for k, v in vars(args).items()}}

    with Device(args.host, args.port) as dev:
        try:
            status = dev.status()
            fs = float(status["sample_rate"])
            report["firmware"] = status.get("firmware")
            print(f"firmware: {status.get('firmware')}  fs={fs} Hz")

            force_safe(dev)
            reset_diagnostics(dev)

            # Arm: confirm the historical latched trip clears with laser in range.
            pre = snapshot(dev)
            print(f"pre-arm  safety=0b{int(pre['safety']):04b} laser={pre['laser']:.3f} mm")
            armed = require_armed_untripped(dev)
            print(f"armed    safety=0b{int(armed['safety']):04b} laser={armed['laser']:.3f} mm  -> armed & untripped")
            report["arm"] = {"pre_safety": int(pre["safety"]), "post_safety": int(armed["safety"])}

            # Quiet armed baseline (zero drive, armed): laser rest + adc0 baseline.
            base, _ = capture_checked(dev, SOURCES, seconds=1.0)
            base_laser = (float(np.min(base["laser"])), float(np.max(base["laser"])))
            base_adc0 = float(np.mean(base["adc0"]))
            print(f"baseline laser {base_laser[0]:.3f}-{base_laser[1]:.3f} mm  adc0 {base_adc0*1e3:.2f} mV  out max {np.max(np.abs(base['out']))*1e3:.2f} mV")
            report["armed_baseline"] = {
                "laser_min_mm": base_laser[0], "laser_max_mm": base_laser[1],
                "adc0_mean_v": base_adc0,
                "out_absmax_v": float(np.max(np.abs(base["out"]))),
            }

            # Drive a small sub-resonance sine.
            print(f"driving {args.amp*2:.3f} Vpp sine @ {args.freq} Hz (settle {args.settle}s)")
            set_sine_forcing(dev, args.freq, args.amp)
            time.sleep(args.settle)
            data, health = capture_checked(dev, SOURCES, seconds=args.capture)

            laser_span = (float(np.min(data["laser"])), float(np.max(data["laser"])))
            verdict = guard.check(*laser_span)
            idx = data["index"]
            laser_h = project_harmonics(data["laser"], idx, args.freq, fs, 3)
            forc_h = project_harmonics(data["forcing"], idx, args.freq, fs, 3)
            adc0_h = project_harmonics(data["adc0"], idx, args.freq, fs, 3)
            out_h = project_harmonics(data["out"], idx, args.freq, fs, 3)

            frf = laser_h["amplitude"][0] / forc_h["amplitude"][0] if abs(forc_h["amplitude"][0]) > 0 else 0
            print(f"  laser span {laser_span[0]:.3f}-{laser_span[1]:.3f} mm  (guard: {verdict})")
            print(f"  forcing A1 {forc_h['amp'][0]*1e3:.2f} mV   out A1 {out_h['amp'][0]*1e3:.2f} mV")
            print(f"  laser  A1 {laser_h['amp'][0]*1e3:.4f} um   phase {np.degrees(laser_h['phase'][0]):.1f} deg")
            print(f"  adc0   A1 {adc0_h['amp'][0]*1e3:.3f} mV   (exciter current sense)")
            print(f"  FRF |X/F| = {abs(frf):.4f} mm/V   phase {np.degrees(np.angle(frf)):.1f} deg")
            print(f"  post safety=0b{int(health['safety']):04b}  loop_max {health['loop_time_max']} us")

            report["drive"] = {
                "freq_hz": args.freq, "amp_v": args.amp,
                "laser_span_mm": laser_span, "guard": verdict,
                "forcing_A1_v": float(forc_h["amp"][0]),
                "out_A1_v": float(out_h["amp"][0]),
                "laser_A1_mm": float(laser_h["amp"][0]),
                "laser_A1_phase_deg": float(np.degrees(laser_h["phase"][0])),
                "adc0_A1_v": float(adc0_h["amp"][0]),
                "frf_gain_mm_per_v": float(abs(frf)),
                "frf_phase_deg": float(np.degrees(np.angle(frf))),
                "post_safety": int(health["safety"]),
            }

            np.savez(outdir / "first_light_drive.npz", **{k: v for k, v in data.items()})
            (outdir / "first_light_summary.json").write_text(
                json.dumps(report, indent=2, sort_keys=True, default=jsonable) + "\n"
            )

            if verdict == "abort":
                raise RigSafetyError(f"displacement guard abort: laser span {laser_span}")

            # "responds" = coherent fundamental clearly above the harmonic-fit
            # noise floor (residual). 3 Hz is well below resonance, so even a
            # few um of coherent motion confirms actuation.
            moved = laser_h["amp"][0] > 3.0 * laser_h["residual"]
            print(f"\nRESULT: beam {'RESPONDS' if moved else 'NO CLEAR RESPONSE'}; "
                  f"safety {'HELD (armed/untripped)' if int(health['safety']) & 0b0011 == 0b0001 else 'CHECK'}.")
            return 0
        finally:
            force_safe(dev)
            final = snapshot(dev)
            print(f"safe: arm={final['arm']} safety=0b{int(final['safety']):04b} laser={final['laser']:.3f} mm")


if __name__ == "__main__":
    raise SystemExit(main())
