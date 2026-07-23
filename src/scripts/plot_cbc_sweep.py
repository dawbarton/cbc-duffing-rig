#!/usr/bin/env python3
"""Plot fixed-point CBC frequency sweeps (cbc_sweep.json): the forced FRF with
folds and up/down hysteresis. Overlays down- and up-sweeps; marks unconverged
(near-fold) points. Reproducible from the JSON.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("json")
    ap.add_argument("--title", default="CBC forced frequency response (fixed-point)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--f0", type=float, default=9.80, help="linear resonance to mark")
    args = ap.parse_args()

    data = json.loads(Path(args.json).read_text())
    forcing = data.get("args", {}).get("forcing", None)
    fig, ax = plt.subplots(2, 1, figsize=(9, 8), sharex=True,
                           gridspec_kw={"height_ratios": [3, 1]})
    styles = {"down": ("C0", "v", "down-sweep"), "up": ("C3", "^", "up-sweep")}
    for sw in data["sweeps"]:
        d = sw["direction"]
        color, mark, lab = styles.get(d, ("C1", "o", d))
        f = np.array([r["omega"] for r in sw["rows"]])
        amp = np.array([r["amp"] for r in sw["rows"]]) * 1e3
        conv = np.array([r["converged"] for r in sw["rows"]])
        ctrl = np.array([r["ctrl"] for r in sw["rows"]]) * 1e3
        ax[0].plot(f, amp, "-", color=color, lw=1.2, alpha=0.8, zorder=1)
        ax[0].scatter(f[conv], amp[conv], c=color, marker=mark, s=30, zorder=3, label=lab)
        if (~conv).any():
            ax[0].scatter(f[~conv], amp[~conv], facecolors="none", edgecolors=color,
                          marker=mark, s=55, zorder=3,
                          label=f"{lab} (near-fold, unconverged)")
        ax[1].plot(f, ctrl, ".-", color=color, lw=0.8, ms=4)

    ax[0].axvline(args.f0, color="0.5", ls=":", lw=1.0, label=f"linear f0={args.f0} Hz")
    ax[0].set_ylabel("tip amplitude |X1|  [µm]")
    ttl = args.title + (f"  —  forcing {forcing} V" if forcing else "")
    ax[0].set_title(ttl, fontsize=11)
    ax[0].legend(fontsize=8, loc="upper left")
    ax[0].grid(alpha=0.3)
    ax[1].axhline(4, color="k", ls="--", lw=0.6, label="tol")
    ax[1].set_ylabel("invasiveness\n|control| [mV]")
    ax[1].set_xlabel("drive frequency  [Hz]")
    ax[1].grid(alpha=0.3)
    ax[1].legend(fontsize=8)

    fig.tight_layout()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, dpi=130)

    # report fold locations from amplitude jumps in each sweep
    for sw in data["sweeps"]:
        f = np.array([r["omega"] for r in sw["rows"]])
        amp = np.array([r["amp"] for r in sw["rows"]])
        jumps = np.where(np.abs(np.diff(amp)) > 0.5 * np.maximum(amp[:-1], amp[1:]))[0]
        for j in jumps:
            print(f"  {sw['direction']}-sweep jump near {f[j]:.3f}-{f[j+1]:.3f} Hz "
                  f"({amp[j]*1e3:.0f}->{amp[j+1]*1e3:.0f} um)")
    print(f"saved {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
