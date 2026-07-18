# Derivative-Free Arclength CBC

Implementation guidance for agents. This variant performs pseudo-arclength continuation of
the experimental solution branch **without forming the experimental Jacobian** at all,
removing the most fragile and expensive part of standard CBC (finite-difference Jacobian
estimation on a noisy rig). It is the newest method in the 2024 review and has supporting
convergence theory (2025).

## 1. Motivation

Standard CBC corrects `G(u)=0` with Newton, needing `J = ∂G/∂u`. On a physical rig `J` is
estimated by finite differences (many extra settlings, noise-amplifying) or Broyden updates
(can stall). Derivative-free arclength CBC replaces the Newton corrector with an iteration
that only uses residual evaluations plus the geometry of the arclength constraint, so no
Jacobian is assembled.

## 2. Ingredients

- **Residual** `G(u)` — the non-invasiveness residual (measured minus reference harmonics),
  exactly as in `control-based-continuation.md`.
- **Arclength constraint** — augment with `N(u) = (u − u_pred)·t̂ − Δs = 0` so folds are
  passable.
- **Derivative-free corrector** — solve the augmented system `[G; N] = 0` with a method
  that needs only function values: e.g. a secant/quasi-Newton scheme that builds directional
  information from the continuation steps themselves, a Nelder–Mead/pattern-search style
  local corrector, or a fixed-point contraction designed so that non-invasive tracking is a
  stable equilibrium. The 2024 arclength CBC and the 2025 analysis provide the specific
  update with path-following guarantees for the autonomous case.

Key idea: the tangent `t̂` and successive residuals already encode local sensitivity;
reuse them (Broyden-like *implicit* Jacobian, or a genuinely Jacobian-free contraction)
rather than paying for explicit finite differences.

## 3. Predictor–corrector loop

```
have two converged points u_{i-1}, u_i → secant tangent t̂ = (u_i − u_{i-1})/‖·‖
predict: u_pred = u_i + Δs · t̂
correct (derivative-free):
    repeat:
        evaluate residual G(u) on the rig (set reference, settle, project harmonics)
        form augmented residual F = [ G(u) ; (u − u_pred)·t̂ − Δs ]
        update u using function-value-only step (implicit-secant / pattern search /
            contraction), no explicit Jacobian
        safety check: displacement/current in limits, else abort → safe state
    until ‖F‖ < tol
adapt Δs from iteration count; append point; update t̂
```

## 4. Trade-offs

- **Pros**: no finite-difference Jacobian (fewer rig evaluations per step, less noise
  amplification); simpler to implement robustly; degrades gracefully near folds.
- **Cons**: derivative-free corrector may need more iterations to converge each point than a
  good Newton step when the Jacobian is cheap/clean; convergence theory is strongest for
  autonomous/path-following settings — validate empirically for forced-response branches.
- **Relation to other variants**: complementary to adaptive-filtering CBC (which removes the
  discrete loop entirely) and to GP-regression continuation (which *approximates* the
  Jacobian with uncertainty rather than avoiding it). Choose per goal: speed/robustness vs
  explicit sensitivity/UQ.

## 5. References

- G. Raze, G. Abeloos, G. Kerschen, "Experimental continuation in nonlinear dynamics:
  recent advances and future challenges" (2024). arXiv:2408.00138 — introduces experimental
  derivative-free arclength control-based continuation and demonstrates it on an electronic
  Duffing oscillator.
- "Theoretical analysis of a derivative-free control-based continuation algorithm with
  path-following capability for autonomous systems" (2025). arXiv:2505.02262 — convergence /
  path-following analysis.
- E. L. Allgower, K. Georg, *Introduction to Numerical Continuation Methods*, SIAM (2003) —
  pseudo-arclength / predictor–corrector background.
- H. Dankowicz, F. Schilder, *Recipes for Continuation*, SIAM (2013) — continuation
  framework background (COCO).

## Duffing rig

- Strong candidate for early adoption on this rig precisely because it sidesteps
  finite-difference Jacobians, which would otherwise mean many extra settling periods per
  continuation step at 5–10 Hz — slow and noise-sensitive on a mechanical rig.
- The electronic-Duffing demonstration in the 2024 review is the closest published analogue
  to this system; use its reported behaviour as a sanity reference for what a healthy branch
  trace should look like.
- Implement host-side (Julia) on top of the same non-invasive residual used by standard CBC;
  it reuses the firmware Fourier/table excitation and the harmonic projection unchanged —
  only the corrector differs.
- Same closed-loop safety envelope as CBC (drive through the exciter): amplitude ceiling,
  arming/lease, fault quieting, per-iteration safety trip to safe state. A derivative-free
  corrector can take larger exploratory steps than Newton, so the per-evaluation safety
  bound matters more, not less.
- Suggested use: once standard CBC has proven non-invasive stabilisation on the
  primary-resonance branch, switch the corrector to derivative-free arclength and compare
  points-per-branch, settling count, and branch scatter — a direct efficiency/robustness
  data point for the method comparison.
