#!/usr/bin/env python3
"""Plot a CBC branch (forced frequency response) from cbc_branch.json.

Shows the response amplitude vs drive frequency traced by control-based
continuation — the S-shaped curve whose middle (negative-slope) segment is the
open-loop-unstable branch that an open-loop sweep cannot reach.  Also plots the
residual invasiveness (control fundamental, should be ~0) and the third-harmonic
ratio.  Reproducible from the JSON.
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
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("jsons", nargs="+", help="cbc_branch.json file(s)")
    p.add_argument("--title", default="CBC forced frequency response")
    p.add_argument("--out", required=True)
    args = p.parse_args()

    fig, ax = plt.subplots(3, 1, figsize=(9, 9), sharex=True,
                           gridspec_kw={"height_ratios": [3, 1, 1]})
    cmap = plt.get_cmap("viridis")
    for fi, jf in enumerate(args.jsons):
        data = json.loads(Path(jf).read_text())
        br = data["branch"]
        f = np.array([b["omega"] for b in br])
        amp = np.array([b["amp"] for b in br]) * 1e3          # um
        ctrl = np.array([b["ctrl_fund"] for b in br]) * 1e3    # mV
        x3 = np.array([b.get("X3", 0.0) for b in br]) * 1e3
        forcing = data.get("args", {}).get("forcing", None)
        label = f"forcing {forcing} V" if forcing else Path(jf).stem
        # colour by continuation index to show the traced path incl. folds
        ax[0].plot(f, amp, "-", color="0.7", lw=1.0, zorder=1)
        sc = ax[0].scatter(f, amp, c=np.arange(len(f)), cmap="viridis", s=22,
                           zorder=2, label=label)
        ax[1].plot(f, ctrl, ".-", ms=4, lw=0.8, color=f"C{fi}")
        with np.errstate(divide="ignore", invalid="ignore"):
            ax[2].plot(f, np.where(amp > 0, x3 / amp, np.nan), ".-", ms=4, lw=0.8, color=f"C{fi}")

    ax[0].set_ylabel("tip amplitude |X1|  [µm]")
    ax[0].set_title(args.title, fontsize=11)
    ax[0].legend(fontsize=8)
    ax[0].grid(alpha=0.3)
    cb = fig.colorbar(sc, ax=ax[0], pad=0.01)
    cb.set_label("continuation index", fontsize=8)
    ax[1].set_ylabel("invasiveness\nctrl |U1| [mV]")
    ax[1].axhline(0, color="k", lw=0.6)
    ax[1].grid(alpha=0.3)
    ax[2].set_ylabel("|X3 / X1|")
    ax[2].set_xlabel("drive frequency  [Hz]")
    ax[2].grid(alpha=0.3)

    fig.tight_layout()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, dpi=130)
    # quick fold detection: sign changes of d(freq)/d(index)
    f_all = np.array([b["omega"] for b in json.loads(Path(args.jsons[0]).read_text())["branch"]])
    df = np.diff(f_all)
    folds = np.where(np.diff(np.sign(df)) != 0)[0] + 1
    print(f"branch points: {len(f_all)}; frequency turning points (folds) near "
          f"indices {folds.tolist()} -> f={[round(float(f_all[i]),3) for i in folds]}")
    print(f"saved {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
