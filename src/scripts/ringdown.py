#!/usr/bin/env python3
"""Free-decay (ring-down) damping measurement for the CBC Duffing rig.

Drives a sine at (near) resonance to steady state, cuts the forcing, and
captures the free decay of the laser.  The damped natural frequency and the
damping ratio are extracted by complex demodulation: multiply the AC signal by
exp(-i 2*pi f0 t), low-pass over one period to get the complex envelope, and
fit log|envelope| linearly in time (slope = -zeta * 2*pi*f0).

This gives zeta / Q directly, without a fine frequency sweep, and — crucially —
tells us the settling time (~ a few / (zeta*2*pi*f0)) needed for artefact-free
stepped-sine sweeps.  Safe: small amplitude, persistent armed session, host
displacement guard, force_safe in finally.
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


def demod_decay(ac, t, f0, fs):
    """Complex-demodulate at f0, return (env_time, log_env, fd_hz)."""
    analytic = ac * np.exp(-1j * 2 * np.pi * f0 * t)
    win = max(1, int(round(fs / f0)))  # one-period moving average (low-pass)
    kernel = np.ones(win) / win
    env = np.convolve(analytic, kernel, mode="same")
    mag = np.abs(env)
    # instantaneous frequency from the demodulated phase slope -> fd offset
    phase = np.unwrap(np.angle(env))
    return mag, phase


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default="192.168.1.235")
    p.add_argument("--port", type=int, default=protocol.CONTROL_PORT)
    p.add_argument("--f0", type=float, default=9.81, help="drive freq near resonance (Hz)")
    p.add_argument("--amp", type=float, default=0.05, help="logical peak volts")
    p.add_argument("--drive", type=float, default=6.0, help="drive-to-steady-state seconds")
    p.add_argument("--decay", type=float, default=6.0, help="free-decay capture seconds")
    p.add_argument("--rest-mm", type=float, default=24.73)
    p.add_argument("--abort-mm", type=float, default=10.0)
    p.add_argument("--fit-lo", type=float, default=0.1, help="fit window start frac of decay")
    p.add_argument("--fit-hi", type=float, default=0.7, help="fit window end frac of decay")
    p.add_argument("--out", default="data/2026-07-23-ringdown")
    args = p.parse_args()

    guard = DisplacementGuard(rest_mm=args.rest_mm, abort_excursion_mm=args.abort_mm)
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    with Device(args.host, args.port) as dev:
        try:
            fs = float(dev.status()["sample_rate"])
            force_safe(dev)
            reset_diagnostics(dev)
            require_armed_untripped(dev)

            print(f"driving {args.amp*2:.3f} Vpp @ {args.f0} Hz for {args.drive}s to steady state")
            set_sine_forcing(dev, args.f0, args.amp)
            time.sleep(args.drive)
            # cut forcing, then capture the decay as fast as possible after
            set_sine_forcing(dev, args.f0, 0.0)  # zero amplitude, keep freq
            data, health = capture_checked(dev, ["laser", "forcing", "out"], seconds=args.decay)

            idx = np.asarray(data["index"], dtype=float)
            t = (idx - idx[0]) / fs
            laser = np.asarray(data["laser"])
            span = (float(laser.min()), float(laser.max()))
            if guard.check(*span) == "abort":
                raise RigSafetyError(f"displacement guard abort during decay: {span}")
            ac = laser - laser.mean()
            mag, phase = demod_decay(ac, t, args.f0, fs)

            lo = int(args.fit_lo * len(t))
            hi = int(args.fit_hi * len(t))
            tf, lm = t[lo:hi], np.log(np.maximum(mag[lo:hi], 1e-9))
            slope, intercept = np.polyfit(tf, lm, 1)
            # slope = -zeta*2*pi*f0
            zeta = -slope / (2 * np.pi * args.f0)
            q = 1.0 / (2 * zeta) if zeta > 0 else float("inf")
            # damped-frequency offset from demod phase slope over fit window
            fd_off = np.polyfit(tf, phase[lo:hi], 1)[0] / (2 * np.pi)
            fd = args.f0 + fd_off
            tau = 1.0 / (zeta * 2 * np.pi * args.f0) if zeta > 0 else float("inf")

            print(f"  decay span {span[0]:.3f}-{span[1]:.3f} mm")
            print(f"  zeta = {zeta:.5f}   Q = {q:.1f}   fd ≈ {fd:.3f} Hz")
            print(f"  time constant tau = {tau:.2f} s  -> settle(5 tau) ≈ {5*tau:.1f} s")
            print(f"  post safety=0b{int(health['safety']):04b}")

            np.savez(outdir / "ringdown.npz", index=idx, laser=laser,
                     forcing=np.asarray(data["forcing"]), env=mag, t=t)
            (outdir / "ringdown_summary.json").write_text(json.dumps({
                "f0": args.f0, "amp_v": args.amp, "zeta": float(zeta), "Q": float(q),
                "fd_hz": float(fd), "tau_s": float(tau), "span_mm": span,
            }, indent=2) + "\n")
            return 0
        finally:
            force_safe(dev)
            fin = snapshot(dev)
            print(f"safe: arm={fin['arm']} safety=0b{int(fin['safety']):04b} laser={fin['laser']:.3f} mm")


if __name__ == "__main__":
    raise SystemExit(main())
