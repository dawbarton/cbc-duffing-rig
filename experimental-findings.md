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
