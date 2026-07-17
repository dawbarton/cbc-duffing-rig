# CBC Duffing Rig quick start

Practical, high-signal tips for an agent starting from a clean context. Read
`AGENTS.md` first (experiment description, channel roles, safety limits, health
monitoring). This file is for how-to detail, not repetition of those.

## Talking to the DAQ

- Device: `cbc-rig` firmware on a W5500-EVB-Pico2 at static IP `192.168.1.235`.
- Host CLI (Python): from `helic-daq/host-python`, run
  `uv run --python 3.12 helic-daq <cmd>` — `status`, `list`, `get <names...>`,
  `set <name> <val>`, `sine <freq> <amp>`, `stop`, `capture --sources a,b,c
  --seconds N --decimation D --output f.npz`, `find`, `sources`.
- `out` is a stream *source*, not a param (so `get out` fails); capture it.
- Julia host lib is in `helic-daq/host-julia`.

## Firmware build / flash

- Crate: `fw-cbc-rig` at `helic-daq/firmware/experiments/cbc-rig`. Only this
  crate may be modified (drivers/core/common are shared — do not touch).
- Build from `helic-daq/firmware`: `cargo build --release -p fw-cbc-rig`
  (default = W5500; add `--no-default-features --features board-w6100` for the
  W6100). Exactly one board feature at a time — `--all-features` fails (two
  WIZnet chips conflict).
- Flash with the cargo runner: `cargo run --release -p fw-cbc-rig` (probe-rs,
  CMSIS-DAP probe attached). It flashes, resets, and streams defmt.
  GOTCHA: `probe-rs download` + `probe-rs reset` left the core non-serving;
  use `cargo run` / `probe-rs run` instead.
- Network takes ~2 s to come up after reset; poll `status` with retries.
- Offline checks before flashing: `cargo fmt -p fw-cbc-rig -- --check`,
  `cargo clippy --release -p fw-cbc-rig -- -D warnings` (repeat for w6100),
  release builds for both boards, and
  `uv run --python 3.12 python tools/check_rt_layout.py` (keeps `measure`/
  `actuate` hot symbols in SRAM). The `proc-macro-error2` future-incompat
  warning is a pre-existing dependency issue, not from our code.

## Exciter drive semantics (differential DAC, since helic-daq 6f82ffc)

- Current controller input is differential: DAC A (positive) minus DAC C
  (negative). Firmware holds C at `MID_RAIL = DAC_VREF/2 = 2.048 V` and biases
  the driven channel A by the same, so the streamed logical `out` is the
  *signed differential command* (out=0 -> A=C -> zero drive), no inversion
  (A up = more drive).
- Output routing is locked to channel A: `rig_out_channel` rejects 1 (broken B)
  and 2 (C reference) with "bad value"; only 0 is accepted.
- The DAC driver clamps the final A voltage to 0-4.096 V, so a logical `out`
  beyond +/-2.048 V silently saturates. There is NO firmware amplitude clamp;
  the 2 V pp limit is a soft/host responsibility for now.
- AD5064 needs ~3 us between sequential SPI words (`WORD_SETTLE_US` in the
  driver); batch/startup writes use `Ad5064::write_volts_with_delay`, and the
  single-word `write_volts`/`write_code` carry a doc warning about it.
  One-per-tick hot-path writes are naturally spaced by the 125 us tick.

## Current physical state / caveats (as of 2026-07-17)

- Exciter and laser power supplies are OFF. Actuation moves the DAC but
  produces no current/motion; `laser` reads 0 and the laser probe logs
  "no reply at any supported baud rate" (expected).
- OUTSTANDING before energising the exciter: David to confirm on a scope that
  A - C is bipolar and non-inverting against the current-controller input
  (software cannot read DAC pin voltages). First energised test: 0.1 V pp
  (amplitude 0.05 V) sine near 5-10 Hz; reconfigure to safe state on any
  instability.

## Sanity numbers observed

- Idle 8 kHz: loop_time_max ~33-35 us, wake phase ~36 us, overruns/jitter/
  tick_timeouts 0. `records_dropped` sits at a fixed ~498 startup count (records
  produced before a UDP consumer connects) — not an anomaly; watch for growth
  during a capture instead.
- adc0 (exciter current sense) idles ~0.38-0.49 V with a few mV of ripple.
