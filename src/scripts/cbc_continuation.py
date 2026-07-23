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


def fd_jacobian_v(rig, u, G0, S, hv=(0.02, 0.05, 0.05)):
    """Finite-difference dG/dv where v = u/S (scaled). Returns 2x3.

    Working in scaled coordinates makes the omega and amplitude columns
    comparable in magnitude, which removes the column-scaling ill-conditioning
    of the raw (V/Hz vs V/mm) Jacobian. hv steps are in scaled units
    (0.02 -> 0.02 Hz; 0.05 -> 0.05*S_amp mm).
    """
    J = np.zeros((2, 3))
    for j in range(3):
        du = np.zeros(3)
        du[j] = S[j] * hv[j]
        Gp, _ = rig.residual(u + du)
        J[:, j] = (Gp - G0) / hv[j]
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
    p.add_argument("--ds-min", type=float, default=0.03, help="min arclength step before giving up")
    p.add_argument("--max-points", type=int, default=40)
    p.add_argument("--f-min", type=float, default=9.2)
    p.add_argument("--f-max", type=float, default=10.6)
    p.add_argument("--amp-max-mm", type=float, default=1.5, help="stop if reference amp exceeds")
    p.add_argument("--settle", type=float, default=4.0)
    p.add_argument("--capture", type=float, default=2.0)
    p.add_argument("--tol", type=float, default=3e-3, help="|G| convergence tol (mm)")
    p.add_argument("--max-corr", type=int, default=6)
    p.add_argument("--trust", type=float, default=0.3, help="trust-region cap on scaled step norm")
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

            def correct(u0, constraint, Jv_init=None):
                """Robust Gauss-Newton corrector in SCALED coordinates v=u/S.

                constraint(u) -> (value, grad_v[3]) with grad w.r.t. v. Extended
                residual H = [G_control(2, V); constraint(1)]. The 2x3 scaled
                control-Jacobian dG/dv is recomputed by FD each iteration (no
                Broyden drift), the step is a pseudo-inverse (regularised lstsq)
                solve trust-region-limited to ||dv|| <= trust, and a halving line
                search never accepts a step increasing |H|. This handles the
                weakly-observable reference-phase (gauge) direction: the
                pseudo-inverse moves in the well-determined amplitude/frequency
                direction and ignores the degenerate one. Jv_init is unused
                (kept for call-site compatibility)."""
                u = np.array(u0, float)
                G0, meta = rig.residual(u)
                cval, _ = constraint(u)
                H = np.array([G0[0], G0[1], cval])
                for it in range(args.max_corr):
                    if np.hypot(G0[0], G0[1]) < args.tol and abs(cval) < args.tol:
                        return u, meta, True, it, None
                    Jv = fd_jacobian_v(rig, u, G0, S)     # fresh FD each iteration
                    _, cgrad = constraint(u)
                    B = np.vstack([Jv, cgrad])
                    dv = np.linalg.lstsq(B, -H, rcond=1e-3)[0]  # regularised
                    nd = np.linalg.norm(dv)
                    if nd > args.trust:                   # trust-region cap
                        dv = dv * (args.trust / nd)
                    Hnorm = np.linalg.norm(H)
                    step = 1.0
                    un, Gn, mn, cvn = u, G0, meta, cval
                    for _ls in range(5):                  # backtracking line search
                        cand = u + step * (S * dv)
                        Gc, mc = rig.residual(cand)
                        cvc, _ = constraint(cand)
                        if np.linalg.norm([Gc[0], Gc[1], cvc]) < Hnorm:
                            un, Gn, mn, cvn = cand, Gc, mc, cvc
                            break
                        step *= 0.5
                    u, G0, meta, cval = un, Gn, mn, cvn
                    H = np.array([G0[0], G0[1], cval])
                    if args.verbose:
                        print(f"    it{it}: |G|={np.hypot(G0[0],G0[1])*1e3:.2f}mV step={step:.2f} "
                              f"u=({u[0]:.3f},{u[1]*1e3:.1f},{u[2]*1e3:.1f})um "
                              f"amp={meta['amp']*1e3:.1f}um cond={np.linalg.cond(B):.0f}")
                ok = np.hypot(G0[0], G0[1]) < args.tol and abs(cval) < args.tol
                return u, meta, ok, args.max_corr, None

            def persist():
                (outdir / "cbc_branch.json").write_text(json.dumps(
                    {"args": vars(args), "r0": r0, "branch": branch}, indent=2,
                    default=lambda o: float(o) if isinstance(o, np.generic) else o) + "\n")

            def fix_freq(target):  # constraint: omega = target; grad_v = [S0,0,0]
                return lambda uu: (uu[0] - target, np.array([S[0], 0.0, 0.0]))

            # --- first point: fix frequency (natural parameter) ---
            u = np.array([args.f_start, 0.02, -0.05])  # small ref guess
            u, meta, ok, its, Jv = correct(u, fix_freq(args.f_start))
            print(f"  P0 f={u[0]:.3f} amp={meta['amp']*1e3:.1f}um ctrl_fund={meta['ctrl_fund']*1e3:.2f}mV "
                  f"conv={ok}({its}) X3/X1={meta['X3']/max(meta['amp'],1e-9):.3f}")
            branch.append(dict(omega=u[0], a1=u[1], b1=u[2], **meta))
            persist()
            if args.single or not ok:
                raise SystemExit(0 if ok else 1)

            # --- second point: shift frequency, correct at fixed freq ---
            u2 = u + np.array([args.df0, 0, 0])
            u2, meta, ok, its, Jv = correct(u2, fix_freq(args.f_start + args.df0), Jv_init=Jv)
            print(f"  P1 f={u2[0]:.3f} amp={meta['amp']*1e3:.1f}um conv={ok}({its})")
            branch.append(dict(omega=u2[0], a1=u2[1], b1=u2[2], **meta))
            persist()
            u_prev, u_cur = u.copy(), u2.copy()

            # --- pseudo-arclength continuation with adaptive step ---
            ds = args.ds
            k = 0
            while k < args.max_points:
                t = (u_cur - u_prev) / S            # secant tangent (scaled)
                t = t / np.linalg.norm(t)

                def arclength(uu, t=t, u_c=u_cur, dsl=ds):
                    d = (uu - u_c) / S
                    return (t @ d - dsl, t.copy())   # grad w.r.t. v is the tangent

                u_pred = u_cur + ds * (S * t)        # predictor
                u_new, meta, ok, its, Jvn = correct(u_pred, arclength, Jv_init=Jv)
                amp = meta["amp"]
                if not ok:
                    if ds > args.ds_min + 1e-9:      # adaptive: shrink and retry
                        ds = max(args.ds_min, ds * 0.5)
                        print(f"  P{k+2} no-converge (ctrl={meta['ctrl_fund']*1e3:.1f}mV); "
                              f"retry ds={ds:.3f} with fresh Jacobian")
                        Jv = None                    # force FD rebuild on retry
                        continue
                    print("  corrector failed at min ds; stopping")
                    break
                Jv = Jvn
                print(f"  P{k+2} f={u_new[0]:.3f} amp={amp*1e3:.1f}um "
                      f"ctrl={meta['ctrl_fund']*1e3:.2f}mV conv={ok}({its}) ds={ds:.3f} "
                      f"evals={rig.evals} span[{meta['span'][0]:.2f},{meta['span'][1]:.2f}]")
                branch.append(dict(omega=u_new[0], a1=u_new[1], b1=u_new[2], ds=ds, **meta))
                persist()
                if amp > args.amp_max_mm or not (args.f_min <= u_new[0] <= args.f_max):
                    print("  reached amplitude/frequency bound; stopping")
                    break
                u_prev, u_cur = u_cur, u_new
                if its <= 3 and ds < args.ds:        # speed up on easy points
                    ds = min(args.ds, ds * 1.4)
                k += 1

            persist()
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
