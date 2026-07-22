# CBC Duffing Rig todo

## Current

Commission the firmware safety stage through the DAC A/C to ADC0 differential
loopback. The current host and firmware source use protocol v3 at helic-daq
commit `cd779ce`; the previously flashed safety image was protocol v2 and must
be rebuilt and flashed before testing. Execute one item at a time and pause for
confirmation after each completed item.

- [x] Agree the complete commissioning plan and confirm the physical setup.
- [x] Record the agreed plan and setup; commit the documentation.
- [x] Add and simulator-test a fail-safe persistent-session Python test script;
      commit it.
- [x] Build and verify the protocol-v3 host and firmware from a clean detached
      worktree, preserving unrelated edits in the main helic-daq worktree.
- [x] Flash the clean W5500 release image; verify its identity, disarmed state,
      live in-range laser, and real-time health.
- [x] Capture the disarmed zero-output loopback baseline.
- [x] Characterise ADC0 gain, offset, and polarity using small differential
      commands and the standard small sine starting point.
- [x] Verify explicit-disarm and TCP-disconnect quieting with a small command
      configured.
- [x] With the exciter isolated, exercise both amplitude-clamp directions and
      verify applied-output telemetry, ADC0, and the safety flags.
- [ ] Zero every output source, disarm, disconnect, and confirm the final quiet
      state and clean diagnostics.
- [ ] Generate the time-series/calibration result, update the project guidance
      and notes, and commit the verified record.

The laser displacement/staleness trip is outside this run unless David
separately approves a coordinated physical interruption; do not induce it by
changing the laser calibration parameter.

## Future

- Select the closed-loop stabilising controller (`ActiveController` swap from
  `PassThrough` to PID/PD) — the remaining functional step for energised
  closed-loop CBC/PLL; the safety gate is controller-agnostic and already in.
- Consider updating the host Python simulator/tests to model the differential
  A/C mapping (currently model the old single-ended `rig_out_channel`).
- Optional safety extensions if commissioning motivates them: `adc0`
  current-based trip (once its scaling is characterised), output slew limiting,
  and (only for unattended running) a heartbeat/lease on the arm flag.
