# CBC rig firmware guide

The experiment is driven over the network through the `cbc-rig` firmware running
on the helic-daq. In normal operation this firmware is **fixed** and you run
experiments over the host API (see `quick-start.md`); the flexibility built into
it — parameter/source discovery, a Fourier-series generator, arbitrary-waveform
tables, a swappable controller — is meant to cover the experimental campaign
without reflashing. This guide is for the rarer occasions when the firmware
itself must be understood, modified, rebuilt, or reflashed.

Reflects the firmware at helic-daq commit `cd779ce` and its 2026-07-22 hardware
commissioning. Authored by the agent.

## Where it lives and what may change

- Crate `fw-cbc-rig` at `helic-daq/firmware/experiments/cbc-rig` (provided by
  the pinned `helic-daq/` Git submodule in this project).
- helic-daq is a **multi-experiment platform**. Only the `cbc-rig` crate may be
  modified; `helic-drivers`, `firmware/common`, and core code are shared with
  other experiments — change them only with care and a clear reason, and re-run
  the root-workspace checks below.
- Source map (all under `src/`):
  - `config.rs` — compile-time choices (experiment name, output channel, laser
    range, sample rate, network config, active controller).
  - `board.rs` — auditable pin and peripheral ownership map, core split.
  - `rig.rs` — acquisition, actuation, parameters, and the CBC-specific DAC
    behaviour.
  - `telemetry.rs` — shared scalar state (laser value, laser error counters).
  - `main.rs` — boots both cores and assigns tasks; orchestration only.
- helic-daq's own documentation: `helic-daq/docs/user_guide.md` (operation),
  `developer_guide.md` (extension rules), `protocol.md` (wire protocol),
  `overrun_handoff.md`. Cross-session firmware history is in
  `helic-daq/notes.md`.

## Build

From `helic-daq/firmware`:

```
cargo build --release -p fw-cbc-rig                                   # W5500 (default)
cargo build --release -p fw-cbc-rig --no-default-features --features board-w6100
```

Select exactly **one** board feature at a time — `--all-features` fails because
the two WIZnet chip features conflict.

## Flash

```
cargo run --release -p fw-cbc-rig      # probe-rs runner over an attached CMSIS-DAP probe
```

This flashes, resets, and streams the defmt log.

- **Gotcha:** `probe-rs download` followed by `probe-rs reset` was observed to
  leave the core non-serving (network never came up). Use `cargo run` /
  `probe-rs run` instead.
- The network takes ~2 s to come up after reset; poll `helic-daq status` with
  retries.
- For reproducibility, commit before flashing so the firmware banner carries a
  clean git hash (an uncommitted tree shows `<hash>-dirty`).

## Offline verification (before flashing)

Firmware crate (repeat clippy/build for `--no-default-features --features
board-w6100`):

```
cargo fmt -p fw-cbc-rig -- --check
cargo clippy --release -p fw-cbc-rig -- -D warnings
cargo build --release --workspace
uv run --python 3.12 python tools/check_rt_layout.py   # checks all production RT ELFs
```

The layout gate requires release ELFs for CBC, whirl, and Pico 2W; a fresh
worktree must therefore build the complete firmware workspace before running
it. Rebuild `fw-cbc-rig` with the intended board feature after any alternate
board build so the artifact selected for flashing is unambiguous.

If shared code (`helic-drivers`, `firmware/common`) was touched, also run the
**root** workspace (from `helic-daq/`): `cargo fmt --check`,
`cargo clippy --all-targets --all-features -- -D warnings`, `cargo test`.

The `proc-macro-error2` future-incompat warning comes from a dependency, not
this code — ignore it.

## Exciter output: differential DAC drive

The exciter's current controller takes a **differential** input: DAC channel A
(positive) minus DAC channel C (negative). The AD5064 DAC is unipolar
(0–4.096 V), so a bipolar drive is produced by biasing about mid-rail:

- The firmware holds channel **C** at `MID_RAIL = DAC_VREF/2 = 2.048 V` and
  biases the driven channel **A** by the same amount. The streamed logical
  `out` is therefore the **signed differential command in volts**: `out = 0` →
  A = C → zero drive. **No inversion** — A up = more drive. (Common-mode
  2.048 V and non-inverting mapping confirmed by David, 2026-07-17.)
- `init()` defines all four channels once — C and A at `MID_RAIL`, unused B and
  D at 0 V — in a single spaced pass via `Ad5064::write_volts_with_delay` (C
  before A so the driven channel settles to match the reference last).
  `actuate()` writes `MID_RAIL + out` to channel A every tick.
- **Clamping:** the safety stage (below) hard-clamps the logical `out` every
  tick so the driven channel voltage `MID_RAIL + out` stays within
  `[DAC_OUT_FLOOR_V, DAC_OUT_CEILING_V]` (0.096–4.0 V by default → differential
  ±1.952 V). The AD5064 driver's own 0–4.096 V clamp remains as a final
  backstop. The streamed `out` is the **applied** value, i.e. after clamping
  and any safety quieting.
- **Output routing is locked:** `rig_out_channel` accepts only `0` (channel A)
  and rejects `1` (broken B) and `2` (the C reference) with "bad value", so a
  host command cannot redirect or clobber the differential output.

## AD5064 inter-word timing

The AD5064 requires ~3 µs between sequential SPI words (`WORD_SETTLE_US` in
`helic-drivers/src/ad5064.rs`). Batch/startup writes must use
`Ad5064::write_volts_with_delay` (or `zero_all_with_delay`), which space the
words; the single-word `write_volts` / `write_code` carry a doc warning about
this. A per-tick hot-path write of a single channel is naturally spaced by the
125 µs tick and needs no extra delay.

## Compile-time configuration (`config.rs`)

Not persisted at runtime — edit and reflash to change:

- `OUTPUT_CHANNEL = 0` (channel A); `LASER_RANGE_MM = 50`.
- Sample rate: 8 kHz default; the `diag-sample-4k` feature selects 4 kHz.
- `NET_CONFIG`: static `192.168.1.235/24`; `MAC_ADDR`.
- `ActiveController = PassThrough`. To run closed-loop control, swap
  `ActiveController` and `make_controller()` together (e.g. a PID controller);
  the host discovers the resulting parameters by name.
- **Safety limits:** `DAC_OUT_CEILING_V = 4.0`, `DAC_OUT_FLOOR_V = 0.096`
  (DAC-output-voltage window for the exciter drive), `DISPLACEMENT_MIN_MM = 10`
  / `DISPLACEMENT_MAX_MM = 40` (laser trip window about the ~25 mm resting
  point), `LASER_STALE_AFTER_S = 0.02` (blind-feedback guard). See the safety
  stage below.

## Output safety stage

`cbc-rig` drives the exciter through a feedback path that can go unstable, so it
opts into the shared per-tick **safety gate** (`Rig::SAFETY_GATED = true`). The
gate runs on core 1 after the controller/forcing/table sum and before the DAC
write; it is a hard, firmware-level constraint that no host script or controller
bug can bypass. Design rationale and the full mechanism are in
`docs/old/2026-07-18-firmware-safety-stage-design.md`.

- **Amplitude ceiling** — `clamp_output` clamps the logical command to the DAC
  window above; the streamed `out` is the applied (post-clamp) value.
- **Arming** — the output is **disarmed after every flash/reset** and is held at
  zero drive until the host writes the `arm` parameter (`arm = 1`). Writing
  `arm = 0`, or dropping the TCP control connection, disarms immediately
  (comms-loss quieting). There is no lease/heartbeat: an operator is present at
  the rig with emergency power-off (decision D1). Arming clears a latched trip
  only if the fault condition is already clear.
- **Fault trip** — `output_fault` latches a trip (held quiet until re-arm) if
  the laser leaves the `[DISPLACEMENT_MIN_MM, DISPLACEMENT_MAX_MM]` window, reads
  non-finite, or its frame counter stalls (`LASER_STALE_AFTER_S`, a
  blind-feedback guard). With the laser unpowered the gate therefore trips and
  quiets — the safe default.
- **Host visibility** — the `safety` parameter is a bitfield: bit0 armed, bit1
  latched trip, bit2 clamped-since-reset, bit3 quieted-since-reset. Exact
  clamp/quiet tick counts appear in the 1 Hz status log. `arm` reads back the
  armed state.

The gate is generic (`firmware/common`), opt-in per experiment; `whirl-rig` and
`pico2w-rig` leave `SAFETY_GATED = false` and are unaffected (the gate compiles
out). A future bipolar output stage will re-home `MID_RAIL` to 0 and turn the
DAC window into independent ± limits.

## Diagnostics

Timing diagnostics (`loop_time_*`, `wake_phase_*`, `t_measure_max`,
`t_actuate_max`, `t_rest_max`), fault counters (`overruns`, `tick_timeouts`,
`clock_jitter`, `cmd_backlog_max`, `records_dropped`, `laser_*`) and the
`safety` bitfield are read-only parameters. See the **Health Monitoring**
section of `AGENTS.md` for the routine-check procedure and `diag_reset` usage.

## Known gaps

- **Closed-loop stabilising controller not yet selected:** `ActiveController`
  is still `PassThrough`. The safety gate is in place and controller-agnostic,
  but energised closed-loop CBC/PLL also needs a feedback controller (the
  documented `config.rs` swap) — a separate step.

## Hardware commissioning status

On 2026-07-22, clean protocol-v3 firmware `cd779ce` was flashed and exercised
with DAC A and C connected to the differential ADC0 input and the exciter
isolated. The loopback established non-inverting near-unity A-minus-C mapping,
verified small-signal sine playback, explicit-disarm quieting,
control-disconnect quieting, and both amplitude-clamp directions. Applied
`out`, ADC0, and the safety flags agreed in every phase; all monitored fault and
loss counters stayed zero. The final state was disarmed with every output source
zero. Detailed numerical results and reproducible scripts are recorded in the
project `notes.md` and `src/scripts/`.

The displacement/stale-laser trip was not deliberately re-induced during this
session; its earlier blind-laser hardware test and unit coverage remain the
evidence for that path. Time-sensitive physical state lives in `todo.md` and
`quick-start.md` rather than this fixed-firmware guide.
