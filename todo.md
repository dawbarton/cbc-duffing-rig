# CBC Duffing Rig todo

## Current

Differential DAC drive implemented in `cbc-rig` (helic-daq commit `6f82ffc`),
flashed and verified offline and on hardware. Blocked on physical state:
- Exciter and laser power supplies are OFF (as of 2026-07-17): actuation moves
  the DAC but produces no current/motion; `laser` reads 0. Re-enable before any
  energised test.
- [ ] Electrical check on a scope that A - C is bipolar and non-inverting
      before powering the exciter (software cannot verify DAC pin voltages).
- [ ] First energised test: 0.1 V pp (amplitude 0.05 V) sine near 5-10 Hz,
      watch laser displacement, reconfigure to safe state on any instability.
- [ ] Once confirmed, prune the "power off" / scope-check caveats that remain in
      `notes.md` history (already removed from quick-start and firmware guide).

## Future

- Consider updating the host Python simulator/tests to model the differential
  A/C mapping (currently model the old single-ended `rig_out_channel`).
- Feedback-control safety before closed-loop CBC: firmware amplitude ceiling,
  output arming/lease + comms-loss quieting, ADC-fault quieting, applied-output
  telemetry. These touch shared `rt_loop`/drivers, so agree scope with David.
