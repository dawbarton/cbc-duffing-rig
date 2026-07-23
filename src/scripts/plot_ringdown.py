#!/usr/bin/env python3
"""Analyse and plot a ring-down: damping fit and free-decay backbone curve.

Reads the NPZ from ``ringdown.py`` and, by complex demodulation at f0, extracts
the instantaneous amplitude envelope A(t) and instantaneous frequency f(t).
For a linear system f(t) is constant; for a Duffing-type nonlinearity f varies
with amplitude, so plotting f vs A traces the *backbone curve* directly from a
single decay.  Softening (magnet-stator attraction) => frequency rises as
amplitude falls during the decay (backbone leans to lower f at high amplitude).

Panels: (1) laser AC decay, (2) log-envelope with exponential-damping fit,
(3) backbone: instantaneous frequency vs amplitude.  Reproducible from the NPZ.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def demodulate(ac, t, f0, fs):
    analytic = ac * np.exp(-1j * 2 * np.pi * f0 * t)
    win = max(1, int(round(fs / f0)))
    kernel = np.ones(win) / win
    env = np.convolve(analytic, kernel, mode="same")
    amp = np.abs(env)
    phase = np.unwrap(np.angle(env))
    # instantaneous frequency = f0 + phase'/2pi (smoothed)
    inst = f0 + np.gradient(phase, t) / (2 * np.pi)
    return amp, inst, win


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--npz", default="data/2026-07-23-ringdown/ringdown.npz")
    p.add_argument("--summary", default="data/2026-07-23-ringdown/ringdown_summary.json")
    p.add_argument("--f0", type=float, default=None)
    p.add_argument("--fs", type=float, default=8000.0)
    p.add_argument("--fit-lo", type=float, default=0.1)
    p.add_argument("--fit-hi", type=float, default=0.7)
    p.add_argument("--amp-floor-um", type=float, default=10.0,
                   help="ignore backbone below this amplitude (noise floor)")
    p.add_argument("--out", default="results/2026-07-23-ringdown.png")
    args = p.parse_args()

    d = np.load(args.npz)
    t = np.asarray(d["t"]) if "t" in d else (np.asarray(d["index"], float) - d["index"][0]) / args.fs
    laser = np.asarray(d["laser"])
    f0 = args.f0
    if f0 is None and Path(args.summary).exists():
        f0 = json.loads(Path(args.summary).read_text())["fd_hz"]
    f0 = f0 or 9.8

    ac = laser - laser.mean()
    amp, inst, win = demodulate(ac, t, f0, args.fs)
    amp_um = amp * 1e3

    # damping fit over the fit window
    lo, hi = int(args.fit_lo * len(t)), int(args.fit_hi * len(t))
    slope, intercept = np.polyfit(t[lo:hi], np.log(np.maximum(amp[lo:hi], 1e-9)), 1)
    zeta = -slope / (2 * np.pi * f0)
    q = 1 / (2 * zeta) if zeta > 0 else np.inf

    # backbone: use samples above the noise floor, and trim edges (convolution)
    edge = 2 * win
    m = np.zeros(len(t), bool)
    m[edge:len(t) - edge] = True
    m &= amp_um > args.amp_floor_um
    inst_s = np.convolve(inst, np.ones(win) / win, mode="same")

    fig, ax = plt.subplots(3, 1, figsize=(9, 9))
    fig.suptitle(f"Ring-down @ ~{f0:.2f} Hz — ζ ≈ {zeta:.5f}, Q ≈ {q:.0f}, τ ≈ "
                 f"{1/(zeta*2*np.pi*f0):.2f} s", fontsize=11)

    ax[0].plot(t, ac * 1e3, lw=0.4, color="0.5")
    ax[0].plot(t, amp_um, color="C3", lw=1.5, label="envelope")
    ax[0].plot(t, -amp_um, color="C3", lw=1.5)
    ax[0].set_ylabel("tip AC [µm]")
    ax[0].set_xlabel("time [s]")
    ax[0].legend(fontsize=8)

    ax[1].semilogy(t, amp_um, color="C0", lw=1.0)
    ax[1].semilogy(t[lo:hi], np.exp(intercept + slope * t[lo:hi]) * 1e3, "C3--",
                   lw=1.5, label="exp fit")
    ax[1].set_ylabel("envelope [µm, log]")
    ax[1].set_xlabel("time [s]")
    ax[1].legend(fontsize=8)

    ax[2].plot(inst_s[m], amp_um[m], ".", ms=3, color="C2")
    ax[2].set_xlabel("instantaneous frequency [Hz]")
    ax[2].set_ylabel("amplitude [µm]")
    ax[2].set_title("free-decay backbone (freq vs amplitude)", fontsize=9)
    ax[2].grid(alpha=0.3)
    # report the frequency shift across the amplitude range
    if m.sum() > 10:
        a_hi = amp_um[m].max()
        f_at_hi = inst_s[m][np.argmax(amp_um[m])]
        f_at_lo = np.median(inst_s[m][amp_um[m] < np.percentile(amp_um[m], 20)])
        df = f_at_hi - f_at_lo
        ax[2].set_title(f"free-decay backbone: Δf ≈ {df*1e3:+.1f} mHz over "
                        f"{a_hi:.0f} µm  ({'softening' if df < 0 else 'hardening'})",
                        fontsize=9)
        print(f"backbone: f(high A={a_hi:.0f}um)={f_at_hi:.4f} Hz, "
              f"f(low A)={f_at_lo:.4f} Hz, df={df*1e3:+.1f} mHz")

    for a in (ax[0], ax[1]):
        a.grid(alpha=0.3)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, dpi=130)
    print(f"zeta={zeta:.5f} Q={q:.1f}")
    print(f"saved {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
