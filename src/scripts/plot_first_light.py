#!/usr/bin/env python3
"""Plot the Phase 0 first-light capture: laser response, drive, and current.

Reads the NPZ saved by ``first_light.py`` and produces a 3-panel time-series
figure over a few drive periods, overlaying the least-squares harmonic fit of
the laser so the coherent response is visible against sensor noise.  Purely a
visualisation of saved data (reproducible from the NPZ).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from rig_session import project_harmonics  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--npz", default="data/2026-07-23-first-light/first_light_drive.npz")
    parser.add_argument("--freq", type=float, default=3.0)
    parser.add_argument("--fs", type=float, default=8000.0)
    parser.add_argument("--periods", type=float, default=4.0, help="periods to display")
    parser.add_argument("--out", default="results/2026-07-23-first-light.png")
    args = parser.parse_args()

    data = np.load(args.npz)
    idx = np.asarray(data["index"], dtype=float)
    t = (idx - idx[0]) / args.fs
    n_show = int(args.periods * args.fs / args.freq)
    sl = slice(0, min(n_show, len(t)))

    laser = np.asarray(data["laser"])
    fit = project_harmonics(laser, idx, args.freq, args.fs, 3)
    w = 2 * np.pi * args.freq
    tt = idx / args.fs
    laser_fit = fit["mean"] + sum(
        fit["a"][n] * np.cos((n + 1) * w * tt) + fit["b"][n] * np.sin((n + 1) * w * tt)
        for n in range(3)
    )

    fig, ax = plt.subplots(3, 1, figsize=(9, 7), sharex=True)
    fig.suptitle(
        f"Phase 0 first-light — {args.freq:g} Hz, 0.1 Vpp drive  "
        f"(gap proxy 6.5)\nlaser fundamental "
        f"{fit['amp'][0] * 1e3:.2f} um, compliance "
        f"{fit['amp'][0] / 0.05:.4f} mm/V",
        fontsize=11,
    )

    ax[0].plot(t[sl], (laser[sl] - fit["mean"]) * 1e3, color="0.6", lw=0.8, label="laser (measured)")
    ax[0].plot(t[sl], (laser_fit[sl] - fit["mean"]) * 1e3, color="C3", lw=1.5, label="harmonic fit (H=3)")
    ax[0].set_ylabel("tip displ.\n[µm, AC]")
    ax[0].legend(loc="upper right", fontsize=8)
    ax[0].set_title(f"resting {fit['mean']:.3f} mm", fontsize=8, loc="left")

    ax[1].plot(t[sl], np.asarray(data["forcing"])[sl] * 1e3, color="C0", lw=1.0, label="forcing")
    ax[1].plot(t[sl], np.asarray(data["out"])[sl] * 1e3, color="C1", lw=0.8, ls="--", label="applied out")
    ax[1].set_ylabel("drive\n[mV]")
    ax[1].legend(loc="upper right", fontsize=8)

    ax[2].plot(t[sl], np.asarray(data["adc0"])[sl] * 1e3, color="C2", lw=0.8)
    ax[2].set_ylabel("exciter current\nadc0 [mV]")
    ax[2].set_xlabel("time [s]")

    for a in ax:
        a.grid(alpha=0.3)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, dpi=130)
    print(f"saved {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
