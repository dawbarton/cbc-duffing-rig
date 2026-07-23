# CBC Duffing Rig todo

## Current

**Investigate the bifurcation structure of the Duffing rig** (autonomous, full
autonomy through closed-loop CBC per David 2026-07-22). Exciter wiring restored
(ADC0 → exciter current sense, DAC A/C → current controller); exciter supply
powered on David's go-ahead. Air gap deliberately large ("probably low"
nonlinearity); David to provide a micrometer stator-position proxy at power-on.
Firmware `cd779ce` (protocol v3, PassThrough controller) is flashed and healthy.
Decision points are flagged; David monitors with an emergency shut-off.

**STATUS 2026-07-23:** Phases 0–3 (stable-branch CBC) and 5 done; report at
`reports/2026-07-23-bifurcation-structure/report.md`. Rig left disarmed, gains 0.
Key results: f0=9.80 Hz, Q=155 (ζ=0.0032), softening backbone (−160 mHz to
345 µm), CBC forced FRFs at 0.1 V & 0.2 V with folds (bistable ≈9.62–9.70 Hz at
0.2 V, peak ~830 µm). Remaining: unstable middle branch, Floquet/ARX stability.

Phase 0 — Bring-up — DONE
- [x] Health check; gap proxy 6.5 recorded; DAQ reset re-configured the
      just-powered laser (stale-trip); first-light 0.1 Vpp confirmed response.
Phase 1 — Linear characterisation — DONE
- [x] Open-loop FRF located f0≈9.8 Hz; ring-down gave ζ=0.0032, Q=155 (the
      reliable value — stepped-sweep Q was under-settled).
Phase 2 — Nonlinearity — DONE (via ring-down, not open-loop ladder)
- [x] High Q (25 s settle) makes open-loop stepped ladders give FALSE hysteresis;
      used free-decay backbones instead → clean softening, folds predicted.
Phase 3 — Closed-loop CBC — DONE (stable branches); middle branch OUTSTANDING
- [x] Firmware PidController swap (helic-daq `06545cb`), flashed, active-damping
      verified (ζ_cl linear in Kd, sign Kd<0).
- [x] CBC forced FRF at 0.1 V and 0.2 V via a robust damped-fixed-point
      corrector: softening overhang, folds, non-invasive (<5 mV) stable branches.
- [ ] **Unstable middle branch** — needs a robust Newton/Broyden corrector in a
      phase-anchored coordinate (the ill-conditioned reference-phase gauge broke
      naive Newton; amplitude-only continuation was invasive). See report §6.
Phase 4 — Cross-checks — OUTSTANDING
- [ ] ARX/Floquet stability + fold classification from closed-loop data.
- [ ] PLL/phase-resonance backbone as an independent cross-check of §3.
Phase 5 — Synthesis — DONE
- [x] Report + findings/quick-start updated; per-forcing CBC + backbone figures.

## Future

- Select the closed-loop stabilising controller (`ActiveController` swap from
  `PassThrough` to PID/PD) — the remaining functional step for energised
  closed-loop CBC/PLL; the safety gate is controller-agnostic and already in.
- Consider updating the host Python simulator/tests to model the differential
  A/C mapping (currently model the old single-ended `rig_out_channel`).
- Optional safety extensions if commissioning motivates them: `adc0`
  current-based trip (once its scaling is characterised), output slew limiting,
  and (only for unattended running) a heartbeat/lease on the arm flag.
