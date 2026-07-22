#!/usr/bin/env python3
"""Open-loop stepped-sine frequency sweeps for the CBC Duffing rig (Phases 1-2).

Drives a pure feed-forward sine at each frequency in a stepped grid, waits for
the transient to settle, captures an integer-ish number of periods, and projects
the laser (and adc0 current, forcing, applied out) onto harmonics of the drive.
This yields the frequency-response function (FRF) and its harmonic content.

Runs an amplitude ladder; each amplitude can be swept up and/or down so that
hysteresis (the fold/saddle-node signature of a Duffing bistable region) shows
up as a mismatch between up- and down-sweep branches.

Safety: a persistent armed connection with a host displacement guard tighter
than the firmware trip (see rig_session.DisplacementGuard).  On any guard abort,
safety-flag trip, or health failure, the run drives the rig safe and stops.  A
guard "warn" stops escalation to the next (higher) amplitude.  Every path ends
in force_safe.  Amplitudes/limits are CLI inputs; AGENTS.md is their source of
truth (start 0.05 V peak = 0.1 Vpp; do not exceed 1.0 V peak = 2 Vpp).
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
    require_armed_untripped,
    reset_diagnostics,
    snapshot,
    set_sine_forcing,
)

SOURCES = ["adc0", "laser", "forcing", "out", "cmd_epoch"]
HARD_AMP_CEILING_V = 1.0  # 2 Vpp logical ceiling (AGENTS.md); refuse above this.


def jsonable(value):
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, Path):
        return str(value)
    return value


def frequency_grid(fmin: float, fmax: float, n: int, direction: str) -> np.ndarray:
    grid = np.linspace(fmin, fmax, n)
    return grid if direction == "up" else grid[::-1]


def sweep_once(dev, fs, amp, freqs, settle, capture_s, harmonics, guard):
    """One directional sweep at a fixed amplitude. Returns (rows, raw, status)."""

    rows = []
    raw = {k: [] for k in ("index", "laser", "forcing", "adc0", "out")}
    status = "ok"
    for freq in freqs:
        set_sine_forcing(dev, float(freq), float(amp))
        time.sleep(settle)
        data, health = capture_checked(dev, SOURCES, seconds=capture_s)
        laser_min = float(np.min(data["laser"]))
        laser_max = float(np.max(data["laser"]))
        verdict = guard.check(laser_min, laser_max)

        idx = data["index"]
        lh = project_harmonics(data["laser"], idx, freq, fs, harmonics)
        fh = project_harmonics(data["forcing"], idx, freq, fs, harmonics)
        ah = project_harmonics(data["adc0"], idx, freq, fs, harmonics)
        oh = project_harmonics(data["out"], idx, freq, fs, harmonics)
        gain = lh["amplitude"][0] / fh["amplitude"][0] if abs(fh["amplitude"][0]) > 1e-9 else 0.0

        rows.append({
            "freq": float(freq),
            "laser_mean": lh["mean"], "laser_min": laser_min, "laser_max": laser_max,
            "laser_A1": float(lh["amp"][0]), "laser_phase": float(lh["phase"][0]),
            "laser_A2": float(lh["amp"][1]) if harmonics >= 2 else 0.0,
            "laser_A3": float(lh["amp"][2]) if harmonics >= 3 else 0.0,
            "laser_residual": lh["residual"],
            "forcing_A1": float(fh["amp"][0]),
            "out_A1": float(oh["amp"][0]), "out_mean": oh["mean"],
            "adc0_A1": float(ah["amp"][0]), "adc0_mean": ah["mean"],
            "gain_mag": float(abs(gain)), "gain_phase": float(np.angle(gain)),
            "safety": int(health["safety"]), "guard": verdict,
        })
        for k in ("index", "laser", "forcing", "adc0", "out"):
            raw[k].append(np.asarray(data[k]))

        tag = "" if verdict == "ok" else f"  [{verdict.upper()}]"
        print(f"    f={freq:6.3f} Hz  |X1|={lh['amp'][0]*1e3:8.3f} mm  "
              f"ph={np.degrees(lh['phase'][0]):7.1f}  A3/A1={ (lh['amp'][2]/lh['amp'][0] if harmonics>=3 and lh['amp'][0]>0 else 0):5.3f}  "
              f"span[{laser_min:.2f},{laser_max:.2f}]{tag}")

        if int(health["safety"]) & 0b0010:  # firmware trip latched
            status = "tripped"
            break
        if verdict == "abort":
            status = "abort"
            break
        if verdict == "warn":
            status = "warn"  # continue this sweep, but signal no-escalate
    return rows, raw, status


def save_raw(path: Path, freqs, raw):
    """Truncate captures to a common length and save a compressed archive."""
    if not raw["laser"]:
        return
    length = min(len(a) for a in raw["laser"])
    stacked = {k: np.stack([a[:length] for a in raw[k]]) for k in raw}
    np.savez_compressed(path, freqs=np.asarray(freqs[:len(raw["laser"])]), **stacked)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="192.168.1.235")
    parser.add_argument("--port", type=int, default=protocol.CONTROL_PORT)
    parser.add_argument("--fmin", type=float, required=True)
    parser.add_argument("--fmax", type=float, required=True)
    parser.add_argument("--nsteps", type=int, default=31)
    parser.add_argument("--amps", default="0.05", help="comma list of logical peak volts")
    parser.add_argument("--directions", default="up", choices=["up", "down", "both"])
    parser.add_argument("--settle", type=float, default=4.0)
    parser.add_argument("--capture", type=float, default=2.0)
    parser.add_argument("--harmonics", type=int, default=3)
    parser.add_argument("--rest-mm", type=float, default=25.0)
    parser.add_argument("--abort-mm", type=float, default=10.0)
    parser.add_argument("--warn-mm", type=float, default=7.0)
    parser.add_argument("--label", required=True, help="run label, e.g. phase1-linear")
    parser.add_argument("--output", default=None, help="dir (default data/<date>-<label>)")
    args = parser.parse_args()

    amps = [float(x) for x in args.amps.split(",")]
    if any(a > HARD_AMP_CEILING_V for a in amps):
        print(f"REFUSED: amplitude above {HARD_AMP_CEILING_V} V peak ceiling: {amps}")
        return 2
    directions = ["up", "down"] if args.directions == "both" else [args.directions]
    guard = DisplacementGuard(rest_mm=args.rest_mm, abort_excursion_mm=args.abort_mm,
                              warn_excursion_mm=args.warn_mm)
    outdir = Path(args.output or f"data/2026-07-22-{args.label}")
    outdir.mkdir(parents=True, exist_ok=True)

    run = {"args": {k: jsonable(v) for k, v in vars(args).items()}, "sweeps": []}
    stop_escalation = False

    with Device(args.host, args.port) as dev:
        try:
            status = dev.status()
            fs = float(status["sample_rate"])
            run["firmware"] = status.get("firmware")
            print(f"firmware {status.get('firmware')}  fs={fs}  label={args.label}")
            force_safe(dev)
            reset_diagnostics(dev)
            armed = require_armed_untripped(dev)
            print(f"armed safety=0b{int(armed['safety']):04b} laser={armed['laser']:.3f} mm")

            for amp in amps:
                if stop_escalation:
                    print(f"skip amp {amp} V (escalation stopped by earlier guard warn/abort)")
                    break
                for direction in directions:
                    freqs = frequency_grid(args.fmin, args.fmax, args.nsteps, direction)
                    print(f"\n== amp {amp:.4f} V ({amp*2:.3f} Vpp)  sweep {direction} "
                          f"{args.fmin}->{args.fmax} Hz x{args.nsteps} ==")
                    rows, raw, sweep_status = sweep_once(
                        dev, fs, amp, freqs, args.settle, args.capture, args.harmonics, guard)
                    raw_path = outdir / f"raw_amp{amp:.4f}_{direction}.npz"
                    save_raw(raw_path, list(freqs), raw)
                    run["sweeps"].append({
                        "amp_v": amp, "direction": direction, "status": sweep_status,
                        "raw": str(raw_path), "rows": rows,
                    })
                    if sweep_status in ("abort", "tripped"):
                        print(f"!! sweep {sweep_status}; stopping run")
                        stop_escalation = True
                        raise RigSafetyError(f"sweep {sweep_status} at amp {amp} V")
                    if sweep_status == "warn":
                        stop_escalation = True  # finish current amp's directions, then stop

            (outdir / f"{args.label}_summary.json").write_text(
                json.dumps(run, indent=2, sort_keys=True, default=jsonable) + "\n")
            print(f"\nsaved summary -> {outdir/f'{args.label}_summary.json'}")
            return 0
        except RigSafetyError as exc:
            print(f"ABORTED: {exc}")
            (outdir / f"{args.label}_summary.json").write_text(
                json.dumps(run, indent=2, sort_keys=True, default=jsonable) + "\n")
            return 1
        finally:
            force_safe(dev)
            final = snapshot(dev)
            print(f"safe: arm={final['arm']} safety=0b{int(final['safety']):04b} "
                  f"laser={final['laser']:.3f} mm")


if __name__ == "__main__":
    raise SystemExit(main())
