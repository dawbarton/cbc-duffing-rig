# Control-Based Continuation (CBC)

Implementation guidance for agents. CBC is the flagship method for this project: it
traces solution branches (including unstable ones) and bifurcations of the physical
experiment directly, without a fitted model, by applying numerical continuation to a
feedback-stabilised rig.

## 1. Principle

Wrap the experiment in a stabilising feedback controller acting on the actuator. Let
`x(t)` be the measured output and `r(t)` a periodic *reference* (control target). The
control law produces an actuator command from the tracking error `e(t) = x(t) − r(t)`.

The reference is iterated until the control is **non-invasive**: on convergence the
controller injects no steady-state force at the harmonics it controls, so the measured
orbit is a genuine solution of the *open-loop* system — but one that has been stabilised
and can therefore be held and measured even where it is naturally unstable (e.g. the
middle branch of a Duffing fold, or an isola).

CBC therefore separates two roles:
- **Stabilisation** — makes an otherwise-unstable orbit observable/reachable.
- **Non-invasiveness** — guarantees what you measured is the true system response, not a
  controller artefact.

## 2. Reference parameterisation

Represent the reference by a truncated Fourier series at frequency `ω` with `H` harmonics:

```
r(t) = A0 + Σ_{n=1..H} [ A_n cos(nωt) + B_n sin(nωt) ]
```

The continuation unknowns are the vector `u = (ω, A0, A1, B1, …, A_H, B_H)` (or a subset;
`A0` is often fixed to 0 for symmetric systems). Measure the response Fourier coefficients
`X = (X0, Xc_1, Xs_1, …)` by projecting `x(t)` onto the harmonic basis over an integer
number of periods (sliding-DFT / correlation against `cos nωt`, `sin nωt`).

## 3. The non-invasiveness zero problem

Define the residual between requested reference harmonics and measured response harmonics:

```
G(u) = X(u) − R(u) = 0
```

where `R(u)` collects the reference harmonics `(A_n, B_n)` and `X(u)` the corresponding
measured response harmonics at the *same* frequency `ω`. When `G(u) = 0`, the response
equals the reference at every controlled harmonic, so `e(t)` has no component at those
harmonics and the control is non-invasive there. This is the experimental analogue of a
periodic-orbit collocation/shooting residual, but evaluated by the rig.

Notes:
- Only harmonics *present in the reference* are directly controlled. Uncontrolled higher
  harmonics of the true orbit appear in `x(t)` but not `r(t)`; the controller must not
  fight them (see §4). Choose `H` large enough to capture the physically significant
  harmonics (odd harmonics dominate for a cubic/Duffing nonlinearity).
- The frequency `ω` is either a continuation parameter (autonomous/backbone-like problems
  need a phase/anchor condition) or externally imposed with an extra equation.

## 4. Controller design

Requirements: (i) stabilise the target orbit, (ii) have zero (or removable) gain at the
controlled harmonics so it can be driven non-invasive, (iii) inject minimal noise.

Common choices:
- **PD / PID** on `e(t)`: `f_ctrl = Kp·e + Kd·ė (+ Ki·∫e)`. Simple and robust. Derivative
  action needs clean velocity — filter or estimate, as differentiating a noisy laser
  signal injects broadband noise into the actuator.
- **Washout / high-pass** structure so the controller does not act on the DC/target.
- **Filtered reference tracking**: split the actuator command into a feedforward reference
  drive plus feedback correction; at convergence the correction → 0.

Gain tuning trades convergence rate and stabilisation margin against noise injection.
Target sensible gain/phase margins on the *linearised-around-operating-point* loop; retune
as the operating point moves along the branch if margins degrade near bifurcations.

## 5. Corrector: Newton on the harmonics

At fixed continuation parameter, solve `G(u) = 0` by Newton:

```
u_{k+1} = u_k − J(u_k)^{-1} G(u_k),   J = ∂G/∂u
```

The Jacobian `J` is not available analytically. Options (in increasing robustness to
noise):
1. **Finite differences** — perturb each component of `u`, remeasure `X`. Expensive
   (`dim(u)` extra settlings per Jacobian) and noise-sensitive.
2. **Broyden / secant update** — build `J` from successive residual/step pairs; refresh
   periodically. Much cheaper; the usual practical default.
3. **Surrogate regression** — fit `X(u)` locally (e.g. Gaussian-process regression, see
   `gaussian-process-continuation.md`) and differentiate the surrogate; also yields
   uncertainty estimates.

Each residual evaluation requires: set `u` → wait for transient decay → average over an
integer number of periods → project onto harmonics. Settling time dominates wall-clock
cost; size it from the closed-loop settling, not the open-loop `Q`.

## 6. Predictor–corrector along the branch

Use **pseudo-arclength continuation** to pass folds (where any single parameter is not
monotonic):

1. **Predict**: secant `u_pred = u_i + Δs·t̂`, with tangent `t̂` from the last two points
   (or nullspace of the extended Jacobian).
2. **Correct**: Newton on the augmented system
   ```
   G(u) = 0
   (u − u_pred)·t̂ − Δs = 0     (arclength constraint)
   ```
3. **Adapt** `Δs` from corrector iteration count / contraction.

This is what lets CBC walk around a saddle-node smoothly instead of jumping branches like
an open-loop sweep. See `derivative-free-arclength-cbc.md` for a variant that avoids
forming `J` at all.

## 7. Algorithm (stepped CBC)

```
initialise controller; pick H, ω0, small reference amplitude
find first solution: Newton on G(u)=0 at fixed ω0
obtain second solution (step a parameter) → tangent t̂
repeat:
    predict u_pred along t̂ with step Δs
    while not converged:
        apply reference r(t; u); wait settling; measure X(u)
        residual = [ X(u) − R(u) ; (u−u_pred)·t̂ − Δs ]
        update u via Newton/Broyden step
        safety check: displacement/current within limits, else abort → safe state
    store (u, X, stability); update t̂; adapt Δs
```

## 8. Common pitfalls

- **Insufficient harmonics** → residual non-invasiveness → measured branch is subtly
  wrong (controller silently loads the orbit). Increase `H`, check control-signal
  spectrum is flat at controlled harmonics.
- **Over-parameterised reference** → injects noise, ill-conditioned `J`. Include only
  harmonics with meaningful energy.
- **Frequency-coefficient scaling** — `ω` and harmonic amplitudes have different units and
  magnitudes; scale/precondition `u` so the Jacobian is well-conditioned.
- **Transient contamination** — averaging before decay biases `X`. Gate measurement on a
  settled-error criterion.
- **Branch jumping** near steep folds if `Δs` too large or margins too thin.

## 9. References

- J. Sieber, A. Gonzalez-Buelga, S. A. Neild, D. J. Wagg, B. Krauskopf, "Experimental
  continuation of periodic orbits through a fold", *Phys. Rev. Lett.* 100, 244101 (2008).
- J. Sieber, B. Krauskopf, "Control-based bifurcation analysis for experiments",
  *Nonlinear Dynamics* 51 (2008).
- D. A. W. Barton, J. Sieber, "Systematic experimental exploration of bifurcations with
  non-invasive control", *Phys. Rev. E* 87, 052916 (2013).
- D. A. W. Barton, "Control-based continuation: Bifurcation and stability analysis for
  physical experiments", *Mech. Syst. Signal Process.* 84 (2017) 54–64. arXiv:1506.04052.
- L. Renson, A. Gonzalez-Buelga, D. A. W. Barton, S. A. Neild, "Robust identification of
  backbone curves using control-based continuation", *J. Sound Vib.* 367 (2016).
- G. Abeloos et al., "Application of control-based continuation to a nonlinear structure
  with harmonically coupled modes", *Mech. Syst. Signal Process.* (2019). arXiv:1808.01865.
- G. Raze, G. Abeloos, G. Kerschen, "Experimental continuation in nonlinear dynamics:
  recent advances and future challenges" (2024). arXiv:2408.00138.

## Duffing rig

- SISO fit: actuator = base electromagnetic exciter (logical `out`; DAC mapping per
  AGENTS.md); controlled output = laser tip displacement (`laser`); optional secondary =
  stator coil pickup / `adc0` exciter-current monitor. Start CBC with the laser as `x`.
- The primary resonance moves with the air gap (AGENTS.md gives its range and the sample
  rate); at those values each period spans on the order of a thousand samples — ample for
  harmonic projection, and worth averaging over ≥ 10–20 periods.
- The magnet–stator attraction is the dominant (Duffing-type) nonlinearity → expect strong
  odd harmonics; start with `H = 3` (1st, 3rd, and keep 2nd to catch any asymmetry from
  air-gap bias), revisit from the measured control spectrum.
- The controller closes the loop *through the exciter*, exactly the instability path the
  project safety notes flag. Prerequisites before energised closed-loop CBC: firmware
  amplitude ceiling, output arming/lease, comms-loss and ADC-fault quieting, applied-output
  telemetry (see `todo.md` Future). The corrector's safety check (§7) must trip to the safe
  state on displacement/current excursion — a bad Jacobian step near a fold can command
  large drive.
- Reference/feedback path lives partly on-host and partly in firmware. The firmware already
  supports a Fourier-series/table excitation model; feed the reference `r(t; u)` through it
  and keep the Newton/arclength logic on the host (Julia) initially. Respect the safe
  operating limits in AGENTS.md.
- First CBC target: trace the primary-resonance frequency response at a fixed modest
  forcing, capturing the unstable middle branch between the two folds — the minimal result
  that proves non-invasive stabilisation works on this rig.
