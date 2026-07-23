# CBC Duffing Rig — experimental findings

Key measured features of the physical rig, with enough context to reproduce.
See `AGENTS.md` for fixed constants/limits and `quick-start.md` for operation.

## Configuration

- **Air gap (magnet–stator):** proxy micrometer reading **6.5** (American
  micrometer barrel, arbitrary units; **higher = smaller gap**). Set
  deliberately large → weak nonlinear interaction expected. Exact gap distance
  not measured. Recorded at exciter power-on 2026-07-23. Reproduce by restoring
  the same barrel reading.
- **Firmware:** helic-daq `cd779ce` (protocol v3, PassThrough controller),
  8 kHz sampling. Exciter driven differentially via DAC A/C; adc0 = exciter
  current sense; laser = tip displacement.
- **Resting tip displacement (laser):** ≈ 24.807 mm (this gap, undriven).

## 2026-07-23 Phase 0 first-light (open-loop, 0.1 Vpp @ 3 Hz)

- First energised actuation after power-on. Data:
  `data/2026-07-23-first-light/`; figure `results/2026-07-23-first-light.png`.
- Drive applied without clamping (forcing = out = 50 mV peak); safety held
  armed/untripped (`0b1001`) throughout; displacement span only ~10 µm.
- **Compliance at 3 Hz ≈ 0.042 mm/V** (laser fundamental 2.10 µm at 50 mV
  peak). This is well below resonance, so ~static compliance.
- FRF phase ≈ 178° at 3 Hz (sign convention: laser distance decreases as drive
  increases). Rolls toward 90° at resonance expected.
- Exciter current (adc0) shows a clean 3 Hz component (~6.9 mV fundamental) on
  the expected broadband noise, with a small DC offset (~-5 mV).
- Laser sensor quantisation ≈ 0.5 µm (limits SNR far below resonance at
  0.1 Vpp; resonance response will be ~10–50× larger and clean).

## 2026-07-23 Linear modal parameters (Phase 1 + ring-down)

- **Primary resonance f0 ≈ 9.80 Hz** at gap proxy 6.5 (near the top of the
  expected 5–10 Hz band). Single clean mode (phase rolls 180°→0° through f0).
- **Damping ζ ≈ 0.0032, Q ≈ 155** from a free-decay ring-down (0.1 Vpp),
  exponential envelope fit — high confidence. Time constant **τ ≈ 5 s**, so
  ~25 s to settle to 1%. Coarse stepped-sweep Q (≈36) was a severe
  underestimate (peak under-resolved AND under-settled at 4 s dwell).
- **Consequence:** open-loop stepped-sine near this resonance is impractical
  and prone to *false hysteresis* from incomplete settling. Use ring-down /
  closed-loop methods for the nonlinear regime.
- Data: `data/2026-07-23-phase1-linear/` (sweep),
  `data/2026-07-23-ringdown*/` (decays). Figures
  `results/2026-07-23-phase1-frf.png`, `...-ringdown-0p1vpp.png`.

## 2026-07-23 Nonlinearity: softening backbone (free-decay)

- **Softening confirmed** even at 0.1 Vpp: free-decay instantaneous frequency
  falls as amplitude rises (magnet–stator attraction). Composite backbone from
  4 ring-downs (0.1/0.2/0.4/0.8 Vpp) collapses onto one curve: **~9.83 Hz at
  30 µm → ~9.675 Hz at ~345 µm (Δf ≈ −160 mHz softening)**.
  Figure `results/2026-07-23-backbone.png`; aggregate `...-backbone.npz`.
- Backbone shift at ~100 µm (~75 mHz) already ≈ the linear half-width
  f0/Q ≈ 63 mHz ⇒ **folds/bistability expected at only a few hundred µm**
  amplitude — reachable at modest drive. This is the target for CBC.
- The backbone is closer to **linear-in-amplitude** than the cubic-Duffing A²
  law (poor A² fit) ⇒ the potential is magnetic/non-polynomial, not a textbook
  cubic. Revisit the model form after CBC.
- **Open-loop amplitude ceiling ~730 µm**: driving at fixed frequency
  self-limits because softening detunes the response below the drive; reaching
  higher amplitude needs resonance-tracking (PLL) or CBC.
- CAVEAT: the ring-down amplitude axis (one-period demod envelope) under-reads
  the true peak-to-peak span by ~2×; frequencies (the backbone shape) are
  robust. Refine the envelope (Hilbert/peak-hold) before quantitative use.

## Method note (2026-07-23)

- Acquisition + quick-look analysis/plots are in Python/matplotlib (reuses the
  proven safe-session harness in `src/lib/rig_session.py`); polished
  CairoMakie/Julia figures deferred to the report stage. Flagged to David.
- Python stdout is block-buffered to files; use `python -u` for live progress
  on backgrounded runs.

## Operational notes established this session

- The laser must be powered **before** the DAQ boots (or the DAQ reset after):
  the laser is configured (MEASRATE) only in the firmware boot path, and a
  laser that is not yet feeding fresh frames latches the firmware stale-laser
  trip so the gate cannot arm. Reset via `cargo run --release -p fw-cbc-rig`
  (re-runs boot/laser config); confirm `tripped 0` holds in the defmt log and
  the host laser capture shows live (non-frozen) values before arming.
- `diag_reset` clears the laser error counters and the startup
  `records_dropped` baseline; run it after boot before trusting health.

## 2026-07-23 Closed-loop bring-up (PID firmware 06545cb)

- Firmware `cbc-rig` PID controller enabled (helic-daq `06545cb`, branch
  cbc-pid-controller): ActiveController=PidController, feedback on laser slot 8,
  gains default 0 (open-loop until set live). Host now exposes ctrl_kp/ki/kd/
  tau_d/ctrl_feedback and an `error` telemetry source (46 params, 15 sources).
- **Loop verified by velocity-feedback active damping** (Kp=Ki=0, Kd only):
  closed-loop ring-down ζ_cl is linear in Kd, ζ_cl ≈ 0.0037 + 1.15·|Kd|:
  Kd=0→0.0037, −0.002→0.0062, +0.002→0.0013, −0.005→0.0099, −0.010→0.0152.
- **Stabilising sign is Kd < 0** (and by the same negative forward-path gain,
  Kp < 0 for correct-sign position tracking). Kd>0 de-damps toward instability.
- Damping is precisely controllable: Kd=−0.010 gives ζ_cl≈0.015 (Q≈33),
  τ_cl≈1.1 s — makes settling tractable and can stabilise unstable branches.
- Data `data/2026-07-23-cbc-bringup/`, figure `results/2026-07-23-cbc-bringup.png`.
- Note: after the PID reflash the DC operating point returned to laser≈24.807 mm
  (the post-power-trip +275 mV adc0 / 24.73 mm shift did not persist across the
  reflash) — consistent with it having been an amplifier power-up state.

## 2026-07-23 CBC forced frequency response (non-invasive), forcing 0.1 V

- First control-based-continuation result: the forced FRF traced with a
  non-invasive stabilising controller (Kp=-0.1, Kd=-0.02), fixed-point corrector
  driving |control|<4 mV. Data `data/2026-07-23-cbc-sweep-0p1/`, figure
  `results/2026-07-23-cbc-sweep-0p1.png`.
- **Softening forced response**: resonance peak bent to **~9.70 Hz** (from linear
  9.80 Hz), peak ~450 µm at forcing 0.1 V (0.2 Vpp).
- **Folds / bistability near ~9.68 Hz** (narrow at this forcing — near the cusp):
  down-sweep holds the upper branch to 9.70 Hz (448 µm) then drops; up-sweep
  holds the lower branch to 9.65 Hz (159 µm) then jumps to 452 µm at 9.70 Hz.
- Near-fold points hit the 30-iteration cap (control 5–12 mV) — the fixed-point
  is marginal exactly where the unstable middle branch is; frequency-stepping
  gets the two stable branches only. Middle branch needs amplitude continuation.
- CBC advantage demonstrated: non-invasive (true open-loop response) and free of
  the settling-induced false hysteresis that plagues open-loop stepped sweeps at
  Q≈155.

## 2026-07-23 CBC at 0.2 V + middle-branch status

- CBC forced FRF at forcing 0.2 V (Kp=-0.12, Kd=-0.025):
  `results/2026-07-23-cbc-sweep-0p2.png`, data `data/2026-07-23-cbc-sweep-0p2/`.
  **Peak ~830 µm bent to 9.70 Hz**; the softening overhang and the bistable
  window widen with forcing to ≈9.62–9.70 Hz (vs ≈9.65–9.70 at 0.1 V). Tip span
  at peak 24.0–25.6 mm (±0.8 mm) — safe. Non-invasive (<5 mV) off the fold.
- **Unstable middle branch: NOT captured.** Frequency-stepping reaches only
  stable branches. Amplitude-controlled continuation (`cbc_middle.py`) matched
  |X|=A but not phase, so it was invasive (control 150–630 mV) — abandoned.
  Needs a robust Newton corrector in a phase-anchored coordinate. See
  `reports/2026-07-23-bifurcation-structure/report.md` §6.
- Controller gains used: Kp∈[-0.1,-0.12] V/mm, Kd∈[-0.02,-0.025] V/(mm/s), both
  negative (negative forward-path gain). tau_d=3 ms. Feedback on laser (slot 8).
