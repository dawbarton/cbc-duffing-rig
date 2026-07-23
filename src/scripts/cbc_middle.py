#!/usr/bin/env python3
"""Amplitude-controlled CBC: trace the full S-curve incl. the UNSTABLE middle
branch of a fold.

Frequency stepping only reaches the stable branches (frequency is non-monotonic
across a fold). Here the continuation parameter is the response AMPLITUDE A,
which IS monotonic along the whole S-curve, so sweeping A traces lower -> middle
-> upper continuously. A is an externally imposed reference magnitude (a stable
knob), so the otherwise-unstable middle-branch orbit is reachable; the feedback
stabilises it and the corrector makes it non-invasive.

At each target A:
  inner (phase tracking): set reference = A * unit(response phase), a few iters
    so the reference amplitude is A and its phase follows the measured response;
  outer (secant on omega): find the drive frequency where the resulting response
    magnitude equals A -> then reference == response -> control ~ 0 (non-invasive).

Safety: persistent armed session, host displacement guard, force_safe in finally.
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
    p.add_argument("--forcing", type=float, required=True)
    p.add_argument("--kp", type=float, default=-0.12)
    p.add_argument("--kd", type=float, default=-0.025)
    p.add_argument("--a-start", type=float, required=True, help="start amplitude (mm)")
    p.add_argument("--a-end", type=float, required=True, help="end amplitude (mm)")
    p.add_argument("--da", type=float, default=0.02, help="amplitude step (mm)")
    p.add_argument("--omega0", type=float, required=True, help="initial frequency guess (Hz)")
    p.add_argument("--inner", type=int, default=4, help="phase-tracking iters per omega eval")
    p.add_argument("--secant-iters", type=int, default=6)
    p.add_argument("--secant-tol", type=float, default=0.004, help="|amp-A|/A tol")
    p.add_argument("--dw", type=float, default=0.02, help="secant initial freq perturbation")
    p.add_argument("--settle0", type=float, default=2.5)
    p.add_argument("--settle", type=float, default=1.2)
    p.add_argument("--capture", type=float, default=2.0)
    p.add_argument("--rest-mm", type=float, default=24.8)
    p.add_argument("--abort-mm", type=float, default=9.0)
    p.add_argument("--out", default="data/2026-07-23-cbc-middle")
    args = p.parse_args()

    guard = DisplacementGuard(rest_mm=args.rest_mm, abort_excursion_mm=args.abort_mm)
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    rows = []

    with Device(args.host, args.port) as dev:
        try:
            fs = float(dev.status()["sample_rate"])
            force_safe(dev)
            dev.set("ctrl_ki", 0.0); dev.set("ctrl_kp", args.kp); dev.set("ctrl_kd", args.kd)
            r0 = float(np.mean(dev.capture(["laser"], seconds=0.5, port=0)["laser"]))
            set_forcing(dev, args.forcing)
            reset_diagnostics(dev)
            require_armed_untripped(dev)
            print(f"CBC middle: forcing={args.forcing}V kp={args.kp} kd={args.kd} r0={r0:.3f}")

            phase_state = {"ang": np.pi / 2}  # response phase estimate (proj basis)

            def eval_at(omega, A, first=False):
                """Phase-tracking inner loop at fixed omega, reference magnitude A.
                Returns (|X|, control_mag, X_vec)."""
                Xv = np.array([0.0, A])
                for i in range(args.inner):
                    # reference target in projection basis: A at current phase
                    T = A * np.array([np.cos(phase_state["ang"]), np.sin(phase_state["ang"])])
                    # need firmware-basis coeffs; phi from forcing projection
                    dev.set("freq", float(omega))
                    # command R = Rot(phi) T  (phi measured below); first pass uses last phi
                    R = rot(phase_state.get("phi", 0.0)) @ T
                    set_ref(dev, r0, R[0], R[1])
                    time.sleep(args.settle0 if (first and i == 0) else args.settle)
                    data, health = capture_checked(dev, ["laser", "out", "forcing"], seconds=args.capture)
                    if int(health["safety"]) & 0b0010:
                        raise RigSafetyError(f"trip at {omega:.3f}")
                    idx = np.asarray(data["index"], float)
                    laser = np.asarray(data["laser"])
                    span = (float(laser.min()), float(laser.max()))
                    if guard.check(*span) == "abort":
                        raise RigSafetyError(f"guard abort at {omega:.3f} span={span}")
                    lh = project_harmonics(laser, idx, omega, fs, 1)
                    fh = project_harmonics(np.asarray(data["forcing"]), idx, omega, fs, 1)
                    ctrl = np.asarray(data["out"]) - np.asarray(data["forcing"])
                    ch = project_harmonics(ctrl, idx, omega, fs, 1)
                    Xv = np.array([lh["a"][0], lh["b"][0]])
                    phase_state["ang"] = float(np.arctan2(Xv[1], Xv[0]))
                    phase_state["phi"] = float(np.arctan2(fh["a"][0], fh["b"][0]))
                    cmag = float(np.hypot(ch["a"][0], ch["b"][0]))
                    phase_state["span"] = span
                return float(np.hypot(*Xv)), cmag, Xv

            # amplitude continuation
            A = args.a_start
            omega = args.omega0
            direction = 1 if args.a_end > args.a_start else -1
            first = True
            while (direction > 0 and A <= args.a_end) or (direction < 0 and A >= args.a_end):
                # secant on omega so that |X(omega)| = A
                w0 = omega
                amp0, c0, _ = eval_at(w0, A, first=first)
                first = False
                w1 = omega + args.dw
                amp1, c1, _ = eval_at(w1, A)
                converged = False
                for _s in range(args.secant_iters):
                    if abs(amp1 - amp0) < 1e-6:
                        break
                    w2 = w1 - (amp1 - A) * (w1 - w0) / (amp1 - amp0)
                    w2 = float(np.clip(w2, 9.0, 10.6))
                    amp2, c2, Xv = eval_at(w2, A)
                    w0, amp0 = w1, amp1
                    w1, amp1, c1 = w2, amp2, c2
                    if abs(amp1 - A) / A < args.secant_tol:
                        converged = True
                        break
                omega = w1
                rows.append({"A_mm": A, "omega": omega, "amp": amp1, "ctrl": c1,
                             "converged": bool(converged), "span": phase_state.get("span")})
                print(f"  A={A*1e3:6.1f}um -> f={omega:.3f}Hz amp={amp1*1e3:6.1f}um "
                      f"ctrl={c1*1e3:5.2f}mV {'OK' if converged else '--'}")
                (outdir / "cbc_middle.json").write_text(json.dumps(
                    {"args": vars(args), "r0": r0, "rows": rows}, indent=2) + "\n")
                A += direction * args.da

            print(f"CBC middle done -> {outdir/'cbc_middle.json'}")
            return 0
        except RigSafetyError as exc:
            print(f"ABORTED: {exc}")
            (outdir / "cbc_middle.json").write_text(json.dumps({"rows": rows, "aborted": str(exc)}, indent=2) + "\n")
            return 1
        finally:
            dev.set("ctrl_kp", 0.0); dev.set("ctrl_kd", 0.0)
            force_safe(dev)
            fin = snapshot(dev)
            print(f"safe: arm={fin['arm']} safety=0b{int(fin['safety']):04b} gains=0 laser={fin['laser']:.3f}")


if __name__ == "__main__":
    raise SystemExit(main())
