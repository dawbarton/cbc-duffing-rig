# CBC Duffing Rig todo

## Current

**Investigate the bifurcation structure of the Duffing rig** (autonomous, full
autonomy through closed-loop CBC per David 2026-07-22). Exciter wiring restored
(ADC0 → exciter current sense, DAC A/C → current controller); exciter supply
powered on David's go-ahead. Air gap deliberately large ("probably low"
nonlinearity); David to provide a micrometer stator-position proxy at power-on.
Firmware `cd779ce` (protocol v3, PassThrough controller) is flashed and healthy.
Decision points are flagged; David monitors with an emergency shut-off.

Phase 0 — Bring-up (read-only done; tiny-drive after power-on)
- [x] Read-only health check: firmware `cd779ce`, laser 24.81 mm in range,
      counters baseline; historical latched trip (bit1) from an earlier laser
      UART hiccup, clears on arm.
- [ ] David powers exciter; record the gap proxy in experimental-findings.
- [ ] Build a persistent-session stepped-sine acquisition + analysis harness
      (arm, safety polling, abort-to-safe on any trip, NPZ save, plots).
- [ ] Tiny-drive check (0.1 V pp sub-resonance): confirm beam responds (laser
      motion + adc0 current), safety clears/holds with a moving beam.

Phase 1 — Linear characterisation (open-loop, 0.1 V pp)
- [ ] Stepped-sine FRF ~3–15 Hz: locate f0, damping/Q, displacement sensitivity.
      DECISION: centre subsequent sweep window on measured f0.

Phase 2 — Nonlinear open-loop map (amplitude ladder, ≤ 2 V pp)
- [ ] Stepped-sine FRFs up an amplitude ladder, each with up- and down-sweep to
      detect hysteresis; extract backbone bending (expect softening) and folds.
      DECISION: nonlinearity strength → proceed to CBC vs report that a smaller
      (manual) air gap is needed.

Phase 3 — Closed-loop CBC (firmware PID swap; energised feedback)
- [ ] Swap ActiveController PassThrough→PID (as PD) in cbc-rig config.rs; build,
      verify offline, flash, health-check.
- [ ] Low-gain stable-branch bring-up; tune gains/margins; confirm
      non-invasiveness (control spectrum ~0 at controlled harmonics).
- [ ] Host-side Newton/Broyden + pseudo-arclength (H=3); trace the primary
      resonance FRF including the unstable middle branch between the folds.

Phase 4 — Cross-checks
- [ ] PLL/phase-resonance backbone; ARX/Floquet stability + fold/PD
      classification; compare methods and noise robustness.

Phase 5 — Synthesis
- [ ] Consolidated bifurcation diagram + report; update findings/quick-start.

## Future

- Select the closed-loop stabilising controller (`ActiveController` swap from
  `PassThrough` to PID/PD) — the remaining functional step for energised
  closed-loop CBC/PLL; the safety gate is controller-agnostic and already in.
- Consider updating the host Python simulator/tests to model the differential
  A/C mapping (currently model the old single-ended `rig_out_channel`).
- Optional safety extensions if commissioning motivates them: `adc0`
  current-based trip (once its scaling is characterised), output slew limiting,
  and (only for unattended running) a heartbeat/lease on the arm flag.
