# CBC Duffing Rig todo

## Current

Firmware safety stage implemented and flashed (`cbc-rig`, helic-daq commit
`c8c3abe`): per-tick output gate (amplitude clamp to 0.096–4.0 V DAC window,
displacement 10–40 mm + laser-staleness trip, arm flag disarmed-after-flash,
disconnect-disarm), applied-output telemetry, `arm`/`safety` params. Verified
offline (host tests, clippy, both boards, RT-layout) and on-rig (timing 33–34 µs
preserved, arm/disarm/disconnect/trip behaviour). Design record in
`docs/old/2026-07-18-firmware-safety-stage-design.md`.

Blocked on physical state:
- Exciter and laser power supplies are OFF (as of 2026-07-17): actuation moves
  the DAC but produces no current/motion; `laser` reads 0. Re-enable before any
  energised test. With the laser off the safety gate correctly trips and quiets
  (`safety = 0b1010`).
- [ ] Electrical check on a scope that A - C is bipolar and non-inverting
      before powering the exciter (software cannot verify DAC pin voltages).
- [ ] First energised test: `set arm 1` over a persistent host session, then
      0.1 V pp (amplitude 0.05 V) sine near 5-10 Hz, watch laser displacement,
      `set arm 0` / disconnect to quiet on any instability.
- [ ] Exercise the amplitude clamp live (armed + in-range laser + over-ceiling
      command → `out` clamped, `safety` bit2 set) — only unit-tested so far.
- [ ] Once confirmed, prune the "power off" / scope-check caveats that remain in
      `notes.md` history (already removed from quick-start and firmware guide).

## Future

- Select the closed-loop stabilising controller (`ActiveController` swap from
  `PassThrough` to PID/PD) — the remaining functional step for energised
  closed-loop CBC/PLL; the safety gate is controller-agnostic and already in.
- Consider updating the host Python simulator/tests to model the differential
  A/C mapping (currently model the old single-ended `rig_out_channel`).
- Optional safety extensions if commissioning motivates them: `adc0`
  current-based trip (once its scaling is characterised), output slew limiting,
  and (only for unattended running) a heartbeat/lease on the arm flag.
