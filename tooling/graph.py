#!/usr/bin/env python3
"""IMML mechanism -> Mermaid dataflow graph (top-down: what's tested at the top, final score at the bottom).

A complement to the railroad (grammar) diagrams: this shows the *computation* — how data flows from the
miner's submission and the ground truth, through guards / metrics / aggregation / smoothing / burn, to the
weights set on chain. Each `Metric` with a `spec:` is expanded into its own little sub-graph.

Usage:
    graph.py instances/corpus/<subnet>.yaml        # print a Mermaid flowchart for one subnet
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

from imml_core import _pascal
import metric_spec


def _lbl(s: str) -> str:
    return str(s).replace('"', "'").replace("\n", " ")


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

    L = ["flowchart TD"]
    E: list[tuple[str, str]] = []

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

    # --- metrics ---
    metric_ids = []
    for i, s in enumerate(signals):
        mid = f"M{i}"
        fam = s.get("metric_family") or s.get("metric_kind") or "other"
        spec = _resolve_spec(s)
        # the metric is the typed hole — draw it with the signature shape. Solid when it's a known
        # family/kind, dashed when it's the bespoke escape hatch (`extern` leaf, or the `other` tail).
        # The dashed/solid distinction stays honest about *bespoke-ness* and is independent of whether we
        # can reconstruct a structural spec: a tail metric is still bespoke even once we open its sub-graph.
        bespoke = s.get("extern") or fam == "other"
        if bespoke:
            desc = _lbl(s.get("metric_kind_other") or ("extern" if s.get("extern") else "other"))
            L.append(f'  {mid}[["the metric: {desc[:44]}"]]:::holex')
        else:
            L.append(f'  {mid}[["the metric: {_lbl(fam)}"]]:::hole')
        E.append((src, mid))
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
        metric_ids.append(mid)
    if not metric_ids:
        metric_ids = [src]                        # degenerate: no metric -> flow straight through

    # --- aggregate -> smooth -> burn -> publish -> out (bottom) ---
    L.append(f'  AGG["aggregate: {_lbl(_pascal(agg.get("method") or "proportional"))}"]:::stage')
    for m in metric_ids:
        E.append((m, "AGG"))
    last = "AGG"
    if sm and (sm.get("kind") or "none") != "none":
        L.append(f'  SM["smooth: {_lbl(_pascal(sm.get("kind")))}"]:::stage')
        E.append((last, "SM"))
        last = "SM"
    if "burn" in overlays and burn:
        L.append('  BURN{{"@burn: redirect a fraction"}}:::ov')
        E.append((last, "BURN"))
        last = "BURN"
    L.append(f'  PUB["publish: {_lbl(_pascal(ws.get("on_chain_call") or "set_weights"))}"]:::stage')
    E.append((last, "PUB"))
    L.append('  OUT(["weights on-chain = final score"]):::out')
    E.append(("PUB", "OUT"))
    if "state" in overlays:                       # state is a side-channel, drawn as a note
        L.append('  ST(["@state: carried across rounds"]):::note')
        E.append(("ST", "AGG"))

    L += [f"  {a} --> {b}" for a, b in E]
    # visual vocabulary (shape = role, colour = layer; mirrored in docs/learn/mental-model.md's legend):
    #   in = inputs · hole/holex = the metric (resolved / extern) · stage = the scoring pipeline ·
    #   ov = overlays · out = on-chain weights · note = @state
    L += ["  classDef in fill:#e6f0ff,stroke:#4488cc,color:#102a43;",
          "  classDef hole fill:#efe3ff,stroke:#7a3cc8,stroke-width:3px,color:#2a1a4a;",
          "  classDef holex fill:#efe3ff,stroke:#7a3cc8,stroke-width:3px,stroke-dasharray:5 3,color:#2a1a4a;",
          "  classDef stage fill:#e3f6f3,stroke:#2a9d8f,color:#0b3b35;",
          "  classDef ov fill:#fff3d6,stroke:#c9a227,color:#5c4a00;",
          "  classDef out fill:#e6ffe6,stroke:#3a3,color:#0a3a0a;",
          "  classDef note fill:#f3f3f3,stroke:#bbb,color:#333;"]
    return "\n".join(L)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    ir = yaml.safe_load(Path(sys.argv[1]).read_text())
    print(mechanism_mermaid(ir))
