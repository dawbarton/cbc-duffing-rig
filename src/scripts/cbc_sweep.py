#!/usr/bin/env python3
"""Fixed-point control-based continuation (frequency-stepped) of the rig.

Robust CBC corrector that avoids the ill-conditioned 2D Newton: at each drive
frequency it drives the controller non-invasive by a damped fixed-point on the
reference,
    R <- R + alpha * (Rot(phi) X - R),
where X is the measured laser fundamental and phi is the firmware->projection
phase offset measured from the (known pure-sine) forcing.  On convergence the
control fundamental -> 0 and the measured orbit is the genuine open-loop forced
response, stabilised by the feedback (so branches an open-loop sweep would jump
are held).  Frequency is stepped (natural parameter), warm-starting each point
from the previous, sweeping down and/or up so the two folds and the stable
branches of the softening resonance are mapped without settling artefacts.

Note: frequency stepping recovers the two stable branches and brackets the
folds; the unstable middle branch needs amplitude-parameterised continuation
(separate). Safety: persistent armed session, host displacement guard,
force_safe in finally.
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
)

NCOEF = 33


def set_ref(dev, r0, a, b):
    c = [0.0] * NCOEF
    c[0] = float(r0); c[1] = float(a); c[17] = float(b)
    dev.set("target_coeffs", c)


def set_forcing(dev, F):
    c = [0.0] * NCOEF
    c[17] = float(F)
    dev.set("forcing_coeffs", c)


def rot(phi):
    c, s = np.cos(phi), np.sin(phi)
    return np.array([[c, -s], [s, c]])


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default="192.168.1.235")
    p.add_argument("--port", type=int, default=protocol.CONTROL_PORT)
    p.add_argument("--forcing", type=float, required=True, help="fixed forcing sine peak V")
    p.add_argument("--kp", type=float, default=-0.1)
    p.add_argument("--kd", type=float, default=-0.02)
    p.add_argument("--f-start", type=float, required=True)
    p.add_argument("--f-end", type=float, required=True)
    p.add_argument("--df", type=float, default=0.05, help="frequency step magnitude (Hz)")
    p.add_argument("--directions", default="both", choices=["down", "up", "both"])
    p.add_argument("--alpha", type=float, default=0.8, help="fixed-point damping")
    p.add_argument("--max-iter", type=int, default=30)
    p.add_argument("--tol", type=float, default=4e-3, help="|control| convergence (V)")
    p.add_argument("--settle0", type=float, default=3.0, help="settle after a freq change")
    p.add_argument("--settle", type=float, default=1.5, help="settle per fixed-point iter")
    p.add_argument("--capture", type=float, default=2.0)
    p.add_argument("--rest-mm", type=float, default=24.8)
    p.add_argument("--abort-mm", type=float, default=8.0)
    p.add_argument("--amp-max-mm", type=float, default=1.5)
    p.add_argument("--out", default="data/2026-07-23-cbc-sweep")
    args = p.parse_args()

    guard = DisplacementGuard(rest_mm=args.rest_mm, abort_excursion_mm=args.abort_mm)
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    def freqs_for(direction):
        n = int(abs(args.f_start - args.f_end) / args.df) + 1
        lo, hi = min(args.f_start, args.f_end), max(args.f_start, args.f_end)
        grid = np.linspace(lo, hi, n)
        return grid[::-1] if direction == "down" else grid

    directions = ["down", "up"] if args.directions == "both" else [args.directions]
    results = {"args": vars(args), "sweeps": []}

    with Device(args.host, args.port) as dev:
        try:
            fs = float(dev.status()["sample_rate"])
            force_safe(dev)
            dev.set("ctrl_ki", 0.0); dev.set("ctrl_kp", args.kp); dev.set("ctrl_kd", args.kd)
            r0 = float(np.mean(dev.capture(["laser"], seconds=0.5, port=0)["laser"]))
            set_forcing(dev, args.forcing)
            reset_diagnostics(dev)
            require_armed_untripped(dev)
            print(f"CBC sweep: forcing={args.forcing}V kp={args.kp} kd={args.kd} r0={r0:.3f}")

            def converge(omega, R):
                """Damped fixed-point at omega; returns (R, X, ctrl, iters, ok, span)."""
                first = True
                for it in range(args.max_iter):
                    set_ref(dev, r0, R[0], R[1])
                    dev.set("freq", float(omega))
                    time.sleep(args.settle0 if first else args.settle)
                    first = False
                    data, health = capture_checked(dev, ["laser", "out", "forcing"], seconds=args.capture)
                    if int(health["safety"]) & 0b0010:
                        raise RigSafetyError(f"trip at {omega:.3f} safety=0b{int(health['safety']):04b}")
                    idx = np.asarray(data["index"], float)
                    laser = np.asarray(data["laser"])
                    span = (float(laser.min()), float(laser.max()))
                    if guard.check(*span) == "abort":
                        raise RigSafetyError(f"guard abort at {omega:.3f} span={span}")
                    lh = project_harmonics(laser, idx, omega, fs, 3)
                    X = np.array([lh["a"][0], lh["b"][0]])
                    ctrl = np.asarray(data["out"]) - np.asarray(data["forcing"])
                    ch = project_harmonics(ctrl, idx, omega, fs, 1)
                    fh = project_harmonics(np.asarray(data["forcing"]), idx, omega, fs, 1)
                    cmag = float(np.hypot(ch["a"][0], ch["b"][0]))
                    if cmag < args.tol:
                        return R, X, cmag, it + 1, True, span, float(lh["amp"][2])
                    phi = np.arctan2(fh["a"][0], fh["b"][0])
                    R = R + args.alpha * (rot(phi) @ X - R)
                return R, X, cmag, args.max_iter, False, span, float(lh["amp"][2])

            for direction in directions:
                grid = freqs_for(direction)
                print(f"\n== sweep {direction}: {grid[0]:.2f} -> {grid[-1]:.2f} Hz, {len(grid)} steps ==")
                R = np.array([0.0, 0.0])
                rows = []
                for omega in grid:
                    R, X, cmag, its, ok, span, X3 = converge(omega, R)
                    amp = float(np.hypot(*X))
                    rows.append({"omega": float(omega), "amp": amp, "ctrl": cmag,
                                 "a1": float(R[0]), "b1": float(R[1]), "X3": X3,
                                 "iters": its, "converged": ok, "span": span})
                    print(f"  f={omega:.3f} amp={amp*1e3:6.1f}um ctrl={cmag*1e3:5.2f}mV "
                          f"its={its:2d} {'OK' if ok else '--'} span[{span[0]:.2f},{span[1]:.2f}]")
                    if amp > args.amp_max_mm:
                        print("  amplitude bound reached; stopping sweep"); break
                results["sweeps"].append({"direction": direction, "rows": rows})
                (outdir / "cbc_sweep.json").write_text(json.dumps(results, indent=2) + "\n")
                # reset reference between directions
                set_ref(dev, r0, 0.0, 0.0)

            (outdir / "cbc_sweep.json").write_text(json.dumps(results, indent=2) + "\n")
            print(f"\nCBC sweep done -> {outdir/'cbc_sweep.json'}")
            return 0
        except RigSafetyError as exc:
            print(f"ABORTED: {exc}")
            (outdir / "cbc_sweep.json").write_text(json.dumps(results, indent=2) + "\n")
            return 1
        finally:
            dev.set("ctrl_kp", 0.0); dev.set("ctrl_kd", 0.0)
            force_safe(dev)
            fin = snapshot(dev)
            print(f"safe: arm={fin['arm']} safety=0b{int(fin['safety']):04b} gains=0 laser={fin['laser']:.3f}")


if __name__ == "__main__":
    raise SystemExit(main())
