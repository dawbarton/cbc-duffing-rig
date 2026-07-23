#!/usr/bin/env python3
"""Control-based continuation (CBC) of the forced frequency response.

Traces the periodic-orbit branch of the rig at FIXED external forcing, using the
closed-loop PID controller (feedback on the laser) to stabilise the orbit and a
non-invasiveness corrector to recover the genuine open-loop response — including
the unstable middle branch and the two saddle-node folds that an open-loop sweep
would jump across.

Method (fundamental harmonic, H=1):
  unknowns  u = (omega, a1, b1)  -- drive frequency and reference cos/sin
  reference r(t) = r0 + a1 cos(wt) + b1 sin(wt)   (r0 = operating point, fixed)
  external forcing = fixed sine (forcing_coeffs), the excitation level
  control   u_ctrl = Kp(r - x) + Kd d/dt(r - x),  Kp,Kd < 0 (stabilising)
  measure   X = (Xa1, Xb1) = laser response fundamental (cos, sin)
  residual  G(u) = X - (a1, b1) = 0   <=>  x = r  <=>  control non-invasive
Continuation: pseudo-arclength in scaled u so the branch is followed around
folds where frequency is not monotonic.

Safety: persistent armed session; host displacement guard; per-evaluation growth
/ trip / guard checks that abort to a safe state (gains 0, forcing 0, disarm);
force_safe in finally.  Gains/forcing/limits are CLI inputs (AGENTS.md is the
source of truth for amplitude limits).
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

NCOEF = 33  # [mean, a1..a16, b1..b16]
HALF = 16


def set_reference(dev, r0, a1, b1):
    c = [0.0] * NCOEF
    c[0] = float(r0)
    c[1] = float(a1)          # a1 (cos fundamental)
    c[1 + HALF] = float(b1)   # b1 (sin fundamental)
    dev.set("target_coeffs", c)


def set_forcing_fundamental(dev, fb1):
    c = [0.0] * NCOEF
    c[1 + HALF] = float(fb1)  # forcing as a sine on the fundamental
    dev.set("forcing_coeffs", c)


class CBCRig:
    """Wraps residual evaluation (set reference, settle, capture, project)."""

    def __init__(self, dev, fs, r0, settle, capture_s, guard, n_project=3):
        self.dev, self.fs, self.r0 = dev, fs, r0
        self.settle, self.capture_s, self.guard = settle, capture_s, guard
        self.n_project = n_project
        self.evals = 0

    def response(self, omega, a1, b1):
        """Return dict with measured fundamental X, control invasiveness, amp."""
        self.dev.set("freq", float(omega))
        set_reference(self.dev, self.r0, a1, b1)
        time.sleep(self.settle)
        data, health = capture_checked(
            self.dev, ["laser", "out", "forcing", "error"], seconds=self.capture_s)
        self.evals += 1
        idx = np.asarray(data["index"], float)
        laser = np.asarray(data["laser"])
        span = (float(laser.min()), float(laser.max()))
        verdict = self.guard.check(*span)
        lh = project_harmonics(laser, idx, omega, self.fs, self.n_project)
        # Residual is the CONTROL fundamental (out - forcing, table off). Driving
        # it to zero IS non-invasiveness, and it is basis-self-consistent: the
        # firmware reference phase is continuous across frequency changes, so the
        # projection basis need not match it (the FD Jacobian absorbs the fixed
        # rotation between the reference knobs and the projected control).
        ctrl = np.asarray(data["out"]) - np.asarray(data["forcing"])
        ch = project_harmonics(ctrl, idx, omega, self.fs, 1)
        Xa1 = float(lh["a"][0])
        Xb1 = float(lh["b"][0])
        amp = float(np.hypot(Xa1, Xb1))  # physical laser fundamental amplitude
        return {
            "Xa1": Xa1, "Xb1": Xb1, "amp": amp,
            "X3": float(lh["amp"][2]) if self.n_project >= 3 else 0.0,
            "ctrl_a1": float(ch["a"][0]), "ctrl_b1": float(ch["b"][0]),
            "ctrl_fund": float(ch["amp"][0]),
            "span": span, "verdict": verdict,
            "safety": int(health["safety"]),
        }

    def residual(self, u):
        """G(u) = control fundamental (cos, sin) for u=(omega,a1,b1); ->0 is
        non-invasive. Returns (G, meta)."""
        omega, a1, b1 = u
        m = self.response(omega, a1, b1)
        if m["verdict"] == "abort" or (m["safety"] & 0b0010):
            raise RigSafetyError(
                f"guard/trip at u=({omega:.3f},{a1:.4f},{b1:.4f}) "
                f"span={m['span']} safety=0b{m['safety']:04b}")
        G = np.array([m["ctrl_a1"], m["ctrl_b1"]])
        return G, m


def fd_jacobian(rig, u, G0, scale, h=(0.02, 0.005, 0.005)):
    """Finite-difference dG/du (2x3). h in (Hz, mm, mm)."""
    J = np.zeros((2, 3))
    for j in range(3):
        du = np.zeros(3)
        du[j] = h[j]
        Gp, _ = rig.residual(u + du)
        J[:, j] = (Gp - G0) / h[j]
    return J


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default="192.168.1.235")
    p.add_argument("--port", type=int, default=protocol.CONTROL_PORT)
    p.add_argument("--forcing", type=float, required=True, help="fixed forcing sine peak V")
    p.add_argument("--kp", type=float, default=-0.1, help="ctrl_kp (V/mm, <0)")
    p.add_argument("--kd", type=float, default=-0.02, help="ctrl_kd (V/(mm/s), <0)")
    p.add_argument("--f-start", type=float, default=10.4, help="start frequency (Hz)")
    p.add_argument("--df0", type=float, default=-0.1, help="initial freq step for 2nd point")
    p.add_argument("--ds", type=float, default=0.15, help="arclength step (scaled units)")
    p.add_argument("--max-points", type=int, default=40)
    p.add_argument("--f-min", type=float, default=9.2)
    p.add_argument("--f-max", type=float, default=10.6)
    p.add_argument("--amp-max-mm", type=float, default=1.5, help="stop if reference amp exceeds")
    p.add_argument("--settle", type=float, default=4.0)
    p.add_argument("--capture", type=float, default=2.0)
    p.add_argument("--tol", type=float, default=3e-3, help="|G| convergence tol (mm)")
    p.add_argument("--max-corr", type=int, default=6)
    p.add_argument("--s-omega", type=float, default=1.0, help="freq scale (Hz)")
    p.add_argument("--s-amp", type=float, default=0.1, help="amplitude scale (mm)")
    p.add_argument("--rest-mm", type=float, default=24.8)
    p.add_argument("--abort-mm", type=float, default=8.0)
    p.add_argument("--single", action="store_true", help="just correct at f-start and exit")
    p.add_argument("--verbose", action="store_true", help="print corrector iterations")
    p.add_argument("--out", default="data/2026-07-23-cbc")
    args = p.parse_args()

    guard = DisplacementGuard(rest_mm=args.rest_mm, abort_excursion_mm=args.abort_mm)
    S = np.array([args.s_omega, args.s_amp, args.s_amp])  # scaling for arclength
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    branch = []

    with Device(args.host, args.port) as dev:
        try:
            fs = float(dev.status()["sample_rate"])
            force_safe(dev)
            # operating point = current laser mean
            base = dev.capture(["laser"], seconds=0.5, port=0)
            r0 = float(np.mean(base["laser"]))
            # controller gains + fixed forcing
            dev.set("ctrl_ki", 0.0)
            dev.set("ctrl_kp", args.kp)
            dev.set("ctrl_kd", args.kd)
            set_forcing_fundamental(dev, args.forcing)
            reset_diagnostics(dev)
            require_armed_untripped(dev)
            print(f"CBC: forcing={args.forcing:.3f}V kp={args.kp} kd={args.kd} r0={r0:.3f}mm "
                  f"f_start={args.f_start}")

            rig = CBCRig(dev, fs, r0, args.settle, args.capture, guard)

            def correct(u0, constraint, J2_init=None):
                """Broyden corrector with backtracking. constraint(u)->(val,grad3).

                Extended residual H = [G_control(2); constraint(1)]. The 2x3
                control-Jacobian J2 is FD-seeded on the first call and carried in
                thereafter (Broyden-updated), so continuation points skip the
                3-eval FD rebuild. Regularised lstsq solve + halving line search
                that never accepts a step increasing |H| (robust to the
                ill-conditioned, nonlinear control map). Returns the final J2 too.
                """
                u = np.array(u0, float)
                G0, meta = rig.residual(u)
                if J2_init is None:
                    J2 = fd_jacobian(rig, u, G0, S)      # dG/du (2x3), cold start
                else:
                    J2 = J2_init.copy()
                cval, cgrad = constraint(u)
                B = np.vstack([J2, cgrad])               # 3x3 extended Jacobian
                H = np.array([G0[0], G0[1], cval])
                if args.verbose:
                    print(f"    init |G|={np.hypot(*G0)*1e3:.2f}mV cond={np.linalg.cond(B):.1f}")
                for it in range(args.max_corr):
                    du = np.linalg.lstsq(B, -H, rcond=1e-6)[0]
                    Hnorm = np.linalg.norm(H)
                    step = 1.0
                    for _ls in range(4):                 # backtracking line search
                        un = u + step * du
                        Gn, mn = rig.residual(un)
                        cvn, cgn = constraint(un)
                        Hn = np.array([Gn[0], Gn[1], cvn])
                        if np.linalg.norm(Hn) < Hnorm:
                            break
                        step *= 0.5
                    dU = un - u
                    dH = Hn - H
                    denom = dU @ dU
                    if denom > 0:                        # Broyden rank-1 update
                        B = B + np.outer((dH - B @ dU), dU) / denom
                    B[2] = cgn                           # keep constraint row exact
                    u, H, G0, meta = un, Hn, Gn, mn
                    nrm = np.hypot(G0[0], G0[1])
                    if args.verbose:
                        print(f"    it{it}: |G|={nrm*1e3:.2f}mV step={step:.2f} "
                              f"u=({u[0]:.3f},{u[1]*1e3:.1f},{u[2]*1e3:.1f})um "
                              f"amp={meta['amp']*1e3:.1f}um")
                    if nrm < args.tol and abs(H[2]) < args.tol:
                        return u, meta, True, it + 1, B[:2].copy()
                return u, meta, False, args.max_corr, B[:2].copy()

            # --- first point: fix frequency (natural parameter) ---
            u = np.array([args.f_start, 0.02, -0.05])  # small ref guess
            f_fixed = [args.f_start]
            u, meta, ok, its, J2 = correct(
                u, lambda uu: (uu[0] - f_fixed[0], np.array([1.0, 0.0, 0.0])))
            print(f"  P0 f={u[0]:.3f} amp={meta['amp']*1e3:.1f}um ctrl_fund={meta['ctrl_fund']*1e3:.2f}mV "
                  f"conv={ok}({its}) X3/X1={meta['X3']/max(meta['amp'],1e-9):.3f}")
            branch.append(dict(omega=u[0], a1=u[1], b1=u[2], **meta))
            if args.single or not ok:
                raise SystemExit(0 if ok else 1)

            # --- second point: shift frequency, correct at fixed freq ---
            f_fixed[0] = args.f_start + args.df0
            u2 = u + np.array([args.df0, 0, 0])
            u2, meta, ok, its, J2 = correct(
                u2, lambda uu: (uu[0] - f_fixed[0], np.array([1.0, 0.0, 0.0])), J2_init=J2)
            print(f"  P1 f={u2[0]:.3f} amp={meta['amp']*1e3:.1f}um conv={ok}({its})")
            branch.append(dict(omega=u2[0], a1=u2[1], b1=u2[2], **meta))
            u_prev, u_cur = u.copy(), u2.copy()

            # --- pseudo-arclength continuation ---
            for k in range(args.max_points):
                t = (u_cur - u_prev) / S            # secant tangent (scaled)
                t = t / np.linalg.norm(t)
                u_pred = u_cur + args.ds * S * t     # predictor (unscaled step)

                def arclength(uu, t=t, u_c=u_cur):
                    d = (uu - u_c) / S
                    return (t @ d - args.ds, t / S)

                u_new, meta, ok, its, J2 = correct(u_pred, arclength, J2_init=J2)
                amp = meta["amp"]
                print(f"  P{k+2} f={u_new[0]:.3f} amp={amp*1e3:.1f}um "
                      f"ctrl={meta['ctrl_fund']*1e3:.2f}mV conv={ok}({its}) "
                      f"evals={rig.evals} span[{meta['span'][0]:.2f},{meta['span'][1]:.2f}]")
                branch.append(dict(omega=u_new[0], a1=u_new[1], b1=u_new[2], **meta))
                if not ok:
                    print("  corrector failed to converge; stopping")
                    break
                if amp > args.amp_max_mm or not (args.f_min <= u_new[0] <= args.f_max):
                    print("  reached amplitude/frequency bound; stopping")
                    break
                u_prev, u_cur = u_cur, u_new
                # periodically persist
                (outdir / "cbc_branch.json").write_text(json.dumps(
                    {"args": vars(args), "r0": r0, "branch": branch}, indent=2,
                    default=lambda o: float(o) if isinstance(o, np.generic) else o) + "\n")

            (outdir / "cbc_branch.json").write_text(json.dumps(
                {"args": vars(args), "r0": r0, "branch": branch}, indent=2,
                default=lambda o: float(o) if isinstance(o, np.generic) else o) + "\n")
            print(f"CBC done: {len(branch)} points, {rig.evals} evaluations")
            return 0
        except (RigSafetyError, SystemExit) as exc:
            if isinstance(exc, SystemExit):
                raise
            print(f"ABORTED: {exc}")
            (outdir / "cbc_branch.json").write_text(json.dumps(
                {"branch": branch, "aborted": str(exc)}, indent=2,
                default=lambda o: float(o) if isinstance(o, np.generic) else o) + "\n")
            return 1
        finally:
            dev.set("ctrl_kp", 0.0)
            dev.set("ctrl_kd", 0.0)
            force_safe(dev)
            fin = snapshot(dev)
            print(f"safe: arm={fin['arm']} safety=0b{int(fin['safety']):04b} "
                  f"gains=0 laser={fin['laser']:.3f} mm")


if __name__ == "__main__":
    raise SystemExit(main())
