#!/usr/bin/env python3
"""Plot frequency-response functions from open_loop_sweep summaries.

Reads one or more sweep summary JSON files (produced by ``open_loop_sweep.py``)
and plots, per amplitude/direction:
  - laser fundamental amplitude |X1| (um) vs frequency  -> resonance peak
  - response phase (deg) vs frequency
  - third-harmonic ratio |X3/X1| vs frequency           -> nonlinearity onset

Estimates the linear natural frequency f0 (parabolic-refined peak) and quality
factor Q (half-power bandwidth) for the smallest-amplitude up-sweep, and prints
them.  For amplitude ladders it overlays branches so hardening/softening and
up/down hysteresis are visible.  Reproducible from the saved summaries.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def rows_arrays(rows):
    f = np.array([r["freq"] for r in rows])
    order = np.argsort(f)
    out = {"freq": f[order]}
    for key in ("laser_A1", "laser_A2", "laser_A3", "gain_phase", "gain_mag",
                "laser_mean", "adc0_A1", "forcing_A1"):
        out[key] = np.array([r[key] for r in rows])[order]
    # keep original (sweep) order too for hysteresis direction plotting
    out["freq_swept"] = f
    out["A1_swept"] = np.array([r["laser_A1"] for r in rows])
    return out


def estimate_f0_q(freq, amp):
    """Parabolic-refined peak f0 and half-power-bandwidth Q from |X1|(f)."""
    i = int(np.argmax(amp))
    f0 = freq[i]
    if 0 < i < len(freq) - 1:  # parabolic vertex refine
        y0, y1, y2 = amp[i - 1], amp[i], amp[i + 1]
        denom = (y0 - 2 * y1 + y2)
        if denom != 0:
            delta = 0.5 * (y0 - y2) / denom
            f0 = freq[i] + delta * (freq[i + 1] - freq[i])
    peak = amp[i]
    half = peak / np.sqrt(2.0)
    # find half-power crossings either side of the peak by linear interpolation
    def cross(lo, hi, i0, i1):
        if amp[i1] == amp[i0]:
            return freq[i0]
        return np.interp(half, [amp[i0], amp[i1]] if amp[i1] > amp[i0]
                         else [amp[i1], amp[i0]],
                         [freq[i0], freq[i1]] if amp[i1] > amp[i0]
                         else [freq[i1], freq[i0]])
    fl = fr = None
    for j in range(i, 0, -1):
        if amp[j - 1] < half <= amp[j]:
            fl = np.interp(half, [amp[j - 1], amp[j]], [freq[j - 1], freq[j]])
            break
    for j in range(i, len(freq) - 1):
        if amp[j + 1] < half <= amp[j]:
            fr = np.interp(half, [amp[j + 1], amp[j]], [freq[j + 1], freq[j]])
            break
    q = None
    if fl is not None and fr is not None and fr > fl:
        q = f0 / (fr - fl)
    return f0, q, peak, fl, fr


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summaries", nargs="+", help="sweep summary JSON files")
    parser.add_argument("--title", default="Open-loop FRF")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    fig, ax = plt.subplots(3, 1, figsize=(9, 9), sharex=True)
    cmap = plt.get_cmap("viridis")
    branches = []
    for path in args.summaries:
        run = json.loads(Path(path).read_text())
        for sw in run["sweeps"]:
            branches.append((sw["amp_v"], sw["direction"], sw["rows"]))

    amps_sorted = sorted({b[0] for b in branches})
    f0_est = q_est = None
    for amp, direction, rows in branches:
        if not rows:
            continue
        a = rows_arrays(rows)
        ci = amps_sorted.index(amp)
        color = cmap(0.15 + 0.7 * ci / max(1, len(amps_sorted) - 1))
        ls = "-" if direction == "up" else "--"
        label = f"{amp*2*1e3:.0f} mVpp {direction}"
        # magnitude in um, plotted in sweep order so up/down trace their branch
        ax[0].plot(a["freq_swept"], a["A1_swept"] * 1e3, ls, color=color, marker=".",
                   ms=4, lw=1.2, label=label)
        ax[1].plot(a["freq"], np.degrees(a["gain_phase"]), ls, color=color,
                   marker=".", ms=3, lw=1.0)
        with np.errstate(divide="ignore", invalid="ignore"):
            h3 = np.where(a["laser_A1"] > 0, a["laser_A3"] / a["laser_A1"], np.nan)
        ax[2].plot(a["freq"], h3, ls, color=color, marker=".", ms=3, lw=1.0)
        # estimate f0/Q from the smallest-amplitude up-sweep (most linear)
        if amp == amps_sorted[0] and direction == "up":
            f0_est, q_est, peak, fl, fr = estimate_f0_q(a["freq"], a["laser_A1"])
            ax[0].axvline(f0_est, color="0.5", lw=0.8, ls=":")
            if fl and fr:
                ax[0].axvspan(fl, fr, color="0.85", alpha=0.5, zorder=0)

    ax[0].set_ylabel("tip |X1|  [µm]")
    ax[0].legend(fontsize=8, ncol=2)
    ax[1].set_ylabel("phase  [deg]")
    ax[2].set_ylabel("|X3 / X1|")
    ax[2].set_xlabel("drive frequency  [Hz]")
    for a in ax:
        a.grid(alpha=0.3)

    subtitle = args.title
    if f0_est is not None:
        subtitle += f"   |   f0 ≈ {f0_est:.3f} Hz"
        if q_est is not None:
            subtitle += f",  Q ≈ {q_est:.1f}  (ζ ≈ {1/(2*q_est):.4f})"
        print(f"f0 ≈ {f0_est:.4f} Hz" + (f", Q ≈ {q_est:.2f}, zeta ≈ {1/(2*q_est):.5f}"
                                         if q_est else ", Q undetermined"))
    fig.suptitle(subtitle, fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, dpi=130)
    print(f"saved {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
