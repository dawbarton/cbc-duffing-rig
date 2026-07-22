#!/usr/bin/env python3
"""Summarise and plot CBC safety-stage DAC-to-ADC commissioning captures.

The input files are the immutable NPZ captures produced by
``commission_safety_loopback.py``.  This script recomputes the principal
calibration and safety results, writes a machine-readable JSON summary, and
creates a compact sanity-check figure.  The sample rate is an argument because
it is firmware configuration, not an analysis constant.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def load_capture(directory: Path, name: str) -> dict[str, np.ndarray]:
    path = directory / f"{name}.npz"
    if not path.is_file():
        raise FileNotFoundError(f"required capture is missing: {path}")
    with np.load(path) as archive:
        return {key: archive[key] for key in archive.files}


def mean(data: dict[str, np.ndarray], source: str) -> float:
    return float(np.mean(data[source]))


def rms(values: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(values))))


def relative_time(data: dict[str, np.ndarray], sample_rate: float) -> np.ndarray:
    return (data["index"] - data["index"][0]) / sample_rate


def build_summary(captures: dict[str, dict[str, np.ndarray]]) -> dict:
    mapping_out = np.concatenate(
        [captures["mapping_positive"]["out"], captures["mapping_negative"]["out"]]
    )
    mapping_adc = np.concatenate(
        [captures["mapping_positive"]["adc0"], captures["mapping_negative"]["adc0"]]
    )
    gain, offset = np.polyfit(mapping_out, mapping_adc, 1)
    residual = mapping_adc - (gain * mapping_out + offset)

    summary = {
        "baseline": {
            "out_mean_v": mean(captures["baseline_disarmed"], "out"),
            "adc0_mean_v": mean(captures["baseline_disarmed"], "adc0"),
            "adc0_std_v": float(np.std(captures["baseline_disarmed"]["adc0"])),
        },
        "mapping": {
            "adc0_per_out_gain": float(gain),
            "adc0_offset_v": float(offset),
            "residual_rms_v": rms(residual),
        },
        "quieting": {},
        "clamp": {},
        "final": {
            "out_mean_v": mean(captures["final_quiet"], "out"),
            "adc0_mean_v": mean(captures["final_quiet"], "adc0"),
            "adc0_std_v": float(np.std(captures["final_quiet"]["adc0"])),
        },
    }
    for name in (
        "explicit_disarm_before",
        "explicit_disarm_after",
        "disconnect_before_close",
        "disconnect_after_close",
    ):
        summary["quieting"][name] = {
            "forcing_mean_v": mean(captures[name], "forcing"),
            "out_mean_v": mean(captures[name], "out"),
            "adc0_mean_v": mean(captures[name], "adc0"),
        }
    for name in ("clamp_positive", "clamp_negative"):
        summary["clamp"][name] = {
            "forcing_mean_v": mean(captures[name], "forcing"),
            "out_mean_v": mean(captures[name], "out"),
            "adc0_mean_v": mean(captures[name], "adc0"),
        }
    return summary


def create_figure(
    captures: dict[str, dict[str, np.ndarray]],
    sample_rate: float,
    output: Path,
) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(11.5, 7.5), constrained_layout=True)

    sine = captures["mapping_sine"]
    time_s = relative_time(sine, sample_rate)
    shown = time_s <= 0.3
    axes[0, 0].plot(time_s[shown], sine["out"][shown], label="applied out", linewidth=1.8)
    axes[0, 0].plot(
        time_s[shown], sine["adc0"][shown], label="ADC0 (A−C)", linewidth=1.0, alpha=0.85
    )
    axes[0, 0].set(title="Small-signal loopback", xlabel="Time (s)", ylabel="Voltage (V)")
    axes[0, 0].legend(loc="upper right")
    axes[0, 0].grid(alpha=0.25)

    mapping_out = np.concatenate(
        [captures["mapping_negative"]["out"], captures["mapping_positive"]["out"]]
    )
    mapping_adc = np.concatenate(
        [captures["mapping_negative"]["adc0"], captures["mapping_positive"]["adc0"]]
    )
    gain, offset = np.polyfit(mapping_out, mapping_adc, 1)
    axes[0, 1].scatter(mapping_out[::20], mapping_adc[::20], s=5, alpha=0.25, label="samples")
    fit_x = np.array([mapping_out.min(), mapping_out.max()])
    axes[0, 1].plot(fit_x, gain * fit_x + offset, color="black", label="linear fit")
    axes[0, 1].set(
        title=f"Differential mapping: gain {gain:.6f}, offset {1e3 * offset:.3f} mV",
        xlabel="Applied out (V)",
        ylabel="ADC0 (V)",
    )
    axes[0, 1].legend(loc="upper left")
    axes[0, 1].grid(alpha=0.25)

    quiet_names = [
        "explicit_disarm_before",
        "explicit_disarm_after",
        "disconnect_before_close",
        "disconnect_after_close",
    ]
    quiet_labels = ["armed", "explicit\ndisarm", "re-armed", "disconnect"]
    x = np.arange(len(quiet_names))
    width = 0.25
    for offset_x, source, label in (
        (-width, "forcing", "forcing request"),
        (0.0, "out", "applied out"),
        (width, "adc0", "ADC0"),
    ):
        axes[1, 0].bar(
            x + offset_x,
            [mean(captures[name], source) for name in quiet_names],
            width,
            label=label,
        )
    axes[1, 0].set(
        title="Explicit and connection-loss quieting",
        ylabel="Mean voltage (V)",
        xticks=x,
        xticklabels=quiet_labels,
    )
    axes[1, 0].axhline(0.0, color="black", linewidth=0.7)
    axes[1, 0].legend(loc="upper right")
    axes[1, 0].grid(axis="y", alpha=0.25)

    clamp_names = ["clamp_negative", "clamp_positive"]
    clamp_labels = ["negative", "positive"]
    x = np.arange(len(clamp_names))
    for offset_x, source, label in (
        (-width, "forcing", "forcing request"),
        (0.0, "out", "applied out"),
        (width, "adc0", "ADC0"),
    ):
        axes[1, 1].bar(
            x + offset_x,
            [mean(captures[name], source) for name in clamp_names],
            width,
            label=label,
        )
    axes[1, 1].set(
        title="Bidirectional amplitude clamp",
        ylabel="Mean voltage (V)",
        xticks=x,
        xticklabels=clamp_labels,
    )
    axes[1, 1].axhline(0.0, color="black", linewidth=0.7)
    axes[1, 1].legend(loc="upper left")
    axes[1, 1].grid(axis="y", alpha=0.25)

    fig.suptitle("CBC rig firmware safety-stage loopback commissioning", fontsize=14)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=180)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("--sample-rate", type=float, required=True)
    parser.add_argument("--figure", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    if args.sample_rate <= 0:
        parser.error("--sample-rate must be positive")

    names = [
        "baseline_disarmed",
        "mapping_positive",
        "mapping_negative",
        "mapping_sine",
        "explicit_disarm_before",
        "explicit_disarm_after",
        "disconnect_before_close",
        "disconnect_after_close",
        "clamp_positive",
        "clamp_negative",
        "final_quiet",
    ]
    captures = {name: load_capture(args.input_dir, name) for name in names}
    summary = build_summary(captures)
    create_figure(captures, args.sample_rate, args.figure)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
