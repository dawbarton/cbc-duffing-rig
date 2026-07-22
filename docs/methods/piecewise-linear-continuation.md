# Piecewise Linear Continuation

Implementation guidance for agents. Piecewise linear continuation (PLC) traces an
implicitly defined solution set using a simplicial approximation, requiring only residual
evaluations and small linear solves. It is particularly relevant to experimental
continuation because the residual is measured, derivatives are costly and noisy, and a
conventional Newton corrector may be the least reliable part of the workflow.

## 1. Principle

Let

```
F : R^n -> R^(n-k),     M = {u in R^n : F(u) = 0}.
```

If `F` is smooth and its Jacobian has full row rank on `M`, the zero set is locally a
`k`-dimensional manifold. PLC tiles the ambient variable space with `n`-simplices,
evaluates `F` at their vertices, and linearly interpolates those values inside each
simplex. It then walks through adjacent simplices whose piecewise linear interpolant has a
zero.

For the curve case `k = 1`, a simplex intersected by the approximate zero set normally has
an entry facet and an exit facet. Crossing the exit facet identifies the next simplex, so
the method follows folds without selecting a globally monotone continuation parameter.
It does not need a tangent predictor, an experimental Jacobian, or a nonlinear corrector.

PLC supplies only the continuation geometry. In an experiment it does not by itself
stabilise an unstable response: for CBC, the feedback controller still supplies
stabilisation and `F` is the measured non-invasiveness residual described in
`control-based-continuation.md`.

## 2. Piecewise linear residual

For a simplex with vertices `v_0, ..., v_n`, every point has barycentric coordinates
`t_i >= 0`, `sum(t_i) = 1`:

```
u = sum_i t_i v_i.
```

Interpolate the vertex labels rather than `F` itself:

```
F_tilde(u) = sum_i t_i F(v_i).
```

For smooth `F`, the local interpolation defect is second order in the simplex diameter,
provided curvature is bounded. The location of the inferred zero also depends on
transversality and conditioning; therefore grain-refinement studies, rather than the
formal interpolation order alone, must establish accuracy on measured data.

To test an `(n-k)`-face, retain its `n-k+1` vertices `w_j` and solve

```
sum_j beta_j F(w_j) = 0,
sum_j beta_j        = 1.
```

The face contains a zero of `F_tilde` when the square system is nonsingular and all
`beta_j` lie in `[0, 1]`. The approximate intersection is
`u_star = sum_j beta_j w_j`. A singular or ill-conditioned system means the face is
parallel, or nearly parallel, to the approximate zero set; treating such a result as a
reliable crossing can select the wrong topology.

## 3. Triangulation and marching

The Coxeter--Freudenthal--Kuhn (usually shortened to Freudenthal) triangulation divides a
regular cubical lattice into path simplices. In unit coordinates, one such simplex has the
staircase vertices

```
0,
e_(pi_1),
e_(pi_1) + e_(pi_2),
...,
e_(pi_1) + ... + e_(pi_n),
```

where `pi` is a permutation of the coordinate directions. This representation makes the
neighbour across any facet inexpensive to construct by a combinatorial pivot/reflection.
The lattice may be mapped to physical coordinates using a separate scale in each
dimension.

For a one-dimensional zero set, the marching operation is:

1. Find a simplex near a supplied point that has a transversal facet crossing.
2. Evaluate and store `F` at its vertices.
3. Test all facets other than the entry facet and locate an admissible exit crossing.
4. Return its barycentric interpolation point.
5. Pivot across that facet, reuse the shared vertex labels, evaluate only the new vertex,
   and repeat.

After initialisation, a one-dimensional path therefore needs one new residual evaluation
per simplex step, plus facet-sized linear solves. This is attractive when a residual
evaluation includes settling and averaging a physical experiment. Reusing each stored
measurement is also important with noise: remeasuring a nearly-zero vertex can otherwise
change a face classification and make adjacent simplices inconsistent.

## 4. Grain, scaling, and refinement

The **grain** is the simplex size. Smaller grain improves geometric fidelity and keeps
evaluations closer to the true manifold, but increases the number of experimental
operating points. A single scalar grain is appropriate only after the continuation
coordinates have been nondimensionalised. Otherwise, use a grain vector so that one
lattice step represents a comparable meaningful change in every coordinate.

Practical checks:

- Repeat a representative branch segment with the grain halved in every coordinate;
  compare both branch geometry and the true residual `F(u_star)`, not merely the
  interpolated residual, which is zero by construction.
- Monitor the condition number of each face system and reject or refine ambiguous
  crossings. A small residual does not rescue a poorly conditioned face classification.
- Use bounds and guarded residual evaluation so that every simplex vertex is safe and
  physically meaningful. PLC samples near the manifold, but its vertices are generally
  off it.
- Average enough periods at each vertex to make label uncertainty small relative to the
  change in `F` across a simplex. If noise is comparable to that change, increasing the
  grain may improve classification but worsen discretisation error; quantify this trade-off.
- Cache vertex labels together with acquisition metadata and diagnostics. For stochastic
  measurements, a deliberate replicate policy is preferable to accidental reevaluation.

The paper interprets the face solve as one Newton step using the finite-difference
Jacobian implicit in the vertex labels. Further approximate-Newton corrections can refine
`u_star`, but require extra residual evaluations and may leave the face. This refinement is
not part of the current Julia interface and should be evaluated separately from the base
marching method.

## 5. Julia implementation

[`SimplexContinuation.jl`](https://github.com/dawbarton/SimplexContinuation.jl) implements
the `k = 1` case for `f : R^n -> R^(n-1)`. Its main interface is

```
path = continuation(f, p, y0; grain = ..., maxsteps = ...)
```

where `f(x, p)` returns the residual, `x` contains every continued state and parameter,
`p` contains fixed parameters, and `path` is a lazy iterator. A scalar or per-coordinate
grain is accepted. The implementation builds a scaled Freudenthal simplex near `y0`,
tests facets in barycentric coordinates, transfers labels across each pivot, and evaluates
one new vertex per steady marching step.

Important current scope limits are: curves only (not general `k > 1` manifolds), fixed
grain, no experimental bounds or safety callback, no noise-aware crossing test, no Newton
refinement, and termination by failure to find an exit or by `maxsteps`. Wrap the residual
accordingly and test closure, domain exit, branch direction, and repeated-point behaviour
at the application level.

## 6. Algorithm (one-dimensional experimental curve)

```
choose scaled coordinates, grain, safe domain, initial point y0
define guarded residual F(u):
    apply u; wait for settling; acquire and average; check diagnostics
    return measured continuation residual
find a transversal Freudenthal simplex near y0 and label its vertices
repeat:
    test every facet except the entry facet
    select a well-conditioned exit with barycentric coordinates in [0, 1]
    emit the interpolated crossing and its true measured/validated residual
    pivot to the neighbouring simplex and reuse labels on the shared facet
    evaluate F only at the new vertex
    stop on safety fault, domain exit, closure, missing/ambiguous exit, or step limit
validate the branch with a smaller grain and repeated measurements
```

## 7. Trade-offs and failure modes

- **Advantage:** no supplied derivatives or nonlinear solves; folds are traversed through
  local topology, and the steady marching cost is one new experimental evaluation per
  simplex for a curve.
- **Approximation bias:** returned points zero the interpolant, not necessarily the measured
  residual. Coarse simplices round high-curvature branches and may alter nearby or
  self-intersecting features.
- **Noise sensitivity:** noisy labels can create, remove, or multiply apparent facet
  crossings. Caching makes the constructed complex consistent but does not make an
  incorrect label accurate.
- **Conditioning:** a facet almost parallel to the zero set produces an unstable crossing
  location. Grain reduction alone may not fix an unfavourable orientation.
- **Dimension:** the number of facets and linear-algebra cost grow with ambient dimension;
  experimental initialisation also needs `n+1` vertex labels. Use the smallest residual and
  reference parameterisation that preserves non-invasiveness.
- **Direction and topology:** a basic curve iterator may follow either orientation, stop at
  a degeneracy, or revisit a closed component. Explicit bookkeeping is needed for robust
  branch coverage.

## 8. References

- M. E. Henderson, R. Melville, "Piecewise Linear Continuation: Derivative-free Manifold
  Generation" (2023 preprint). doi:10.21203/rs.3.rs-3612152/v1.
- E. L. Allgower, P. H. Schmidt, "An algorithm for piecewise-linear approximation of an
  implicitly defined manifold", *SIAM J. Numer. Anal.* 22 (1985) 322--346.
- E. L. Allgower, K. Georg, "Piecewise linear methods for nonlinear equations and
  optimization", *J. Comput. Appl. Math.* 124 (2000) 245--261.
- E. L. Allgower, K. Georg, *Introduction to Numerical Continuation Methods*, SIAM
  (2003).
- D. A. W. Barton, [`SimplexContinuation.jl`](https://github.com/dawbarton/SimplexContinuation.jl),
  Julia implementation of derivative-free one-dimensional simplex continuation.

## Duffing rig

- Use PLC as the branch-following layer around CBC, not as a replacement for feedback
  stabilisation. With `m` controlled non-invasiveness residuals, take a minimal continued
  vector such as `u = (frequency, m reference coefficients)`, giving
  `F : R^(m+1) -> R^m`; fix other experiment settings outside the continuation vector.
- Keep the residual evaluation host-side in Julia: set the Fourier reference/forcing through
  the existing host API, wait for the controlled orbit to settle, project the laser response,
  and return the non-invasiveness harmonics. The firmware remains responsible for its hard
  real-time safety gate.
- Start with a reduced harmonic parameterisation. Although each path pivot adds only one
  new vertex evaluation, high ambient dimension increases initialisation cost, the number
  of facet tests, and the chance that one noisy harmonic changes the crossing decision.
- PLC deliberately evaluates off-manifold simplex vertices. Before applying a vertex,
  enforce the operating limits and fault response in `AGENTS.md`; perform the prescribed
  health checks around each capture, and abort immediately on instability, a safety trip,
  or anomalous real-time diagnostics.
- Choose per-coordinate grain from repeatability and sensitivity tests at a fixed,
  confirmed rig configuration. Frequency and Fourier coefficients have different units;
  an unscaled scalar grain would give a physically arbitrary triangulation.
- First comparison: trace the same primary-response fold segment with
  `SimplexContinuation.jl` PLC and Broyden/pseudo-arclength CBC, then compare residual
  norm, branch scatter, evaluations per accepted point, elapsed acquisition time, and
  sensitivity to halving the PLC grain.
