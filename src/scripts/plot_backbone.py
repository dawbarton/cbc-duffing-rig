#!/usr/bin/env python3
"""Composite free-decay backbone from several ring-downs.

Each ring-down decay traces part of the nonlinear backbone (amplitude-dependent
resonance frequency).  This overlays the (instantaneous frequency, amplitude)
loci from several ring-downs and fits a Duffing-type backbone
    f(A) = f0 * (1 + kappa * A^2)
by binning amplitude and least-squares fitting frequency vs A^2 on the medians.
Softening (magnet-stator attraction) => kappa < 0.

Reproducible from the ring-down NPZs.
"""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def demod(ac, t, f0, fs):
    analytic = ac * np.exp(-1j * 2 * np.pi * f0 * t)
    win = max(1, int(round(fs / f0)))
    env = np.convolve(analytic, np.ones(win) / win, mode="same")
    amp = np.abs(env)
    inst = f0 + np.gradient(np.unwrap(np.angle(env)), t) / (2 * np.pi)
    inst = np.convolve(inst, np.ones(win) / win, mode="same")
    return amp, inst, win


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dirs", nargs="+", required=True,
                   help="ring-down dirs (each with ringdown.npz + ringdown_summary.json)")
    p.add_argument("--fs", type=float, default=8000.0)
    p.add_argument("--amp-floor-um", type=float, default=12.0)
    p.add_argument("--out", default="results/2026-07-23-backbone.png")
    args = p.parse_args()

    fig, ax = plt.subplots(1, 1, figsize=(8, 6))
    cmap = plt.get_cmap("plasma")
    all_f, all_a = [], []
    dirs = sorted(args.dirs)
    for i, dirp in enumerate(dirs):
        npz = Path(dirp) / "ringdown.npz"
        summ = json.loads((Path(dirp) / "ringdown_summary.json").read_text())
        f0 = summ["f0"]
        d = np.load(npz)
        t = np.asarray(d["t"])
        laser = np.asarray(d["laser"])
        amp, inst, win = demod(laser - laser.mean(), t, f0, args.fs)
        amp_um = amp * 1e3
        edge = 2 * win
        m = np.zeros(len(t), bool)
        m[edge:len(t) - edge] = True
        m &= amp_um > args.amp_floor_um
        color = cmap(0.1 + 0.75 * i / max(1, len(dirs) - 1))
        label = f"{summ['amp_v']*2*1e3:.0f} mVpp @ {f0:.2f} Hz (peak {amp_um[m].max():.0f} µm)"
        ax.plot(inst[m], amp_um[m], ".", ms=2.5, color=color, alpha=0.5, label=label)
        all_f.append(inst[m])
        all_a.append(amp_um[m])

    F = np.concatenate(all_f)
    A = np.concatenate(all_a)
    # bin by amplitude, median frequency per bin
    bins = np.linspace(A.min(), A.max(), 26)
    idx = np.digitize(A, bins)
    ba, bf = [], []
    for b in range(1, len(bins)):
        sel = idx == b
        if sel.sum() > 20:
            ba.append(np.median(A[sel]))
            bf.append(np.median(F[sel]))
    ba, bf = np.array(ba), np.array(bf)
    ax.plot(bf, ba, "k-o", ms=5, lw=1.5, label="binned median (backbone)")

    # Duffing fit f = f0*(1 + kappa A^2)  -> f = f0 + (f0 kappa) A^2
    c = np.polyfit(ba**2, bf, 1)  # bf ≈ c[0]*A^2 + c[1]
    f0lin = c[1]
    kappa = c[0] / f0lin
    Afit = np.linspace(0, ba.max(), 100)
    ax.plot(f0lin + c[0] * Afit**2, Afit, "r--", lw=1.5,
            label=f"fit f0={f0lin:.3f} Hz, κ={kappa:.3e} /µm²")
    ax.set_xlabel("instantaneous frequency [Hz]")
    ax.set_ylabel("amplitude [µm]")
    ax.set_title("Free-decay backbone (composite) — softening Duffing", fontsize=11)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="upper right")
    fig.tight_layout()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, dpi=130)

    # save aggregated backbone
    np.savez(Path(args.out).with_suffix(".npz"), freq=F, amp_um=A,
             bin_freq=bf, bin_amp=ba, f0_lin=f0lin, kappa_per_um2=kappa)
    df_total = bf.max() - bf.min()
    print(f"f0(A->0) ≈ {f0lin:.4f} Hz, kappa ≈ {kappa:.3e} /µm^2")
    print(f"backbone spans {ba.min():.0f}-{ba.max():.0f} µm, "
          f"Δf = {df_total*1e3:+.0f} mHz ({'softening' if bf[np.argmax(ba)]<bf[np.argmin(ba)] else 'hardening'})")
    print(f"saved {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
