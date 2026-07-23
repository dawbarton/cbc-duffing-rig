#!/usr/bin/env python3
"""Closed-loop bring-up for CBC: velocity-feedback active-damping test.

Establishes that the feedback loop (PidController on the laser slot) is wired
with the stabilising sign and quantifies its effect, BEFORE any full CBC run.

Method (pure derivative feedback, Kp=Ki=0): the controller output is
    u = Kd * d/dt(reference - laser) = -Kd * d(laser)/dt   (reference constant),
i.e. velocity feedback that adds/removes damping.  For each test Kd we:
  1. open-loop excite the mode with a small sine burst at f0 (gains 0),
  2. set Kd (enable feedback) and cut the forcing simultaneously,
  3. capture the free decay and fit the closed-loop damping zeta_cl.
Stabilising sign => zeta_cl > open-loop zeta (faster decay); destabilising =>
slower decay or growth.

Safety: persistent armed session; host displacement guard; per-capture growth
check that aborts (gains->0, disarm) if the envelope grows; force_safe in
finally.  Kd magnitudes are CLI inputs; escalation stops on the first unstable
or guard event.
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
    require_armed_untripped,
    reset_diagnostics,
    set_sine_forcing,
    snapshot,
)


def set_gains(dev, kp, ki, kd):
    dev.set("ctrl_kp", float(kp))
    dev.set("ctrl_ki", float(ki))
    dev.set("ctrl_kd", float(kd))


def fit_zeta(laser, t, f0, fs, lo=0.15, hi=0.75):
    ac = laser - laser.mean()
    analytic = ac * np.exp(-1j * 2 * np.pi * f0 * t)
    win = max(1, int(round(fs / f0)))
    env = np.abs(np.convolve(analytic, np.ones(win) / win, mode="same"))
    a, b = int(lo * len(t)), int(hi * len(t))
    slope = np.polyfit(t[a:b], np.log(np.maximum(env[a:b], 1e-9)), 1)[0]
    zeta = -slope / (2 * np.pi * f0)
    # growth check: compare late vs early envelope medians
    early = np.median(env[a:(a + b) // 2])
    late = np.median(env[(a + b) // 2:b])
    return zeta, env, (late > 1.3 * early)  # True => growing => unstable


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default="192.168.1.235")
    p.add_argument("--port", type=int, default=protocol.CONTROL_PORT)
    p.add_argument("--f0", type=float, default=9.80)
    p.add_argument("--exc-amp", type=float, default=0.05, help="excitation burst peak V")
    p.add_argument("--kds", default="0.0,-0.002,0.002,-0.005,-0.01,-0.02",
                   help="comma list of Kd values to test (V per mm/s)")
    p.add_argument("--drive", type=float, default=6.0)
    p.add_argument("--decay", type=float, default=6.0)
    p.add_argument("--rest-mm", type=float, default=24.8)
    p.add_argument("--abort-mm", type=float, default=8.0)
    p.add_argument("--out", default="data/2026-07-23-cbc-bringup")
    args = p.parse_args()

    guard = DisplacementGuard(rest_mm=args.rest_mm, abort_excursion_mm=args.abort_mm)
    kds = [float(x) for x in args.kds.split(",")]
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    results = []

    with Device(args.host, args.port) as dev:
        try:
            fs = float(dev.status()["sample_rate"])
            force_safe(dev)
            set_gains(dev, 0, 0, 0)
            reset_diagnostics(dev)
            require_armed_untripped(dev)
            print(f"open-loop reference zeta ~ 0.0032 (Q~155). Testing Kd values: {kds}")

            for kd in kds:
                # 1. open-loop excite (gains 0)
                set_gains(dev, 0, 0, 0)
                set_sine_forcing(dev, args.f0, args.exc_amp)
                time.sleep(args.drive)
                # 2. enable feedback, cut forcing
                dev.set("ctrl_kd", float(kd))
                set_sine_forcing(dev, args.f0, 0.0)
                # 3. capture decay under feedback
                data, health = capture_checked(dev, ["laser", "out", "forcing"],
                                               seconds=args.decay)
                set_gains(dev, 0, 0, 0)  # feedback off between tests

                laser = np.asarray(data["laser"])
                idx = np.asarray(data["index"], float)
                t = (idx - idx[0]) / fs
                span = (float(laser.min()), float(laser.max()))
                verdict = guard.check(*span)
                zeta, env, growing = fit_zeta(laser, t, args.f0, fs)
                out_rms = float(np.sqrt(np.mean(np.asarray(data["out"]) ** 2)))
                tag = "STABILISING" if zeta > 0.0035 else ("~neutral" if zeta > 0.0028 else "DE-DAMPED")
                if growing:
                    tag = "UNSTABLE(growing)"
                print(f"  Kd={kd:+.4f}: zeta_cl={zeta:.5f}  span[{span[0]:.2f},{span[1]:.2f}] "
                      f"out_rms={out_rms*1e3:.1f}mV  {tag}  guard={verdict} safety=0b{int(health['safety']):04b}")
                results.append({"kd": kd, "zeta_cl": float(zeta), "span_mm": span,
                                "out_rms_v": out_rms, "growing": bool(growing),
                                "safety": int(health["safety"])})
                np.savez(outdir / f"decay_kd{kd:+.4f}.npz", index=idx, laser=laser,
                         out=np.asarray(data["out"]), env=env, t=t)

                if growing or verdict == "abort" or int(health["safety"]) & 0b0010:
                    raise RigSafetyError(f"unstable/guard at Kd={kd}: growing={growing} "
                                         f"verdict={verdict} safety=0b{int(health['safety']):04b}")

            (outdir / "bringup_summary.json").write_text(
                json.dumps({"f0": args.f0, "results": results}, indent=2) + "\n")
            print("bring-up complete")
            return 0
        except RigSafetyError as exc:
            print(f"ABORTED: {exc}")
            (outdir / "bringup_summary.json").write_text(
                json.dumps({"f0": args.f0, "results": results, "aborted": str(exc)},
                           indent=2) + "\n")
            return 1
        finally:
            set_gains(dev, 0, 0, 0)
            force_safe(dev)
            fin = snapshot(dev)
            print(f"safe: arm={fin['arm']} safety=0b{int(fin['safety']):04b} "
                  f"gains=0 laser={fin['laser']:.3f} mm")


if __name__ == "__main__":
    raise SystemExit(main())
