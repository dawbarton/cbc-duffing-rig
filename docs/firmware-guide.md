# CBC rig firmware guide

The experiment is driven over the network through the `cbc-rig` firmware running
on the helic-daq. In normal operation this firmware is **fixed** and you run
experiments over the host API (see `quick-start.md`); the flexibility built into
it — parameter/source discovery, a Fourier-series generator, arbitrary-waveform
tables, a swappable controller — is meant to cover the experimental campaign
without reflashing. This guide is for the rarer occasions when the firmware
itself must be understood, modified, rebuilt, or reflashed.

Reflects helic-daq commit `6f82ffc`. Authored by the agent.

## Where it lives and what may change

- Crate `fw-cbc-rig` at `helic-daq/firmware/experiments/cbc-rig` (reachable via
  the `helic-daq/` symlink in this project).
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
cargo build --release -p fw-cbc-rig
uv run --python 3.12 python tools/check_rt_layout.py   # keeps measure/actuate hot symbols in SRAM
```

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
- **Clamping / no amplitude limit:** the AD5064 driver clamps the final channel
  voltage to 0–4.096 V, so a logical `out` beyond ±2.048 V saturates silently.
  There is **no firmware amplitude clamp**.
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

## Diagnostics

Timing diagnostics (`loop_time_*`, `wake_phase_*`, `t_measure_max`,
`t_actuate_max`, `t_rest_max`) and fault counters (`overruns`, `tick_timeouts`,
`clock_jitter`, `cmd_backlog_max`, `records_dropped`, `laser_*`) are read-only
parameters. See the **Health Monitoring** section of `AGENTS.md` for the
routine-check procedure and `diag_reset` usage.

## Known gaps

- **Feedback-control safety is not yet in the firmware:** no amplitude clamp, no
  output arming/lease or communication-loss quieting, no ADC-fault quieting.
  These matter for closed-loop CBC (which can go unstable), not for open-loop
  forcing, and some touch shared `rt_loop` code — agree scope before
  implementing.

Time-sensitive commissioning items (e.g. the outstanding scope check that A − C
is bipolar and non-inverting before the exciter is energised) live in
`todo.md`, not here.
