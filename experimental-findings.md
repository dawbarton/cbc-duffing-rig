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

## Operational notes established this session

- The laser must be powered **before** the DAQ boots (or the DAQ reset after):
  the laser is configured (MEASRATE) only in the firmware boot path, and a
  laser that is not yet feeding fresh frames latches the firmware stale-laser
  trip so the gate cannot arm. Reset via `cargo run --release -p fw-cbc-rig`
  (re-runs boot/laser config); confirm `tripped 0` holds in the defmt log and
  the host laser capture shows live (non-frozen) values before arming.
- `diag_reset` clears the laser error counters and the startup
  `records_dropped` baseline; run it after boot before trusting health.
