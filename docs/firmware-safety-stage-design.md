# Firmware safety stage — scoped design proposal

**Status:** proposal for review (not yet implemented). Authored by the agent, 2026-07-18.
Reflects helic-daq firmware as read at project commit state on that date.

Prerequisite for energised **closed-loop** operation (CBC, PLL, adaptive-filtering CBC,
derivative-free arclength CBC, GP continuation, and the multisine injection used for
stability/Floquet estimation). See `docs/methods/*` — every closed-loop method doc lists
the same safety envelope, and `docs/firmware-guide.md` "Known gaps" records its absence.

This document scopes **what** to add, **where** it lives (shared vs experiment code), and
**how** it stays zero-impact on the other experiments that share the firmware. Numeric
limits and the arm policy are called out as decision points at the end.

---

## 1. Problem and constraints

Closing the loop through the electromagnetic exciter is exactly the instability path the
project safety notes flag: a bad Jacobian step near a fold, a mistuned gain, a dropped host
link mid-adaptation, or a blind feedback path (stale laser) can command large drive and
drive the tip to large displacement. Today:

- **No firmware amplitude clamp.** `out = controller_out + forcing + table_out` is written
  straight to the DAC; the AD5064 only *silently* saturates the final channel voltage at
  0–4.096 V (i.e. logical `out` beyond ±2.048 V). The 0.1 V pp start / ≤ 2 V pp ceiling are
  soft (host) conventions only.
- **No output arming.** A freshly flashed board, or a reconnecting host, can drive
  immediately.
- **No comms-loss quieting.** If the host link drops, the RT loop keeps applying whatever
  `target`/`forcing`/`table`/controller state it last held — a continuously adapting loop
  would keep adapting blind.
- **No sensor-fault quieting.** If the laser feed goes stale or an ADC frame faults,
  feedback is computed on stale data with no reaction.

Design constraints:

1. **Hard constraints belong in firmware** (AGENTS.md). The amplitude ceiling, comms-loss
   quieting, and sensor-fault/displacement trip must be enforced on core 1, not in a host
   script that can crash.
2. **Shared code, other experiments unaffected.** The gate lives in `firmware/common`
   (`rt_loop.rs` + the `Rig` trait). `whirl-rig` (no actuator) and `pico2w-rig` (open-loop
   DAC, different bias convention) must be byte-for-byte behaviourally unchanged.
3. **Auditable and centralised.** A safety feature should be readable in one place, not
   scattered across per-tick arithmetic.
4. **No wire-protocol change.** Reuse the existing param/command plumbing.

---

## 2. Proposed architecture

### 2.1 Signal flow change (shared `rt_loop::run_rt_tick`)

Current tail of the tick:

```
out = controller_out + forcing + table_out
rig.actuate(out)
values[generated + 3] = out            // streamed "out"
```

Proposed:

```
out_cmd = controller_out + forcing + table_out
out_applied = if R::SAFETY_GATED { safety_gate::<R>(rig, &values[..n_inputs], out_cmd) }
              else               { out_cmd }
rig.actuate(out_applied)
values[generated + 3] = out_applied    // streamed "out" is now the APPLIED command
```

`const SAFETY_GATED: bool = false;` is added to the `Rig` trait. For `whirl-rig` /
`pico2w-rig` it stays `false`, the compiler removes the branch entirely, and behaviour is
identical to today. `cbc-rig` sets it `true`. This single const is the opt-in switch and the
one place a reviewer checks to know whether a build is gated.

Streaming the **applied** value as `out` closes the "applied-output telemetry" gap: the host
sees what was actually driven (post-clamp / post-quiet), which is the safety-relevant
quantity and what the stability-estimation LTP-ARX must treat as the true plant input.
(The host already knows what it *commanded*; if a raw pre-gate copy is ever wanted it can be
added as a separate source later.)

### 2.2 The gate (generic mechanism, shared)

`safety_gate` is a small free function in `rt_loop.rs`, pure mechanism, no experiment
constants:

```
fn safety_gate<R: Rig>(rig, inputs, out_cmd) -> f32:
    # 1. Latching fault trip (experiment decides the condition)
    if rig.output_fault(inputs):
        SAFETY_TRIPPED.store(true)              # latches until explicit re-arm
    # 2. Arm / lease (host heartbeat) and comms-loss
    armed = now_us().wrapping_sub(LEASE_DEADLINE_US) as i32 < 0   # wrap-safe "not expired"
    # 3. Decide
    if SAFETY_TRIPPED or not armed:
        SAFETY_QUIET_TICKS += 1
        return rig.safe_output()                # experiment's quiet value
    else:
        applied = rig.clamp_output(out_cmd)     # experiment's hard ceiling
        if applied != out_cmd: SAFETY_CLAMP_TICKS += 1
        return applied
```

All state is in shared atomics alongside the existing diagnostics:

| Atomic | Set by | Meaning |
|---|---|---|
| `LEASE_DEADLINE_US: AtomicU32` | core 0 (param write, TCP close) | absolute TIMER0 µs; output armed iff not yet reached |
| `SAFETY_TRIPPED: AtomicU32` | core 1 (gate), cleared by core 0 arm | latched fault trip |
| `SAFETY_CLAMP_TICKS: AtomicU32` | core 1 | count of ticks the ceiling was active (diagnostic) |
| `SAFETY_QUIET_TICKS: AtomicU32` | core 1 | count of ticks output was forced to safe (diagnostic) |

Wrap-safety: `LEASE_DEADLINE_US` is compared with `now_us()` (TIMER0 low word, ~71.6 min
wrap) using `wrapping_sub` cast to `i32`, the same idiom already used for tick spacing. Lease
durations are far below the wrap period, so the sign test is unambiguous.

### 2.3 Experiment-specific policy (`Rig` trait hooks, defaulted)

Three new trait methods, each with a safe default so existing experiments need no edit:

```rust
/// Opt in to the shared safety gate. Default: no gate (identity behaviour).
const SAFETY_GATED: bool = false;

/// Hard output ceiling, applied to the *summed* command every tick. A buggy
/// controller cannot exceed it. Default: identity.
fn clamp_output(&self, out: f32) -> f32 { out }

/// Value actuated when disarmed / tripped. Default: 0.0.
fn safe_output(&self) -> f32 { 0.0 }

/// Latching fault condition evaluated on this tick's inputs (displacement
/// excursion, stale sensor, ...). `&mut` so the rig can track staleness.
/// Default: never faults.
fn output_fault(&mut self, _inputs: &[f32]) -> bool { false }
```

`cbc-rig` implementations:

- `SAFETY_GATED = true`.
- `clamp_output(out) = out.clamp(-OUT_CEILING_V, OUT_CEILING_V)` where `OUT_CEILING_V` is the
  logical differential ceiling (a `config.rs` constant; see decision D2). Because the gate
  runs *after* the controller+forcing+table sum, this is the hard amplitude limit.
- `safe_output() = 0.0` — logical 0 maps to `MID_RAIL` on channel A, i.e. zero differential
  drive (the rig's defined quiet state). No change to `actuate`, which already biases.
- `output_fault(inputs)` returns true if **either**:
  - `|laser − laser_ref|` exceeds a safe displacement bound (decision D3), **or**
  - the laser feed is stale: `LASER_FRAMES_RECEIVED` has not advanced for more than
    `STALE_TICKS` ticks (blind-feedback guard). The rig holds the last frame count and a
    tick-since-change counter in its own state.

The displacement trip depends on the laser sign/calibration being scope-verified first (the
outstanding commissioning item in `todo.md`); the amplitude ceiling and the arm/lease/
comms-loss path do **not** depend on the laser and can land first (see §5 staging).

### 2.4 Host interface (no protocol change)

- **Arm / renew:** one new writable base param `arm_lease_ms` (u32). Writing `n > 0` arms and
  sets `LEASE_DEADLINE_US = now_us() + n·1000`, and clears `SAFETY_TRIPPED` (the fault
  re-latches on the next tick if the condition persists, so this cannot mask a live fault).
  Writing `0` disarms immediately (`LEASE_DEADLINE_US = now_us()`). Applied **directly on
  core 0** in the param handler — the same pattern as `diag_reset` — so the disarm path has
  no command-queue latency. To hold the output live the host renews the lease periodically
  (a heartbeat); a stalled or crashed host lets the lease expire and the output quiets. This
  single mechanism covers "arming", "host crash", and "comms-loss".
- **Auto-disarm on disconnect:** in `comms::tcp::control_run`, the existing
  post-`serve` cleanup (which already sets `STREAM.enabled = false`) also sets
  `LEASE_DEADLINE_US = now_us()`. A dropped TCP control connection quiets the actuator
  immediately, independent of the lease timeout.
- **Telemetry (read-only base params):** `safety_armed` (u32 0/1, derived), `safety_tripped`
  (u32 0/1), `safety_clamp_ticks`, `safety_quiet_ticks`. Surfaced through the same
  `BASE_PARAMS` + `get()` path as `overruns` et al., and added to the 1 Hz defmt status line.
  On a non-gated experiment these read a constant `armed=1, tripped=0, 0, 0` — inert and
  harmless. (Alternative: expose them as `cbc-rig` extras to avoid inert params on other
  experiments — a minor placement choice, see D4.)

### 2.5 Why lease-based rather than a separate watchdog

Reusing an absolute-deadline atomic unifies four requirements — explicit arming, host-crash
quieting, comms-loss quieting, and "output off by default after flash" (deadline initialises
to 0 = already expired = disarmed) — into one comparison per tick with no new task. It
composes with the existing `time_watchdog` (which recovers lost embassy-time alarms on core
0) rather than duplicating it.

---

## 3. What is intentionally NOT in this stage

- **In-firmware harmonic projection / adaptive law / PLL** — stays host-side (see the methods
  review). The gate is orthogonal to them.
- **Current-based trip** using `adc0` (exciter current monitor) — a useful second,
  independent interlock, but `adc0` is documented as *low-fidelity*; deferred until its
  scaling is characterised. The hook design already accommodates it (extend `output_fault`).
- **Hardware interlock** (analogue over-travel switch, series current limit) — defence in
  depth at the hardware layer, out of firmware scope; recommended as a separate track for
  truly fail-safe protection, since any firmware trip still depends on the RT core running.
- **Rate limiting / slew limiting** of `out` — not required by the methods; can be added to
  `clamp_output` later if commissioning shows it useful.

---

## 4. Impact and verification

**Files touched (shared — needs the root-workspace checks):**

- `firmware/common/src/rig.rs` — add `SAFETY_GATED`, `clamp_output`, `safe_output`,
  `output_fault` to the `Rig` trait, all defaulted.
- `firmware/common/src/rt_loop.rs` — the `safety_gate` function, the four atomics, the
  `reset_diagnostics` additions (clamp/quiet counters), the applied-output substitution.
- `firmware/common/src/params.rs` + `params/schema.rs` — `arm_lease_ms` writable param
  (direct core-0 apply) and the read-only safety telemetry.
- `firmware/common/src/comms/tcp.rs` — one line in the disconnect cleanup.

**Files touched (cbc-rig only):**

- `experiments/cbc-rig/src/config.rs` — `OUT_CEILING_V`, displacement/stale constants.
- `experiments/cbc-rig/src/rig.rs` — implement the four hooks; add staleness state.

**Behavioural equivalence for other experiments:** guaranteed by `SAFETY_GATED = false`
compiling the gate out, and by every hook defaulting to identity/never-fault. Confirm with a
diff of the generated `out` on `whirl-rig`/`pico2w-rig` smoke runs (should be unchanged) and
by the root `cargo test`.

**New tests (host-testable, no hardware):**

- Gate: disarmed → returns `safe_output`; armed + in-range → returns `clamp_output(out)`;
  over-ceiling → clamped; fault → latched quiet until re-arm; lease expiry across the
  `now_us` comparison including a wrap boundary.
- `clamp_output` symmetry and ceiling for `cbc-rig`.
- Staleness counter logic in `output_fault`.

**On-rig verification (staged, low drive first):** with `OUT_CEILING_V` set low, confirm (a)
output is quiet until `arm_lease_ms` is written; (b) stopping the host heartbeat quiets the
output within the lease timeout; (c) dropping the TCP connection quiets immediately; (d) a
forced over-ceiling command is clamped (observe on `out` telemetry and a scope); (e)
`safety_*` telemetry and the status line reflect each state. Watch health counters throughout.

---

## 5. Suggested staging (each an atomic, committable step)

1. **Trait hooks + gate scaffolding + `SAFETY_GATED=false` everywhere.** Pure shared
   refactor; no behavioural change; other experiments verified unchanged. Host tests for the
   gate with defaults.
2. **Amplitude ceiling + arm/lease + comms-loss, `cbc-rig` gated.** Does *not* depend on the
   laser. Delivers the core interlock: output off until armed, quiets on host loss/disconnect,
   hard-clamps drive. On-rig verification (a)–(e) above at low ceiling.
3. **Displacement + stale-sensor trip.** Depends on the laser sign/calibration commissioning
   item; add once that is verified. Extends `output_fault`.
4. **(Later / optional)** current-based trip via `adc0`; slew limiting; raw pre-gate `out`
   source — only if commissioning motivates them.

Only after step 2 is on the rig should any *energised closed-loop* CBC/PLL run begin.

---

## 6. Open decisions (need David)

- **D1 — Arm policy.** Explicit-arm-required + heartbeat lease (recommended, above), vs a
  simpler "armed whenever a control connection is open" (no periodic renew). The lease adds a
  host-side heartbeat obligation but is the only variant that quiets on a *hung* (not closed)
  host. Recommendation: lease, with a generous default timeout (e.g. 500 ms) that the host
  renews at ~10 Hz.
- **D2 — `OUT_CEILING_V`.** The hard logical differential ceiling. Given the ≤ 2 V pp soft
  limit and MID_RAIL bias, a logical ceiling around ±1.0–1.5 V is a plausible hard cap, but
  this should be set from the exciter current-controller's safe input range, not guessed.
- **D3 — Displacement bound.** The safe tip-displacement trip level (in laser mm about a
  reference), pending the laser calibration/sign check. Also whether to trip on absolute
  range-of-travel, on excursion from the operating point, or both.
- **D4 — Telemetry placement.** Safety telemetry + `arm_lease_ms` as shared `BASE_PARAMS`
  (inert on other experiments) vs `cbc-rig` extras (zero footprint elsewhere, slightly more
  wiring). Recommendation: `BASE_PARAMS`, since the mechanism is shared and the inert cost is
  four read-only params.
