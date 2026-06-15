#!/usr/bin/env python3
"""IMML mechanism -> Mermaid dataflow graph (top-down: what's tested at the top, final score at the bottom).

A complement to the railroad (grammar) diagrams: this shows the *computation* — how data flows from the
miner's submission and the ground truth, through guards / metrics / aggregation / smoothing / burn, to the
weights set on chain. Each `Metric` with a `spec:` is expanded into its own little sub-graph.

The *scoring topology* is graphical too: the diagram branches on `composition.shape` so each combinator
renders distinctly rather than as one generic fan-in. `pipeline` is the linear flow; `multiplex` splits the
submission into parallel tracks and merges them at an explicit combine step (labelled by
`sub_competitions.structure`); `gated` draws the pass/fail condition as an if-then gate on the score;
`multiplicative` draws an explicit `×` product node (quality × penalties); `opaque` is drawn honestly as a
single black box rather than a pretend metric pipeline. The visual vocabulary is documented in the legend
in docs/learn/mental-model.md.

Usage:
    graph.py instances/corpus/<subnet>.yaml        # print a Mermaid flowchart for one subnet
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

from imml_core import _pascal
import metric_spec


def _lbl(s: str) -> str:
    return str(s).replace('"', "'").replace("\n", " ")


# Signal-name heuristics for the conditional shapes: which signals act as a pass/fail gate (gated) vs a
# multiplier/penalty term (multiplicative). All multiplicative signals in the corpus are higher_is_better,
# so `direction` can't split them — the signal *name* carries the role (…_gate, …_bonus, …_multiplier).
_GATE_KW = re.compile(r"gate|verif|valid|pass|eligib|thresh|qualif|checklist|proof|liveness|whitelist|filter|success_rate", re.I)
_MULT_KW = re.compile(r"penal|multiplier|malus|discount|bonus|factor|decay|punish|rarity", re.I)


# The metric is the typed hole. Its sub-structure lives in three places, in priority order: an authored
# `extensions.spec` (none in the corpus yet), the bespoke-tail map keyed by `metric_kind_other`, and the
# named-family map keyed by `metric_kind`. We resolve all three (mirroring simulate._signal_spec) so the
# gallery's metric box can be opened into its sub-graph for the 20 named kinds + ~85% of the tail — not
# just the (currently empty) authored-spec case. Kept self-contained: graph.py is a docs concern, and the
# simulator is deliberately excluded from the published site.
_ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, key: str) -> dict:
    try:
        return {r[key]: r["spec"] for r in (yaml.safe_load((_ROOT / "vocab" / name).read_text()) or [])
                if isinstance(r, dict) and r.get("spec")}
    except Exception:    # noqa: BLE001 — a missing/garbled vocab file just means no expansion
        return {}


_TAIL = _load("metric-tail-specs.yaml", "raw")
_KIND = _load("metric-kind-specs.yaml", "kind")


def _resolve_spec(sig: dict) -> str | None:
    return ((sig.get("extensions") or {}).get("spec")
            or _TAIL.get(sig.get("metric_kind_other"))
            or _KIND.get(sig.get("metric_kind")))


def mechanism_mermaid(ir: dict) -> str:
    comp = ir.get("composition") or {}
    overlays = set(comp.get("overlays") or [])
    shape = comp.get("shape") or "pipeline"
    signals = [s for s in (ir.get("scoring_signals") or []) if isinstance(s, dict)]
    gts = [g for g in (ir.get("ground_truth_sources") or []) if isinstance(g, dict)]
    agg = ir.get("aggregation") or {}
    ws = ir.get("weight_setting") or {}
    sm = ws.get("smoothing") or {}
    guards = [a for a in (ir.get("anti_gaming") or []) if isinstance(a, dict)]
    burn = agg.get("burn_allocation") or {}
    subc = ir.get("sub_competitions") or {}
    method = _pascal(agg.get("method") or "proportional")

    L = ["flowchart TD"]
    E: list[tuple] = []                           # 2-tuple (a,b) or 3-tuple (a,b,label)

    # --- inputs (top) ---
    L.append('  SUB(["submission"]):::in')
    if gts:
        L.append(f'  GT(["groundTruth: {_lbl(", ".join(_pascal(g.get("kind")) for g in gts[:3]))}"]):::in')

    # submission passes through guards first
    src = "SUB"
    if guards and "guards" in overlays:
        L.append(f'  G{{{{"@guards: {_lbl(", ".join(_pascal(a.get("kind")) for a in guards[:3]))}"}}}}:::ov')
        E.append(("SUB", "G"))
        src = "G"

    # The metric is the typed hole — drawn identically in every topology (shape = role; dashed = bespoke),
    # with its spec sub-graph opened when there's real structure. Only the *downstream wiring* changes per
    # shape, so the hole-expansion (the corpus' 367 sub-graphs) is preserved across all combinators.
    def metric_node(i: int, s: dict, feed: str) -> str:
        mid = f"M{i}"
        fam = s.get("metric_family") or s.get("metric_kind") or "other"
        spec = _resolve_spec(s)
        # Solid when it's a known family/kind, dashed when it's the bespoke escape hatch (`extern` leaf, or
        # the `other` tail). The dashed/solid distinction stays honest about *bespoke-ness* and is
        # independent of whether we can reconstruct a structural spec.
        bespoke = s.get("extern") or fam == "other"
        if bespoke:
            desc = _lbl(s.get("metric_kind_other") or ("extern" if s.get("extern") else "other"))
            L.append(f'  {mid}[["the metric: {desc[:44]}"]]:::holex')
        else:
            L.append(f'  {mid}[["the metric: {_lbl(fam)}"]]:::hole')
        E.append((feed, mid))
        if gts:
            E.append(("GT", mid))
        if spec:                                  # expand the spec's own dataflow into a subgraph
            try:
                body, root = metric_spec.to_mermaid(spec, prefix=f"m{i}_")
                if "-->" in body:                 # only open the hole when there's real structure to show;
                    L.append(f'  subgraph sg{i} ["spec: {_lbl(spec[:48])}"]')   # a bare `submission.x`
                    L.append("  " + body.replace("\n", "\n  "))                 # projection adds nothing the
                    L.append("  end")                                          # box label doesn't already say.
                    E.append((root, mid))
            except Exception:                     # noqa: BLE001 — never let a bad spec break the graph
                pass
        return mid

    # --- scoring topology: branch on composition.shape so each combinator renders STRUCTURALLY distinctly
    #     rather than as one generic flat fan-in. Each branch produces a `score` node that the shared
    #     tail (smooth/burn/publish) attaches to.
    pass_lbl = ""                                 # label for the first tail edge (gated pass-branch)
    if shape in ("opaque", "overlay_only"):
        # Drawn honestly as a single black box: the mechanism is one undocumented extern, not a pretend
        # metric pipeline. No metric holes are invented — the box IS the scorer.
        names = ", ".join(_lbl(s.get("metric_kind_other") or s.get("name") or s.get("metric_kind") or "extern")
                          for s in signals[:2]) or "undocumented"
        tag = "overlay-only — no live scorer" if shape == "overlay_only" else "opaque mechanism"
        L.append(f'  BOX["<b>{tag}</b><br/>{names[:60]}"]:::box')
        E.append((src, "BOX"))
        if gts:
            E.append(("GT", "BOX"))
        score = "BOX"

    elif shape == "multiplex":
        # N parallel tracks routed from the submission, then merged by an explicit combine step. The split
        # is labelled by sub_competitions.structure (+count); the combine by the aggregation method.
        n = subc.get("count")
        struct = _pascal(subc.get("structure") or "tracks")
        slab = f"split into tracks: {struct}" + (f" ×{n}" if n else "")
        L.append(f'  SPLIT[/"{_lbl(slab)}"\\]:::comb')
        E.append((src, "SPLIT"))
        L.append(f'  COMBINE[\\"combine tracks: {_lbl(method)}"/]:::comb')
        mids = [metric_node(i, s, "SPLIT") for i, s in enumerate(signals)]
        if not mids:
            E.append(("SPLIT", "COMBINE"))
        for m in mids:
            E.append((m, "COMBINE"))
        score = "COMBINE"

    elif shape == "gated":
        # A pass/fail gate multiplies a magnitude: the gate signals become an if-then on the aggregated
        # score (pass -> through, fail -> 0). The remaining signals are the magnitude being gated.
        gate_sigs = [s for s in signals
                     if _GATE_KW.search((s.get("name") or "") + " " + (s.get("metric_kind") or ""))]
        mag_sigs = [s for s in signals if s not in gate_sigs]
        L.append(f'  AGG["aggregate: {_lbl(method)}"]:::stage')
        mids = [metric_node(i, s, src) for i, s in enumerate(mag_sigs)]
        for m in mids:
            E.append((m, "AGG"))
        if not mids:
            E.append((src, "AGG"))
        glabel = _pascal(gate_sigs[0].get("name")) if gate_sigs else "pass / fail"
        L.append(f'  GATE{{"gate: {_lbl(glabel)}?"}}:::gate')
        for j, s in enumerate(gate_sigs):
            E.append((metric_node(900 + j, s, src), "GATE"))
        E.append(("AGG", "GATE"))
        L.append('  ZERO(["fail → 0, no reward"]):::zero')
        E.append(("GATE", "ZERO", "fail"))
        score = "GATE"
        pass_lbl = "pass"

    elif shape == "multiplicative":
        # Explicit product: quality × penalties/multipliers. A single zero zeroes the miner. Multiplier
        # / penalty terms (matched by name) feed the product on a labelled edge; the rest are the base.
        L.append('  PROD(("× product")):::op')
        mids = []
        for i, s in enumerate(signals):
            m = metric_node(i, s, src)
            E.append((m, "PROD", "×") if _MULT_KW.search(s.get("name") or "") else (m, "PROD"))
            mids.append(m)
        if not mids:
            E.append((src, "PROD"))
        score = "PROD"

    else:  # pipeline (and any unknown shape): the linear flow — metrics fan into the aggregate.
        L.append(f'  AGG["aggregate: {_lbl(method)}"]:::stage')
        mids = [metric_node(i, s, src) for i, s in enumerate(signals)]
        for m in mids:
            E.append((m, "AGG"))
        if not mids:
            E.append((src, "AGG"))                 # degenerate: no metric -> flow straight through
        score = "AGG"

    # --- shared tail: smooth -> burn -> publish -> weights (real regardless of the combinator) ---
    last = score
    if sm and (sm.get("kind") or "none") != "none":
        L.append(f'  SM["smooth: {_lbl(_pascal(sm.get("kind")))}"]:::stage')
        E.append((last, "SM", pass_lbl) if pass_lbl else (last, "SM"))
        last, pass_lbl = "SM", ""
    if "burn" in overlays and burn:
        L.append('  BURN{{"@burn: redirect a fraction"}}:::ov')
        E.append((last, "BURN", pass_lbl) if pass_lbl else (last, "BURN"))
        last, pass_lbl = "BURN", ""
    L.append(f'  PUB["publish: {_lbl(_pascal(ws.get("on_chain_call") or "set_weights"))}"]:::stage')
    E.append((last, "PUB", pass_lbl) if pass_lbl else (last, "PUB"))
    L.append('  OUT(["weights on-chain = final score"]):::out')
    E.append(("PUB", "OUT"))
    if "state" in overlays:                       # state is a side-channel, drawn as a note into the scorer
        L.append('  ST(["@state: carried across rounds"]):::note')
        E.append(("ST", score))

    for e in E:
        if len(e) == 3 and e[2]:
            L.append(f'  {e[0]} -->|"{_lbl(e[2])}"| {e[1]}')
        else:
            L.append(f"  {e[0]} --> {e[1]}")
    # visual vocabulary (shape = role, colour = layer; mirrored in docs/learn/mental-model.md's legend):
    #   in = inputs · hole/holex = the metric (resolved / extern) · stage = pipeline step · comb = the
    #   multiplex split/combine (trapezoids) · gate = the gated if-then (diamond) · op = the multiplicative
    #   product (circle) · box = the opaque black box · ov = overlays · out = on-chain weights · note/zero.
    L += ["  classDef in fill:#e6f0ff,stroke:#4488cc,color:#102a43;",
          "  classDef hole fill:#efe3ff,stroke:#7a3cc8,stroke-width:3px,color:#2a1a4a;",
          "  classDef holex fill:#efe3ff,stroke:#7a3cc8,stroke-width:3px,stroke-dasharray:5 3,color:#2a1a4a;",
          "  classDef stage fill:#e3f6f3,stroke:#2a9d8f,color:#0b3b35;",
          "  classDef comb fill:#d9f2ee,stroke:#2a9d8f,stroke-width:2px,color:#0b3b35;",
          "  classDef gate fill:#d9f2ee,stroke:#2a9d8f,stroke-width:2px,color:#0b3b35;",
          "  classDef op fill:#d9f2ee,stroke:#2a9d8f,stroke-width:2px,color:#0b3b35;",
          "  classDef box fill:#3a3a4a,stroke:#15151f,stroke-width:2px,color:#f5f5f5;",
          "  classDef ov fill:#fff3d6,stroke:#c9a227,color:#5c4a00;",
          "  classDef out fill:#e6ffe6,stroke:#3a3,color:#0a3a0a;",
          "  classDef zero fill:#fde8e8,stroke:#c0392b,color:#7a1f15;",
          "  classDef note fill:#f3f3f3,stroke:#bbb,color:#333;"]
    return "\n".join(L)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    ir = yaml.safe_load(Path(sys.argv[1]).read_text())
    print(mechanism_mermaid(ir))
