# Bifurcation structure of the CBC Duffing rig — investigation report

**Author:** Claude (Anthropic agent), on behalf of Prof. David A. W. Barton
**Date:** 2026-07-23
**Rig configuration:** air-gap proxy 6.5 (micrometer barrel, arbitrary units;
higher = smaller gap; deliberately large → weak nonlinearity), firmware
`cbc-rig` at helic-daq `06545cb` (PID controller build), 8 kHz sampling.

All results are reproducible from the scripts in `src/` and the raw data in
`data/`; figures are in `results/`. Amplitude/safety limits follow `AGENTS.md`.

---

## 1. Summary

The rig is a lightly-damped single-mode oscillator with a **softening**
nonlinearity from the magnet–stator attraction. Its bifurcation structure was
characterised by four complementary methods, escalating in capability:

| Quantity | Value | Method |
|---|---|---|
| Linear resonance `f0` | **9.80 Hz** | low-amplitude FRF + ring-down |
| Damping ratio `ζ` | **0.0032** (Q ≈ 155) | free-decay ring-down |
| Nonlinearity | **softening** (magnetic) | free-decay backbone |
| Backbone shift | −160 mHz over 0→345 µm | 4 ring-downs (collapse) |
| Forced folds (0.2 V) | bistable ≈ **9.62–9.70 Hz**, peak ≈ 830 µm | CBC |

The key methodological finding: at Q ≈ 155 the open-loop settling time is ≈ 25 s,
so **open-loop stepped-sine is impractical and produces false hysteresis**;
ring-down and control-based continuation (CBC) are the appropriate tools and
agree with each other.

---

## 2. Linear characterisation

A low-amplitude (0.1 Vpp) open-loop stepped sweep (3–15 Hz) located a single
clean resonance near 9.8 Hz with a classic 180°→0° phase roll
(`results/2026-07-23-phase1-frf.png`). The sweep **under-estimated** Q (≈36)
because the peak was both under-resolved and under-settled at a 4 s dwell.

A **free-decay ring-down** at resonance gave the reliable values
(`results/2026-07-23-ringdown-0p1vpp.png`): a clean exponential envelope over
~4 s yields **ζ = 0.0032, Q = 155, f0 = 9.80 Hz**, time-constant τ ≈ 5 s. The
implied ~25 s settling is why the stepped sweep failed — a general lesson for
high-Q rigs.

## 3. Nonlinearity: the softening backbone

Free-decay backbones from four ring-downs (drive 0.1/0.2/0.4/0.8 Vpp) **collapse
onto a single curve** (`results/2026-07-23-backbone.png`): the instantaneous
frequency falls from ~9.83 Hz at 30 µm to ~9.675 Hz at ~345 µm (Δf ≈ −160 mHz).
This is unambiguous **softening** — the magnet–stator attraction reducing the
effective stiffness as the tip approaches. The backbone is closer to
linear-in-amplitude than the cubic-Duffing A² law, consistent with a magnetic
(non-polynomial) potential rather than a textbook cubic term.

Even at 100 µm the backbone shift (~75 mHz) already ≈ the linear half-width
`f0/Q` ≈ 63 mHz, predicting folds at only a few hundred µm — confirmed by CBC.

Open-loop driving self-limits at ~730 µm because the softening detunes the fixed
drive frequency; reaching higher amplitude needs resonance tracking or CBC.

## 4. Closed-loop control-based continuation (CBC)

**Firmware.** The `cbc-rig` controller was switched `PassThrough → PidController`
(feedback on the laser, gains host-tunable, default 0 so the image drives
open-loop until armed and gained). Verified by an active-damping test: the
closed-loop ring-down ζ is linear in the derivative gain (`ζ_cl ≈ 0.0037 +
1.15·|Kd|`), stabilising sign Kd<0 (`results/2026-07-23-cbc-bringup.png`).

**Corrector.** A 2-D Newton/Broyden non-invasiveness corrector proved fragile
here: the reference-phase is a weakly-observable gauge direction near the high-Q
resonance, so the Jacobian is ill-conditioned and convergence was stochastic. A
**damped fixed-point** corrector, `R ← R + α(Rot(φ)·X − R)` with φ measured from
the (pure-sine) forcing, converges monotonically and robustly. It drives the
control fundamental to <5 mV — genuinely non-invasive, so the measured orbit is
the true open-loop forced response, stabilised so it can be held.

**Result.** Frequency-stepped CBC at fixed forcing traces the forced FRF
including the softening overhang and folds:

- **0.1 V** (`results/2026-07-23-cbc-sweep-0p1.png`): peak ~450 µm bent to
  9.70 Hz; narrow bistability ≈ 9.65–9.70 Hz.
- **0.2 V** (`results/2026-07-23-cbc-sweep-0p2.png`): peak ~830 µm bent to
  9.70 Hz; **wider bistability ≈ 9.62–9.70 Hz**. The fold and overhang grow
  strongly with forcing, as expected for a Duffing fold.

CBC is non-invasive and free of the settling-induced false hysteresis that
would corrupt an open-loop sweep at this Q — the central advantage demonstrated.

## 5. Comparison of methods

- **Ring-down backbone**: fastest and most robust for the *conservative*
  nonlinear structure (the NNM), noise-robust via coherent decay; gives ζ for
  free. Cannot give the forced response or stability.
- **Open-loop stepped-sine**: fails at high Q (settling) — false hysteresis;
  usable only far below resonance / at very low amplitude.
- **CBC (fixed-point)**: gives the true non-invasive forced FRF and the stable
  branches + fold locations, robustly. Best overall, at the cost of a controller
  and per-point settling.

Backbone (§3) and CBC peak loci (§4) are mutually consistent (both put the
large-amplitude resonance near 9.68–9.70 Hz).

## 6. Limitations and future work

- **Unstable middle branch not captured** — attempted in depth; the remaining
  obstacle is *root selection*, not conditioning. Findings:
  - The Newton corrector's ill-conditioning is caused by the sharply *resonant*
    reference→control sensitivity (`∂control/∂R = g(I−T)`, T = complementary
    sensitivity). **Strong damping fixes it**: the 2×2 `∂control/∂(a1,b1)`
    condition number falls from 6.9 at Kd=−0.02 to **1.0 at Kd=−0.12** — and,
    crucially, at the non-invasive point control→0 so the extra damping does
    *not* bias the measured orbit. Use large |Kd| for CBC correction here.
  - A fixed-point warm-start + column-equilibrated arclength Newton
    (`cbc_continuation.py`) then converges the *approach*, but still stalls
    right at the fold; a fixed-ω 2×2 Newton (well-conditioned at high Kd)
    converges cleanly but, from any starting amplitude, lands on the **dominant
    (upper) stable orbit** — it does not select the unstable middle root.
  - The 0.2 V bistable window is narrow (≈9.62–9.70 Hz), so the middle branch is
    short and nearly merged with the upper branch, worsening root selection.
  - **Robust routes for future work:** (a) *deflation* — after finding the upper
    orbit at a frequency, deflate it (`G(R)/‖R−R_upper‖`) and re-solve to force a
    different root; (b) a *wider fold* at higher forcing or a smaller air gap so
    the branches separate; (c) a proper arclength predictor that steps *onto* the
    middle branch from a fold point with a tangent that has turned. High |Kd|
    (well-conditioned Jacobian) should be used throughout.
  - Amplitude-controlled continuation (`cbc_middle.py`) matched only |X| (not
    phase) so it was invasive — superseded by the above; do not reuse as-is.
- **Higher harmonics.** CBC used H=1; odd harmonics were small (|X3/X1| < 0.02
  near resonance) but should be controlled (H=3) for quantitative branches.
- **Amplitude calibration** of the ring-down demod under-reads ~2× vs the raw
  span (frequencies are robust); use a Hilbert/peak-hold envelope.
- **Wider forcing/gap sweep.** Map the cusp (fold onset vs forcing) and repeat at
  a smaller air gap (stronger nonlinearity → possible double-well/period
  doubling). The gap is currently manual (stepper not fitted) — needs David.
- **Stability/Floquet estimation** (ARX from closed-loop data) to classify the
  folds and detect any secondary bifurcations — not yet done.

## 7. Reproduction

Scripts (Python, `src/scripts/`, run via the `helic-daq/host-python` uv env):
`first_light.py`, `open_loop_sweep.py`, `ringdown.py`, `cbc_bringup.py`,
`cbc_sweep.py` (+ `plot_*.py`); shared safe-session helpers in
`src/lib/rig_session.py`. Raw data under `data/2026-07-23-*`. See
`experimental-findings.md` for numeric detail and `notes.md` for the session log.
