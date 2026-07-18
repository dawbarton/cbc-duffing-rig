# Phase-Locked Loop (PLL) / Phase-Resonance Testing

Implementation guidance for agents. PLL is the main alternative to CBC for tracing
**backbone curves** (nonlinear normal modes) and nonlinear frequency responses. It is
simpler to implement than CBC when a single mode dominates, and is the natural comparison
method for the project's robustness study.

## 1. Principle

Instead of matching Fourier coefficients (CBC), a PLL controls the **phase lag** between
excitation and response to a prescribed value. Locking to the phase-quadrature condition
(−90° between force and displacement for the fundamental) places the system at **phase
resonance**. For lightly damped systems, phase resonance coincides with the amplitude peak
of the underlying conservative **nonlinear normal mode (NNM)**, so sweeping excitation
level while holding quadrature traces the **backbone curve** directly — no root-finding on
harmonics required.

Two complementary tests:
- **Backbone**: hold phase = −90°, vary amplitude → amplitude–frequency backbone.
- **Nonlinear FRF (NLFRF)**: hold amplitude, vary target phase across a range → the full
  frequency response including the overhang, one phase value at a time (each phase is
  stable under PLL, so folds are passable).

## 2. Loop structure

A PLL drives the excitation frequency so that the measured response phase tracks a set
point. Standard blocks:

1. **Phase detector** — estimate instantaneous phase difference `φ(t)` between excitation
   `f(t)` and response `x(t)`. Implementations: product detector (`f·x` + low-pass),
   Hilbert transform, or synchronous demodulation (project `x` onto `cos/sin(θ)` where `θ`
   is the internal oscillator phase).
2. **Loop filter** — a PI controller on the phase error `φ_set − φ`:
   ```
   ω(t) = ω_c + Kp_φ (φ_set − φ) + Ki_φ ∫ (φ_set − φ) dt
   ```
3. **Voltage-controlled oscillator (VCO)** — integrate the commanded frequency to get the
   drive phase `θ(t) = ∫ ω dt`; excitation is `f(t) = a·cos(θ(t))` (optionally with
   controlled harmonics).
4. **Amplitude controller** (outer loop, for NLFRF) — adjust drive amplitude `a` to hold a
   target response amplitude, using a slow PI loop so it does not fight the phase loop.

At lock, `ω` has converged so the response sits at the prescribed phase; the pair
`(ω, |X1|)` is one point on the backbone/NLFRF.

## 3. Phase resonance and NNMs

- The **phase-quadrature criterion**: at −90° fundamental phase lag, the excitation
  balances only damping, and the displacement approximates the conservative NNM motion
  (phase-resonance / force-appropriation generalised to nonlinear systems).
- Holding quadrature while increasing energy sweeps up the backbone; the locked frequency
  vs amplitude *is* the backbone curve.
- Higher-harmonic content of the NNM is captured by measuring the full response spectrum at
  each locked point; a *single-harmonic* phase criterion is an approximation that degrades
  when harmonics are strong (see NCPLL below).

## 4. Tuning

- **VCO centre frequency `ω_c`** near the expected resonance; initialise from an open-loop
  sweep or ring-down.
- **Loop-filter gains** set the lock bandwidth: fast enough to track the backbone as
  amplitude changes, slow enough to reject noise and not couple into the amplitude loop.
  Separate the phase-loop and amplitude-loop bandwidths by ≥ ~5–10×.
- **Phase-detector low-pass** cutoff below the carrier but above the sweep rate; trades
  phase-noise rejection against tracking lag.
- **Nonlinear-controller PLL (NCPLL)** replaces linear loop gains with a nonlinearity-aware
  design for faster, more uniform locking across amplitude — worth adopting if a linear PI
  loop locks sluggishly at high amplitude.

## 5. Algorithm (backbone sweep)

```
initialise ω ← ω_c, small amplitude a, φ_set ← −90°
lock: run phase PI loop until |φ_set − φ| below tolerance and ω steady
repeat over increasing energy:
    increase a (or target amplitude) by a small step
    let phase PI reacquire lock; wait settling
    measure ω_lock, response spectrum X, force spectrum F
    record backbone point (ω_lock, |X1|, harmonics)
    safety check: displacement/current within limits, else abort → safe state
```

For an NLFRF, replace "increase energy" with "hold amplitude, step `φ_set` across a range".

## 6. PLL vs CBC (practical)

- PLL: fewer tuning parameters, no experimental Jacobian, fast; naturally yields
  backbones/NLFRFs. Weaker for full bifurcation structure (isolas, general folds not
  organised by phase), and single-harmonic phase criterion is approximate under strong
  harmonics.
- CBC: general branch/bifurcation tracking, explicit non-invasiveness, harder to tune and
  slower. Consistency studies show the two agree on backbones/NLFRFs where both apply — run
  both and cross-check (this project's brief).

## 7. References

- M. Peeters, G. Kerschen, J. C. Golinval, "Dynamic testing of nonlinear vibrating
  structures using nonlinear normal modes", *J. Sound Vib.* 330 (2011).
- S. Peter, R. I. Leine, "Excitation power quantities in phase resonance testing of
  nonlinear systems with phase-locked-loop excitation", *Mech. Syst. Signal Process.* 96
  (2017).
- V. Denis, M. Jossic, C. Giraud-Audine, B. Chomette, A. Renault, O. Thomas, "Identification
  of nonlinear modes using phase-locked-loop experimental continuation and normal form",
  *Mech. Syst. Signal Process.* 106 (2018).
- G. Abeloos, F. Müller, E. Ferhatoglu, et al., "A consistency analysis of phase-locked-loop
  testing and control-based continuation for a geometrically nonlinear frictional system",
  *Mech. Syst. Signal Process.* 170 (2022).
- G. Abeloos et al., "Comparison between control-based continuation and phase-locked loop
  methods for the identification of backbone curves and nonlinear frequency responses",
  IMAC (2020).
- "Implementation of a nonlinear controller in Phase-Locked Loop experiments for nonlinear
  structure identification" (NCPLL), *Mech. Syst. Signal Process.* (2025).

## Duffing rig

- Well-suited: the rig has one dominant, reasonably isolated primary resonance (range in
  AGENTS.md), which is the regime where single-mode phase-resonance testing is most valid.
- Phase detector: synchronous demodulation of the laser signal against the internal drive
  phase is cleanest given the deterministic real-time loop and the firmware's phase-coherent
  excitation model. `adc0` (exciter current) or the coil pickup can supply the force-phase
  reference.
- The VCO/drive is generated host-side and pushed through the firmware Fourier/table
  excitation; keep the phase PI loop slow relative to the primary resonance and well within
  the actuator bandwidth.
- Expect strong odd harmonics from the magnet nonlinearity → measure the full spectrum at
  each locked point and be aware the −90° *fundamental* criterion is approximate; consider
  an NCPLL-style phase definition if backbones from PLL and CBC disagree.
- Same closed-loop safety envelope as CBC: the loop drives the exciter, so amplitude
  ceiling, arming/lease, and fault quieting must be in place; the sweep loop's safety check
  must trip to the safe state on any displacement/current excursion, within the safe
  operating limits in AGENTS.md.
- Good first comparison experiment: PLL backbone vs CBC-traced fold locus on the same
  operating point / air gap, as the noise-robustness head-to-head the project calls for.
