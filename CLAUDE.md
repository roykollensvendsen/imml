# CLAUDE.md — IMML

Guidance for working in this repository: **IMML**, a declarative language for Bittensor incentive
mechanisms (a versioned JSON Schema / IR, a textual surface + grammar, lift/compile/format/generate
tooling, a metric ontology, a 189-subnet corpus, and a Qt-styled, Diátaxis-structured docs site).

**Start here:** the repo-scoped skills capture the workflows and invariants —
- **`imml-dev`** — extend the language (schema/grammar/ontology/generator/tooling); the hard invariants
  and the gates every change must pass.
- **`imml-docs`** — build / preview / deploy the documentation site.

Also read `spec/04-imml-language.md` (the language) and `spec/05-imml-style.md` (coding conventions).

## Hard invariants (do not break)
- **Round-trip fidelity = 100%.** `tooling/coverage.py` lifts every IR to IMML, compiles back, and
  compares the *structural signature* (`imml_core.signature`, which excludes prose/provenance). `lift`
  and `compile` must stay inverse over that signature.
- **Governed versioning.** No schema field / enum value / ontology entry without ≥2× evidence + a
  CHANGELOG entry + a VERSION (and `$id`) bump + re-stamping & re-validating all instances.
- **The metric tail is flat — don't bloat enums.** Use the `other` + `*_other` escape hatch; canonicalize
  downstream (`vocab/metric-ontology.yaml`). Extraction stays faithful (ELT); the ontology resolves
  families at read time and never mutates the raw level.
- **Extraction is evidence-based.** Every non-trivial field in an `extracted` instance needs a
  `provenance.evidence` item (source_path + line_ref + verbatim quote); unknowable → `unresolved`, never
  guessed.

## Gates (keep green)
```bash
./.venv/bin/python tooling/validate.py instances/ templates/blank-instance.yaml   # 190/190 valid
./.venv/bin/python tooling/coverage.py instances/                                  # PASS (100% fidelity, 95.8% structural)
./.venv/bin/python tooling/generate.py --check instances/                          # 53/53
./.venv/bin/mkdocs build --strict                                                  # docs clean (~221 pages)
```
A pre-commit hook (`tooling/pre-commit.sh`) enforces `validate.py` on any `instances|schema|templates`
change; a commit-msg hook (`tooling/commit-msg.sh`) enforces [Conventional Commits](https://www.conventionalcommits.org/)
(also checked in CI by `.github/workflows/commitlint.yml`). Install both:
`ln -sf ../../tooling/pre-commit.sh .git/hooks/pre-commit && ln -sf ../../tooling/commit-msg.sh .git/hooks/commit-msg`.

Commits follow `<type>[(scope)][!]: <description>` (e.g. `feat(lang): …`, `fix(tooling): …`, `docs: …`),
one commit per completed task.

## Current state (handoff)
Phases complete and committed (see `docs/understand/pipeline.md` — "The full picture" — for the consolidated map):
- **schema→IR v1.2.0** + the **IMML language**, fully QML-faithful (`Mechanism { id: … }`, PascalCase
  types, `groundTruth`/`publish`, list-valued `score`/`groundTruth`, `Metric { … }`); lift/compile
  round-trip at **100% over 189 subnets**. The metric ontology (95.8% structural); the generator (53/53).
- **Metric spec language (Layer 2)** — `tooling/metric_spec.py`: a typed combinator algebra for the metric
  hole with parser + sort type-checker + **evaluator**. 85% of the 75-metric tail expressible at 0.7
  generators each (`vocab/metric-tail-specs.yaml`); all 20 named kinds spec'd (`metric-kind-specs.yaml`).
  Wired into the surface as `Metric { spec: "…" }`, validated at compile, stored in the `extensions` hatch
  (no schema field yet — accumulating ≥2× evidence). Spec: `spec/06-metric-spec-language.md`.
- **Dataflow diagrams** — `tooling/graph.py` (mechanism) + `metric_spec.to_mermaid` (spec) → Mermaid, live
  on each example page's Dataflow tab. A **visual vocabulary** (shape = role, colour = layer): the metric is
  a purple double-box (the hole) — solid when it resolves to a known family, dashed when bespoke
  (`extern`/`other`); aggregate/smooth/publish share one teal pipeline layer; inputs blue, `@overlays` a
  yellow hexagon, on-chain weights green. Legend in `docs/learn/mental-model.md`; verified light + dark.
- **Incentive simulator (chain-grounded, validated)** — a suite, NOT published to the docs site
  (per-subnet "gameable" verdicts are reputationally sensitive). Optional deps in
  `tooling/requirements-sim.txt` (cadCAD + bittensor, now installed in `.venv`).
  - `tooling/simulate.py`: strategic miners vs a mechanism's structure → honest-dominance / gameability /
    Gini / sybil-resistance; drives 173/180 by their real spec. Reports concentration at two layers: the
    *scoring-layer* Gini (within active miners) and the *effective* Gini that folds the real dTAO emission
    split (18% owner / 41% validators-by-stake / 41% miners-by-score, from `chain.py`'s measured stake
    concentration) over the full registered-uid set — the credible one (validation r≈0.73 vs scoring's
    ≈0). Modes: `--corpus`; `--attack` (best-response search + Goodhart field-gaming, guard-aware);
    `--calibrate` (scoring + effective Gini vs real emission Gini); `--equilibrium` (replicator dynamics
    with a mutation floor → is honest the *attractor*, or does the population collapse to a dominant cheat?
    `--equilibrium --corpus` checks it vs the one-shot verdict: 91% agree over 180, the 15 disagreements
    split 2 fragile / 13 lenient — equilibrium is frequency-dependent, the better predictor of real play).
  - `tooling/chain.py`: REAL finney economics per netuid (recycle/burn/emission/kappa/stake-Gini/
    top-bloc stake fractions/sybil_cost_ratio/validator_emission_frac), cached in `vocab/chain-params.json`
    (~103 subnets warmed). `cached()` is the cache-only accessor the sim uses (no live fetch).
  - `tooling/simulate_cadcad.py`: cadCAD Monte-Carlo; modes `--sweep-reg` (registration barrier threshold),
    `--temporal` (ramp-then-defect under EMA), `--yuma` (validator collusion on real stake + verified
    clipped-median consensus — finding: one validator with 55–88% stake exceeds κ on most subnets).
  - `tooling/validate_sim.py`: correlates verdicts vs real chain over 148 subnets. **FINDING:
    sybil-resistance verdicts AGREE with reality, and concentration is now credible too — the *scoring-only*
    Gini stays uncorrelated (r≈0.06), but the *effective* Gini (validator-stake dividend + registered-uid
    tail folded in) correlates at r≈0.73 and recovers the level (median 0.945 vs real 0.984). This confirms
    the diagnosis: real reward concentration is validator-stake-driven, not scoring-driven — and the
    effective layer captures it. Trust the effective Gini; the scoring-layer Gini is the within-miner signal.**
- **Research** — `reports/metric-language-research.md`: adversarially-verified, primary-sourced — the tail
  is a compressibility/MDL question, not impossibility.
- **Documentation (zero-to-hero, Diátaxis)** — overhauled and live at the URL below. The reader spine, all
  hand-written natively in `docs/` on the existing Material/snippets/mermaid infra (nav in `docs/SUMMARY.md`):
  `learn/` (Why IMML, a visual **mental-model**, a 7-step hands-on **tutorial** that designs → compiles →
  generates → simulates a fresh example — verified end-to-end against the tooling), `reference/glossary.md`,
  task-oriented `guides/` how-tos (author/read/extract/generate/simulate), and `understand/` (the old dense
  `pipeline.md` split into full-picture / metric-hole / simulator / theory). The 189-example gallery is now
  indexed by **use case** via `vocab/use-case-tags.yaml` (a governed, hand-curated map — seeded by a keyword
  heuristic then corrected; `docs/gen/build.py` reads it for the column + grouped nav; refine an assignment
  there if a subnet looks mis-binned). The simulator suite stays OUT of the published site (per-subnet
  "gameable" verdicts are sensitive). Tutorial/snippet sources live in `docs/_snippets/` (excluded from the
  build via `mkdocs.yml` `exclude_docs`). Deploy is automatic on push to `main` (`.github/workflows/docs.yml`
  → mike → gh-pages, versioned by schema VERSION).
- **Process** — Conventional Commits enforced (commit-msg hook + CI), subjects ≤72 chars (now a hard fail);
  one commit per task.

QML-faithful coding conventions + `imml-fmt`; docs live at https://roykollensvendsen.github.io/imml/. This
repo is the source of truth; referenced as the `incentive-schema` submodule in `~/mining/sn109`.

## Backlog / next work
1. Reconcile the rest of `lang/imml.ebnf` with the live grammar (root/metric/gt/publish/smoother now match;
   the `multiplex` track/combine surface still differs).
2. Comment-preserving formatter (`fmt.py` currently drops `#` comments).
3. Generation beyond the pipeline archetype (multiplex/gated/tournament) — and wire the spec evaluator into
   generated validator code (`spec:` → a runnable `score_i()`).
4. **Simulator** — chain economics, cadCAD, best-response/Goodhart, temporal, Yuma collusion, validation,
   **concentration (the effective Gini layer, validation r≈0.73)**, and **equilibrium dynamics
   (`--equilibrium`: replicator with a mutation floor; 91% agreement with the one-shot verdict over 180,
   the better predictor of real play)** are all complete (see Current state). Next, in priority order:
   (a) the residual blocker is **per-subnet submission semantics** (`submission.<field>` is one stylized
   quality axis; needs a real validator — not closeable from the corpus); (b) the **honest_dominant /
   gameable_by verdicts are still unvalidated** against chain (no clean on-chain "is this gamed" signal —
   sybil-resistance and concentration are validated, these are not). Also: promote `spec:` to a governed schema
   field once ≥2× corpus instances use it. (Tried and rejected: a per-subnet emission split from chain —
   `chain.py` now records `validator_emission_frac` — A/B'd neutral over 148 subnets (effective-Gini r
   0.750→0.746); the validator/miner split is second-order vs stake concentration + the uid tail, and a
   single snapshot is mid-epoch noisy, so the flat dTAO constants (18/41/41) are retained. A multi-epoch
   average might carry signal a snapshot doesn't.)
5. Full-subnet description — an extended language that describes the **whole subnet**, not just the
   incentive mechanism: extend the IR to facets (chain_config/architecture/economics/health). `bittensor`
   is installed and finney is reachable (`tooling/chain.py` is the adapter), so chain facets are buildable.
   Keep the macro/ecosystem layer HERE, not in the IM grammar — the core language stays disciplined to the
   *mechanism*; this layer makes a subnet's *value* legible, not just its scoring.
   Concrete content for the **economics/demand facet** (distilled from a design discussion on Bittensor
   liquidity/competition — the conclusion: the real bottleneck is *legibility*; subnets are a market for
   lemons, and "better signal" — not "fewer subnets" — is the cure, so a full-subnet language is exactly the
   instrument to make value legible):
   - **demand-legibility axis** — derivable TODAY from `ground_truth_sources.kind`: external-demand-grounded
     (`organic_traffic`, `real_engagement`, `market_data`) vs synthetic/internal (`deterministic_dataset`,
     `llm_judgment`, `reference_model`). I.e. "is the subnet scored against real demand, or a constructed
     challenge?" — the cheapest first signal, no new data needed.
   - **revenue source** — self-emission (subsidy) vs external / cross-subnet payment (real derived demand);
     and utilization (serving real jobs vs proving idle capacity).
   - **served market** (workload + buyer) for cross-subnet differentiation / substitutability —
     `vocab/use-case-tags.yaml` is the first cut at this axis.
   - **scale / liquidity** — pool depth, validator coverage (from `tooling/chain.py`).
   Natural but data-blocked follow-on: an *ecosystem-level* simulator (subnets competing for finite external
   capital + emission — "how many compute subnets is stable?"), distinct from today's intra-subnet sim.
6. CI hygiene — bump `actions/checkout@v4` → `@v5` and `actions/setup-python@v5` → `@v6` in
   `.github/workflows/{docs,commitlint}.yml` (GitHub deprecated Node 20 for actions as of 2026-06-16;
   they still run forced onto Node 24, but the action versions should be updated). Low priority.
7. **Graph the metric's internals (active thread — do this next).** Today `graph.py` expands a metric into
   its sub-dataflow only when the signal carries an authored `extensions.spec`, and **0 corpus signals do**,
   so in the gallery the metric is always an opaque box. But `vocab/metric-kind-specs.yaml` (20 kinds) +
   `metric-tail-specs.yaml` (75 raws) hold specs the simulator already resolves (`simulate._signal_spec`:
   `extensions` → tail → kind). Wire `graph.py` to resolve from vocab too (not just `extensions`) and open
   the hole into its sub-graph via the existing `metric_spec.to_mermaid` — lights up the metric for the 20
   kinds + ~85% of the tail. Most specs are shallow (~0.7 generators) so the sub-graphs are small, but even
   `rate(submission.correct)` beats a bare `accuracy` label. Plan: before/after on a shallow + a composite
   metric before rolling out to all 189. (Minor side-question: give the abstract anatomy diagram in
   `mental-model.md` a light colour hint too, or keep it deliberately abstract.)

Re-running bulk extraction needs the `academia-archives` corpus (not vendored): set
`ARCHIVES=/path/to/academia-archives/repos` for `tooling/list-pending.sh`. The `extract-corpus` workflow
script lives in the `~/mining/sn109` workspace, not in this repo.
