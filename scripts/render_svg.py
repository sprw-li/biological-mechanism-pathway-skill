# -*- coding: utf-8 -*-
"""Deterministic, editable, layered SVG renderer.

Design rules (frozen contract, see ``references/layout_and_svg.md``)
-------------------------------------------------------------------
* **Exactly seven top-level layer groups**, in this z-order:
  ``layer:background, layer:containers, layer:edges, layer:nodes, layer:labels,
  layer:legend, layer:annotations``.  Every group has a ``<title>``.
* **Chart chrome lives inside those layers**: the axes group
  (``<g id="axes:<figure>"``) is nested in ``layer:background`` and the data
  marks (``<g id="series:N">``) in ``layer:nodes``, so the frozen seven-group
  structure and its z-order stay exactly as specified while axes, ticks, axis
  labels and series marks keep their own provenance attributes.
* **Text stays text**: every label/title/legend entry is a real ``<text>``
  element with ``font-family`` taken from ``figure.style.font_stack``, a
  ``font-size`` converted from points to user units (``pt * 96 / 72``) and an
  explicit ``text-anchor``.  No ``<image>``, never text-as-path.
* **Provenance**: nodes ``id="ent:<id>"``, relations ``id="rel:<id>"``, legend
  items ``id="lg:<id>"``, each with ``data-prov="<path>#<locator>"`` and
  ``data-src-kind="explicit|derived|unsupported"``; edges additionally carry
  ``data-rel-type`` and ``data-direction`` so a reviewer can machine-check that
  inhibition is drawn as a tee and activation as an arrow.
* **Machine-addressable element ids**: every drawn element also carries the
  frozen id attribute ``data-entity-id`` / ``data-relation-id`` /
  ``data-container-id`` / ``data-legend-id`` so downstream consumers (the
  ``content_map`` walker, the compliance gate) address the canvas by id instead
  of by parsing ``id="ent:..."``; the contract's ``data-source-*`` triple
  (``data-source-path`` / ``data-source-locator`` / ``data-source-kind``) is
  emitted next to each provenance binding.
* **Interaction semantics are frozen** (CONTRACT 3.4).  The ``(arrow, stroke)``
  pair of every relation is derived from its ``type`` through
  :data:`INTERACTION_STYLE`, never from free-form style input; the model's
  declared type is authoritative and is emitted as ``data-model-rel-type``
  beside the drawn ``data-rel-type`` so a layout that silently rewrites a type
  stays visible to the gate.
* **Data encodings are frozen** (CONTRACT 3.6): ``evidence.strength`` sets the
  stroke width (high 1.4 / medium 1.0 / low 0.6 pt) and ``abundance.value`` sets
  the node box **area**.  Both are applied by :func:`decorate_layout`, which the
  exporter calls too, so the SVG, the PDF and the PNG encode the same numbers.
* **Determinism**: identical model + layout -> byte-identical SVG.  Set-like
  collections are iterated in sorted order, ties break on id and no timestamp or
  random value is ever embedded (the model hash is used instead).
* Unit scale: 1 user unit = 1 px @ 96 dpi, ``uu = mm * 96 / 25.4``.  The root
  element carries physical ``width``/``height`` in mm.
"""

from __future__ import annotations

import json
import re

try:                                        # package-style import
    from .common import xml_escape as _esc
except Exception:                           # pragma: no cover - script-style import
    try:
        from common import xml_escape as _esc
    except Exception:
        def _esc(text):
            s = "" if text is None else str(text)
            return (s.replace("&", "&amp;").replace("<", "&lt;")
                    .replace(">", "&gt;").replace('"', "&quot;"))

MM_TO_UU = 96.0 / 25.4
PT_TO_UU = 96.0 / 72.0
LAYER_IDS = ("background", "containers", "edges", "nodes", "labels", "legend",
             "annotations")
LAYER_TITLES = {
    "background": "background: canvas fill and chart axes chrome",
    "containers": "containers: enclosure rectangles (containment)",
    "edges": "edges: relations with arrow / tee heads",
    "nodes": "nodes: entity boxes and labels (chart data marks)",
    "labels": "labels: figure title and panel letters",
    "legend": "legend: legend items derived from model and data series",
    "annotations": "annotations: panel captions",
}
DEFAULT_FONT_STACK = ["DejaVu Sans", "Liberation Sans", "Arial"]
DEFAULT_PALETTE = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#56B4E9",
                   "#E69F00", "#F0E442", "#999999"]
HEAD_LEN_UU = 4.4
HEAD_HALF_UU = 2.1
TEE_HALF_UU = 4.2
AXIS_COLOR = "#333333"
GRID_COLOR = "#E4E4E4"
FRAME_COLOR = "#B9BFC6"
#: journal rule: never emit a stroked element thinner than this (pt).  The
#: export-compliance gate measures every stroked element, so decorative hairlines
#: are clamped up instead of being drawn below the printable minimum.  The extra
#: 0.02 pt keeps a margin over the gate even after rounding to 3 decimals.
MIN_STROKE_PT = 0.52

#: CONTRACT 3.4 -- frozen semantic style table.  ``arrow`` is the abstract
#: CONTRACT spelling (``normal`` / ``tee`` / ``none``), ``head`` is the drawn
#: geometry (:func:`_head`), ``stroke`` is the dash grammar.  A relation whose
#: ``type`` is absent here keeps whatever the layout supplied (legacy behaviour);
#: every frozen type is forced onto this table, so a hand-written
#: ``relations[].style`` can never contradict the type's meaning.
INTERACTION_STYLE = {
    "activation":    {"arrow": "normal", "head": "arrow", "stroke": "solid"},
    "inhibition":    {"arrow": "tee",    "head": "tee",   "stroke": "solid"},
    "binding":       {"arrow": "none",   "head": "none",  "stroke": "solid",
                      "same_compartment": True},
    "modification":  {"arrow": "normal", "head": "arrow", "stroke": "dashed"},
    "transport":     {"arrow": "normal", "head": "arrow", "stroke": "solid",
                      "crosses_boundary": True},
    "transcription": {"arrow": "normal", "head": "arrow", "stroke": "solid"},
    "translation":   {"arrow": "normal", "head": "arrow", "stroke": "solid"},
    "feedback":      {"arrow": "normal", "head": "arrow", "stroke": "dashed",
                      "directional": False},
    "association":   {"arrow": "none",   "head": "none",  "stroke": "dotted"},
    "containment":   {"arrow": "none",   "head": "none",  "stroke": "dotted",
                      "derived": True},
    "membership":    {"arrow": "none",   "head": "none",  "stroke": "dotted",
                      "derived": True},
    "sequence":      {"arrow": "normal", "head": "arrow", "stroke": "solid"},
    "causation":     {"arrow": "normal", "head": "arrow", "stroke": "solid"},
}

#: CONTRACT 3.6 -- frozen line-width mapping for ``relations[].evidence.strength``.
STRENGTH_WIDTH_PT = {"high": 1.4, "medium": 1.0, "low": 0.6}

#: CONTRACT 3.3 -- container kinds that carry a membrane band.
MEMBRANE_ROLES = ("transmembrane", "membrane_anchored")

#: CONTRACT 3.5 -- outward-to-inward order used for the hierarchy advisory.
COMPARTMENT_ORDER = {
    "extracellular": 0, "membrane": 1, "cytosol": 2, "cytoplasm": 2,
    "mitochondrion": 3, "er": 3, "golgi": 3, "lysosome": 3, "nucleus": 4,
}

#: Node area encoding is area-proportional but clamped so a single outlier can
#: never push a box out of its compartment (the layout engine owns placement).
ABUNDANCE_SCALE_RANGE = (0.68, 1.55)
MEMBRANE_BAND_FILL = "#EAF2FA"
MEMBRANE_BAND_EDGE = "#2F6FA8"


def _polyline_style(value):
    """Normalise a stroke grammar to ``solid|dashed|dotted``."""
    text = str(value or "solid").strip().lower()
    return text if text in ("solid", "dashed", "dotted") else "solid"


def _dash_attr(style):
    return {"solid": None, "dashed": (2.6, 1.8), "dotted": (0.7, 1.7)}[_polyline_style(style)]


def _sw(width_pt):
    return max(MIN_STROKE_PT, _num(width_pt, MIN_STROKE_PT))


# --------------------------------------------------------------------------
# formatting helpers (deterministic, no locale, no exponent notation)
# --------------------------------------------------------------------------
def _fmt(value):
    try:
        x = round(float(value), 3)
    except (TypeError, ValueError):
        return "0"
    if x == 0:
        x = 0.0
    s = ("%.3f" % x).rstrip("0").rstrip(".")
    if s in ("", "-0"):
        return "0"
    return s


def _uu(mm):
    try:
        return float(mm) * MM_TO_UU
    except (TypeError, ValueError):
        return 0.0


def _num(value, default=0.0):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return f if f == f else default


def _attr(value):
    return _esc(value)


def _canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _key(value):
    """Comparison key for values/fields: casefolded, separators dropped.

    **CJK is preserved.**  Dropping every non-Latin character made ``缺氧`` and
    ``正常`` both normalise to ``""``, so the first ``legend[].encoding`` mapping
    row matched *every* Chinese value and all of them were drawn in one colour --
    a silent legend/data mismatch on exactly the Chinese materials the official
    cases use.  Character-for-character the same rule as
    ``compliance._norm_name`` and ``mech.normalise_key``.
    """
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").casefold())


def _sha256_text(text):
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# style / model access
# --------------------------------------------------------------------------
def _style_of(model, layout):
    style = layout.get("style") if isinstance(layout.get("style"), dict) else {}
    fig = model.get("figure") if isinstance(model.get("figure"), dict) else {}
    fstyle = fig.get("style") if isinstance(fig.get("style"), dict) else {}
    stack = style.get("font_stack") or fstyle.get("font_stack")
    stack = [str(s).strip() for s in stack if str(s).strip()] if isinstance(stack, list) else []
    if not stack:
        stack = list(DEFAULT_FONT_STACK)
    sizes = style.get("font_sizes_pt") if isinstance(style.get("font_sizes_pt"), dict) else {}
    sizes = dict(sizes)
    if isinstance(fstyle.get("font_sizes_pt"), dict):
        for k in sorted(fstyle["font_sizes_pt"]):
            sizes.setdefault(k, fstyle["font_sizes_pt"][k])
    for k in ("panel", "label", "title", "legend"):
        v = _num(sizes.get(k), 0.0)
        sizes[k] = v if v > 0 else {"panel": 9.0, "label": 7.0, "title": 9.0,
                                    "legend": 7.0}[k]
    widths = style.get("line_widths_pt") if isinstance(style.get("line_widths_pt"), dict) else {}
    if isinstance(fstyle.get("line_widths_pt"), dict):
        widths = dict(fstyle["line_widths_pt"], **widths)
    for k in ("edge", "node", "axis"):
        v = _num(widths.get(k), 0.0)
        widths[k] = v if v > 0 else {"edge": 0.8, "node": 0.6, "axis": 0.6}[k]
    palette = style.get("palette") if isinstance(style.get("palette"), list) else None
    if not palette:
        palette = fstyle.get("palette") if isinstance(fstyle.get("palette"), list) else None
    palette = [str(c) for c in palette] if palette else list(DEFAULT_PALETTE)
    return {"font_stack": stack, "font_family": ", ".join(stack),
            "font_sizes_pt": sizes, "line_widths_pt": widths, "palette": palette}


def _src_of(obj):
    src = obj.get("source") if isinstance(obj, dict) else None
    if not isinstance(src, dict):
        return "(none)", "(none)", "unsupported"
    kind = str(src.get("kind") or "")
    if kind not in ("explicit", "derived", "unsupported"):
        kind = "unsupported"
    return (str(src.get("path") or "(none)"), str(src.get("locator") or "(none)"), kind)


#: CONTRACT 4 (frozen locator grammar): ``L12 | L12-L18 | p12 | table:<col> |
#: fig:<n> | json:<json-pointer> | csv:<col>``.  The final alternative accepts any
#: lower-case ``scheme:`` prefix (``json:entities/e_exr1``, ``csv:fold_change``),
#: which is what the ingest layer really emits for workorder and table inputs --
#: rejecting it silently downgraded every workorder element's provenance to
#: ``(none)#(none)``/``unsupported`` in the delivered SVG.
_PROV_LOCATOR_RE = re.compile(
    r"^(L\d+(?:-L\d+)?|p\d+|table:[^\s#]+|fig:[\w.\-]+|[a-z]+:[^\s#]+)$")


def _valid_locator(locator):
    return bool(_PROV_LOCATOR_RE.match(str(locator or "").strip()))


def _prov_attr(obj):
    """``(data-prov, data-src-kind)`` for one drawn element, in the frozen form.

    ``data-prov`` is ``<relative POSIX path>#<locator>`` with the locator drawn
    from the frozen CONTRACT 4 grammar (``L12 | L12-L18 | p12 | table:<col> |
    fig:<n> | json:<pointer> | csv:<col>``).  A source that names a real file and
    carries a verbatim quote keeps its declared ``src_kind`` even when its
    locator is unusable -- the claim is still backed by a quotation, so the
    element is emitted as ``path#(none)`` with ``data-locator-valid="false"``
    instead of being flattened to an unverifiable ``unsupported`` placeholder.
    Only a source with neither a usable locator nor a quote is downgraded.
    """
    path, locator, kind = _src_of(obj)
    if isinstance(obj, dict) and obj.get("prov"):
        prov = str(obj["prov"])
        p, _, loc = prov.partition("#")
        if prov == "(none)#(none)" or (p and p != "(none)" and _valid_locator(loc)):
            return prov, str(obj.get("src_kind") or kind)
        return "(none)#(none)", "unsupported"
    if not path or path == "(none)":
        return "(none)#(none)", "unsupported"
    if _valid_locator(locator):
        return "%s#%s" % (path, locator), kind
    quote = str((obj.get("source") or {}).get("quote") or "") if isinstance(obj, dict) else ""
    if quote.strip():
        return "%s#(none)" % path, kind
    return "(none)#(none)", "unsupported"


# --------------------------------------------------------------------------
# model-driven decoration of a layout (frozen semantics + data encodings)
# --------------------------------------------------------------------------
def _model_index(model):
    """``{kind: {id: element}}`` for the four drawable model collections."""
    out = {"entities": {}, "relations": {}, "containers": {}, "legend": {}}
    if not isinstance(model, dict):
        return out
    for key in out:
        arr = model.get(key)
        if isinstance(arr, dict):
            arr = [arr[k] for k in sorted(arr)]
        for item in arr or []:
            if isinstance(item, dict) and str(item.get("id") or ""):
                out[key].setdefault(str(item["id"]), item)
    return out


def _container_compartment(cid, index):
    """The compartment a container stands for (``extracellular`` … ``nucleus``).

    Accepts the CONTRACT 3.3 spellings -- ``kind`` may be the compartment name
    itself or the generic ``compartment`` with the name in ``compartment`` /
    ``id`` / ``label`` (a membrane band is recognised from any of them so the
    hard placement gate can tell "on the membrane" from "inside a compartment").
    """
    con = index["containers"].get(str(cid))
    if not isinstance(con, dict):
        return ""
    kind = str(con.get("kind") or "").strip().lower()
    if kind in COMPARTMENT_ORDER:
        return kind
    if kind not in ("compartment", "membrane", "cell"):
        # A plain ``group`` is a visual grouping, not a biological compartment:
        # its id must never be read as a placement claim.
        return ""
    for key in ("compartment", "kind", "id", "label"):
        norm = re.sub(r"[^a-z]", "", str(con.get(key) or "").lower())
        if not norm:
            continue
        for name in sorted(COMPARTMENT_ORDER, key=len, reverse=True):
            if norm == name or (name in norm and len(name) >= 4):
                return name
    return ""


def _abundance_scales(index):
    """Area-proportional, median-normalised node scales, keyed by entity id.

    Area ∝ value means the linear scale is ``sqrt(value / reference)``; the
    reference is the median of the encoded channel so a single outlier can only
    shrink the rest, never explode the canvas.  The result is clamped to
    :data:`ABUNDANCE_SCALE_RANGE` because placement belongs to the layout engine.
    """
    values = {}
    for eid, ent in index["entities"].items():
        ab = ent.get("abundance")
        if isinstance(ab, dict) and _num(ab.get("value"), 0.0) > 0:
            values[eid] = _num(ab["value"])
    if not values:
        return {}
    ordered = sorted(values.values())
    reference = ordered[len(ordered) // 2] or 1.0
    lo, hi = ABUNDANCE_SCALE_RANGE
    return {eid: min(hi, max(lo, (value / reference) ** 0.5))
            for eid, value in values.items()}


def _model_levels(model, index):
    """Entity id -> flow level, from ``figure.flow.ranks`` or from the topology.

    The renderer must never invent a level: if the layout forgot to carry
    ``nodes[id].level`` the value is recovered here from the model's declared
    ranks, and only then from a longest-path layering of the non-``feedback``
    edges.  Emitting ``data-level="0"`` for every node would make the artifact
    contradict the layout and silently break the flow-direction gate.
    """
    ranks = {}
    flow = ((model or {}).get("figure") or {}).get("flow") if isinstance(model, dict) else None
    if isinstance(flow, dict) and isinstance(flow.get("ranks"), dict):
        for key, value in flow["ranks"].items():
            try:
                ranks[str(key)] = int(value)
            except (TypeError, ValueError):
                continue
    if ranks:
        return ranks, "figure.flow.ranks"
    adjacency = {}
    for rid in sorted(index["relations"]):
        rel = index["relations"][rid]
        if str(rel.get("type") or "") == "feedback":
            continue
        source, target = str(rel.get("from")), str(rel.get("to"))
        if source in index["entities"] and target in index["entities"]:
            adjacency.setdefault(source, []).append(target)
    level = {eid: 0 for eid in index["entities"]}
    for _round in range(len(index["entities"]) + 1):
        changed = False
        for source in sorted(adjacency):
            for target in sorted(set(adjacency[source])):
                if level[target] < level[source] + 1:
                    level[target] = level[source] + 1
                    changed = True
        if not changed:
            break
    return (level, "longest-path layering of non-feedback edges") if level else ({}, "unknown")


def _resolve_level(node, eid, model_levels, model_level_basis):
    """``(level, source)`` for one layout node: layout, model ranks, else unknown."""
    value = node.get("level")
    if not isinstance(value, int) or isinstance(value, bool):
        nested = node.get("layout") if isinstance(node.get("layout"), dict) else {}
        value = nested.get("level")
    if isinstance(value, int) and not isinstance(value, bool):
        return value, "layout.nodes[%s].level" % eid
    if eid in model_levels:
        return model_levels[eid], model_level_basis
    return None, "unknown"


def _shrink_into(box, containers, pad=0.8):
    """Shrink ``box`` (x, y, w, h) so it stays inside its container, centred."""
    con = containers.get(str(box.get("container") or ""))
    if not isinstance(con, dict):
        return box
    try:
        cx0, cy0 = _num(con.get("x_mm")), _num(con.get("y_mm"))
        cw, ch = _num(con.get("w_mm")), _num(con.get("h_mm"))
    except (TypeError, ValueError):       # pragma: no cover - defensive
        return box
    if cw <= 0 or ch <= 0:
        return box
    avail_w, avail_h = max(1.0, cw - 2 * pad), max(1.0, ch - 2 * pad)
    w = min(_num(box.get("w_mm")), avail_w)
    h = min(_num(box.get("h_mm")), avail_h)
    cx = _num(box.get("x_mm")) + _num(box.get("w_mm")) / 2.0
    cy = _num(box.get("y_mm")) + _num(box.get("h_mm")) / 2.0
    cx = min(max(cx, cx0 + pad + w / 2.0), cx0 + cw - pad - w / 2.0)
    cy = min(max(cy, cy0 + pad + h / 2.0), cy0 + ch - pad - h / 2.0)
    box["w_mm"], box["h_mm"] = w, h
    box["x_mm"], box["y_mm"] = cx - w / 2.0, cy - h / 2.0
    return box


def decorate_layout(model, layout):
    """Return a copy of ``layout`` with the frozen semantics applied.

    Purely additive: layouts that carry none of the new constructs come back
    byte-equivalent after re-serialisation, so the pre-0060 rendering is
    unchanged.  The step exists as a separate function because the **exporter**
    must apply exactly the same mapping when it redraws the figure with
    matplotlib -- otherwise the SVG would encode one line width and the PDF
    another.
    """
    import copy as _copy
    out = _copy.deepcopy(layout) if isinstance(layout, dict) else {}
    index = _model_index(model)
    scales = _abundance_scales(index)
    model_levels, model_level_basis = _model_levels(model, index)

    # ---- levels first: edges and containers quote them --------------------
    nodes = out.get("nodes") if isinstance(out.get("nodes"), dict) else {}
    resolved_levels = {}
    for nid in sorted(nodes):
        if not isinstance(nodes[nid], dict):
            continue
        level, source = _resolve_level(nodes[nid], str(nid), model_levels, model_level_basis)
        resolved_levels[str(nid)] = level
        nodes[nid]["level"] = level
        nodes[nid]["level_source"] = source

    # ---- relations: frozen (arrow, stroke) + evidence line width ----------
    for edge in out.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        edge["level_from"] = resolved_levels.get(str(edge.get("from")))
        edge["level_to"] = resolved_levels.get(str(edge.get("to")))
        rid = str(edge.get("id"))
        rel = index["relations"].get(rid) if rid else None
        model_type = str((rel or {}).get("type") or "")
        layout_type = str(edge.get("type") or "")
        drawn_type = model_type or layout_type or "association"
        edge["layout_rel_type"] = layout_type
        edge["model_rel_type"] = model_type
        edge["type"] = drawn_type
        spec = INTERACTION_STYLE.get(drawn_type)
        if spec:
            head = spec["head"]
            edge["head_end"] = head
            edge["head_start"] = (head if str(edge.get("direction")) == "bidirectional"
                                  else "none")
            edge["arrow"] = spec["arrow"]
            edge["stroke"] = spec["stroke"]
        else:
            edge["head_end"] = str(edge.get("head_end") or "none")
            edge["head_start"] = str(edge.get("head_start") or "none")
            edge["stroke"] = _polyline_style(edge.get("stroke"))
            edge["arrow"] = {"arrow": "normal", "tee": "tee"}.get(str(edge["head_end"]), "none")
        evidence = (rel or {}).get("evidence")
        strength = ""
        if isinstance(evidence, dict):
            candidate = str(evidence.get("strength") or "").strip().lower()
            if candidate in STRENGTH_WIDTH_PT:
                strength = candidate
        edge["evidence_strength"] = strength
        if strength:
            edge["width_pt"] = STRENGTH_WIDTH_PT[strength]
        else:
            edge["width_pt"] = _num(edge.get("width_pt"), 0.8)
        edge["direction"] = str((rel or {}).get("direction") or edge.get("direction") or "none")

    # ---- nodes: abundance area encoding + membrane/compartment anchors ----
    containers = out.get("containers") if isinstance(out.get("containers"), dict) else {}
    nodes = out.get("nodes") if isinstance(out.get("nodes"), dict) else {}
    for nid in sorted(nodes):
        node = nodes[nid]
        if not isinstance(node, dict):
            continue
        ent = index["entities"].get(str(nid)) or {}
        ab = ent.get("abundance")
        scale = scales.get(str(nid), 1.0)
        node["entity_id"] = str(nid)
        node["value"] = ent.get("value")
        node["unit"] = str(ent.get("unit") or "")
        # The layout decides WHERE a box sits (it may anchor a cytosolic protein to
        # the membrane band and record W_MEMBRANE_ANCHOR_COMPARTMENT); the model
        # decides which compartment the entity belongs to.  Both are kept, and the
        # abundance clamp respects the layout's placement, so scaling never drags a
        # drawn box off the band the layout chose.
        layout_container = str(node.get("container") or "")
        node["layout_container"] = layout_container
        node["container"] = str(ent.get("container") or node.get("container") or "")
        node["membrane_role"] = str(ent.get("membrane_role") or node.get("membrane_role") or "")
        node["compartment"] = _container_compartment(node["container"], index)
        node["label_is_italic"] = (str(ent.get("kind") or node.get("kind") or "") == "gene")
        node["normalized_symbol"] = str(
            ((ent.get("attributes") or {}).get("normalized_symbol")
             if isinstance(ent.get("attributes"), dict) else "") or "")
        if isinstance(ab, dict):
            node["abundance_value"] = ab.get("value")
            node["abundance_unit"] = str(ab.get("unit") or "")
            node["abundance_source"] = ab.get("source")
            node["abundance_scale"] = round(scale, 4)
        # The layout engine owns geometry AND the abundance -> size channel: it has already
        # scaled these boxes (and has already disclosed any legibility clamp).  Scaling a
        # second time here broke area proportionality (a node with factor 0.5 was drawn at
        # 0.34 of its base box), so the renderer now draws the layout box unchanged and
        # states which scale it observed.
        if scale != 1.0:
            node["abundance_scale_applied_by"] = "layout"
        node = nodes[nid]
        node["node_area_mm2"] = round(_num(node.get("w_mm")) * _num(node.get("h_mm")), 4)

    # ---- containers: kind / compartment anchors --------------------------
    for cid in sorted(containers):
        con = containers[cid]
        if not isinstance(con, dict):
            continue
        declared = index["containers"].get(str(cid)) or {}
        kind = str(declared.get("kind") or con.get("container_kind") or con.get("kind")
                   or "group")
        con["container_id"] = str(declared.get("id") or cid)
        con["container_kind"] = kind
        con["compartment"] = _container_compartment(cid, index)
        con["is_membrane"] = (kind == "membrane")
        span = con.get("level_span")
        if isinstance(span, (list, tuple)) and len(span) >= 2:
            try:
                con["level_min"], con["level_max"] = int(span[0]), int(span[1])
            except (TypeError, ValueError):
                pass
        member_levels = [resolved_levels.get(str(m)) for m in (declared.get("members") or [])]
        member_levels = [lv for lv in member_levels if isinstance(lv, int)]
        if member_levels:
            con.setdefault("level_min", min(member_levels))
            con.setdefault("level_max", max(member_levels))

    # ---- legend glyphs: a type's legend entry must carry the type's style ---
    # CONTRACT 3.4 freezes both the edge style AND the legend entry ("箭头=激活",
    # "平头(⊥)=抑制", ...).  When a legend entry names a frozen relation type, its
    # glyph is derived here from the same table instead of trusting a possibly
    # absent/contradictory `marker`, so the legend and the edges cannot disagree.
    legend = out.get("legend") if isinstance(out.get("legend"), dict) else {}
    for item in legend.get("items") or []:
        if not isinstance(item, dict):
            continue
        value = str(item.get("value") or "").strip()
        spec = INTERACTION_STYLE.get(value)
        if not spec or spec.get("derived"):
            continue
        item["marker"] = "arrow:%s" % spec["arrow"]
        item["stroke_style"] = spec["stroke"]
        item["frozen_type"] = value

    # ---- legend encodings: apply the declared channel to the drawn marks ----
    # A ``legend[].encoding`` is a claim about the canvas: "strand X is drawn at
    # 1.4 pt".  The canvas must actually carry it, so each chart series resolves
    # its own value through the declared mapping (line_width -> pt, colour ->
    # swatch, node_size -> area) and the resolved visual is annotated for both
    # this renderer and the exporter.
    encodings = []
    for lid in sorted(index["legend"]):
        enc = index["legend"][lid].get("encoding")
        if isinstance(enc, dict) and isinstance(enc.get("mapping"), list):
            encodings.append((lid, str(enc.get("channel") or "").lower(),
                              str(enc.get("field") or ""), enc["mapping"]))
    chart = out.get("chart") if isinstance(out.get("chart"), dict) else {}
    model_series = []
    if isinstance(model, dict) and isinstance((model.get("data") or {}).get("series"), list):
        model_series = [s for s in model["data"]["series"] if isinstance(s, dict)]
    by_name = {str(s.get("name")): s for s in model_series}
    for position, series in enumerate(chart.get("series") or []):
        if not isinstance(series, dict):
            continue
        source = (model_series[position] if position < len(model_series)
                  else None) or by_name.get(str(series.get("name"))) or {}
        for lid, channel, field, mapping in encodings:
            value = source.get(field)
            if isinstance(value, list):
                value = value[0] if value else None
            if value in (None, ""):
                continue
            for row in mapping:
                if not isinstance(row, dict):
                    continue
                if _key(row.get("value")) != _key(value):
                    continue
                visual = row.get("visual")
                series["encoding_legend"] = lid
                series["encoding_channel"] = channel
                series["encoding_field"] = field
                series["encoding_value"] = str(value)
                if channel == "line_width":
                    width = _num(visual, 0.0)
                    if width > 0:
                        series["width_pt"] = min(3.0, max(MIN_STROKE_PT, width))
                elif channel == "color":
                    series["color"] = str(visual)
                elif channel == "node_size":
                    series["marker_size_mm"] = visual
                break
    return out


# --------------------------------------------------------------------------
# primitives
# --------------------------------------------------------------------------
def _source_attrs(obj):
    """Frozen ``data-source-*`` triple (CONTRACT 3.6 / 4) for one drawn element."""
    path, locator, kind = _src_of(obj)
    src = obj.get("source") if isinstance(obj, dict) else None
    quote = ""
    if isinstance(src, dict):
        quote = str(src.get("quote") or "")
    return (' data-source-path="%s" data-source-locator="%s" data-source-kind="%s"'
            ' data-has-quote="%s"'
            % (_attr(path), _attr(locator), _attr(kind),
               "true" if quote.strip() else "false"))


def _text(x_mm, y_mm, content, font_pt, font_family, anchor="start", extra=""):
    return ('<text x="%s" y="%s" font-family="%s" font-size="%s" text-anchor="%s"%s>%s</text>'
            % (_fmt(_uu(x_mm)), _fmt(_uu(y_mm)), _attr(font_family),
               _fmt(font_pt * PT_TO_UU), anchor, extra, _esc(content)))


def _rect(x, y, w, h, fill, stroke="none", width_pt=0.0, rx=0.0, extra=""):
    sw = 0.0 if str(stroke) == "none" else _sw(width_pt)
    return ('<rect x="%s" y="%s" width="%s" height="%s" rx="%s" fill="%s" '
            'stroke="%s" stroke-width="%s"%s/>'
            % (_fmt(_uu(x)), _fmt(_uu(y)), _fmt(_uu(w)), _fmt(_uu(h)), _fmt(_uu(rx)),
               _attr(fill), _attr(stroke), _fmt(sw * PT_TO_UU), extra))


def _polyline(points_mm, stroke, width_pt, dash=False, extra="", style=None):
    if len(points_mm) < 2:
        return ""
    d = "M %s" % " L ".join("%s %s" % (_fmt(_uu(x)), _fmt(_uu(y))) for x, y in points_mm)
    if style is None:
        style = "dashed" if dash else "solid"
    dash_pair = _dash_attr(style)
    dash_attr = (' stroke-dasharray="%s %s"' % (_fmt(dash_pair[0]), _fmt(dash_pair[1]))
                 if dash_pair else "")
    return ('<path d="%s" fill="none" stroke="%s" stroke-width="%s" '
            'stroke-linecap="round" stroke-linejoin="round"%s%s/>'
            % (d, _attr(stroke), _fmt(_sw(width_pt) * PT_TO_UU), dash_attr, extra))


def _head(points_mm, at_end, kind, color):
    """Explicit arrow head / tee bar geometry (no <marker>, converter-proof)."""
    if kind not in ("arrow", "tee") or len(points_mm) < 2:
        return ""
    if at_end:
        tip = points_mm[-1]
        ref = points_mm[-2]
    else:
        tip = points_mm[0]
        ref = points_mm[1]
    dx = float(tip[0]) - float(ref[0])
    dy = float(tip[1]) - float(ref[1])
    ln = (dx * dx + dy * dy) ** 0.5
    if ln <= 0:
        return ""
    ux, uy = dx / ln, dy / ln
    px, py = -uy, ux
    if kind == "tee":
        half = TEE_HALF_UU / MM_TO_UU
        p1 = (tip[0] - px * half, tip[1] - py * half)
        p2 = (tip[0] + px * half, tip[1] + py * half)
        return ('<path d="M %s %s L %s %s" fill="none" stroke="%s" stroke-width="%s"/>'
                % (_fmt(_uu(p1[0])), _fmt(_uu(p1[1])), _fmt(_uu(p2[0])), _fmt(_uu(p2[1])),
                   _attr(color), _fmt(_sw(2.0) * PT_TO_UU)))
    back = HEAD_LEN_UU / MM_TO_UU
    half = HEAD_HALF_UU / MM_TO_UU
    base = (tip[0] - ux * back, tip[1] - uy * back)
    a = (base[0] - px * half, base[1] - py * half)
    b = (base[0] + px * half, base[1] + py * half)
    return ('<path d="M %s %s L %s %s L %s %s Z" fill="%s" stroke="%s" '
            'stroke-width="%s"/>'
            % (_fmt(_uu(tip[0])), _fmt(_uu(tip[1])), _fmt(_uu(a[0])), _fmt(_uu(a[1])),
               _fmt(_uu(b[0])), _fmt(_uu(b[1])), _attr(color), _attr(color),
               _fmt(_sw(0.2) * PT_TO_UU)))


# --------------------------------------------------------------------------
# layers
# --------------------------------------------------------------------------
def _layer_open(layer_id):
    return ('<g id="layer:%s">' % layer_id,
            "<title>%s</title>" % _esc(LAYER_TITLES.get(layer_id, layer_id)))


def _background_layer(layout, style, chart):
    W = _num(layout.get("canvas", {}).get("width_mm"), 180.0)
    H = _num(layout.get("canvas", {}).get("height_mm"), 120.0)
    bg = layout.get("canvas", {}).get("background") or "#FFFFFF"
    out = list(_layer_open("background"))
    out.append(_rect(0.0, 0.0, W, H, bg))
    if chart:
        out.extend(_axes_group(chart, style, layout))
    out.append("</g>")
    return out


def _axes_group(chart, style, layout):
    fig_id = "chart"
    fig = (layout.get("figure_id") or "")
    if fig:
        fig_id = str(fig)
    prov = chart.get("prov") or "(none)"
    kind = chart.get("src_kind") or "derived"
    ff = style["font_family"]
    plot = chart.get("plot") or {}
    x0 = _num(plot.get("x"))
    y0 = _num(plot.get("y"))
    w = _num(plot.get("w"))
    h = _num(plot.get("h"))
    x2, y2 = x0 + w, y0 + h
    out = ['<g id="axes:%s" data-prov="%s" data-src-kind="%s" data-chart="axes">'
           % (_attr(fig_id), _attr(prov), _attr(kind))]
    out.append("<title>%s</title>" % _esc("axes: %s / %s"
                                          % ((chart.get("x") or {}).get("title", "x"),
                                             (chart.get("y") or {}).get("title", "y"))))
    out.append(_rect(x0, y0, w, h, "#FFFFFF", FRAME_COLOR, _num(style["line_widths_pt"]["axis"]) * 0.8))
    yspec = chart.get("y") or {}
    xspec = chart.get("x") or {}
    for tick in yspec.get("ticks") or []:
        ty = _num(tick.get("pos_mm"))
        out.append(_polyline([(x0, ty), (x2, ty)], GRID_COLOR,
                             _num(style["line_widths_pt"]["axis"]) * 0.7,
                             dash=True, extra=' data-prov="%s" data-src-kind="%s"'
                             % (_attr(yspec.get("prov", prov)), _attr(yspec.get("src_kind", kind)))))
        out.append(_polyline([(x0 - 1.3, ty), (x0, ty)], AXIS_COLOR,
                             _num(style["line_widths_pt"]["axis"])))
        tick_pt = _num(yspec.get("tick_font_pt"), 7.0)
        out.append(_text(x0 - 2.0, ty + tick_pt * 0.3528 * 0.36,
                         tick.get("label", ""), tick_pt, ff,
                         "end", ' data-prov="%s" data-src-kind="%s"'
                         % (_attr(yspec.get("prov", prov)), _attr(yspec.get("src_kind", kind)))))
    xlabels = xspec.get("ticks") or []
    spacing = 0.0
    if len(xlabels) >= 2:
        positions = sorted(_num(t.get("pos_mm")) for t in xlabels)
        spacing = min(positions[i + 1] - positions[i] for i in range(len(positions) - 1))
    longest = max([len(str(t.get("label", ""))) for t in xlabels] or [0])
    label_pt = _num(xspec.get("tick_font_pt"), 7.0)
    rotate = bool(xlabels) and (longest * label_pt * 0.58 * 0.3528 > max(4.0, spacing * 0.85))
    for tick in xlabels:
        tx = _num(tick.get("pos_mm"))
        out.append(_polyline([(tx, y2), (tx, y2 + 1.3)], AXIS_COLOR,
                             _num(style["line_widths_pt"]["axis"])))
        extra = ' data-prov="%s" data-src-kind="%s"' % (
            _attr(xspec.get("prov", prov)), _attr(xspec.get("src_kind", kind)))
        if rotate:
            extra += ' transform="rotate(-35 %s %s)"' % (_fmt(_uu(tx)), _fmt(_uu(y2 + 3.6)))
            out.append(_text(tx, y2 + 3.6, tick.get("label", ""), label_pt, ff, "end", extra))
        else:
            out.append(_text(tx, y2 + 1.3 + label_pt * 0.3528 * 0.9, tick.get("label", ""),
                             label_pt, ff, "middle", extra))
    if xspec.get("title"):
        out.append(_text(x0 + w / 2.0, y2 + 3.0 + label_pt * 0.3528 * (2.4 if rotate else 1.6),
                         xspec["title"], _num(xspec.get("font_pt"), 7.0), ff, "middle",
                         ' data-prov="%s" data-src-kind="%s"'
                         % (_attr(xspec.get("prov", prov)), _attr(xspec.get("src_kind", kind)))))
    if yspec.get("title"):
        out.append(_text(x0 - 11.0, y0 + h / 2.0, yspec["title"],
                         _num(yspec.get("font_pt"), 7.0), ff, "middle",
                         ' transform="rotate(-90 %s %s)" data-prov="%s" data-src-kind="%s"'
                         % (_fmt(_uu(x0 - 11.0)), _fmt(_uu(y0 + h / 2.0)),
                            _attr(yspec.get("prov", prov)), _attr(yspec.get("src_kind", kind)))))
    out.append("</g>")
    return out


def _series_marks(chart, style):
    """Chart data marks; live in layer:nodes (above the axes chrome)."""
    out = []
    bar = chart.get("bar") or {}
    nser = max(1, int(_num(bar.get("n_series"), 1)))
    bar_w = _num(bar.get("bar_w_mm"))
    yspec = chart.get("y") or {}
    plot = chart.get("plot") or {}
    y_lo = _num(yspec.get("min"))
    y_hi = _num(yspec.get("max"))
    span = y_hi - y_lo

    def y_of(value):
        if span <= 0:
            return _num(plot.get("y")) + _num(plot.get("h")) / 2.0
        return _num(plot.get("y")) + _num(plot.get("h")) - (value - y_lo) / span * _num(plot.get("h"))

    for s in chart.get("series") or []:
        prov = s.get("prov") or "(none)#(none)"
        kind = s.get("src_kind") or ("derived" if chart.get("src_kind") == "derived"
                                     else "unsupported")
        color = s.get("color") or style["palette"][int(_num(s.get("index"), 0)) % len(style["palette"])]
        idx = int(_num(s.get("index"), 0))
        # the declared encoding decides the stroke width, so a legend entry that
        # claims "1.4 pt" is a statement the canvas really makes
        series_width_pt = _num(s.get("width_pt"), 0.0) or _num(style["line_widths_pt"]["edge"])
        encoding = ("".join(
            ' data-%s="%s"' % (name, _attr(s.get(key)))
            for name, key in (("encoding-legend", "encoding_legend"),
                              ("encoding-channel", "encoding_channel"),
                              ("encoding-field", "encoding_field"),
                              ("encoding-value", "encoding_value"))
            if s.get(key) not in (None, "")))
        out.append('<g id="series:%d" data-prov="%s" data-src-kind="%s" data-name="%s" '
                   'data-unit="%s" data-color="%s" data-width-pt="%s"%s%s%s>'
                   % (idx, _attr(prov), _attr(kind),
                      _attr(s.get("name", "")), _attr(s.get("unit", "")),
                      _attr(color), _fmt(series_width_pt), encoding,
                      ' data-legend="%s"' % _attr(s.get("legend_id")) if s.get("legend_id") else "",
                      ' data-entity="%s"' % _attr(s.get("entity_id")) if s.get("entity_id") else ""))
        out.append("<title>%s</title>" % _esc(s.get("name", "")))
        shape = s.get("shape") or "line"
        if shape == "bar" and bar_w > 0:
            group_w = _num(bar.get("group_w_mm"))
            offset = -group_w / 2.0 + idx * bar_w
            zero_pt = _num(bar.get("baseline"), 0.0)
            y_zero = y_of(zero_pt)          # the baseline bar lengths are measured from
            for pt in s.get("points") or []:
                py = _num(pt.get("y_mm"))
                x = _num(pt.get("x_mm")) + offset
                top = min(py, y_zero)
                height = max(0.2, abs(y_zero - py))
                out.append(_rect(x, top, bar_w * 0.86, height, color,
                                 "none", 0.0, 0.0,
                                 ' data-prov="%s" data-src-kind="%s" data-value="%s" '
                                 'data-baseline="%s"'
                                 % (_attr(prov), _attr(kind), _attr(pt.get("y")),
                                    _fmt(zero_pt))))
        else:
            pts = [(pt.get("x_mm"), pt.get("y_mm")) for pt in (s.get("points") or [])]
            if len(pts) >= 2:
                out.append(_polyline(pts, color, series_width_pt,
                                     extra=' data-prov="%s" data-src-kind="%s"'
                                     % (_attr(prov), _attr(kind))))
            for pt in s.get("points") or []:
                out.append('<circle cx="%s" cy="%s" r="%s" fill="%s" stroke="#FFFFFF" '
                           'stroke-width="%s" data-prov="%s" data-src-kind="%s" data-value="%s"/>'
                           % (_fmt(_uu(_num(pt.get("x_mm")))), _fmt(_uu(_num(pt.get("y_mm")))),
                              _fmt(1.5), _attr(color), _fmt(_sw(0.5) * PT_TO_UU), _attr(prov),
                              _attr(kind), _attr(pt.get("y"))))
        out.append("</g>")
    return out


def _containers_layer(layout, style):
    out = list(_layer_open("containers"))
    containers = layout.get("containers") if isinstance(layout.get("containers"), dict) else {}
    ordered = sorted(containers, key=lambda c: (_num(containers[c].get("depth")),
                                                _num(containers[c].get("y_mm")),
                                                _num(containers[c].get("x_mm")), str(c)))
    line_w = _num(style["line_widths_pt"]["node"])
    for cid in ordered:
        c = containers[cid]
        if not isinstance(c, dict):
            continue
        eid = str(c.get("element_id") or ("cnt:%s" % cid))
        prov, skind = _prov_attr(c)
        is_membrane = bool(c.get("is_membrane"))
        dash = (' stroke-dasharray="%s %s"' % (_fmt(2.4), _fmt(1.6))
                if c.get("role") == "entity" else "")
        out.append('<g id="%s" data-container-id="%s" data-prov="%s" data-src-kind="%s" '
                   'data-role="%s" data-level-span="%s" data-level="%s" data-level-min="%s" '
                   'data-level-max="%s" data-container-kind="%s" '
                   'data-compartment="%s" data-is-membrane="%s" class="container"%s>'
                   % (_attr(eid), _attr(c.get("container_id") or cid), _attr(prov),
                      _attr(skind), _attr(c.get("role", "explicit")),
                      _attr("%s-%s" % ((c.get("level_span") or [0, 0])[0],
                                       (c.get("level_span") or [0, 0])[1])),
                      _attr(c.get("level_min") if c.get("level_min") is not None else ""),
                      _attr(c.get("level_min") if c.get("level_min") is not None else ""),
                      _attr(c.get("level_max") if c.get("level_max") is not None else ""),
                      _attr(c.get("container_kind") or "group"),
                      _attr(c.get("compartment") or ""),
                      "true" if is_membrane else "false", _source_attrs(c)))
        out.append("<title>%s</title>" % _esc(c.get("label", cid)))
        x = _num(c.get("x_mm"))
        y = _num(c.get("y_mm"))
        w = _num(c.get("w_mm"))
        h = _num(c.get("h_mm"))
        if is_membrane:
            # A lipid bilayer reads as a band, not as another compartment box: a
            # tinted body plus two edge rules.  The band's outer rect stays the
            # element a reviewer measures an entity against.
            out.append(_rect(x, y, w, h, MEMBRANE_BAND_FILL, MEMBRANE_BAND_EDGE,
                             line_w, 0.6,
                             dash + ' data-band-axis="horizontal" data-band-top-mm="%s" '
                             'data-band-bottom-mm="%s"'
                             % (_fmt(y), _fmt(y + h))))
            for edge_y in (y, y + h):
                out.append(_polyline([(x, edge_y), (x + w, edge_y)], MEMBRANE_BAND_EDGE,
                                     line_w * 1.4, extra=' class="membrane-edge"'))
        else:
            out.append(_rect(x, y, w, h, "#F5F8FB", "#8C97A3", line_w, 2.2, dash))
        lines = c.get("lines") or ([c.get("label")] if c.get("label") else [])
        anchor = c.get("label_anchor") or {}
        ax = _num(anchor.get("x_mm"), _num(c.get("x_mm")))
        ay = _num(anchor.get("y_mm"), _num(c.get("y_mm")) + 3.5)
        pt = _num(c.get("font_pt"), style["font_sizes_pt"]["legend"])
        for i, line in enumerate(lines):
            out.append(_text(ax, ay + i * pt * 0.3528 * 1.35, line, pt,
                             style["font_family"], "start"))
        out.append("</g>")
    out.append("</g>")
    return out


def _edges_layer(layout, style):
    out = list(_layer_open("edges"))
    edges = layout.get("edges") if isinstance(layout.get("edges"), list) else []
    for e in sorted([x for x in edges if isinstance(x, dict)], key=lambda x: str(x.get("id"))):
        prov, skind = _prov_attr(e)
        color = e.get("color") or style["palette"][0]
        width_pt = _num(e.get("width_pt"), 0.8)
        stroke_style = _polyline_style(e.get("stroke"))
        rel_type = str(e.get("type") or "association")
        model_type = str(e.get("model_rel_type") or "")
        layout_type = str(e.get("layout_rel_type") or "")
        desync = (' data-layout-rel-type="%s"' % _attr(layout_type)
                  if layout_type and layout_type != rel_type else "")
        strength = str(e.get("evidence_strength") or "")
        points = [(p[0], p[1]) for p in (e.get("points_mm") or [])
                  if isinstance(p, (list, tuple)) and len(p) >= 2]
        out.append('<g id="rel:%s" data-relation-id="%s" data-prov="%s" data-src-kind="%s" '
                   'data-rel-type="%s" data-model-rel-type="%s"%s data-direction="%s" '
                   'data-arrow="%s" data-stroke-style="%s" data-head-start="%s" '
                   'data-head-end="%s" data-evidence-strength="%s" data-width-pt="%s" '
                   'data-level-from="%s" data-level-to="%s" '
                   'data-feedback="%s" class="relation"%s>'
                   % (_attr(e.get("id")), _attr(e.get("id")), _attr(prov), _attr(skind),
                      _attr(rel_type), _attr(model_type), desync,
                      _attr(e.get("direction", "forward")),
                      _attr(INTERACTION_STYLE.get(rel_type, {}).get("arrow", "none")),
                      _attr(stroke_style),
                      _attr(e.get("head_start", "none")), _attr(e.get("head_end", "none")),
                      _attr(strength), _fmt(width_pt),
                      _attr(e.get("level_from") if e.get("level_from") is not None else ""),
                      _attr(e.get("level_to") if e.get("level_to") is not None else ""),
                      "true" if e.get("feedback") else "false", _source_attrs(e)))
        out.append("<title>%s</title>" % _esc(e.get("label") or "%s %s" % (rel_type, e.get("id", ""))))
        if len(points) >= 2:
            out.append(_polyline(points, color, width_pt, style=stroke_style))
            out.append(_head(points, False, str(e.get("head_start") or "none"), color))
            out.append(_head(points, True, str(e.get("head_end") or "none"), color))
        lines = e.get("label_lines") or []
        pos = e.get("label_pos_mm")
        if lines and pos:
            pt = _num(e.get("font_pt"), style["font_sizes_pt"]["label"])
            anchor = str(e.get("label_anchor") or "middle")
            lw = _num(e.get("label_w_mm"), 0.0)
            lh = _num(e.get("label_h_mm"), len(lines) * pt * 0.3528 * 1.3)
            # white plate behind the label so the line never strikes through the text
            plate_h = lh + 0.8
            plate_w = lw + 1.6
            plate_x = _num(pos[0]) - (plate_w / 2.0 if anchor == "middle" else 0.8)
            plate_y = _num(pos[1]) - pt * 0.3528 * 0.95 - 0.4
            out.append('<rect class="edge-label-plate" x="%s" y="%s" width="%s" '
                       'height="%s" fill="#FFFFFF" stroke="none" data-prov="%s" '
                       'data-src-kind="%s" data-relation-id="%s"/>'
                       % (_fmt(_uu(plate_x)), _fmt(_uu(plate_y)), _fmt(_uu(plate_w)),
                          _fmt(_uu(plate_h)), _attr(prov), _attr(skind), _attr(e.get("id"))))
            for i, line in enumerate(lines):
                out.append(_text(_num(pos[0]), _num(pos[1]) + i * pt * 0.3528 * 1.3, line, pt,
                                 style["font_family"], anchor,
                                 ' data-relation-id="%s" data-text-role="edge-label"'
                                 % _attr(e.get("id"))))
        out.append("</g>")
    out.append("</g>")
    return out


def _nodes_layer(layout, style, chart):
    out = list(_layer_open("nodes"))
    nodes = layout.get("nodes") if isinstance(layout.get("nodes"), dict) else {}
    line_w = _num(style["line_widths_pt"]["node"])
    ordered = sorted(nodes, key=lambda n: (_num(nodes[n].get("y_mm")),
                                           _num(nodes[n].get("x_mm")), str(n)))
    for nid in ordered:
        n = nodes[nid]
        if not isinstance(n, dict):
            continue
        prov, skind = _prov_attr(n)
        x = _num(n.get("x_mm"))
        y = _num(n.get("y_mm"))
        w = _num(n.get("w_mm"))
        h = _num(n.get("h_mm"))
        font_pt = _num(n.get("font_pt"), style["font_sizes_pt"]["label"])
        line_h = _num(n.get("line_h_mm"), font_pt * 0.3528 * 1.35)
        lines = n.get("lines") or ([n.get("label")] if n.get("label") else [])
        italic = bool(n.get("label_is_italic"))
        role = str(n.get("membrane_role") or "")
        out.append('<g id="ent:%s" data-entity-id="%s" data-container-id="%s" '
                   'data-prov="%s" data-src-kind="%s" data-node-kind="%s" '
                   'data-level="%s" data-level-source="%s" data-container="%s" '
                   'data-compartment="%s" '
                   'data-membrane-role="%s" data-normalized-symbol="%s" '
                   'data-node-area-mm2="%s" data-node-w-mm="%s" data-node-h-mm="%s" '
                   'data-label-style="%s" class="entity entity-%s"%s>'
                   % (_attr(nid), _attr(n.get("entity_id") or nid),
                      _attr(n.get("container") or ""), _attr(prov), _attr(skind),
                      _attr(n.get("kind", "concept")),
                      _attr(n.get("level") if n.get("level") is not None else ""),
                      _attr(n.get("level_source") or ""),
                      _attr(n.get("container") or ""),
                      _attr(n.get("compartment") or ""), _attr(role),
                      _attr(n.get("normalized_symbol") or ""),
                      _fmt(_num(n.get("node_area_mm2"), w * h)), _fmt(w), _fmt(h),
                      "italic" if italic else "normal", _attr(n.get("kind", "concept")),
                      _source_attrs(n)))
        out.append("<title>%s</title>" % _esc(n.get("label", nid)))
        out.append(_rect(x, y, w, h, n.get("fill") or "#FFFFFF", n.get("stroke") or "#333333",
                         line_w, 1.6))
        total = len(lines) * line_h
        first = y + h / 2.0 - total / 2.0 + line_h * 0.5 + font_pt * 0.3528 * 0.36
        text_extra = (' data-entity-id="%s" data-text-role="entity-label"%s'
                      % (_attr(n.get("entity_id") or nid),
                         ' font-style="italic"' if italic else ""))
        for i, line in enumerate(lines):
            out.append(_text(x + w / 2.0, first + i * line_h, line, font_pt,
                             style["font_family"], "middle", text_extra))
        # An entity that carries a measured value must expose that number on the
        # canvas, so the "every annotated number is source-bound" gate can see it.
        value = n.get("value")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out.append('<g id="entval:%s" data-entity-id="%s" data-value="%s" '
                       'data-unit="%s" data-text-role="entity-value" '
                       'data-prov="%s" data-src-kind="%s"><title>%s</title></g>'
                       % (_attr(nid), _attr(n.get("entity_id") or nid), _fmt(value),
                          _attr(n.get("unit") or ""), _attr(prov), _attr(skind),
                          _esc("%s = %s %s" % (n.get("label", nid), _fmt(value),
                                               n.get("unit") or ""))))
        abundance = n.get("abundance_value")
        if isinstance(abundance, (int, float)) and not isinstance(abundance, bool):
            out.append('<g id="entabund:%s" data-entity-id="%s" data-value="%s" '
                       'data-unit="%s" data-node-area-mm2="%s" data-abundance-scale="%s" '
                       'data-text-role="entity-abundance" data-prov="%s" '
                       'data-src-kind="%s"><title>%s</title></g>'
                       % (_attr(nid), _attr(n.get("entity_id") or nid), _fmt(abundance),
                          _attr(n.get("abundance_unit") or ""),
                          _fmt(_num(n.get("node_area_mm2"), w * h)),
                          _fmt(_num(n.get("abundance_scale"), 1.0)),
                          _attr(prov), _attr(skind),
                          _esc("%s abundance=%s %s" % (n.get("label", nid), _fmt(abundance),
                                                       n.get("abundance_unit") or ""))))
        out.append("</g>")
    if chart:
        out.extend(_series_marks(chart, style))
    out.append("</g>")
    return out


def _labels_layer(layout, style):
    out = list(_layer_open("labels"))
    title = layout.get("title")
    if isinstance(title, dict) and title.get("lines"):
        prov, skind = _prov_attr(title)
        pt = _num(title.get("font_pt"), style["font_sizes_pt"]["title"])
        line_h = pt * 0.3528 * 1.35
        lines = title["lines"]
        y0 = _num(title.get("y_mm"))
        out.append('<g id="fig:title" data-prov="%s" data-src-kind="%s" class="title">'
                   % (_attr(prov), _attr(skind)))
        out.append("<title>%s</title>" % _esc(title.get("text", "")))
        for i, line in enumerate(lines):
            out.append(_text(_num(title.get("x_mm")), y0 + i * line_h, line, pt,
                             style["font_family"], "middle",
                             ' font-weight="bold"'))
        out.append("</g>")
    panels = layout.get("panels") if isinstance(layout.get("panels"), dict) else {}
    for pid in sorted(panels, key=lambda p: _num(panels[p].get("x_mm"))):
        p = panels[pid]
        if not isinstance(p, dict):
            continue
        prov, skind = _prov_attr(p)
        out.append('<g id="pnl:%s" data-prov="%s" data-src-kind="%s" class="panel">'
                   % (_attr(pid), _attr(prov), _attr(skind)))
        out.append("<title>%s</title>" % _esc("panel %s" % pid))
        out.append(_text(_num(p.get("x_mm")), _num(p.get("y_mm")), p.get("letter", pid),
                         _num(p.get("font_pt"), style["font_sizes_pt"]["panel"]),
                         style["font_family"], "start", ' font-weight="bold"'))
        out.append("</g>")
    out.append("</g>")
    return out


_ENCODING_CHANNELS = ("color", "line_width", "node_size", "line_style")
_NODE_SIZE_NAMES = {"tiny": 0.9, "small": 1.2, "medium": 1.8, "large": 2.6, "huge": 3.3}


def _legend_encoding_layout(model, legend):
    """``[(legend_id, item, encoding)]`` for every declared encoding channel."""
    declared = []
    seen = set()
    source = model.get("legend") if isinstance(model, dict) else None
    if not isinstance(source, list):
        source = legend.get("items") or []
    for item in source or []:
        if not isinstance(item, dict):
            continue
        enc = item.get("encoding")
        channel = str((enc or {}).get("channel") or "").strip().lower() if isinstance(enc, dict) else ""
        lid = str(item.get("id") or "")
        if lid in seen or channel not in _ENCODING_CHANNELS:
            continue
        seen.add(lid)
        declared.append((lid, item, enc))
    return declared


def _node_size_radius(visual):
    """Radius (mm) for a ``node_size`` visual: a number is an area in mm2."""
    text = str(visual).strip()
    lowered = text.lower()
    if lowered in _NODE_SIZE_NAMES:
        return _NODE_SIZE_NAMES[lowered]
    value = _num(text, 0.0)
    if value <= 0:
        return 1.4
    return max(0.7, min(4.2, (value / 3.141592653589793) ** 0.5))


def _legend_encoding_blocks(model, legend, style):
    """Render ``legend[].encoding`` (CONTRACT 3.6) as a real, addressable table.

    One group per (legend item, channel) and one row per ``mapping[]`` entry.
    Each row carries ``data-legend-encoding`` / ``data-legend-field`` /
    ``data-mapping-value`` / ``data-visual`` so the three-way consistency gate
    (legend == canvas == data) can be decided from the artifact, and draws a
    glyph whose *geometry* encodes the same visual (a swatch, a stroke of the
    declared width, a circle whose area matches, a line with the declared dash
    and head).  Rows are stacked inside the legend frame; the layout engine owns
    ``legend.h_mm`` and must reserve the room, otherwise the group is flagged
    with ``data-legend-encoding-overflow="true"`` rather than silently clipped.
    """
    declared = _legend_encoding_layout(model, legend)
    if not declared:
        return []
    x0 = _num(legend.get("x_mm")) + 2.6
    y_bottom = _num(legend.get("y_mm")) + _num(legend.get("h_mm")) - 2.0
    row_h = 4.6
    header_h = 4.2
    gap = 1.6
    total = sum(header_h + len(enc.get("mapping") or []) * row_h + gap
                for _lid, _item, enc in declared)
    y = y_bottom - total
    overflow = y < _num(legend.get("y_mm")) + 2.0
    out = ['<g id="legend:encodings" data-role="legend-encoding-table" '
           'data-legend-encoding-overflow="%s">' % ("true" if overflow else "false"),
           "<title>%s</title>" % _esc("legend data encodings (channel -> visual)")]
    for lid, item, enc in declared:
        channel = str(enc.get("channel")).strip().lower()
        field = str(enc.get("field") or "")
        unit = str(enc.get("unit") or "")
        prov, skind = _prov_attr(item)
        pt = _num(item.get("font_pt"), style["font_sizes_pt"]["legend"])
        out.append('<g id="lgenc:%s:%s" data-legend-id="%s" data-legend-encoding="%s" '
                   'data-legend-field="%s" data-legend-unit="%s" data-prov="%s" '
                   'data-src-kind="%s" class="legend-encoding">'
                   % (_attr(lid), _attr(channel), _attr(lid), _attr(channel),
                      _attr(field), _attr(unit), _attr(prov), _attr(skind)))
        out.append("<title>%s</title>" % _esc(
            "%s: %s%s" % (channel, field, (" [%s]" % unit) if unit else "")))
        head_text = channel.replace("_", " ")
        if field:
            head_text += " = %s" % field
        if unit:
            head_text += " (%s)" % unit
        out.append(_text(x0, y + 2.6, head_text, pt, style["font_family"], "start",
                         ' font-weight="bold" data-text-role="legend-encoding-header"'))
        y += header_h
        for row_index, row in enumerate(enc.get("mapping") or []):
            if not isinstance(row, dict):
                continue
            value = row.get("value")
            visual = row.get("visual")
            cy = y + row_h * 0.55
            gw = 7.0
            row_extra = (' data-legend-id="%s" data-legend-encoding="%s" '
                         'data-mapping-value="%s" data-visual="%s" data-visual-kind="%s" '
                         'data-mapping-index="%d" data-text-role="legend-encoding-row"'
                         % (_attr(lid), _attr(channel), _attr(value), _attr(visual),
                            _attr(channel), row_index))
            out.append('<g id="lgenc:%s:%s:%d"%s>'
                       % (_attr(lid), _attr(channel), row_index, row_extra))
            out.append("<title>%s</title>" % _esc("%s -> %s" % (value, visual)))
            glyph = ""
            if channel == "color":
                fill = str(visual) if re.match(r"^#?[0-9a-fA-F]{6}$", str(visual).strip()) \
                    else style["palette"][0]
                if not str(fill).startswith("#"):
                    fill = "#" + str(fill)
                glyph = _rect(x0, cy - 1.4, gw, 2.8, fill, "#FFFFFF", _sw(0.4))
            elif channel == "line_width":
                glyph = _polyline([(x0, cy), (x0 + gw, cy)], "#333333",
                                  _num(visual, 0.8) or 0.8)
            elif channel == "node_size":
                radius = _node_size_radius(visual)
                glyph = ('<circle cx="%s" cy="%s" r="%s" fill="%s" stroke="#FFFFFF" '
                         'stroke-width="%s"/>'
                         % (_fmt(_uu(x0 + gw / 2.0)), _fmt(_uu(cy)), _fmt(_uu(radius)),
                            style["palette"][0], _fmt(_sw(0.4) * PT_TO_UU)))
            else:
                style_name, head_name = _split_line_style(visual)
                pts = [(x0, cy), (x0 + gw, cy)]
                glyph = _polyline(pts, "#333333", _num(style["line_widths_pt"]["edge"], 0.8),
                                  style=style_name)
                glyph += _head(pts, True, head_name, "#333333")
            out.append(glyph)
            label = "%s -> %s" % (value, visual)
            out.append(_text(x0 + gw + 2.2, cy + pt * 0.3528 * 0.36, label, pt,
                             style["font_family"], "start"))
            out.append("</g>")
            y += row_h
        y += gap
        out.append("</g>")
    out.append("</g>")
    return out


def _split_line_style(visual):
    """``"dashed+arrow:tee"`` -> ``("dashed", "tee")`` (tolerant of spellings)."""
    text = str(visual or "solid").strip().lower()
    stroke = "solid"
    head = "none"
    for token in re.split(r"[+|,;:/ ]+", text):
        if token in ("solid", "dashed", "dotted"):
            stroke = token
        elif token in ("normal", "arrow"):
            head = "arrow"
        elif token == "tee":
            head = "tee"
        elif token == "none":
            head = "none"
    return stroke, head


def _legend_layer(layout, style, model=None):
    out = list(_layer_open("legend"))
    legend = layout.get("legend") if isinstance(layout.get("legend"), dict) else None
    if not legend:
        out.append("</g>")
        return out
    line_w = _num(style["line_widths_pt"]["node"])
    # decorative chrome: no provenance attributes at all.  A provenance claim must
    # be verifiable, and CONTRACT 4.7 lists only explicit/derived/unsupported as
    # src-kinds - the frame is none of them; the legend ITEMS below are the bound ones.
    out.append('<g id="legend:frame" data-role="legend-frame">'
               "<title>%s</title>" % _esc("legend frame"))
    out.append(_rect(_num(legend.get("x_mm")), _num(legend.get("y_mm")),
                     _num(legend.get("w_mm")), _num(legend.get("h_mm")),
                     "#FFFFFF", FRAME_COLOR, line_w * 0.8, 1.6))
    out.append("</g>")
    for it in legend.get("items") or []:
        if not isinstance(it, dict):
            continue
        prov, skind = _prov_attr(it)
        color = it.get("color") or style["palette"][0]
        gx = _num(it.get("x_mm"))
        cy = _num(it.get("glyph_cy_mm"))
        gw = _num(it.get("glyph_w_mm"), 6.0)
        kind = str(it.get("kind") or "category")
        marker = str(it.get("marker") or "")
        out.append('<g id="lg:%s" data-legend-id="%s" data-prov="%s" data-src-kind="%s" '
                   'data-legend-kind="%s" data-legend-value="%s" data-marker="%s" '
                   'data-origin="%s" class="legend-item"%s>'
                   % (_attr(it.get("id")), _attr(it.get("id")), _attr(prov), _attr(skind),
                      _attr(kind), _attr(it.get("value") or ""), _attr(marker),
                      _attr(it.get("origin", "legend")), _source_attrs(it)))
        out.append("<title>%s</title>" % _esc(it.get("label", "")))
        if kind == "line_style":
            pts = [(gx, cy), (gx + gw, cy)]
            stroke_style = str(it.get("stroke_style") or "").strip().lower()
            if stroke_style not in ("solid", "dashed", "dotted"):
                stroke_style = ("dashed" if ("dashed" in marker
                                             or "dashed" in str(it.get("value") or ""))
                                else "solid")
            out.append(_polyline(pts, color, _num(style["line_widths_pt"]["edge"]),
                                 style=stroke_style))
            head = "none"
            if marker.endswith("normal"):
                head = "arrow"
            elif marker.endswith("tee"):
                head = "tee"
            out.append(_head(pts, True, head, color))
        elif marker == "line":
            pts = [(gx, cy), (gx + gw, cy)]
            out.append(_polyline(pts, color, _num(style["line_widths_pt"]["edge"])))
            out.append('<circle cx="%s" cy="%s" r="%s" fill="%s" stroke="#FFFFFF" '
                       'stroke-width="%s"/>' % (_fmt(_uu(gx + gw * 0.5)), _fmt(_uu(cy)),
                                                _fmt(1.4), _attr(color),
                                                _fmt(_sw(0.5) * PT_TO_UU)))
        elif marker == "circle":
            out.append('<circle cx="%s" cy="%s" r="%s" fill="%s" stroke="#FFFFFF" '
                       'stroke-width="%s"/>' % (_fmt(_uu(gx + gw / 2.0)), _fmt(_uu(cy)),
                                                _fmt(1.9), _attr(color),
                                                _fmt(_sw(0.5) * PT_TO_UU)))
        elif marker == "triangle":
            out.append(_triangle(gx + gw / 2.0, cy, 2.2, color))
        elif marker == "diamond":
            out.append(_diamond(gx + gw / 2.0, cy, 2.2, color))
        elif kind == "value_scale":
            out.append(_rect(gx, cy - 1.6, gw, 3.2, color, "#666666", line_w * 0.6))
        else:
            size = 6.4
            out.append(_rect(gx + (gw - size) / 2.0, cy - size / 2.0, size, size, color,
                             "#FFFFFF", _sw(0.4)))
        pt = _num(it.get("font_pt"), style["font_sizes_pt"]["legend"])
        line_h = pt * 0.3528 * 1.3
        for i, line in enumerate(it.get("lines") or [it.get("label", "")]):
            out.append(_text(_num(it.get("text_x_mm")), _num(it.get("y_mm")) + line_h * 0.8 + i * line_h,
                             line, pt, style["font_family"], "start"))
        out.append("</g>")
    out.extend(_legend_encoding_blocks(model, legend, style))
    out.append("</g>")
    return out


def _triangle(cx, cy, half, color):
    pts = [(cx, cy - half), (cx + half, cy + half * 0.8), (cx - half, cy + half * 0.8)]
    d = "M %s %s L %s %s L %s %s Z" % tuple(
        v for p in pts for v in (_fmt(_uu(p[0])), _fmt(_uu(p[1]))))
    return '<path d="%s" fill="%s" stroke="#FFFFFF" stroke-width="%s"/>' % (
        d, _attr(color), _fmt(0.4))


def _diamond(cx, cy, half, color):
    pts = [(cx, cy - half), (cx + half, cy), (cx, cy + half), (cx - half, cy)]
    d = "M %s %s L %s %s L %s %s L %s %s Z" % tuple(
        v for p in pts for v in (_fmt(_uu(p[0])), _fmt(_uu(p[1]))))
    return '<path d="%s" fill="%s" stroke="#FFFFFF" stroke-width="%s"/>' % (
        d, _attr(color), _fmt(0.4))


def _annotations_layer(layout, style):
    out = list(_layer_open("annotations"))
    for ann in layout.get("annotations") or []:
        if not isinstance(ann, dict):
            continue
        prov, skind = _prov_attr(ann)
        pt = _num(ann.get("font_pt"), style["font_sizes_pt"]["legend"])
        line_h = pt * 0.3528 * 1.35
        out.append('<g id="%s" data-prov="%s" data-src-kind="%s" class="caption">'
                   % (_attr(ann.get("id")), _attr(prov), _attr(skind)))
        out.append("<title>%s</title>" % _esc("panel %s caption" % ann.get("panel", "")))
        for i, line in enumerate(ann.get("lines") or []):
            out.append(_text(_num(ann.get("x_mm")), _num(ann.get("y_mm")) + i * line_h,
                             line, pt, style["font_family"],
                             str(ann.get("anchor") or "start")))
        out.append("</g>")
    out.append("</g>")
    return out


# --------------------------------------------------------------------------
# metadata
# --------------------------------------------------------------------------
def _metadata(model, layout, style, chart):
    fig = model.get("figure") if isinstance(model.get("figure"), dict) else {}
    prov = model.get("provenance") if isinstance(model.get("provenance"), dict) else {}
    meta = {
        "schema_version": str(layout.get("schema_version") or model.get("schema_version") or "1.0"),
        "case_id": str(model.get("case_id") or "(none)"),
        "figure_id": str(fig.get("id") or ""),
        "figure_kind": str(fig.get("kind") or ""),
        "model_sha256": _sha256_text(_canonical(model)),
        "generated_by": str(prov.get("generated_by") or "(none)"),
        "created_utc": str(prov.get("created_utc") or "(none)"),
        "unit_scale": {"uu_per_mm": round(MM_TO_UU, 10), "uu_per_pt": round(PT_TO_UU, 10),
                       "base_dpi": 96.0, "canvas_width_mm": _num(
                           (layout.get("canvas") or {}).get("width_mm")),
                       "canvas_height_mm": _num(
                           (layout.get("canvas") or {}).get("height_mm"))},
        "font_stack": list(style["font_stack"]),
        "palette": list(style["palette"]),
        "layers": ["layer:%s" % x for x in LAYER_IDS],
        "id_scheme": {"entity": "ent:<id>", "relation": "rel:<id>",
                      "legend": "lg:<id>", "container": "cnt:<id>|ent:<id>",
                      "axes": "axes:<figure-id>", "series": "series:<index>"},
        "data_id_attributes": ["data-entity-id", "data-relation-id",
                               "data-container-id", "data-legend-id"],
        "provenance_attributes": ["data-prov", "data-src-kind", "data-source-path",
                                  "data-source-locator", "data-source-kind",
                                  "data-has-quote", "data-rel-type",
                                  "data-direction"],
        "interaction_style_table": {k: {"arrow": v["arrow"], "stroke": v["stroke"]}
                                    for k, v in sorted(INTERACTION_STYLE.items())},
        "strength_line_width_pt": dict(STRENGTH_WIDTH_PT),
        "chart": bool(chart),
        "editable_text": True,
    }
    if isinstance(model.get("data"), dict) and model["data"].get("path"):
        meta["data"] = {"path": str(model["data"]["path"]),
                        "sha256": str(model["data"].get("sha256") or "")}
    return meta


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------
def render(model, layout):
    """Return the complete SVG document for ``model`` + ``layout`` (never raises)."""
    if not isinstance(model, dict):
        model = {}
    if not isinstance(layout, dict):
        layout = {}
    # The frozen interaction vocabulary and the data encodings are applied here,
    # not by the caller, so every consumer (render, export, edit) sees one truth.
    layout = decorate_layout(model, layout)
    style = _style_of(model, layout)
    canvas = layout.get("canvas") if isinstance(layout.get("canvas"), dict) else {}
    fig = model.get("figure") if isinstance(model.get("figure"), dict) else {}
    fig_canvas = fig.get("canvas") if isinstance(fig.get("canvas"), dict) else {}
    W = _num(canvas.get("width_mm"), _num(fig_canvas.get("width_mm"), 180.0)) or 180.0
    H = _num(canvas.get("height_mm"), _num(fig_canvas.get("height_mm"), 120.0)) or 120.0
    chart = layout.get("chart") if isinstance(layout.get("chart"), dict) else None

    title_text = ""
    if isinstance(layout.get("title"), dict):
        title_text = str(layout["title"].get("text") or "")
    if not title_text and isinstance(fig.get("title"), dict):
        title_text = str(fig["title"].get("text") or "")
    if not title_text:
        title_text = "figure %s" % (fig.get("id") or "(unnamed)")

    body = []
    body.append('<?xml version="1.0" encoding="UTF-8"?>')
    body.append('<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
                'width="%smm" height="%smm" viewBox="0 0 %s %s" '
                'preserveAspectRatio="xMidYMid meet" '
                'shape-rendering="geometricPrecision" text-rendering="geometricPrecision">'
                % (_fmt(W), _fmt(H), _fmt(_uu(W)), _fmt(_uu(H))))
    body.append("<title>%s</title>" % _esc(title_text))
    body.append("<desc>%s</desc>" % _esc(
        "Editable layered scientific figure generated deterministically from a "
        "source-bound model; %s" % (style["font_family"])))
    body.append("<metadata>%s</metadata>" % _esc(_canonical(_metadata(model, layout, style, chart))))
    body.extend(_background_layer(layout, style, chart))
    body.extend(_containers_layer(layout, style))
    body.extend(_edges_layer(layout, style))
    body.extend(_nodes_layer(layout, style, chart))
    body.extend(_labels_layer(layout, style))
    body.extend(_legend_layer(layout, style, model))
    body.extend(_annotations_layer(layout, style))
    body.append("</svg>")
    return "\n".join(body) + "\n"


def svg_stats(svg_text):
    """Machine-checkable statistics of a rendered SVG (frozen key set)."""
    t = svg_text if isinstance(svg_text, str) else ""
    return {
        "texts": len(re.findall(r"<text[\s>]", t)),
        "paths": len(re.findall(r"<path[\s>]", t)),
        "rects": len(re.findall(r"<rect[\s>]", t)),
        "images": len(re.findall(r"<image[\s>]", t)),
        "layers": len(re.findall(r'<g id="layer:', t)),
        "has_metadata": "<metadata" in t,
        "data_prov_count": len(re.findall(r'data-prov="', t)),
        # frozen machine-addressable anchors (CONTRACT 4: content_map / data-entity-id)
        "data_entity_ids": len(re.findall(r'data-entity-id="', t)),
        "data_relation_ids": len(re.findall(r'data-relation-id="', t)),
        "data_container_ids": len(re.findall(r'data-container-id="', t)),
        "data_legend_ids": len(re.findall(r'data-legend-id="', t)),
        "data_source_attrs": len(re.findall(r'data-source-path="', t)),
        "legend_encoding_rows": len(re.findall(r'data-mapping-index="', t)),
        "bytes": len(t.encode("utf-8")),
    }


def _main(argv):
    import sys
    if len(argv) < 3:
        sys.stderr.write("usage: render_svg.py <model.json> <layout.json> [out.svg]\n")
        return 2
    with open(argv[1], "r", encoding="utf-8") as fh:
        model = json.load(fh)
    with open(argv[2], "r", encoding="utf-8") as fh:
        layout = json.load(fh)
    svg = render(model, layout)
    if len(argv) > 3:
        with open(argv[3], "w", encoding="utf-8", newline="\n") as fh:
            fh.write(svg)
    else:
        sys.stdout.write(svg)
    sys.stderr.write(json.dumps(svg_stats(svg)) + "\n")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_main(sys.argv))
