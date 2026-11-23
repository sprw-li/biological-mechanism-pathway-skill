# -*- coding: utf-8 -*-
"""Deterministic layered layout for source-bound scientific figures.

Unit scale
----------
Every coordinate in the returned layout is in millimetres.  The SVG renderer
converts millimetres to user units at ``1 uu = 1 px @ 96 dpi``::

    uu = mm * 96 / 25.4        (1 mm = 3.7795275590551185 uu)
    uu = pt * 96 / 72          (font sizes are given in points)

Graphical grammar (what each relation type looks like)
------------------------------------------------------
============================  ==========================================
activation / sequence / cause solid line + filled arrow head
inhibition                    solid line + tee head (bar, no arrow head)
direction="none" association  plain line, no head
direction="bidirectional"     heads at both ends
containment / membership      enclosure rectangle, members inside its bounds
style.stroke == "dashed"      ``stroke-dasharray`` on the line
============================  ==========================================

Algorithm (all steps deterministic; every tie is broken by id)
--------------------------------------------------------------
1. **Levels** - longest path over the directional grammar
   (activation/inhibition/sequence/causation with ``direction == "forward"``).
   Cycles are broken by an iterative DFS in id order; the edge that closes the
   cycle becomes a *feedback* edge: it keeps its level endpoints and is routed
   around the outside of the figure.  ``containment`` never creates a level
   edge.  ``entity.layout.level`` acts as a lower bound, never as an override
   that would contradict a forward edge.
2. **Columns** - one column per level, column width = widest box of that level.
   Labels are wrapped (greedy, no information loss) so a label never overflows
   its box; text width is estimated as ``sum(factor) * font_pt * 25.4/72`` with
   factor 0.58 for Latin and 1.0 for CJK / fullwidth characters.
3. **Bands (swimlanes)** - containers become nested horizontal bands: explicit
   ``containers[]``, entity-as-container created by ``containment`` relations,
   and nested containers.  A band stacks its child bands plus its own per-level
   node stacks, so every container box encloses exactly its members by
   construction and containers never overlap.  When a model has no directional
   edge at all the columns are synthesised as an aspect-aware grid instead of a
   single very tall column.
4. **Ordering** - three barycentre sweeps reorder the nodes inside every
   (band, level) stack; ties fall back to ``layout.order`` then id.
5. **Routing** - orthogonal polylines through free channels: inter-column gaps,
   root band gaps and the two outer lanes.  Feedback edges are routed around the
   top or bottom outer lane.
6. **Spacing** - a compaction ladder (gaps x 1.0/0.85/0.7/0.55) keeps the
   content inside ``figure.canvas``; when the content is too tall the canvas
   grows in height only (recorded in ``stats.canvas_adjusted``).  Horizontal
   overflow is *never* hidden: ``check_layout`` reports ``E_OUT_OF_CANVAS``.

Returned object (frozen keys first, documented extras after)
-----------------------------------------------------------
``schema_version, canvas, nodes, containers, edges, legend, panels, stats``
plus ``style, title, annotations, chart, metrics, warnings`` - all extras are
consumed by ``render_svg.py`` and documented in
``references/layout_and_svg.md``.

Mechanism / pathway figures (FROZEN CONTRACT v1.1)
--------------------------------------------------
Everything below is *additive*: a model that carries none of these fields lays
out exactly as before (that is what keeps the historical 67/67 self-test green).

``figure.flow.orientation``
    ``top_down`` (default) or ``left_right``.  The layered engine always works
    in "level = column" logical coordinates; for ``top_down`` the finished
    schematic geometry is transposed (x/y and w/h swapped, edges and anchors
    follow, labels re-wrapped against the *real* box).  Page furniture - title,
    panels, legend, captions - is never transposed, and
    ``layout.flow.transposed`` records which geometry was rotated.

``figure.flow.ranks`` ``{entityId: int}``
    Authoritative ranks.  When absent, ranks are derived by longest path with
    compartment-order lower bounds (only for containers that explicitly declare
    ``kind``), so ``extracellular -> membrane -> cytosol -> nucleus`` comes out
    monotone.  All tie-breaks are by id: repeated runs are byte-identical.

``containers[].kind`` ``compartment | membrane | cell | group``
    A ``membrane`` container is an *interface band*: it spans the full cross
    axis and is one rank deep, and the compartment on the other side of it
    (``extracellular``) stays outside.  ``extracellular``/``cell``/``cytosol``
    are full-width bands; ``nucleus``/``mitochondrion``/``er``/``golgi``/
    ``lysosome`` are inset boxes inside their parent.  The biological chain is
    reported verbatim in ``layout.compartments`` (``chain``, ``interfaces`` with
    the extracellular/cytosolic side of every membrane, ``nesting_repairs`` for
    declarations that cannot hold geometrically).  An ``entity.container`` is
    never rewritten silently: the effective container is reported next to the
    declared one.

``entities[].membrane_role``
    ``transmembrane`` must name a ``kind == "membrane"`` container.
    ``membrane_anchored`` may be modelled in the adjacent cytosolic compartment;
    it is drawn on the membrane band and reported as
    ``container_mode: "forced"`` with ``W_MEMBRANE_ANCHOR_COMPARTMENT``.  Both
    roles get ``membrane_outward`` / ``membrane_domain_out_mm`` so the
    extracellular domain faces the extracellular side.

``legend[].encoding``
    ``{channel, field, unit, mapping:[{value, visual}]}`` is expanded into real
    legend rows; the number of rows equals the number of mapped values, and the
    drawn colours/widths/sizes are taken *from* the mapping, so legend, figure
    and data cannot drift apart.

Error codes owned by this module (additive to the frozen set)
-------------------------------------------------------------
``E_MEMBRANE_PLACEMENT``   membrane_role entity is not on the membrane band,
                           or names a non-membrane container, or the outward
                           domain does not face the extracellular side.
``E_FLOW_DIRECTION``       a non-``feedback`` edge violates
                           ``rank[to] > rank[from]``, or the non-feedback edges
                           contain a directed cycle.
``E_COMPARTMENT_MISMATCH`` ``binding`` endpoints are neither in the same
                           compartment nor adjacent across a membrane.
``E_TRANSPORT_BOUNDARY``   ``transport`` does not cross a real container
                           boundary (checked against the drawn geometry).
``E_EDGE_THROUGH_NODE``    a routed edge passes through a node box, i.e. it
                           would strike a label.
``E_LEGEND_DATA_MISMATCH`` an ``encoding`` mapping disagrees with the values the
                           figure actually uses.
``E_OUT_OF_CANVAS`` / ``E_NODE_OVERLAP`` / ``E_LEVEL_REGRESSION`` /
``E_TEXT_OVERFLOW_EST``    unchanged from the original contract.
"""

from __future__ import annotations

import heapq
import math
import re

# --------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------
SCHEMA_VERSION = "1.0"

UNIT_PER_MM = 96.0 / 25.4          # user units per millimetre (1 uu = 1 px @96dpi)
MM_PER_PT = 25.4 / 72.0            # millimetres per point
EPS = 0.01                         # mm tolerance for geometric checks

DIRECTIONAL_TYPES = ("activation", "inhibition", "modification", "transport",
                     "transcription", "translation", "feedback", "sequence", "causation")

#: FROZEN CONTRACT sec 3.4 - the arrow/stroke of a type is not a style choice.
#: ``HEAD_FOR_TYPE`` keeps the renderer's vocabulary (arrow / tee / none) while
#: ``ARROW_FOR_TYPE`` keeps the contract's (normal / tee / none).
ARROW_FOR_TYPE = {
    "activation": "normal", "sequence": "normal", "causation": "normal",
    "inhibition": "tee",
    "binding": "none",
    "modification": "normal",
    "transport": "normal",
    "transcription": "normal",
    "translation": "normal",
    "feedback": "normal",
    "association": "none",
    "containment": "none",
    "membership": "none",
}
STROKE_FOR_TYPE = {
    "modification": "dashed",
    "feedback": "dashed",
    "association": "dotted",
    "containment": "dotted",
    "membership": "dotted",
}
HEAD_FOR_TYPE = dict(
    (t, {"normal": "arrow", "tee": "tee", "none": "none"}[a])
    for t, a in ARROW_FOR_TYPE.items())
CONTAINMENT_TYPES = ("containment", "membership")
#: types that advance the pathway (``rank[to] > rank[from]``).  ``feedback`` is
#: deliberately *not* here: it is the frozen backward arc of a cycle.
FLOW_TYPES = ("activation", "inhibition", "sequence", "causation", "modification",
              "transport", "transcription", "translation")
#: types allowed to sit on the same rank (sec 3.5)
RANK_EQUAL_TYPES = ("binding", "association")
#: evidence strength -> stroke width (sec 3.6, frozen)
EVIDENCE_WIDTH_PT = {"high": 1.4, "medium": 1.0, "low": 0.6}
TYPE_COLOR_INDEX = {
    "activation": 0, "sequence": 0, "causation": 0, "inhibition": 1,
    "association": 2, "containment": 3, "membership": 3,
}
ENTITY_KINDS = ("gene", "protein", "process", "treatment", "sample", "category",
                "axis", "concept", "compound", "cell", "condition",
                # sec 3.2 (mechanism / pathway figures)
                "complex", "organelle", "cell_type", "metabolite",
                "modification_site", "stimulus", "drug")

#: sec 3.3 - ``containers[].kind``
CONTAINER_KINDS = ("compartment", "membrane", "cell", "group")
#: compartment sub-names; also accepted directly as ``kind``
COMPARTMENT_NAMES = ("extracellular", "plasma_membrane", "membrane", "cytosol",
                     "cytoplasm", "nucleus", "mitochondrion", "mitochondria",
                     "er", "endoplasmic_reticulum", "golgi", "lysosome")
#: order along the flow axis, outermost/upstream first.  Used to (a) synthesise
#: the extracellular > membrane > cytosol > organelle chain when the model
#: declares flat compartments and (b) seed rank lower bounds.
COMPARTMENT_ORDER = {
    "cell": -1, "extracellular": 0,
    "plasma_membrane": 1, "membrane": 1,
    "cytosol": 2, "cytoplasm": 2,
    "nucleus": 3, "mitochondrion": 3, "mitochondria": 3, "er": 3,
    "endoplasmic_reticulum": 3, "golgi": 3, "lysosome": 3,
}
#: membrane roles that must be drawn on the membrane band (sec 3.3)
MEMBRANE_ROLES = ("transmembrane", "membrane_anchored")

#: The vertical (``top_down``) rendering path is deliberately disabled in this version.
#: Node boxes are sized and their labels wrapped against the *horizontal* level axis, and
#: the transposition step then swaps the box extents without re-wrapping, so a requested
#: ``top_down`` figure came out with one-character-per-line labels and geometry outside the
#: canvas.  Rather than emit a broken figure we render the pathway horizontally and report
#: the substitution (``W_ORIENTATION_RENDERED_HORIZONTAL`` + ``flow.orientation_fallback``):
#: rank order, compartment nesting and edge semantics are unchanged, only the page axis is.
#: Set this to True only after the transposition re-wraps labels for the swapped boxes.
TOP_DOWN_RENDER_ENABLED = False

#: Legibility bounds for the abundance -> node size channel (CONTRACT sec 3.6, area
#: proportional).  The drawn factor is bounded so a single outlier cannot blow up the
#: canvas, but every clamped element raises ``W_ABUNDANCE_SIZE_CLAMPED`` with the true
#: factor, so the deviation is disclosed instead of silently changing the data story.
MIN_ABUNDANCE_SCALE = 0.5
MAX_ABUNDANCE_SCALE = 2.5
#: compartments drawn as a band spanning the full cross axis
SPAN_COMPARTMENTS = ("cell", "extracellular", "cytosol", "cytoplasm",
                     "plasma_membrane", "membrane")
#: compartments drawn as an inset box inside their parent (organelles)
INSET_COMPARTMENTS = ("nucleus", "mitochondrion", "mitochondria", "er",
                      "endoplasmic_reticulum", "golgi", "lysosome")
DEFAULT_FONT_STACK = ["DejaVu Sans", "Liberation Sans", "Arial"]
DEFAULT_FONT_SIZES_PT = {"panel": 9.0, "label": 7.0, "title": 9.0, "legend": 7.0}
DEFAULT_LINE_WIDTHS_PT = {"edge": 0.8, "node": 0.6, "axis": 0.6}
DEFAULT_PALETTE = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#56B4E9",
                   "#E69F00", "#F0E442", "#999999"]
DEFAULT_CANVAS_MM = (180.0, 120.0)
DEFAULT_BACKGROUND = "#FFFFFF"
DEFAULT_MARGIN_MM = 6.0
#: default node paint: the legend is the colour authority, so an entity the
#: model does not colour is drawn neutral instead of inventing a semantic colour
NEUTRAL_NODE_FILL = "#F4F7FA"
NEUTRAL_NODE_STROKE = "#4A5560"
MAX_CANVAS_GROWTH = 2.0            # never grow the canvas beyond this factor
MAX_EDGE_LABEL_MM = 34.0
LINE_FACTOR = 1.35                 # line height / font size

#: base spacing constants (mm); the compaction ladder scales the gaps only
BASE_GAPS = {
    "margin": DEFAULT_MARGIN_MM,
    "col_gap": 7.0,
    "row_gap": 3.6,
    "band_gap": 3.6,
    "cont_pad": 2.6,
    "cont_label_h": 5.0,
    "node_pad_x": 2.2,
    "node_pad_y": 1.7,
    "min_node_w": 15.0,
    "min_node_h": 7.2,
    "min_col_w": 9.0,
    "legend_row_h": 4.4,
    "legend_pad": 2.0,
    "legend_glyph_w": 6.0,
    "legend_gap": 1.6,
    "legend_sep": 4.0,
    "caption_row_h": 4.0,
    "title_pad": 3.0,
    "panel_band": 6.0,
    "lane_pad": 1.6,
}
COMPACTION_SCALES = (1.0, 0.85, 0.7, 0.55, 0.42)

#: readability budget.  A label is never dropped: it is re-wrapped, then shrunk
#: (down to ``MIN_LABEL_FONT_PT``), and every degradation is recorded in
#: ``stats.degradations`` plus a warning.
MIN_LABEL_FONT_PT = 5.5
MAX_LABEL_LINES = 6
DEGRADE_LADDER = (1.0, 0.9, 0.8, 0.72)
#: the deterministic fit may shrink the page uniformly, but never below the
#: smallest text size a journal preset accepts (7 pt * 0.86 = 6.02 pt)
MIN_FIT_SCALE = 0.86

#: membrane band geometry
MEMBRANE_MIN_H_MM = 8.0            # a narrow band still has to hold its nodes
MEMBRANE_BAND_STEP_MM = 1.4        # outward probe length used by check_layout
OUTWARD_DIRS = {"top_down": ("up", "down"), "left_right": ("left", "right")}

# character width factors (fraction of the font size)
LATIN_FACTOR = 0.58
CJK_FACTOR = 1.0
_WIDE_RANGES = ((0x1100, 0x115F), (0x2E80, 0x303F), (0x3040, 0x30FF),
                (0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xA000, 0xA4CF),
                (0xAC00, 0xD7A3), (0xF900, 0xFAFF), (0xFE30, 0xFE4F),
                (0xFF00, 0xFF60), (0xFFE0, 0xFFE6))
_WIDE_CHARS = u"\u2014\u2013\u2026\u00b7\u2192\u2190\u22a5"


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------
def _w(code, message, where=""):
    return {"code": code, "message": message, "where": where}


def _skey(value):
    """Sort key for containers/bands: the root (None) first, then id order."""
    return (value is not None, str(value))


def _num_or(value, default=0.0):
    f = _as_float(value)
    return default if f is None else f


def _as_float(value, default=None):
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        f = float(value)
        if math.isfinite(f):
            return f
        return default
    if isinstance(value, str):
        try:
            f = float(value.strip())
        except (TypeError, ValueError):
            return default
        return f if math.isfinite(f) else default
    return default


def _is_wide(ch):
    o = ord(ch)
    if ch in _WIDE_CHARS:
        return True
    for lo, hi in _WIDE_RANGES:
        if lo <= o <= hi:
            return True
    return False


def char_factor(ch):
    """Width factor of one character: 1.0 for CJK/fullwidth, 0.58 otherwise."""
    return CJK_FACTOR if _is_wide(ch) else LATIN_FACTOR


def est_text_width_mm(text, font_pt):
    """char count x 0.58 x font size (CJK x 1.0), in millimetres."""
    total = 0.0
    for ch in str(text if text is not None else ""):
        total += char_factor(ch)
    return total * float(font_pt) * MM_PER_PT


def wrap_label(text, max_w_mm, font_pt, max_lines=None):
    """Greedy deterministic wrap; never drops characters.

    Breaks at a space when one is available in the current line, otherwise
    between characters (CJK safe).  ``max_lines`` is only a soft limit: the last
    line absorbs the remainder so that no text is ever lost - callers that want
    a hard truncation must do it themselves.
    """
    s = " ".join(str(text if text is not None else "").split())
    if not s:
        return [""]
    limit = max(0.5, float(max_w_mm))
    lines = []
    cur = ""
    for ch in s:
        if cur and est_text_width_mm(cur + ch, font_pt) > limit:
            sp = cur.rfind(" ")
            if 0 < sp and est_text_width_mm(cur[:sp], font_pt) <= limit:
                lines.append(cur[:sp].rstrip())
                cur = (cur[sp + 1:] + ch).lstrip()
            else:
                lines.append(cur)
                cur = ch
        else:
            cur += ch
    if cur or not lines:
        lines.append(cur)
    if max_lines is not None and len(lines) > max_lines:
        head = lines[:max_lines - 1]
        head.append("".join(lines[max_lines - 1:]))
        lines = head
    return lines


def _valid_color(value):
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.startswith("#"):
        body = s[1:]
        if len(body) in (3, 6) and all(c in "0123456789abcdefABCDEF" for c in body):
            return s
        return None
    if s.lower().startswith("rgb(") and s.endswith(")"):
        return s
    if all(c.isalpha() or c == " " for c in s):
        return s
    return None


def _hex_rgb(value):
    s = _valid_color(value) or ""
    if s.startswith("#"):
        body = s[1:]
        if len(body) == 3:
            body = "".join(c * 2 for c in body)
        if len(body) == 6:
            try:
                return (int(body[0:2], 16), int(body[2:4], 16), int(body[4:6], 16))
            except ValueError:
                return None
    return None


def _mix_with_white(color, keep):
    """Mix ``color`` with white; ``keep`` = weight of the original colour."""
    rgb = _hex_rgb(color)
    if rgb is None:
        return color if _valid_color(color) else "#FFFFFF"
    k = min(1.0, max(0.0, float(keep)))
    out = [int(round(c * k + 255.0 * (1.0 - k))) for c in rgb]
    return "#%02X%02X%02X" % (out[0], out[1], out[2])


def _src(source):
    if not isinstance(source, dict):
        return {"path": "", "locator": "", "quote": "", "kind": "unsupported"}
    kind = str(source.get("kind") or "")
    if kind not in ("explicit", "derived", "unsupported"):
        kind = "unsupported"
    return {
        "path": str(source.get("path") or ""),
        "locator": str(source.get("locator") or ""),
        "quote": str(source.get("quote") or ""),
        "kind": kind,
    }


def _prov_of(source):
    src = _src(source)
    path = src["path"] or "(none)"
    locator = src["locator"] or "(none)"
    return "%s#%s" % (path, locator), src["kind"]


#: locator forms frozen by CONTRACT.md 4.1:
#: L12 | L12-L18 | p3 | table:col | fig:1 | json:<json-pointer> | csv:<col>
LOCATOR_RE = re.compile(
    r"^(L\d+(?:-L\d+)?|p\d+|table:[^\s#]+|fig:[\w.\-]+|"
    r"json:[^\s#]+|csv:[^\s#]+)$")


def _valid_locator(locator):
    """True when a locator uses one of the frozen CONTRACT 4.1 forms.

    ``json:``/``csv:`` locators are structured-input citations produced by
    ``ingest`` for a figure workorder / a data table; they are first-class
    provenance, never downgraded to ``unsupported``.
    """
    return bool(LOCATOR_RE.match(str(locator or "").strip()))


def _table_locator(text):
    """``table:<name>`` with the name sanitised to a single token."""
    name = " ".join(str(text or "").split()).strip()
    name = name.replace("#", "-")
    return "table:%s" % (name or "value")


def _series_provenance(series, data):
    """``(prov, src_kind, locator)`` for one drawn series.

    Matches the ``series:<i>`` element run.py writes into source_map.json:
    ``<data.path>#table:<series.column|x_column|name>`` with ``kind=derived``,
    because the marks are computed from that table column.  ``unsupported`` is
    returned only when the model gives no ``data.path`` at all.
    """
    data = data if isinstance(data, dict) else {}
    path = str(data.get("path") or "").strip()
    src = series.get("src") if isinstance(series.get("src"), dict) else {}
    explicit_path = str(src.get("path") or "").strip()
    explicit_loc = str(src.get("locator") or "").strip()
    if src.get("kind") == "explicit" and explicit_path and _valid_locator(explicit_loc):
        return "%s#%s" % (explicit_path, explicit_loc), "explicit", explicit_loc
    column = (series.get("column") or series.get("x_column")
              or (explicit_loc.split(":", 1)[1] if explicit_loc.startswith("table:") else None)
              or series.get("name") or "")
    locator = _table_locator(column)
    if not path:
        return "(none)#(none)", "unsupported", "(none)"
    return "%s#%s" % (path, locator), "derived", locator


def _style(fig, warnings):
    st = fig.get("style") if isinstance(fig.get("style"), dict) else {}
    raw_stack = st.get("font_stack")
    stack = []
    if isinstance(raw_stack, list):
        stack = [str(x).strip() for x in raw_stack if str(x).strip()]
    if not stack:
        stack = list(DEFAULT_FONT_STACK)
        if raw_stack:
            warnings.append(_w("W_STYLE_DEFAULT",
                               "figure.style.font_stack unusable; default stack used",
                               "figure.style.font_stack"))
    sizes = dict(DEFAULT_FONT_SIZES_PT)
    raw_sizes = st.get("font_sizes_pt")
    if isinstance(raw_sizes, dict):
        for key in sorted(raw_sizes):
            f = _as_float(raw_sizes[key])
            if f and f > 0:
                sizes[str(key)] = f
    for key in sorted(DEFAULT_FONT_SIZES_PT):
        sizes.setdefault(key, DEFAULT_FONT_SIZES_PT[key])
    widths = dict(DEFAULT_LINE_WIDTHS_PT)
    raw_widths = st.get("line_widths_pt")
    if isinstance(raw_widths, dict):
        for key in sorted(raw_widths):
            f = _as_float(raw_widths[key])
            if f and f > 0:
                widths[str(key)] = f
    for key in sorted(DEFAULT_LINE_WIDTHS_PT):
        widths.setdefault(key, DEFAULT_LINE_WIDTHS_PT[key])
    raw_pal = st.get("palette")
    palette = []
    if isinstance(raw_pal, list):
        palette = [c for c in (_valid_color(x) for x in raw_pal) if c]
    if not palette:
        palette = list(DEFAULT_PALETTE)
    background = _valid_color(st.get("background")) or _valid_color(
        (fig.get("canvas") or {}).get("background")) or DEFAULT_BACKGROUND
    cs = str(st.get("color_space") or "RGB")
    if cs not in ("RGB", "CMYK"):
        cs = "RGB"
    return {
        "font_stack": stack,
        "font_sizes_pt": sizes,
        "line_widths_pt": widths,
        "palette": palette,
        "background": background,
        "color_space": cs,
        "color_by_kind": st.get("color_by_kind") is True,
    }


def _canvas(fig, warnings):
    cnv = fig.get("canvas") if isinstance(fig.get("canvas"), dict) else {}
    w = _as_float(cnv.get("width_mm"))
    h = _as_float(cnv.get("height_mm"))
    if not w or w <= 0:
        w = DEFAULT_CANVAS_MM[0]
        warnings.append(_w("W_CANVAS_DEFAULT", "figure.canvas.width_mm missing; 180 mm used",
                           "figure.canvas"))
    if not h or h <= 0:
        h = DEFAULT_CANVAS_MM[1]
        warnings.append(_w("W_CANVAS_DEFAULT", "figure.canvas.height_mm missing; 120 mm used",
                           "figure.canvas"))
    return {"width_mm": float(w), "height_mm": float(h)}


# --------------------------------------------------------------------------
# model normalisation
# --------------------------------------------------------------------------
def _membrane_role(raw, attrs):
    """``entities[].membrane_role`` (sec 3.3), accepted at top level or in attributes."""
    role = raw.get("membrane_role")
    if role in (None, ""):
        role = attrs.get("membrane_role") if isinstance(attrs, dict) else None
    if role in (None, ""):
        role = attrs.get("localization") if isinstance(attrs, dict) else None
    role = str(role or "na").strip().lower().replace("-", "_").replace(" ", "_")
    return role if role in MEMBRANE_ROLES + ("luminal", "cytosolic",
                                             "extracellular", "na") else "na"


def _abundance(raw, warnings, eid):
    """``entities[].abundance`` ``{value, unit, source}`` -> node size (sec 3.6).

    Layout never invents a unit: an abundance without one is ignored for sizing
    and reported, so the figure cannot encode an unlabelled number.
    """
    if not isinstance(raw, dict):
        return None
    value = _as_float(raw.get("value"))
    if value is None or value <= 0:
        return None
    unit = str(raw.get("unit") or "").strip()
    if not unit:
        warnings.append(_w("W_UNIT_MISSING",
                           "entity %s has abundance without a unit; size encoding skipped"
                           % eid, "entities.%s.abundance" % eid))
        return None
    return {"value": value, "unit": unit, "source": _src(raw.get("source"))}


def _evidence(raw, warnings, rid):
    """``relations[].evidence`` (sec 3.6) -> ``{strength, kind, note, source}``."""
    if not isinstance(raw, dict):
        return None
    strength = str(raw.get("strength") or "").strip().lower()
    kind = str(raw.get("kind") or "").strip().lower()
    if strength not in EVIDENCE_WIDTH_PT:
        if strength:
            warnings.append(_w("W_EVIDENCE_STRENGTH",
                               "relation %s has unknown evidence.strength %r; line width "
                               "uses the default" % (rid, strength),
                               "relations.%s.evidence" % rid))
        return None
    if kind not in ("direct", "indirect", "inferred", ""):
        warnings.append(_w("W_EVIDENCE_KIND",
                           "relation %s has unknown evidence.kind %r" % (rid, kind),
                           "relations.%s.evidence" % rid))
    return {"strength": strength, "kind": kind,
            "note": str(raw.get("note") or ""),
            "source": _src(raw.get("source"))}


def _entities(model, warnings):
    out = {}
    arr = model.get("entities")
    if arr is None:
        warnings.append(_w("W_NO_ENTITIES", "model has no entities[]", "entities"))
        return out
    if not isinstance(arr, list):
        warnings.append(_w("W_ENTITIES_TYPE", "entities is not a list", "entities"))
        return out
    for i, raw in enumerate(arr):
        if not isinstance(raw, dict):
            warnings.append(_w("W_ENTITY_TYPE", "entity is not an object", "entities[%d]" % i))
            continue
        eid = str(raw.get("id") or "").strip()
        if not eid:
            eid = "entity-%d" % i
            warnings.append(_w("W_ENTITY_NO_ID", "entity without id renamed %s" % eid,
                               "entities[%d]" % i))
        if eid in out:
            warnings.append(_w("W_DUP_ENTITY", "duplicate entity id %s ignored" % eid,
                               "entities[%d]" % i))
            continue
        label = raw.get("label")
        label = str(label) if label not in (None, "") else eid
        kind = str(raw.get("kind") or "concept")
        container = raw.get("container")
        attrs = raw.get("attributes") if isinstance(raw.get("attributes"), dict) else {}
        out[eid] = {
            "id": eid,
            "label": label,
            "kind": kind,
            "container": str(container) if isinstance(container, str) and container else None,
            "membrane_role": _membrane_role(raw, attrs),
            "abundance": _abundance(raw.get("abundance"), warnings, eid),
            "source": _src(raw.get("source")),
            "hint": raw.get("layout") if isinstance(raw.get("layout"), dict) else {},
            "attributes": attrs,
        }
    return out


def _relations(model, ents, warnings):
    out = []
    arr = model.get("relations")
    if arr is None:
        warnings.append(_w("W_NO_RELATIONS", "model has no relations[]", "relations"))
        return out
    if not isinstance(arr, list):
        warnings.append(_w("W_RELATIONS_TYPE", "relations is not a list", "relations"))
        return out
    seen = set()
    for i, raw in enumerate(arr):
        if not isinstance(raw, dict):
            warnings.append(_w("W_RELATION_TYPE", "relation is not an object", "relations[%d]" % i))
            continue
        rid = str(raw.get("id") or "").strip() or "relation-%d" % i
        if rid in seen:
            warnings.append(_w("W_DUP_RELATION", "duplicate relation id %s ignored" % rid,
                               "relations[%d]" % i))
            continue
        seen.add(rid)
        a = str(raw.get("from") or "")
        b = str(raw.get("to") or "")
        rtype = str(raw.get("type") or "association")
        if rtype not in HEAD_FOR_TYPE:
            warnings.append(_w("W_RELATION_KIND_UNKNOWN",
                               "unknown relation type %r treated as association" % rtype,
                               "relations[%d]" % i))
            rtype = "association"
        direction = str(raw.get("direction") or ("forward" if rtype in DIRECTIONAL_TYPES else "none"))
        if direction not in ("forward", "bidirectional", "none"):
            direction = "forward" if rtype in DIRECTIONAL_TYPES else "none"
        style = raw.get("style") if isinstance(raw.get("style"), dict) else {}
        stroke = str(style.get("stroke") or "")
        if stroke and stroke not in ("solid", "dashed", "dotted"):
            warnings.append(_w("W_RELATION_STROKE",
                               "relation %s has unknown style.stroke %r ignored" % (rid, stroke),
                               "relations[%d]" % i))
            stroke = ""
        arrow = str(style.get("arrow") or "")
        if arrow and arrow not in ("normal", "tee", "none"):
            arrow = ""
        # FROZEN sec 3.4: the arrow/stroke of a type is not a style choice.  A
        # contradicting model style is reported and the table wins, so the drawn
        # figure and the mandatory legend entry always agree.
        keep_i = i
        want_arrow = ARROW_FOR_TYPE.get(rtype, "none")
        want_stroke = STROKE_FOR_TYPE.get(rtype, "solid")
        if arrow and arrow != want_arrow:
            warnings.append(_w("W_INTERACTION_STYLE_MISMATCH",
                               "relation %s type %s must use arrow=%s; model said %s"
                               % (rid, rtype, want_arrow, arrow), "relations[%d]" % keep_i))
        if stroke and stroke != want_stroke:
            warnings.append(_w("W_INTERACTION_STYLE_MISMATCH",
                               "relation %s type %s must use stroke=%s; model said %s"
                               % (rid, rtype, want_stroke, stroke), "relations[%d]" % keep_i))
        missing = [x for x in (a, b) if x and x not in ents]
        if not a or not b:
            warnings.append(_w("W_RELATION_ENDPOINT", "relation %s has no endpoints" % rid,
                               "relations[%d]" % i))
            continue
        if missing:
            warnings.append(_w("W_RELATION_DANGLING",
                               "relation %s references unknown id(s) %s; skipped"
                               % (rid, ",".join(sorted(missing))), "relations[%d]" % i))
            continue
        crosses = raw.get("crosses")
        crosses = [str(c) for c in crosses if isinstance(c, str)] \
            if isinstance(crosses, list) else []
        out.append({
            "id": rid, "from": a, "to": b, "type": rtype, "direction": direction,
            "label": str(raw.get("label") or ""),
            "stroke": want_stroke, "arrow": want_arrow,
            "stroke_declared": stroke or want_stroke,
            "arrow_declared": arrow or want_arrow,
            "color": _valid_color(style.get("color")),
            "evidence": _evidence(raw.get("evidence"), warnings, rid),
            "crosses": crosses,
            "source": _src(raw.get("source")),
            "index": i,
        })
    out.sort(key=lambda r: (r["id"], r["index"]))
    return out


def _compartment_from_text(text):
    """Map a container id/label onto a canonical compartment name, or ``None``.

    Exact token matching only: ``c_intracellular`` is *not* the cytosol, and a
    label that merely mentions a compartment is not turned into one.
    """
    s = re.sub(r"[^0-9a-z]+", "_", str(text or "").lower()).strip("_")
    if not s:
        return None
    if s in COMPARTMENT_ORDER:
        return s
    toks = s.split("_")
    if toks and toks[0] in ("c", "cnt", "con", "container", "comp", "cmp"):
        toks = toks[1:]
    if not toks:
        return None
    if "_".join(toks) in COMPARTMENT_ORDER:
        return "_".join(toks)
    for name in sorted(COMPARTMENT_ORDER, key=lambda n: (-len(n), n)):
        parts = name.split("_")
        for i in range(len(toks) - len(parts) + 1):
            if toks[i:i + len(parts)] == parts:
                return name
    return None


def _container_class(raw, cid, label):
    """``(class, compartment)`` for ``containers[].kind`` (sec 3.3).

    The class is ``None`` unless the model *declares* one: an undeclared
    container keeps the legacy behaviour (a plain nested band).  This is what
    makes every mechanism rule opt-in and keeps old models byte-identical.
    """
    kind = re.sub(r"[^0-9a-z]+", "_", str(raw.get("kind") or "").lower()).strip("_")
    subtype = None
    for key in ("compartment", "subtype", "name"):
        v = raw.get(key)
        if isinstance(v, str) and v.strip():
            subtype = _compartment_from_text(v)
            if subtype:
                break
    if subtype is None and kind in COMPARTMENT_ORDER:
        subtype = kind
    if kind in ("membrane", "plasma_membrane"):
        cls = "membrane"
    elif kind in CONTAINER_KINDS:
        cls = kind
    elif kind in COMPARTMENT_ORDER:
        cls = "compartment"
    elif kind:
        cls = "group"
    else:
        cls = None
    if cls == "compartment" and subtype in ("membrane", "plasma_membrane"):
        cls = "membrane"
    if cls is not None and subtype is None:
        subtype = _compartment_from_text(cid) or _compartment_from_text(label)
    return cls, subtype


def _containers(model, ents, warnings):
    out = {}
    arr = model.get("containers")
    if arr is None:
        return out
    if not isinstance(arr, list):
        warnings.append(_w("W_CONTAINERS_TYPE", "containers is not a list", "containers"))
        return out
    for i, raw in enumerate(arr):
        if not isinstance(raw, dict):
            continue
        cid = str(raw.get("id") or "").strip() or "container-%d" % i
        if cid in out:
            warnings.append(_w("W_DUP_CONTAINER", "duplicate container id %s ignored" % cid,
                               "containers[%d]" % i))
            continue
        members = raw.get("members")
        label = str(raw.get("label") or cid)
        cls, subtype = _container_class(raw, cid, label)
        out[cid] = {
            "id": cid,
            "label": label,
            "kind": cls,
            "compartment": subtype,
            "synthetic": False,
            "members": [str(m) for m in members if isinstance(m, str)] if isinstance(members, list) else [],
            "source": _src(raw.get("source")),
            "hint": raw.get("layout") if isinstance(raw.get("layout"), dict) else {},
        }
    return out


# --------------------------------------------------------------------------
# levels
# --------------------------------------------------------------------------
def _flow_config(fig, warnings):
    """``figure.flow`` (sec 3.5): orientation + authoritative ranks."""
    flow = fig.get("flow") if isinstance(fig.get("flow"), dict) else {}
    raw_orient = flow.get("orientation")
    if raw_orient in (None, ""):
        raw_orient = fig.get("orientation")
    orientation = re.sub(r"[^a-z]+", "_", str(raw_orient or "").lower()).strip("_")
    aliases = {
        "top_down": "top_down", "topdown": "top_down", "top_to_bottom": "top_down",
        "top_bottom": "top_down", "vertical": "top_down", "ttb": "top_down",
        "down": "top_down", "column": "top_down",
        "left_right": "left_right", "leftright": "left_right",
        "left_to_right": "left_right", "horizontal": "left_right",
        "ltr": "left_right", "row": "left_right",
    }
    if not orientation:
        orientation = "top_down"                    # sec 3.5 default
    elif orientation not in aliases:
        warnings.append(_w("W_FLOW_ORIENTATION",
                           "figure.flow.orientation %r is unknown; using top_down"
                           % str(raw_orient), "figure.flow.orientation"))
        orientation = "top_down"
    else:
        orientation = aliases[orientation]
    ranks = {}
    raw_ranks = flow.get("ranks")
    if raw_ranks is not None and not isinstance(raw_ranks, dict):
        warnings.append(_w("W_FLOW_RANKS_TYPE", "figure.flow.ranks is not an object; ignored",
                           "figure.flow.ranks"))
        raw_ranks = None
    for key in sorted(raw_ranks or {}):
        val = _as_float((raw_ranks or {})[key])
        if val is None:
            warnings.append(_w("W_FLOW_RANK_VALUE",
                               "figure.flow.ranks[%s] is not a number; ignored" % key,
                               "figure.flow.ranks"))
            continue
        ranks[str(key)] = int(val)
    requested_orientation = orientation
    if orientation == "top_down" and not TOP_DOWN_RENDER_ENABLED:
        warnings.append(_w("W_ORIENTATION_RENDERED_HORIZONTAL",
                           "figure.flow.orientation 'top_down' is rendered left-to-right by "
                           "this version; rank order, compartment nesting and edge semantics "
                           "are unchanged, only the page axis differs",
                           "figure.flow.orientation"))
        orientation = "left_right"
    return {
        "orientation": orientation,
        "requested_orientation": requested_orientation,
        "rendered_orientation": orientation,
        "orientation_fallback": requested_orientation != orientation,
        "ranks": ranks,
        "explicit_ranks": bool(ranks),
        "transposed": orientation == "top_down",
    }


def _compartment_level_hints(ents, conts):
    """Rank lower bounds from *explicitly declared* compartment kinds (sec 3.5).

    ``extracellular -> membrane -> cytosol -> nucleus`` therefore comes out
    monotone even when the model omits ``flow.ranks``.  A container whose kind
    the model does not declare contributes nothing, so legacy models are
    unaffected.
    """
    hints = {}
    for cid in sorted(conts):
        c = conts[cid]
        if not c.get("kind"):
            continue
        order = COMPARTMENT_ORDER.get(c.get("compartment") or "")
        if order is None or order < 0:
            continue
        for eid in sorted(ents):
            if ents[eid].get("container") == cid:
                hints[eid] = max(hints.get(eid, 0), order)
    return hints


def _cycle_edges(ids, adj, kept):
    """Kept edges (u, v) where v can reach u again -> the edge lies on a cycle."""
    reach = {}
    for u in ids:
        seen = set()
        stack = [u]
        while stack:
            x = stack.pop()
            for y in adj.get(x, []):
                if (x, y) in kept and y not in seen:
                    seen.add(y)
                    stack.append(y)
        reach[u] = seen
    out = []
    for (u, v) in sorted(kept):
        if u in reach.get(v, ()):       # v reaches u, so u -> v closes a cycle
            out.append((u, v))
    return out


def _level_edges(relations, warnings):
    """Graph edges that carry the pathway direction (``feedback`` never does)."""
    edges = set()
    dup = []
    for r in relations:
        if r["type"] not in FLOW_TYPES or r["direction"] != "forward":
            continue
        a, b = r["from"], r["to"]
        if a == b:
            continue                     # self-modification is not a level step
        if (a, b) in edges:
            dup.append((a, b))
            continue
        edges.add((a, b))
    for a, b in sorted(set(dup)):
        warnings.append(_w("W_PARALLEL_LEVEL_EDGE",
                           "several relations repeat %s -> %s; the pathway step is drawn once"
                           % (a, b), "relations"))
    return edges


def _assign_levels(ents, relations, warnings, flow=None, conts=None):
    """Deterministic layering: longest path + ``flow.ranks`` pins (sec 3.5)."""
    flow = flow or {}
    ids = sorted(ents)
    adj = dict((i, []) for i in ids)
    hint = {}
    for eid in ids:
        h = ents[eid]["hint"].get("level")
        hv = _as_float(h)
        if hv is not None:
            hint[eid] = max(0, int(hv))
    if conts:
        for eid, lvl in _compartment_level_hints(ents, conts).items():
            hint[eid] = max(hint.get(eid, 0), lvl)
    edge_set = _level_edges(relations, warnings)
    for (a, b) in sorted(edge_set):
        adj[a].append(b)
    for i in ids:
        adj[i] = sorted(set(adj[i]))

    pinned = dict((k, v) for k, v in (flow.get("ranks") or {}).items() if k in ents)
    for key in sorted(set(flow.get("ranks") or {}) - set(ents)):
        warnings.append(_w("W_FLOW_RANK_UNKNOWN",
                           "figure.flow.ranks names unknown entity %s; ignored" % key,
                           "figure.flow.ranks"))

    def levels_for(kept, hint_map=hint, pins=pinned):
        """Longest-path levels of the kept acyclic edges (hints as lower bounds)."""
        dag = dict((i, [j for j in adj[i] if (i, j) in kept]) for i in ids)
        rev = dict((i, []) for i in ids)
        indeg = dict((i, 0) for i in ids)
        for i in ids:
            for j in dag[i]:
                rev[j].append(i)
                indeg[j] += 1
        heap = [i for i in ids if indeg[i] == 0]
        heapq.heapify(heap)
        topo = []
        while heap:
            u = heapq.heappop(heap)
            topo.append(u)
            for v in dag[u]:
                indeg[v] -= 1
                if indeg[v] == 0:
                    heapq.heappush(heap, v)
        lvl = {}
        for u in topo:
            base = hint_map.get(u, 0)
            if u in pins:
                base = pins[u]
            for p in rev[u]:
                base = max(base, lvl.get(p, 0) + 1)
            lvl[u] = base
        for i in ids:                   # safety net for unexpected leftovers
            if i not in lvl:
                lvl[i] = hint_map.get(i, pins.get(i, 0))
        return lvl

    # Greedy deterministic cycle break.  A candidate is any kept edge that lies
    # on a cycle (its head can reach its tail).  Among the candidates we remove
    # the edge that is *semantically* the feedback arc, in this order:
    #   1. an edge the model styles `dashed` (dashed = indirect / feedback arc);
    #   2. the tightest layering: fewest skip-level edges, then smallest total span;
    #   3. the most negative level jump in the trial layering, i.e. keep the edge
    #      whose source stays deep and whose target stays shallow - that is a real
    #      backward arc, not a main-chain step (breaking p53 -> MDM2 instead of
    #      MDM2 -| p53 would invert the whole axis);
    #   4. most redundant endpoints, then id order.
    # All criteria are computed on the model, never on a guess about biology.
    kept = set(edge_set)
    dropped = []
    dashed = set()
    for r in relations:
        if r["type"] in FLOW_TYPES and r["direction"] == "forward" and \
                r["stroke"] in ("dashed", "dotted"):
            dashed.add((r["from"], r["to"]))
    indeg_all = dict((i, 0) for i in ids)
    outdeg_all = dict((i, 0) for i in ids)
    for (u, v) in edge_set:
        outdeg_all[u] += 1
        indeg_all[v] += 1
    for _ in range(len(edge_set) + 1):
        candidates = _cycle_edges(ids, adj, kept)
        if not candidates:
            break
        best = None
        for (u, v) in candidates:
            trial = kept - {(u, v)}
            lvl = levels_for(trial)
            spans = [lvl[t] - lvl[s] for (s, t) in sorted(trial)]
            backward = lvl.get(v, 0) - lvl.get(u, 0)
            redundancy = indeg_all.get(v, 0) + outdeg_all.get(u, 0)
            key = (0 if (u, v) in dashed else 1,
                   sum(1 for x in spans if x > 1), sum(spans),
                   backward, -redundancy, u, v)
            if best is None or key < best[0]:
                best = (key, (u, v))
        if best is None:
            break
        kept.discard(best[1])
        dropped.append(best[1])
    level = levels_for(kept)
    feedback = set()
    for r in relations:
        a, b = r["from"], r["to"]
        if a not in level or b not in level:
            continue
        if r["type"] == "feedback":
            feedback.add((a, b))
            if a != b and level[b] > level[a]:
                warnings.append(_w("W_FEEDBACK_RANK",
                                   "relation %s is typed feedback but rank[%s]=%d > rank[%s]=%d; "
                                   "a feedback arc must go from rank >= to rank"
                                   % (r["id"], b, level[b], a, level[a]),
                                   "relations.%s" % r["id"]))
        elif r["type"] in FLOW_TYPES and r["direction"] == "forward" and a != b:
            if level[b] <= level[a]:
                feedback.add((a, b))
    dropped = sorted(dropped)
    if dropped:
        warnings.append(_w(
            "W_FEEDBACK_CYCLE",
            "directional cycle broken at %s; the edge is drawn as a routed feedback edge"
            % ", ".join("%s->%s" % (a, b) for a, b in dropped),
            "relations"))
    return level, feedback


# --------------------------------------------------------------------------
# membership (containers, entity-as-container, nesting) + cycle breaking
# --------------------------------------------------------------------------
def _membership(ents, conts, relations, levels, warnings):
    """Resolve parent/child membership and break container cycles.

    Precedence (documented): entity.container field > containment relation >
    containers[].members.  Conflicts are reported, never silently dropped.
    """
    warnings = list(warnings)
    parent = {}
    cont_ids = set(conts)
    conflict = []

    def assign(child, par):
        if child == par:
            warnings.append(_w("W_CONTAINER_SELF", "%s contains itself; ignored" % child,
                               "containers"))
            return
        old = parent.get(child)
        if old is not None and old != par:
            conflict.append((child, old, par))
            return
        parent[child] = par

    # 1. explicit per-entity field
    for eid in sorted(ents):
        c = ents[eid].get("container")
        if c and (c in cont_ids or c in ents):
            assign(eid, c)
        elif c:
            warnings.append(_w("W_CONTAINER_DANGLING",
                               "entity %s names unknown container %s" % (eid, c),
                               "entities.%s.container" % eid))
    # 2. containment / membership relations (entity -> entity)
    rel_children = {}
    rel_parent_of = {}
    for r in relations:
        if r["type"] not in CONTAINMENT_TYPES or r["direction"] == "bidirectional":
            continue
        a, b = r["from"], r["to"]
        if a in ents and b in ents and a != b:
            rel_children.setdefault(a, [])
            if b not in rel_parent_of or a < rel_parent_of[b]:
                rel_parent_of[b] = a
    for a in sorted(rel_children):
        rel_children[a] = sorted(rel_children[a])
    for b in sorted(rel_parent_of):
        assign(b, rel_parent_of[b])
    # 3. containers[].members (also allows container-in-container nesting)
    for cid in sorted(conts):
        for mid in sorted(set(conts[cid]["members"])):
            if mid in cont_ids or mid in ents:
                assign(mid, cid)
            else:
                warnings.append(_w("W_CONTAINER_DANGLING_MEMBER",
                                   "container %s lists unknown member %s" % (cid, mid),
                                   "containers.%s.members" % cid))
    for child, old, new in sorted(conflict):
        warnings.append(_w("W_CONTAINER_CONFLICT",
                           "%s is claimed by %s and %s; %s wins" % (child, old, new, old),
                           "containers"))

    # container definitions = explicit containers + entity-as-container
    defs = {}
    for cid in sorted(conts):
        defs[cid] = {
            "id": cid, "label": conts[cid]["label"], "source": conts[cid]["source"],
            "role": "explicit", "element_id": "cnt:%s" % cid,
            "hint": conts[cid]["hint"],
        }
    for eid in sorted(ents):
        kids = [c for c in sorted(parent) if parent[c] == eid and c in ents]
        if kids:
            defs[eid] = {
                "id": eid, "label": ents[eid]["label"], "source": ents[eid]["source"],
                "role": "entity", "element_id": "ent:%s" % eid, "hint": ents[eid]["hint"],
            }
    # only containers can be parents; drop parent links pointing at plain entities
    for child in sorted(parent):
        if parent[child] not in defs:
            parent.pop(child)
    # break cycles deterministically: remove the parent link of the largest id
    cycle_flag = False
    guard = 0
    while guard <= len(defs) + 2:
        guard += 1
        broken = None
        for cid in sorted(defs):
            seen = []
            cur = cid
            while cur is not None and cur in defs:
                if cur in seen:
                    idx = seen.index(cur)
                    cyc = sorted(seen[idx:])
                    broken = cyc[-1]
                    break
                seen.append(cur)
                cur = parent.get(cur)
            if broken:
                break
        if not broken:
            break
        cycle_flag = True
        old_parent = parent.get(broken)
        parent.pop(broken, None)
        warnings.append(_w("W_CONTAINER_CYCLE",
                           "container cycle broken at %s (was inside %s); check_layout reports it"
                           % (broken, old_parent), "containers"))
    # drop parents that are no longer containers / that would create a cycle
    for child in sorted(list(parent)):
        seen = set()
        cur = parent.get(child)
        while cur is not None:
            if cur in seen or cur not in defs:
                parent.pop(child, None)
                break
            seen.add(cur)
            cur = parent.get(cur)
    return parent, defs, cycle_flag, warnings


# --------------------------------------------------------------------------
# compartments / membranes (sec 3.3)
# --------------------------------------------------------------------------
def _abundance_scales(ents, warnings):
    """``entities[].abundance`` -> node size factor (area proportional, sec 3.6).

    The size channel is only used when the model supplies abundance *with* a
    unit; mixed units are reported because they cannot share one scale.

    Proportionality is kept honest rather than clamped silently: the factor is exactly
    ``sqrt(value / reference)``, so a reader measuring areas recovers the real ratio.
    Any scale that a legibility bound would have to distort is reported instead
    (``W_ABUNDANCE_SIZE_CLAMPED``) and the caller discloses it in ``exceptions``.
    """
    vals = {}
    for eid in sorted(ents):
        ab = ents[eid].get("abundance")
        if ab and _as_float(ab.get("value"), 0.0) > 0:
            vals[eid] = float(ab["value"])
    if not vals:
        return {}
    units = sorted(set(str(ents[e].get("abundance", {}).get("unit") or "")
                       for e in vals))
    if len(units) > 1:
        warnings.append(_w("W_ABUNDANCE_UNIT_MIX",
                           "abundance values use several units (%s); node size compares them "
                           "on one scale" % ", ".join(units), "entities.abundance"))
    ordered = sorted(vals.values())
    ref = ordered[len(ordered) // 2]
    if ref <= 0:
        return {}
    out = {}
    for eid in sorted(vals):
        factor = math.sqrt(vals[eid] / ref)
        out[eid] = min(MAX_ABUNDANCE_SCALE, max(MIN_ABUNDANCE_SCALE, factor))
        if not (MIN_ABUNDANCE_SCALE <= factor <= MAX_ABUNDANCE_SCALE):
            warnings.append(_w(
                "W_ABUNDANCE_SIZE_CLAMPED",
                "abundance %g needs a node size factor %.3f outside the drawn range "
                "[%.2f, %.2f]; the drawn size is bounded for legibility, so areas must be read "
                "with this deviation in mind (the true factor is recomputable from "
                "entities[].abundance)" % (vals[eid], factor,
                                           MIN_ABUNDANCE_SCALE, MAX_ABUNDANCE_SCALE),
                "entities.%s.abundance" % eid))
    return out


def _compartment_order(conts, cid):
    sub = conts.get(cid, {}).get("compartment")
    return COMPARTMENT_ORDER.get(sub or "", 99)


def _compartments(ents, conts, parent, warnings):
    """Resolve compartment nesting, membrane interfaces and membrane entities.

    Geometry rules (all deterministic, all reported):

    * a ``membrane`` is an *interface band*: it spans the cross axis and is one
      rank deep, so a compartment declared *inside* it is drawn on its inner
      side instead (the declared parent is kept in ``declared_parent``);
    * ``extracellular``/``cell``/``cytosol`` are full-width bands,
      organelles are inset boxes inside their cytosol;
    * ``transmembrane`` must name a membrane container - a contradiction is left
      visible and reported, never silently redrawn;
    * ``membrane_anchored`` may be modelled in the adjacent cytosolic
      compartment; it is moved onto the membrane band and reported.
    """
    info = {
        "classes": {}, "subtypes": {}, "order": {}, "span": {}, "chain": [],
        "membranes": [], "interfaces": {}, "nesting_repairs": [],
        "container_mode": {}, "effective_container": {}, "declared_container": {},
        "placement_errors": [],
    }
    for cid in sorted(conts):
        c = conts[cid]
        info["classes"][cid] = c.get("kind")
        info["subtypes"][cid] = c.get("compartment")
        order = _compartment_order(conts, cid)
        info["order"][cid] = order
        info["span"][cid] = bool(c.get("kind") == "cell" or
                                 (c.get("compartment") in SPAN_COMPARTMENTS))
        if c.get("kind") == "membrane":
            info["membranes"].append(cid)

    declared = dict((k, v) for k, v in parent.items() if k in conts)
    cp = dict(declared)

    def assign(child, par, reason):
        if child == par:
            return
        cur = par
        guard = 0
        while cur is not None and guard <= len(conts) + 2:
            if cur == child:
                return
            cur = cp.get(cur)
            guard += 1
        old = cp.get(child)
        if old != par:
            info["nesting_repairs"].append({
                "container": child, "declared_parent": old, "parent": par,
                "reason": reason})
            warnings.append(_w("W_COMPARTMENT_NESTING",
                               "compartment %s declared inside %s cannot hold geometrically; "
                               "drawn inside %s (%s)" % (child, old, par, reason),
                               "containers.%s" % child))
        cp[child] = par

    # 1. a membrane is an interface band, not a parent box
    for mcid in info["membranes"]:
        m_parent = cp.get(mcid)
        for cid in sorted(conts):
            if cp.get(cid) != mcid:
                continue
            if conts[cid].get("kind") not in ("compartment", "membrane"):
                continue
            sub = conts[cid].get("compartment")
            if sub in ("cytosol", "cytoplasm") or sub in INSET_COMPARTMENTS:
                target = m_parent
                if sub in INSET_COMPARTMENTS:
                    inner = [c for c in sorted(conts)
                             if conts[c].get("compartment") in ("cytosol", "cytoplasm")
                             and c != cid and c != mcid
                             and not _is_descendant(c, mcid, cp)]
                    target = inner[0] if inner else m_parent
                assign(cid, target, "membrane band is an interface, not a container box")

    # 2. synthesise the extracellular > membrane > cytosol > organelle order when
    #    the model declares flat compartments with no nesting at all
    top = [cid for cid in sorted(conts)
           if info["classes"].get(cid) in ("compartment", "membrane", "cell")
           and cp.get(cid) is None]
    if "cell" not in [conts[c].get("kind") for c in top]:
        ordered = sorted(top, key=lambda c: (info["order"].get(c, 99), str(c)))
        inner = [c for c in ordered
                 if conts[c].get("compartment") in ("cytosol", "cytoplasm")]
        organelles = [c for c in ordered
                      if conts[c].get("compartment") in INSET_COMPARTMENTS]
        if len(ordered) > 1 and (inner or organelles):
            for cid in ordered:
                sub = conts[cid].get("compartment")
                if sub in ("cytosol", "cytoplasm"):
                    assign(cid, None, "full-width band next to the membrane")
                elif sub in INSET_COMPARTMENTS and inner:
                    assign(cid, inner[0], "organelle is an inset box inside the cytosol")

    # 3. cell container (explicit or not) is the box around the intracellular bands
    cells = [cid for cid in sorted(conts) if conts[cid].get("kind") == "cell"]
    cell = cells[0] if cells else None
    if cell is not None:
        for cid in sorted(conts):
            if cid == cell or conts[cid].get("kind") not in ("compartment", "membrane"):
                continue
            if conts[cid].get("compartment") == "extracellular":
                continue
            if cp.get(cid) is None:
                assign(cid, cell, "intracellular compartment belongs to the cell")
            elif cp.get(cid) == cell:
                pass

    for cid in sorted(cp):
        parent[cid] = cp[cid]

    # 4. membrane interfaces + membrane-role entity placement
    for mcid in info["membranes"]:
        m_order = info["order"].get(mcid, 1)
        outer = [c for c in sorted(conts)
                 if c != mcid and info["order"].get(c, 99) < m_order]
        inner = [c for c in sorted(conts)
                 if c != mcid and info["order"].get(c, 99) > m_order]
        info["interfaces"][mcid] = {
            "outer": outer[0] if outer else None,
            "inner": inner[0] if inner else None,
            "outward": "before",
        }
    for eid in sorted(ents):
        ent = ents[eid]
        role = ent.get("membrane_role")
        if role not in MEMBRANE_ROLES:
            continue
        cid = ent.get("container")
        info["declared_container"][eid] = cid
        if cid in info["membranes"]:
            info["container_mode"][eid] = "declared"
            info["effective_container"][eid] = cid
            continue
        membranes = info["membranes"]
        if not membranes:
            info["container_mode"][eid] = "invalid"
            info["effective_container"][eid] = cid
            info["placement_errors"].append({
                "code": "E_MEMBRANE_PLACEMENT",
                "where": "entities.%s.membrane_role" % eid,
                "message": ("entity %s has membrane_role=%s but the model declares no "
                            "container with kind=membrane to place it on" % (eid, role))})
            continue
        if role == "transmembrane":
            info["container_mode"][eid] = "invalid"
            info["effective_container"][eid] = cid
            info["placement_errors"].append({
                "code": "E_MEMBRANE_PLACEMENT",
                "where": "entities.%s.container" % eid,
                "message": ("transmembrane entity %s must sit on a kind=membrane container; "
                            "the model puts it in %r" % (eid, cid))})
            continue
        # membrane_anchored: the anchor is in the membrane even when the model
        # records the protein in the adjacent cytosolic compartment.
        pick = sorted(membranes, key=lambda m: (abs(info["order"].get(m, 1) -
                                                     (info["order"].get(cid, 2))), str(m)))[0]
        info["container_mode"][eid] = "forced"
        info["effective_container"][eid] = pick
        parent[eid] = pick
        warnings.append(_w("W_MEMBRANE_ANCHOR_COMPARTMENT",
                           "entity %s is membrane_anchored but modelled in %r; drawn on the "
                           "membrane band %r (declared container kept in the output)"
                           % (eid, cid, pick), "entities.%s.container" % eid))

    info["chain"] = [cid for cid in sorted(conts,
                                           key=lambda c: (info["order"].get(c, 99), str(c)))]
    return info


def _is_descendant(cid, ancestor, cp):
    cur = cp.get(cid)
    guard = 0
    while cur is not None and guard <= len(cp) + 2:
        if cur == ancestor:
            return True
        cur = cp.get(cur)
        guard += 1
    return False


# --------------------------------------------------------------------------
# geometry construction
# --------------------------------------------------------------------------
def _scaled_gaps(scale):
    """Spacing for one rung of the compaction ladder.

    The ladder scales *all* spacing, including the minimum node size, so a very
    dense model (dozens of nodes on one level) can still fit a finite canvas
    instead of being reported as an overflow.
    """
    g = dict(BASE_GAPS)
    s = float(scale)
    g["col_gap"] = max(1.8, BASE_GAPS["col_gap"] * s)
    g["row_gap"] = max(1.2, BASE_GAPS["row_gap"] * s)
    g["band_gap"] = max(1.2, BASE_GAPS["band_gap"] * s)
    g["cont_pad"] = max(1.2, BASE_GAPS["cont_pad"] * s)
    g["cont_label_h"] = max(3.2, BASE_GAPS["cont_label_h"] * s)
    g["node_pad_x"] = max(1.0, BASE_GAPS["node_pad_x"] * s)
    g["node_pad_y"] = max(0.8, BASE_GAPS["node_pad_y"] * s)
    g["min_node_w"] = max(8.0, BASE_GAPS["min_node_w"] * s)
    g["min_node_h"] = max(4.8, BASE_GAPS["min_node_h"] * s)
    g["min_col_w"] = max(4.0, BASE_GAPS["min_col_w"] * s)
    g["legend_row_h"] = max(3.4, BASE_GAPS["legend_row_h"] * s)
    g["legend_pad"] = max(1.4, BASE_GAPS["legend_pad"] * s)
    g["caption_row_h"] = max(3.4, BASE_GAPS["caption_row_h"] * s)
    return g


def _legend_key(text):
    """Normalised key used to match legend values/labels against entity labels."""
    s = " ".join(str(text if text is not None else "").split()).strip().lower()
    for sep in (u"\uff08", "(", " [", u"\u3010"):
        if sep in s:
            s = s.split(sep, 1)[0].strip()
    return s


def _legend_keys(text):
    """All plausible match keys for a legend value/label (whole + decorated head)."""
    keys = []
    for cand in (str(text if text is not None else ""), _legend_key(text)):
        k = _legend_key(cand)
        if k and k not in keys:
            keys.append(k)
    return keys


def _legend_colour_maps(legends, style, warnings):
    """value/label -> colour for category-ish legend entries and line styles.

    ``category``/``marker``/``value_scale`` entries map entity labels to colours;
    ``line_style`` entries whose value names a relation type map that relation to
    its colour.  This is what keeps the legend and the drawn marks consistent.
    """
    entity_colors = {}
    line_colors = {}
    conflicts = []
    for it in legends or []:
        color = _valid_color(it.get("color"))
        if not color:
            continue
        kind = str(it.get("kind") or "")
        keys = []
        for raw in (it.get("value"), it.get("label")):
            keys.extend(_legend_keys(raw))
        if kind == "line_style":
            value = _legend_key(it.get("value"))
            if value:
                line_colors.setdefault(value, color)
            continue
        for key in keys:
            if not key:
                continue
            old = entity_colors.get(key)
            if old is not None and old != color:
                conflicts.append((key, old, color))
                continue
            entity_colors.setdefault(key, color)
    for key, old, new in sorted(set(conflicts)):
        warnings.append(_w("W_LEGEND_COLOR_CONFLICT",
                           "legend maps %r to both %s and %s; %s wins" % (key, old, new, old),
                           "legend"))
    return entity_colors, line_colors


def _entity_color(kind, style, used_colors=None):
    """Kind-based palette colour, skipping colours the legend already claims.

    Without this, a category legend could share a colour with an unrelated
    entity kind, which makes the legend impossible to map onto the figure.
    """
    palette = style["palette"]
    kinds = sorted(set(ENTITY_KINDS))
    idx = kinds.index(kind) if kind in kinds else (len(kinds) % max(1, len(palette)))
    used = set(c.upper() for c in (used_colors or ()))
    chosen = None
    for step in range(len(palette)):
        cand = palette[(idx + step) % len(palette)]
        if cand.upper() not in used:
            chosen = cand
            break
    if chosen is None:
        chosen = palette[idx % len(palette)]
    return chosen, _mix_with_white(chosen, 0.86)


def _kind_color_map(style, used_colors=None):
    """Distinct palette colour per entity kind, avoiding colours the legend claims.

    When the palette is too small to give every kind a free colour, the palette
    entry is lightened by a deterministic amount instead of re-using a colour the
    legend already maps to something else.  That keeps every kind visually
    distinct and - more importantly - keeps a single colour from carrying two
    meanings, which would make the legend impossible to map back onto the figure.
    """
    palette = style["palette"]
    kinds = sorted(set(ENTITY_KINDS))
    taken = set(c.upper() for c in (used_colors or ()))
    out = {}
    shade_steps = (0.45, 0.62, 0.78, 0.30, 0.90)
    for idx, kind in enumerate(kinds):
        chosen = None
        for step in range(len(palette)):
            cand = palette[(idx + step) % len(palette)]
            if cand.upper() not in taken:
                chosen = cand
                break
        if chosen is None:
            base = palette[idx % len(palette)]
            for keep in shade_steps:
                cand = _mix_with_white(base, keep)
                if cand.upper() not in taken:
                    chosen = cand
                    break
        if chosen is None:
            chosen = palette[idx % len(palette)]
        out[kind] = chosen
        taken.add(chosen.upper())
    return out


def _resolve_node_color(eid, ent, style, legend_colors, legend_line_colors,
                        used_colors=None, kind_colors=None):
    """Node colour: legend mapping > explicit attribute > neutral / by-kind.

    The legend is the colour authority: an entity the model does not colour is
    drawn neutral by default, so every colour on the figure is accounted for by
    a legend entry (a kind palette is opt-in via ``figure.style.color_by_kind``
    and still skips colours the legend already claims).
    """
    for key in _legend_keys(ent.get("label")) + _legend_keys(eid):
        if key and key in legend_colors:
            color = legend_colors[key]
            return color, _mix_with_white(color, 0.86), "legend:" + key
    attrs = ent.get("attributes") if isinstance(ent.get("attributes"), dict) else {}
    explicit = _valid_color(attrs.get("color")) or _valid_color(attrs.get("fill"))
    if explicit:
        return explicit, _mix_with_white(explicit, 0.86), "attribute"
    if not style.get("color_by_kind", False):
        return NEUTRAL_NODE_STROKE, NEUTRAL_NODE_FILL, "neutral"
    kind = ent.get("kind")
    if kind_colors and kind in kind_colors:
        color = kind_colors[kind]
    else:
        color = _entity_color(kind, style, used_colors)[0]
    return color, _mix_with_white(color, 0.86), "kind"


def _relation_color(rtype, style, legend_line_colors=None):
    if legend_line_colors:
        mapped = legend_line_colors.get(str(rtype).lower())
        if mapped:
            return mapped
    palette = style["palette"]
    if rtype in CONTAINMENT_TYPES:
        # a containment link is structural chrome, not a directional signal:
        # neutral grey keeps it from stealing the activation/inhibition palette
        return "#8C97A3"
    idx = TYPE_COLOR_INDEX.get(rtype, 2)
    return palette[idx % len(palette)]


def _size_node(label, font_pt, max_w, gaps, swap=False):
    """Node box for a label; ``swap`` sizes it for a transposed (top_down) run.

    Without ``swap`` the box is ``w x h`` for a horizontal label.  With ``swap``
    the returned pair is already in *logical* coordinates, where the logical
    width is the extent along the flow axis and the logical height is the extent
    across it, so the label still wraps against its real drawn width.
    """
    pad_x = gaps["node_pad_x"]
    pad_y = gaps["node_pad_y"]
    inner = max(1.0, max_w - 2.0 * pad_x)
    lines = wrap_label(label, inner, font_pt)
    text_w = max([est_text_width_mm(ln, font_pt) for ln in lines] or [0.0])
    w = min(max_w, max(text_w + 2.0 * pad_x, min(gaps["min_node_w"], max_w)))
    line_h = font_pt * MM_PER_PT * LINE_FACTOR
    h = max(gaps["min_node_h"], len(lines) * line_h + 2.0 * pad_y)
    if swap:
        return lines, h, w, text_w, line_h
    return lines, w, h, text_w, line_h


def _text_block(text, font_pt, max_w):
    lines = wrap_label(text, max(1.0, max_w), font_pt)
    width = max([est_text_width_mm(ln, font_pt) for ln in lines] or [0.0])
    line_h = font_pt * MM_PER_PT * LINE_FACTOR
    return lines, width, line_h


def _nice_ticks(vmin, vmax, target=5):
    if vmax < vmin:
        vmin, vmax = vmax, vmin
    if not math.isfinite(vmin) or not math.isfinite(vmax):
        vmin, vmax = 0.0, 1.0
    if vmax - vmin < 1e-9:
        pad = max(abs(vmax) * 0.1, 1.0)
        vmin, vmax = vmin - pad, vmax + pad
    raw = (vmax - vmin) / max(1, int(target))
    mag = 10.0 ** math.floor(math.log10(raw)) if raw > 0 else 1.0
    norm = raw / mag
    if norm <= 1.0:
        step = 1.0 * mag
    elif norm <= 2.0:
        step = 2.0 * mag
    elif norm <= 5.0:
        step = 5.0 * mag
    else:
        step = 10.0 * mag
    start = math.floor(vmin / step) * step
    end = math.ceil(vmax / step) * step
    ticks = []
    v = start
    guard = 0
    while v <= end + step * 0.5 and guard < 64:
        ticks.append(round(v, 10))
        v = start + step * (len(ticks))
        guard += 1
    if not ticks:
        ticks = [vmin, vmax]
    return ticks, start, end


# --------------------------------------------------------------------------
# edge routing
# --------------------------------------------------------------------------
def _route_edge(edge, anchors, ctx):
    """Orthogonal route through free channels -> list of (x, y) points in mm."""
    a = anchors.get(edge["from"])
    b = anchors.get(edge["to"])
    if not a or not b:
        return []
    gx_after = ctx["gap_after"]
    ncols = ctx["n_columns"]
    content = ctx["content"]
    if b["column"] > a["column"]:
        span = b["column"] - a["column"]
        if span == 1:
            gx = gx_after[a["column"]]
            return [(a["right"], a["cy"]), (gx, a["cy"]), (gx, b["cy"]), (b["left"], b["cy"])]
        gx1 = gx_after[a["column"]]
        gx2 = ctx["gap_before"][b["column"]]
        mid = (a["cy"] + b["cy"]) / 2.0
        lane = _nearest_lane(mid, ctx)
        return [(a["right"], a["cy"]), (gx1, a["cy"]), (gx1, lane),
                (gx2, lane), (gx2, b["cy"]), (b["left"], b["cy"])]
    if b["column"] == a["column"]:
        if a["band"] == b["band"] and abs(a["order"] - b["order"]) == 1:
            if b["cy"] > a["cy"]:
                my = (a["bottom"] + b["top"]) / 2.0
                return [(a["cx"], a["bottom"]), (a["cx"], my), (b["cx"], my), (b["cx"], b["top"])]
            my = (b["bottom"] + a["top"]) / 2.0
            return [(a["cx"], a["top"]), (a["cx"], my), (b["cx"], my), (b["cx"], b["bottom"])]
        gx = gx_after[a["column"]] if a["column"] < ncols - 1 else ctx["gap_before"][a["column"]]
        side_right = a["column"] < ncols - 1
        xs = a["right"] if side_right else a["left"]
        xt = b["right"] if side_right else b["left"]
        return [(xs, a["cy"]), (gx, a["cy"]), (gx, b["cy"]), (xt, b["cy"])]
    # backwards in column order: route around through a free internal lane,
    # falling back to the outer top/bottom lane when no band gap is available
    mid = (a["cy"] + b["cy"]) / 2.0
    content_mid = content["y0"] + _num_or(content.get("h"), 0.0) / 2.0
    internal = [y for y in ctx.get("lanes", [])
                if content["y0"] + 1.0 <= y <= content["y0"] + _num_or(content.get("h"), 0.0) - 1.0]
    if internal:
        lane = _nearest_lane(mid, {"lanes": internal})
    else:
        lane = ctx["top_lane"] if mid < content_mid else ctx["bottom_lane"]
    gx1 = gx_after[a["column"]]
    gx2 = gx_after[b["column"]]
    return [(a["right"], a["cy"]), (gx1, a["cy"]), (gx1, lane),
            (gx2, lane), (gx2, b["cy"]), (b["right"], b["cy"])]


def _nearest_lane(value, ctx):
    lanes = ctx["lanes"]
    if not lanes:
        return value
    best = min(lanes, key=lambda y: (abs(y - value), y))
    return best


def _dedupe_points(points):
    """Drop consecutive duplicate points (zero-length segments) from a route."""
    out = []
    for p in points:
        x, y = float(p[0]), float(p[1])
        if out and abs(out[-1][0] - x) < 1e-9 and abs(out[-1][1] - y) < 1e-9:
            continue
        out.append((x, y))
    return out


PARALLEL_EDGE_OFFSET_MM = 1.2


def _offset_parallel_edges(edges):
    """Separate relations that share the same node pair by a small parallel offset.

    Two relations between the same two nodes (e.g. "activates" and "binds")
    would otherwise be drawn exactly on top of each other and one of them would
    be invisible.  Each edge of the group is shifted perpendicular to its first
    segment by ``(index - (n-1)/2) * 1.2 mm`` in sorted-id order, so the result
    is deterministic and the heads land on the node borders.
    """
    groups = {}
    for e in edges:
        key = tuple(sorted((str(e["from"]), str(e["to"]))))
        groups.setdefault(key, []).append(e)
    for key in sorted(groups):
        group = sorted(groups[key], key=lambda e: str(e["id"]))
        if len(group) < 2:
            continue
        span = len(group) - 1
        for idx, e in enumerate(group):
            delta = (idx - span / 2.0) * PARALLEL_EDGE_OFFSET_MM
            pts = e.get("points_mm") or []
            if abs(delta) < 1e-9 or len(pts) < 2:
                continue
            dx = float(pts[1][0]) - float(pts[0][0])
            dy = float(pts[1][1]) - float(pts[0][1])
            ln = math.hypot(dx, dy)
            if ln <= 0:
                continue
            # perpendicular of the outgoing direction
            ux, uy = -dy / ln, dx / ln
            last = len(pts) - 1
            moved = []
            for i, p in enumerate(pts):
                if i in (0, last):
                    # keep the endpoints on the node border line, only offset
                    # along the border (perpendicular to the incoming segment)
                    ex = float(pts[-2][0]) - float(pts[-1][0]) if i == last else dx
                    ey = float(pts[-2][1]) - float(pts[-1][1]) if i == last else dy
                    el = math.hypot(ex, ey)
                    if el > 0:
                        moved.append([p[0] + (-ey / el) * delta, p[1] + (ex / el) * delta])
                    else:
                        moved.append([p[0], p[1]])
                else:
                    moved.append([p[0] + ux * delta, p[1] + uy * delta])
            e["points_mm"] = [[round(p[0], 4), round(p[1], 4)] for p in moved]


def _polyline_midpoint(points, prefer_below=False):
    if len(points) < 2:
        return None, "middle"
    total = 0.0
    segs = []
    for i in range(len(points) - 1):
        x1, y1 = points[i]
        x2, y2 = points[i + 1]
        ln = math.hypot(x2 - x1, y2 - y1)
        segs.append((ln, i))
        total += ln
    if total <= 0:
        return points[0], "middle"
    target = total / 2.0
    acc = 0.0
    for ln, i in segs:
        if acc + ln >= target or i == segs[-1][1]:
            x1, y1 = points[i]
            x2, y2 = points[i + 1]
            t = 0.0 if ln <= 0 else (target - acc) / ln
            mx = x1 + (x2 - x1) * t
            my = y1 + (y2 - y1) * t
            if abs(y2 - y1) <= abs(x2 - x1):        # horizontal segment
                off = BASE_GAPS["lane_pad"]
                return (mx, my + off if prefer_below else my - off), "middle"
            return (mx + BASE_GAPS["lane_pad"], my), "start"
        acc += ln
    return points[0], "middle"


def _seg_cross(p1, p2, p3, p4):
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    d1 = orient(p3, p4, p1)
    d2 = orient(p3, p4, p2)
    d3 = orient(p1, p2, p3)
    d4 = orient(p1, p2, p4)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def _count_crossings(edges):
    """Number of proper polyline intersections between different edges."""
    segs = []
    for e in edges:
        pts = e.get("points_mm") or []
        for i in range(len(pts) - 1):
            segs.append((e["id"], pts[i], pts[i + 1]))
    count = 0
    for i in range(len(segs)):
        for j in range(i + 1, len(segs)):
            ea, a1, a2 = segs[i]
            eb, b1, b2 = segs[j]
            if ea == eb:
                continue
            if _seg_cross(a1, a2, b1, b2):
                count += 1
    return count


# --------------------------------------------------------------------------
# the layout builder
# --------------------------------------------------------------------------
def _build(ctx):
    """Compute all geometry for ctx['gaps'] / ctx['canvas_h'] (mutates ctx)."""
    gaps = ctx["gaps"]
    ents = ctx["ents"]
    style = ctx["style"]
    W = ctx["canvas_w"]
    H = ctx["canvas_h"]
    margin = gaps["margin"]
    region = ctx["schematic_region"]
    content = dict(region)
    content_w = content["w"]

    # ---- 1. logical columns ------------------------------------------------
    nodes = {}
    cont_ids = set(ctx["cont_defs"])
    for eid in sorted(ents):
        if eid in cont_ids:
            continue
        e = ents[eid]
        resolved = (ctx.get("node_colors") or {}).get(eid)
        if resolved:
            color, fill, color_source = resolved
        else:
            color, fill = _entity_color(e["kind"], style)
            color_source = "kind"
        nodes[eid] = {
            "id": eid, "label": e["label"], "kind": e["kind"], "source": e["source"],
            "level": ctx["levels"].get(eid, 0), "column": ctx["levels"].get(eid, 0),
            "container": ctx["parent"].get(eid), "hint": e["hint"],
            "font_pt": style["font_sizes_pt"]["label"],
            "color": color, "fill": fill, "color_source": color_source, "order": 0,
        }
    ctx["nodes"] = nodes
    max_level = max([n["level"] for n in nodes.values()] or [0])
    if ctx["grid_columns"]:
        order = sorted(nodes, key=lambda i: (nodes[i]["container"] or "~", i))
        n = len(order)
        rows_cap = _row_capacity(ctx, nodes, gaps)
        aspect = content_w / max(10.0, content["h"])
        ncols = max(1, int(math.ceil(math.sqrt(max(1, n) * aspect))))
        ncols = max(ncols, int(math.ceil(n / float(rows_cap))))
        ncols = min(ncols, max(1, n))
        rows = max(1, int(math.ceil(n / float(ncols))))
        for pos, eid in enumerate(order):
            nodes[eid]["column"] = min(ncols - 1, pos // rows)
        n_columns = max(1, max(nodes[eid]["column"] for eid in nodes) + 1)
    else:
        # A level whose per-band stack would be taller than the drawing area is
        # split into several side-by-side physical columns (its "sub-columns"),
        # so a dense model stays inside the requested canvas instead of growing
        # a 250 mm tall page.  The split is global per level, which keeps every
        # band aligned on the same column grid.
        n_columns, ctx["level_cols"] = _assign_level_columns(ctx, nodes, gaps)
    ctx["n_columns"] = n_columns

    # ---- 2. node sizes and column widths ----------------------------------
    swap = bool(ctx.get("transposed"))
    if swap:
        # In a transposed run the drawn width of a node is its *logical* height
        # and the drawn height is its logical width, so the wrap budget is the
        # cross axis of the drawing area.
        cap = min(56.0, max(gaps["min_node_w"], content["h"] * 0.55))
    else:
        cap = min(56.0, max(gaps["min_node_w"], content_w * 0.55))
    size_scale = ctx.get("size_scale") or {}
    degrade = ctx.setdefault("degradations", {})
    font_scale = float(ctx.get("font_scale") or 1.0)

    def _fit(eid, budget):
        """Largest font from the degradation ladder whose label is readable."""
        n = nodes[eid]
        base_pt = n["base_font_pt"]
        chosen = None
        for factor in DEGRADE_LADDER:
            pt = max(MIN_LABEL_FONT_PT, base_pt * factor)
            lines, w, h, text_w, line_h = _size_node(n["label"], pt, budget, gaps, swap)
            s = size_scale.get(eid, 1.0)
            if s != 1.0:
                w = max(text_w + 2.0 * gaps["node_pad_x"], w * s)
                h = max(len(lines) * line_h + 2.0 * gaps["node_pad_y"], h * s)
            chosen = (lines, w, h, text_w, line_h, pt)
            if len(lines) <= MAX_LABEL_LINES or pt <= MIN_LABEL_FONT_PT + 1e-9:
                break
        lines, w, h, text_w, line_h, pt = chosen
        n["font_pt"] = pt
        if pt < base_pt - 1e-9 or len(lines) > MAX_LABEL_LINES:
            degrade[("W_LABEL_DEGRADED", eid)] = _w(
                "W_LABEL_DEGRADED",
                "label of %s wrapped to %d lines; font %.1f -> %.1f pt to stay inside its box"
                % (eid, len(lines), base_pt, pt), "nodes.%s" % eid)
        return (lines, w, h, text_w, line_h)

    nat = {}
    for eid in sorted(nodes):
        nodes[eid]["base_font_pt"] = nodes[eid]["font_pt"] * font_scale
        nat[eid] = _fit(eid, cap)
    col_w = [gaps["min_col_w"]] * n_columns
    for eid in sorted(nodes):
        c = nodes[eid]["column"]
        col_w[c] = max(col_w[c], nat[eid][1])
    total = sum(col_w) + gaps["col_gap"] * max(0, n_columns - 1)
    if total > content_w and n_columns > 0:
        slot = (content_w - gaps["col_gap"] * max(0, n_columns - 1)) / float(n_columns)
        avail = max(2.0, min(cap, slot))
        degrade[("W_DENSE_FIGURE", "columns")] = _w(
            "W_DENSE_FIGURE",
            "%d columns need %.1f mm but only %.1f mm are available; nodes are squeezed and "
            "labels re-wrapped (no element is dropped)" % (n_columns, total, content_w),
            "figure.canvas")
        for eid in sorted(nodes):
            nat[eid] = _fit(eid, avail)
        col_w = [min(gaps["min_col_w"], avail)] * n_columns
        for eid in sorted(nodes):
            c = nodes[eid]["column"]
            col_w[c] = max(col_w[c], nat[eid][1])
    for eid in sorted(nodes):
        lines, w, h, text_w, line_h = nat[eid]
        n = nodes[eid]
        n["lines"] = lines
        n["w_mm"] = w
        n["h_mm"] = h
        n["text_w_mm"] = text_w
        n["line_h_mm"] = line_h

    # ---- 3. column x positions --------------------------------------------
    need = sum(col_w) + gaps["col_gap"] * max(0, n_columns - 1)
    pad = gaps["cont_pad"] if ctx["cont_defs"] else 0.0
    inner_x0 = content["x0"] + pad
    inner_w = max(gaps["min_col_w"], content_w - 2.0 * pad)
    extra = inner_w - need
    gap = gaps["col_gap"]
    if n_columns > 1 and extra > 0:
        gap = min(gap + extra / float(n_columns - 1), gaps["col_gap"] * 2.5)
    col_x = []
    x = inner_x0
    for i in range(n_columns):
        extra = inner_w - (sum(col_w) + gap * max(0, n_columns - 1))
        col_x.append(x)
        x += col_w[i] + gap
    block_w = sum(col_w) + gap * max(0, n_columns - 1)
    if block_w < inner_w:
        shift = (inner_w - block_w) / 2.0
        col_x = [cx + shift for cx in col_x]
    for eid in sorted(nodes):
        n = nodes[eid]
        c = n["column"]
        n["x_mm"] = col_x[c] + (col_w[c] - n["w_mm"]) / 2.0
    ctx["col_w"] = col_w
    ctx["col_x"] = col_x
    ctx["col_gap_used"] = gap
    ctx["content_w_used"] = block_w + 2.0 * pad
    ctx["gap_after"] = []
    ctx["gap_before"] = []
    for i in range(n_columns):
        if i < n_columns - 1:
            g = (col_x[i] + col_w[i] + col_x[i + 1]) / 2.0
        else:
            g = min(content["x0"] + content_w + gaps["lane_pad"], W - margin / 2.0)
        ctx["gap_after"].append(g)
    for i in range(n_columns):
        if i > 0:
            ctx["gap_before"].append(ctx["gap_after"][i - 1])
        else:
            ctx["gap_before"].append(max(margin / 2.0, content["x0"] - gaps["lane_pad"]))

    # ---- 4. bands ----------------------------------------------------------
    bands = {}
    comp = ctx.get("comp_info") or {}
    root = {"id": None, "parent": None, "children": [], "own": {}, "label_lines": [],
            "label_font_pt": 0.0, "depth": 0, "kind": None, "compartment": None,
            "span": False}
    bands[None] = root
    for cid in sorted(ctx["cont_defs"]):
        d = ctx["cont_defs"][cid]
        bands[cid] = {"id": cid, "parent": ctx["parent"].get(cid), "children": [],
                      "own": {}, "label_lines": [], "label_font_pt": 0.0, "depth": 0,
                      "kind": d.get("kind"), "compartment": d.get("compartment"),
                      "span": bool((comp.get("span") or {}).get(cid)),
                      "def": d}
    for cid in sorted(bands, key=_skey):
        if cid is None:
            continue
        p = bands[cid]["parent"]
        if p not in bands or p == cid:
            p = None
        bands[cid]["parent"] = p
        bands[p]["children"].append(cid)
    for eid in sorted(nodes):
        p = nodes[eid]["container"]
        if p not in bands:
            p = None
        n = nodes[eid]
        bands[p]["own"].setdefault(n["column"], []).append(eid)
    for cid in bands:
        if cid is None:
            continue
        lab = bands[cid]["def"]["label"]
        font_pt = style["font_sizes_pt"]["legend"]
        bands[cid]["label_font_pt"] = font_pt
        if lab:
            maxw = max(6.0, content_w * 0.5)
            lines, tw, lh = _text_block(lab, font_pt, maxw)
            bands[cid]["label_lines"] = lines
            bands[cid]["label_w"] = tw
            bands[cid]["label_line_h"] = lh
        # depth
        d = 0
        cur = bands[cid]["parent"]
        while cur is not None and d < 64:
            d += 1
            cur = bands[cur]["parent"]
        bands[cid]["depth"] = d
    ctx["bands"] = bands

    # initial order (layout hint then id), then barycentre sweeps
    for eid in sorted(nodes):
        h = nodes[eid]["hint"].get("order")
        hv = _as_float(h)
        nodes[eid]["hint_order"] = int(hv) if hv is not None else 0
    for cid in bands:
        for col in sorted(bands[cid]["own"]):
            bands[cid]["own"][col].sort(
                key=lambda i: (nodes[i]["hint_order"], i))

    _compute_band_x(ctx)
    # container labels are wrapped to the *actual* band width, which is only
    # known once the columns are fixed (a wide label must not overflow its box)
    for cid in sorted(bands, key=_skey):
        if cid is None:
            continue
        b = bands[cid]
        lab = b["def"]["label"]
        font_pt = style["font_sizes_pt"]["legend"]
        b["label_font_pt"] = font_pt
        if lab:
            inner = max(4.0, (b["x_max"] - b["x_min"]) - 2.0 * gaps["cont_pad"])
            lines, tw, lh = _text_block(lab, font_pt, inner)
            b["label_lines"] = lines
            b["label_w"] = tw
            b["label_line_h"] = lh
        else:
            b["label_lines"] = []
            b["label_w"] = 0.0
            b["label_line_h"] = font_pt * MM_PER_PT * LINE_FACTOR
    ctx["neighbours"] = _neighbours(ctx)
    for iteration in range(4):
        _measure(ctx)
        _place(ctx)
        if iteration < 3:
            _reorder(ctx)

    # ---- 5. band rectangles ----------------------------------------------
    # The fitting ladder watches the *content* extent, which is only known before
    # the full-width compartments are stretched.
    ctx["content_cross_extent"] = bands[None]["height"]
    # A compartment band spans the region itself, so the (undrawn) root band has
    # to reach the region edge for that to stay a valid containment.
    if any(bands[c].get("span") for c in bands if c is not None):
        root_band = bands[None]
        root_band["y_top"] = region["y0"]
        root_band["height"] = region["h"]
        ctx["content_cross_extent"] = max(ctx["content_cross_extent"],
                                          _own_height(ctx, None))
    _finalize_band_boxes(ctx)
    ctx["content"] = content
    ctx["content"]["x0"] = content["x0"]
    return ctx


def _finalize_band_boxes(ctx):
    """Band rectangles, cross-axis expansion and transposed label re-wrap.

    A ``membrane``/``cell``/``extracellular``/``cytosol`` band is drawn as a
    band that spans the cross axis of its parent (a membrane is therefore a
    narrow, full-width strip).  The expansion is clamped against every
    non-related box that shares the same part of the flow axis, so a band can
    never swallow a foreign node or an unrelated band.
    """
    bands = ctx["bands"]
    nodes = ctx["nodes"]
    gaps = ctx["gaps"]
    style = ctx["style"]
    swap = bool(ctx.get("transposed"))
    pads = gaps["cont_pad"]
    parents = dict((cid, bands[cid]["parent"]) for cid in bands if cid is not None)

    def related(a, c):
        if a == c:
            return True
        return _is_descendant(a, c, parents) or _is_descendant(c, a, parents)

    def flow_overlap(x0, x1, y0, y1):
        return x0 < y1 - EPS and y0 < x1 - EPS

    for cid in sorted(bands, key=_skey):
        if cid is None:
            continue
        b = bands[cid]
        b["x_mm"] = b["x_min"]
        b["y_mm"] = b["y_top"]
        b["w_mm"] = max(4.0, b["x_max"] - b["x_min"])
        b["h_mm"] = b["height"]

    barriers = {}
    for cid in sorted([c for c in bands if c is not None],
                      key=lambda c: (bands[c]["depth"], str(c))):
        b = bands[cid]
        x0, y0 = b["x_mm"], b["y_mm"]
        x1, y1 = x0 + b["w_mm"], y0 + b["h_mm"]
        if b["parent"] is None:
            region = ctx["schematic_region"]
            lo, hi = region["y0"], region["y0"] + region["h"]
        else:
            p = bands[b["parent"]]
            lo = p["y_top"] + p.get("content_head", 0.0)
            hi = p["y_top"] + p["height"]
        up, down = lo, hi
        outside = False
        for oid in sorted(barriers):
            ox0, ox1, oy0, oy1 = barriers[oid]
            if related(cid, oid) or not flow_overlap(x0, x1, ox0, ox1):
                continue
            if oy1 <= y0 + EPS:
                up = max(up, oy1 + gaps["band_gap"])
            elif oy0 >= y1 - EPS:
                down = min(down, oy0 - gaps["band_gap"])
            else:
                outside = True
                break
        for eid in sorted(nodes):
            n = nodes[eid]
            if n["container"] == cid or (n["container"] is not None and
                                         related(n["container"], cid)):
                continue
            nx0, nx1 = n["x_mm"], n["x_mm"] + n["w_mm"]
            ny0, ny1 = n["y_mm"], n["y_mm"] + n["h_mm"]
            if not flow_overlap(x0, x1, nx0, nx1):
                continue
            if ny1 <= y0 + EPS:
                up = max(up, ny1 + gaps["row_gap"])
            elif ny0 >= y1 - EPS:
                down = min(down, ny0 - gaps["row_gap"])
            else:
                outside = True
                break
        target = y1 - y0
        if b.get("span"):
            target = max(target, hi - lo)
        label_need = 0.0
        if swap and b.get("label_lines"):
            label_need = (b.get("label_w") or 0.0) + 2.0 * pads
        if label_need:
            target = max(target, label_need)
        room = down - up
        if not outside and room + EPS >= target and target > y1 - y0 + EPS:
            extra = target - (y1 - y0)
            take_up = min(extra, max(0.0, y0 - up))
            extra -= take_up
            take_down = min(extra, max(0.0, down - y1))
            extra -= take_down
            if extra <= EPS:
                y0 -= take_up
                y1 += take_down
                b["y_mm"] = round(y0, 6)
                b["h_mm"] = round(max(4.0, y1 - y0), 6)
            else:
                b["h_mm"] = round(max(4.0, y1 - y0), 6)
        elif b.get("span"):
            degrade = ctx.setdefault("degradations", {})
            degrade[("W_COMPARTMENT_BAND_NARROW", cid)] = _w(
                "W_COMPARTMENT_BAND_NARROW",
                "container %s cannot span the full width of its parent without hitting a "
                "neighbour; it keeps %.1f mm" % (cid, target), "containers.%s" % cid)
        barriers[cid] = (x0, x1, b["y_mm"], b["y_mm"] + b["h_mm"])

    # transposed container labels are wrapped against the *real* box width, which
    # is the (now final) logical height of the band
    for cid in sorted(bands, key=_skey):
        if cid is None:
            continue
        b = bands[cid]
        lab = b["def"]["label"]
        line_h = b.get("label_line_h") or (style["font_sizes_pt"]["legend"] *
                                           MM_PER_PT * LINE_FACTOR)
        if swap and lab:
            inner = max(4.0, b["h_mm"] - 2.0 * pads)
            head = max(2.0, b.get("content_head", 0.0) - 0.2)
            base_pt = style["font_sizes_pt"]["legend"]
            lines, tw, lh, pt = None, 0.0, line_h, base_pt
            for factor in DEGRADE_LADDER:
                pt = max(MIN_LABEL_FONT_PT, base_pt * factor)
                cand_lines, cand_tw, cand_lh = _text_block(lab, pt, inner)
                lines, tw, lh = cand_lines, cand_tw, cand_lh
                if len(cand_lines) * cand_lh <= head + EPS and cand_tw <= inner + EPS:
                    break
                if pt <= MIN_LABEL_FONT_PT + 1e-9:
                    break
            if lines is not None:
                b["label_font_pt"] = pt
                b["label_lines"] = lines
                b["label_w"] = tw
                b["label_line_h"] = lh
                if tw > inner + EPS:
                    degrade = ctx.setdefault("degradations", {})
                    degrade[("W_COMPARTMENT_LABEL", cid)] = _w(
                        "W_COMPARTMENT_LABEL",
                        "container %s label %r does not fit %.1f mm even at %.1f pt"
                        % (cid, lab, inner, pt), "containers.%s" % cid)
        anchor_line_h = b.get("label_line_h") or line_h
        b["label_anchor"] = {
            "x_mm": b["x_mm"] + pads,
            "y_mm": b["y_mm"] + pads * 0.6 + anchor_line_h * 0.8,
        }
        levels_of = [nodes[i]["level"] for i in _band_desc_nodes(bands, cid) if i in nodes]
        b["level_span"] = [min(levels_of), max(levels_of)] if levels_of else [0, 0]


def _band_desc_nodes(bands, cid):
    out = []
    for eid in bands[cid]["own"]:
        out.extend(bands[cid]["own"][eid])
    for ch in bands[cid]["children"]:
        out.extend(_band_desc_nodes(bands, ch))
    return out


def _neighbours(ctx):
    nb = {}
    for r in ctx["relations"]:
        if r["type"] in CONTAINMENT_TYPES:
            continue
        a, b = r["from"], r["to"]
        if a in ctx["ents"] and b in ctx["ents"]:
            nb.setdefault(a, set()).add(b)
            nb.setdefault(b, set()).add(a)
    return dict((k, sorted(v)) for k, v in nb.items())


def _band_sort_order(ctx, cid):
    """Compartment order of a band (``99`` when the model declares none).

    Declared compartments keep the biological order
    ``extracellular < membrane < cytosol < organelle`` independently of the
    derived levels, so a band never drifts above its upstream neighbour.
    """
    if cid is None:
        return -2
    b = ctx["bands"].get(cid) or {}
    comp = b.get("compartment")
    if comp in COMPARTMENT_ORDER:
        return COMPARTMENT_ORDER[comp]
    return 99


def _blocks(ctx, cid):
    bands = ctx["bands"]
    b = bands[cid]
    items = []
    for ch in b["children"]:
        items.append((_band_min_level(ctx, ch), 0, str(ch), "child", ch))
    if b["own"]:
        items.append((min(b["own"]), 1, "own", "own", None))
    items.sort(key=lambda t: (_band_sort_order(ctx, cid if t[4] is None else t[4]),
                              t[0], t[1], t[2]))
    return items


def _band_min_level(ctx, cid):
    cached = ctx["bands"][cid].get("min_level")
    if cached is not None:
        return cached
    bands = ctx["bands"]
    vals = []
    for col in bands[cid]["own"]:
        vals.extend(ctx["nodes"][i]["level"] for i in bands[cid]["own"][col])
    for ch in bands[cid]["children"]:
        vals.append(_band_min_level(ctx, ch))
    val = min(vals) if vals else 0
    bands[cid]["min_level"] = val
    return val


def _own_height(ctx, cid):
    b = ctx["bands"][cid]
    heights = []
    for col in sorted(b["own"]):
        stack = 0.0
        for pos, eid in enumerate(b["own"][col]):
            if pos:
                stack += ctx["gaps"]["row_gap"]
            stack += ctx["nodes"][eid]["h_mm"]
        heights.append(stack)
    return max(heights) if heights else 0.0


def _compute_band_x(ctx):
    """Band x extents from the (already fixed) node columns, bottom-up.

    Guarantees that a nested band is strictly inside its parent: the parent
    subtracts one extra ``cont_pad`` from the minimum of its blocks.
    """
    nodes = ctx["nodes"]
    gaps = ctx["gaps"]
    region = ctx["schematic_region"]

    def recurse(cid):
        b = ctx["bands"][cid]
        lo = None
        hi = None
        for col in b["own"]:
            for eid in b["own"][col]:
                n = nodes[eid]
                lo = n["x_mm"] if lo is None else min(lo, n["x_mm"])
                hi = (n["x_mm"] + n["w_mm"]) if hi is None else max(hi, n["x_mm"] + n["w_mm"])
        for ch in b["children"]:
            clo, chi = recurse(ch)
            lo = clo if lo is None else min(lo, clo)
            hi = chi if hi is None else max(hi, chi)
        if cid is None:
            b["x_min"] = region["x0"]
            b["x_max"] = region["x0"] + region["w"]
            return b["x_min"], b["x_max"]
        if lo is None:
            lo, hi = region["x0"], region["x0"] + 4.0
        b["x_min"] = lo - gaps["cont_pad"]
        b["x_max"] = hi + gaps["cont_pad"]
        return b["x_min"], b["x_max"]

    for cid in _measure_order(ctx):
        recurse(cid)


def _own_x(ctx, cid):
    nodes = ctx["nodes"]
    b = ctx["bands"][cid]
    lo = None
    hi = None
    for col in b["own"]:
        for eid in b["own"][col]:
            n = nodes[eid]
            lo = n["x_mm"] if lo is None else min(lo, n["x_mm"])
            hi = (n["x_mm"] + n["w_mm"]) if hi is None else max(hi, n["x_mm"] + n["w_mm"])
    return lo, hi


def _measure(ctx):
    for cid in _measure_order(ctx):
        ctx["bands"][cid].pop("min_level", None)
    for cid in sorted(ctx["bands"], key=_skey):
        if cid is not None:
            ctx["bands"][cid].pop("min_level", None)
    for cid in _measure_order(ctx):
        _measure_band(ctx, cid)


def _measure_order(ctx):
    """Post-order (children before parents) over the band tree."""
    order = []
    stack = [(None, False)]
    while stack:
        cid, done = stack.pop()
        if done:
            order.append(cid)
            continue
        stack.append((cid, True))
        for ch in reversed(ctx["bands"][cid]["children"]):
            stack.append((ch, False))
    return order


def _pack(blocks, gap):
    """Deterministic 2-D shelf packing: the lowest y whose x-interval is free.

    Blocks with disjoint x intervals are allowed to share a y band, which is
    what puts two side-by-side compartments on the same visual row.
    """
    placed = []
    out = []
    for blk in blocks:
        cands = [0.0]
        for p in placed:
            cands.append(p["y"] + p["h"] + gap)
        chosen = None
        for y in sorted(set(round(c, 6) for c in cands)):
            ok = True
            for p in placed:
                if blk["x0"] < p["x1"] - EPS and p["x0"] < blk["x1"] - EPS:
                    if y < p["y"] + p["h"] - EPS and p["y"] < y + blk["h"] - EPS:
                        ok = False
                        break
            if ok:
                chosen = y
                break
        if chosen is None:
            chosen = max([p["y"] + p["h"] + gap for p in placed] or [0.0])
        placed.append({"y": chosen, "h": blk["h"], "x0": blk["x0"], "x1": blk["x1"]})
        out.append({"kind": blk["kind"], "key": blk["key"], "y": chosen})
    total = max([p["y"] + p["h"] for p in placed] or [0.0])
    return out, total


def _row_capacity(ctx, nodes, gaps):
    """How many node rows fit into the drawing area (conservative estimate)."""
    region_h = _num_or((ctx.get("schematic_region") or {}).get("h"), 60.0)
    h_est = 0.0
    for eid in sorted(nodes):
        pt = _num_or(nodes[eid].get("font_pt"), 7.0)
        h_est = max(h_est, pt * MM_PER_PT * LINE_FACTOR + 2.0 * gaps["node_pad_y"])
    h_est = max(h_est, gaps["min_node_h"]) * 1.6      # allow for wrapped lines
    rows = int((region_h - 4.0) / max(1.0, h_est + gaps["row_gap"]))
    return max(1, min(12, rows))


def _assign_level_columns(ctx, nodes, gaps):
    """Physical column index per node; a wide level may span several columns.

    Returns ``(n_columns, level_cols)`` where ``level_cols[level]`` is the
    ``(first_column, span)`` pair of that logical level.
    """
    levels = sorted(set(nodes[eid]["level"] for eid in nodes))
    if not levels:
        return 1, {}
    rows_cap = _row_capacity(ctx, nodes, gaps)
    counts = {}
    for eid in sorted(nodes):
        key = (nodes[eid]["container"], nodes[eid]["level"])
        counts[key] = counts.get(key, 0) + 1
    level_cols = {}
    acc = 0
    for lvl in levels:
        mx = 0
        for (parent, level) in counts:
            if level == lvl:
                mx = max(mx, counts[(parent, level)])
        span = max(1, int(math.ceil(mx / float(rows_cap))))
        level_cols[lvl] = (acc, span)
        acc += span
    for key in sorted(counts, key=lambda k: (_skey(k[0]), k[1])):
        lvl = key[1]
        first, span = level_cols[lvl]
        ids = sorted(eid for eid in nodes
                     if nodes[eid]["container"] == key[0] and nodes[eid]["level"] == lvl)
        for i, eid in enumerate(ids):
            sub = min(span - 1, i // rows_cap)
            nodes[eid]["column"] = first + sub
    for eid in sorted(nodes):                    # safety: never leave a hole
        nodes[eid]["column"] = int(nodes[eid]["column"])
    return max(1, acc), level_cols


def _measure_band(ctx, cid):
    gaps = ctx["gaps"]
    b = ctx["bands"][cid]
    head = 0.0
    if cid is not None:
        head = gaps["cont_pad"]
        if b["label_lines"]:
            head += b.get("label_line_h", gaps["cont_label_h"]) + 1.0
    blocks = []
    for _ml, _rank, _key, kind, key in _blocks(ctx, cid):
        if kind == "child":
            x0, x1, h = ctx["bands"][key]["x_min"], ctx["bands"][key]["x_max"], ctx["bands"][key]["height"]
        else:
            lo, hi = _own_x(ctx, cid)
            x0 = lo if lo is not None else 0.0
            x1 = hi if hi is not None else 0.0
            h = _own_height(ctx, cid)
        blocks.append({"kind": kind, "key": key, "x0": x0, "x1": x1, "h": h})
    placements, content_h = _pack(blocks, gaps["band_gap"])
    b["placements"] = placements
    tail = gaps["cont_pad"] if cid is not None else 0.0
    h = head + content_h + tail
    if cid is None:
        h = max(h, 1.0)
    else:
        h = max(h, gaps["cont_label_h"] + 2.0 * gaps["cont_pad"])
    b["content_head"] = head
    b["height"] = h
    return h


def _place(ctx):
    region = ctx["schematic_region"]
    root_h = ctx["bands"][None]["height"]
    spare = _num_or(region.get("h"), root_h) - root_h
    offset = max(0.0, spare / 2.0) if not ctx.get("top_align") else 0.0
    ctx["content_offset_y"] = offset
    _place_band(ctx, None, region["x0"], region["y0"] + offset)


def _place_band(ctx, cid, x_left, y_top):
    gaps = ctx["gaps"]
    b = ctx["bands"][cid]
    b["y_top"] = y_top
    content_top = y_top + b.get("content_head", 0.0)
    for pl in b.get("placements", []):
        y = content_top + pl["y"]
        if pl["kind"] == "child":
            _place_band(ctx, pl["key"], x_left, y)
        else:
            _place_own(ctx, cid, y)
    b["content_bottom"] = content_top + max(
        [pl["y"] + ctx["bands"][pl["key"]]["height"] if pl["kind"] == "child"
         else _own_height(ctx, cid) + pl["y"] for pl in b.get("placements", [])] or [0.0])


def _place_own(ctx, cid, y_top):
    gaps = ctx["gaps"]
    b = ctx["bands"][cid]
    for col in sorted(b["own"]):
        y = y_top
        for pos, eid in enumerate(b["own"][col]):
            n = ctx["nodes"][eid]
            n["y_mm"] = y
            n["order"] = pos
            n["band"] = cid
            y += n["h_mm"] + gaps["row_gap"]


def _reorder(ctx):
    """One barycentre sweep over every (band, level) stack.

    Uses the y centre of each node's graph neighbours from the previous
    placement pass; a node without neighbours keeps its current y as the key, so
    passes are stable and every tie is broken by the layout hint and then by id.
    """
    nodes = ctx["nodes"]
    for cid in sorted(ctx["bands"], key=lambda c: (ctx["bands"][c]["depth"], str(c))):
        b = ctx["bands"][cid]
        for col in sorted(b["own"]):
            eids = list(b["own"][col])

            def key(eid):
                n = nodes[eid]
                vals = []
                for other in ctx["neighbours"].get(eid, []):
                    po = nodes.get(other)
                    if po is not None and "y_mm" in po:
                        vals.append(po["y_mm"] + po["h_mm"] / 2.0)
                bary = (sum(vals) / len(vals)) if vals else (n.get("y_mm", 0.0) or 0.0)
                return (bary, n.get("hint_order", 0), eid)

            b["own"][col].sort(key=key)


def _required_content_height(ctx):
    return ctx["bands"][None]["height"]


def _flow_extent(ctx):
    """Cross-axis extent of the content (the axis the fitting ladder watches).

    ``_build`` always works with ``level = logical x``; the cross axis is the
    logical y, which becomes the drawn height for ``left_right`` and the drawn
    width for ``top_down``.
    """
    val = _as_float(ctx.get("content_cross_extent"))
    if val:
        return val
    return ctx["bands"][None]["height"]


def _flow_available(region, transposed):
    """Room the cross axis has inside ``region`` (a *real* region)."""
    if transposed:
        return _num_or(region.get("w"), 0.0)
    return _num_or(region.get("h"), 0.0)


def _logical_region(region, transposed):
    """Map a real drawing region onto the engine's logical frame."""
    if not transposed:
        return region
    return {"x0": region["y0"], "y0": region["x0"],
            "w": region["h"], "h": region["w"]}


def _transpose_rect(box, lreg, rreg):
    """Logical box -> real box (x/y and w/h swapped)."""
    lx = _num_or(box.get("x_mm"), 0.0)
    ly = _num_or(box.get("y_mm"), 0.0)
    lw = _num_or(box.get("w_mm"), 0.0)
    lh = _num_or(box.get("h_mm"), 0.0)
    return (rreg["x0"] + (ly - lreg["y0"]), rreg["y0"] + (lx - lreg["x0"]), lh, lw)


def _transpose_pt(point, lreg, rreg):
    """Logical point -> real point."""
    return (rreg["x0"] + (float(point[1]) - lreg["y0"]),
            rreg["y0"] + (float(point[0]) - lreg["x0"]))


DIR_SWAP = {"up": "left", "down": "right", "left": "up", "right": "down"}


def _outward_dir(before_side, orientation):
    """Real-space direction of the side that faces the outer compartment."""
    first, second = OUTWARD_DIRS[orientation]
    return first if before_side else second


# --------------------------------------------------------------------------
# legend / title / panels / annotations
# --------------------------------------------------------------------------
def _legend_entries(model, ents, relations, style, warnings):
    """Legend items: model legend[] first, then series-derived entries."""
    items = []
    seen = set()
    arr = model.get("legend")
    if arr is not None and not isinstance(arr, list):
        warnings.append(_w("W_LEGEND_TYPE", "legend is not a list", "legend"))
        arr = None
    for i, raw in enumerate(arr or []):
        if not isinstance(raw, dict):
            continue
        lid = str(raw.get("id") or "").strip() or "legend-%d" % i
        if lid in seen:
            warnings.append(_w("W_DUP_LEGEND", "duplicate legend id %s ignored" % lid,
                               "legend[%d]" % i))
            continue
        seen.add(lid)
        kind = str(raw.get("kind") or "category")
        if kind not in ("category", "marker", "line_style", "value_scale"):
            kind = "category"
        items.append({
            "id": lid, "label": str(raw.get("label") or lid), "kind": kind,
            "value": raw.get("value"), "color": _valid_color(raw.get("color")),
            "marker": str(raw.get("marker") or "") or None,
            "source": _src(raw.get("source")), "origin": "legend",
        })
    if not items:
        warnings.append(_w("W_EMPTY_LEGEND", "model.legend is empty", "legend"))
    return items


def _series(model, warnings):
    """Normalised chart series (explicit series[] or derived from rows/columns)."""
    data = model.get("data") if isinstance(model.get("data"), dict) else None
    if not data:
        return [], None, {}
    units = data.get("units") if isinstance(data.get("units"), dict) else {}
    units = dict((str(k), str(v)) for k, v in sorted(units.items()))
    out = []
    arr = data.get("series")
    if isinstance(arr, list) and arr:
        seen = set()
        for i, raw in enumerate(arr):
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or "series-%d" % i)
            if name in seen:
                continue
            seen.add(name)
            xs = raw.get("x") if isinstance(raw.get("x"), list) else []
            ys = raw.get("y") if isinstance(raw.get("y"), list) else []
            pairs = []
            for j in range(min(len(xs), len(ys))):
                yv = _as_float(ys[j])
                if yv is None:
                    continue
                pairs.append((xs[j], yv))
            if not pairs:
                continue
            out.append({"name": name, "pairs": pairs,
                        "unit": str(raw.get("unit") or ""),
                        "color": _valid_color(raw.get("color")),
                        "src": _src(raw.get("source")),
                        "column": (str(raw.get("column") or raw.get("x_column") or "")
                                   or None),
                        "locator": "table:%s" % name})
        return out, data, units
    # ---- derive from rows -------------------------------------------------
    rows = data.get("rows")
    columns = data.get("columns")
    if not isinstance(rows, list) or not rows or not isinstance(columns, list) or not columns:
        return [], data, units
    cols = [str(c) for c in columns]
    norm = []
    for row in rows:
        if isinstance(row, list):
            norm.append([("" if v is None else str(v)) for v in row])
    if not norm:
        return [], data, units
    ncol = min(len(cols), max(len(r) for r in norm))
    numeric = []
    for ci in range(ncol):
        vals = [r[ci] if ci < len(r) else "" for r in norm]
        conv = [_as_float(v) for v in vals]
        if all(v is not None for v in conv) and all(v != "" for v in vals):
            numeric.append(ci)
    if not numeric:
        warnings.append(_w("W_CHART_NO_NUMERIC",
                           "data.rows has no fully numeric column; chart skipped", "data"))
        return [], data, units
    y_col = numeric[-1]
    others = [ci for ci in range(ncol) if ci not in numeric]
    series_col = None
    x_col = None
    if len(others) >= 2:
        uniq = [(len(set(r[ci] for r in norm)), ci) for ci in others]
        uniq.sort(key=lambda t: (t[0], -t[1]))
        series_col = uniq[0][1]
        x_col = max((c for c in others if c != series_col),
                    key=lambda c: (len(set(r[c] for r in norm)), -c))
    elif others:
        x_col = others[0]
    if x_col is None:
        x_col = others[0] if others else 0
    groups = []
    if series_col is None:
        groups.append((cols[y_col], 0, norm))
    else:
        seen = []
        for r in norm:
            v = r[series_col] if series_col < len(r) else ""
            if v not in seen:
                seen.append(v)
        for v in seen:
            groups.append((v, 0, [r for r in norm if r[series_col] == v]))
    for name, _z, rs in groups:
        pairs = []
        for r in rs:
            yv = _as_float(r[y_col]) if y_col < len(r) else None
            if yv is None:
                continue
            pairs.append((r[x_col] if x_col < len(r) else "", yv))
        if pairs:
            out.append({"name": name, "pairs": pairs,
                        "unit": units.get(cols[y_col], ""),
                        "color": None,
                        "src": {"path": str(data.get("path") or ""),
                                "locator": "table:%s" % cols[y_col],
                                "quote": "", "kind": "derived"},
                        "column": cols[y_col],
                        "locator": "table:%s" % cols[y_col]})
    warnings.append(_w("W_CHART_SERIES_DERIVED",
                       "data.series missing; series derived from data.rows by "
                       "y=%s, group=%s, x=%s" % (cols[y_col],
                                                 cols[series_col] if series_col is not None else "-",
                                                 cols[x_col]), "data"))
    return out, data, units


def _link_series_to_model(series, legends, ents):
    """Bind each chart series to its legend item and entity (by name).

    Chart figures draw series marks, not entity boxes, so without this link a
    reviewer cannot tell which `lg:*` swatch corresponds to which drawn colour.
    The ids end up as ``data-legend`` / ``data-entity`` on ``<g id="series:N">``.
    """
    legend_keys = []
    for it in legends or []:
        keys = set()
        for raw in (it.get("value"), it.get("label")):
            keys.update(_legend_keys(raw))
        legend_keys.append((it.get("id"), keys))
    entity_keys = []
    for eid in sorted(ents or {}):
        keys = set(_legend_keys(ents[eid].get("label")))
        keys.update(_legend_keys(eid))
        entity_keys.append((eid, keys))
    for s in series or []:
        keys = set(_legend_keys(s.get("name")))
        if not keys:
            continue
        for lid, lkeys in legend_keys:
            if lid and keys & lkeys:
                s["legend_id"] = lid
                break
        for eid, ekeys in entity_keys:
            if keys & ekeys:
                s["entity_id"] = eid
                break


def _chart_plan(model, series, data, units, region, style, warnings):
    """Axes, ticks and per-series points inside `region` (mm)."""
    if not series or region is None:
        return None
    font_pt = style["font_sizes_pt"]["legend"]
    axis_font = style["font_sizes_pt"]["label"]
    y_label_w = 14.0
    x_label_h = 11.0
    top_pad = 4.0
    right_pad = 5.0
    plot = {
        "x": region["x0"] + y_label_w,
        "y": region["y0"] + top_pad,
    }
    plot["w"] = max(20.0, region["w"] - y_label_w - right_pad)
    plot["h"] = max(20.0, region["h"] - x_label_h - top_pad)
    # x domain
    xs = []
    numeric_x = True
    for s in series:
        for xv, _yv in s["pairs"]:
            v = _as_float(xv)
            if v is None:
                numeric_x = False
            xs.append(xv if v is None else v)
    categories = []
    if numeric_x:
        xvals = [v for v in xs if isinstance(v, (int, float))]
        xticks, xmin, xmax = _nice_ticks(min(xvals), max(xvals))
        xkind = "numeric"
    else:
        xkind = "category"
        for s in series:
            for xv, _yv in s["pairs"]:
                key = str(xv)
                if key not in categories:
                    categories.append(key)
        xticks, xmin, xmax = [], 0.0, max(1, len(categories) - 1)
    yvals = [yv for s in series for _xv, yv in s["pairs"]]
    # A bar encodes its value by length, so a truncated baseline misstates the
    # ratios between bars.  Bars therefore always include 0 in the value domain;
    # a non-zero baseline stays legitimate for point/line charts.
    bars_present = xkind == "category"
    lo, hi = min(yvals), max(yvals)
    if bars_present:
        lo, hi = min(0.0, lo), max(0.0, hi)
    yticks, ymin, ymax = _nice_ticks(lo, hi)
    if bars_present and ymin > 0:
        # _nice_ticks only ever widens the domain, but never let a bar chart go
        # out with a truncated baseline silently.
        warnings.append(_w("W_BAR_BASELINE_TRUNCATED",
                           "bar chart value axis starts at %s, not 0; bar lengths no "
                           "longer encode the ratios" % _tick_label(ymin), "chart.y"))

    def xpos(xv):
        if xkind == "numeric":
            v = _as_float(xv)
            if v is None:
                return None
            if xmax - xmin <= 0:
                return plot["x"] + plot["w"] / 2.0
            return plot["x"] + (v - xmin) / (xmax - xmin) * plot["w"]
        if str(xv) in categories:
            idx = categories.index(str(xv))
        else:
            return None
        if len(categories) <= 1:
            return plot["x"] + plot["w"] / 2.0
        return plot["x"] + (idx + 0.5) / len(categories) * plot["w"]

    def ypos(yv):
        if ymax - ymin <= 0:
            return plot["y"] + plot["h"] / 2.0
        return plot["y"] + plot["h"] - (yv - ymin) / (ymax - ymin) * plot["h"]

    out_series = []
    for idx, s in enumerate(series):
        color = s["color"] or style["palette"][idx % len(style["palette"])]
        points = []
        for xv, yv in s["pairs"]:
            px = xpos(xv)
            if px is None:
                continue
            points.append({"x_mm": px, "y_mm": ypos(yv), "x": xv, "y": yv})
        if not points:
            continue
        prov, prov_kind, prov_locator = _series_provenance(s, data)
        out_series.append({
            "name": s["name"], "color": color, "unit": s["unit"],
            "shape": "bar" if xkind == "category" else "line",
            "points": points, "src": s["src"], "locator": prov_locator,
            "prov": prov, "src_kind": prov_kind,
            "index": idx, "legend_id": s.get("legend_id"),
            "entity_id": s.get("entity_id"),
        })
    if not out_series:
        return None
    cols = data.get("columns") if isinstance(data.get("columns"), list) else []
    y_values = [yv for s in series for _xv, yv in s["pairs"]]
    x_values = [xv for s in series for xv, _yv in s["pairs"]]
    # y column: the unit mapping names it; otherwise match the drawn values against
    # the table itself, so the axis label and the provenance locator name a real
    # column even when the model forgot data.units.
    y_col = ""
    for key in units:
        y_col = key
        break
    if not y_col:
        y_col = _match_column(y_values, data, cols)
    if not y_col:
        for s in series:
            if s.get("column"):
                y_col = str(s["column"])
                break
    unit_str = out_series[0]["unit"] or (units.get(y_col, "") if y_col else "")
    x_title = ""
    if xkind == "category":
        x_title = _x_column_title(categories, data, cols)
    else:
        x_title = _match_column(x_values, data, cols, exclude=(y_col,))
    y_title = y_col + (" (%s)" % unit_str if unit_str else "") if y_col else unit_str
    x_ticks = []
    if xkind == "numeric":
        for t in xticks:
            px = xpos(t)
            if px is None:
                continue
            x_ticks.append({"pos_mm": px, "label": _tick_label(t), "value": t})
    else:
        if len(categories) <= 12:
            for i, c in enumerate(categories):
                x_ticks.append({"pos_mm": xpos(c), "label": c, "value": c})
        else:
            step = int(math.ceil(len(categories) / 12.0))
            for i, c in enumerate(categories):
                if i % step == 0:
                    x_ticks.append({"pos_mm": xpos(c), "label": c, "value": c})
    y_ticks = [{"pos_mm": ypos(t), "label": _tick_label(t), "value": t} for t in yticks]
    dp = str(data.get("path") or "")
    src_kind = "derived" if dp else "unsupported"
    axis_prov = ("%s#%s" % (dp, _table_locator(x_title or "x")) if dp
                 else "(none)#(none)")
    y_axis_prov = ("%s#%s" % (dp, _table_locator(y_col or "y")) if dp
                   else "(none)#(none)")
    cats_out = []
    bar = None
    if xkind == "category":
        cats_out = [{"value": c, "pos_mm": xpos(c)} for c in categories]
        if len(categories) >= 2:
            spacing = abs(cats_out[1]["pos_mm"] - cats_out[0]["pos_mm"])
        else:
            spacing = plot["w"] * 0.5
        nser = max(1, len(out_series))
        group_w = max(1.0, spacing * 0.76)
        bar = {"group_w_mm": group_w, "bar_w_mm": group_w / nser, "n_series": nser,
               "baseline": 0.0}
    return {
        "plot": plot,
        "x": {"kind": xkind, "title": x_title, "ticks": x_ticks,
              "font_pt": axis_font, "tick_font_pt": font_pt,
              "prov": axis_prov, "src_kind": src_kind},
        "y": {"kind": "numeric", "title": y_title, "ticks": y_ticks,
              "font_pt": axis_font, "tick_font_pt": font_pt,
              "min": ymin, "max": ymax, "includes_zero": bool(ymin <= 0 <= ymax),
              "prov": y_axis_prov, "src_kind": src_kind},
        "series": out_series,
        "categories": cats_out,
        "bar": bar,
        "unit": unit_str,
        "prov": ("%s#%s" % (dp, _table_locator(y_col or "value")) if dp
                 else "(none)#(none)"),
        "src_kind": src_kind,
    }


def _tick_label(value):
    v = float(value)
    if abs(v) < 1e-12:
        v = 0.0
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return ("%.4f" % v).rstrip("0").rstrip(".")


def _x_column_title(categories, data, cols):
    """Name of the data column the category labels come from (best value match)."""
    if not categories or not cols:
        return str(cols[0]) if cols else "category"
    rows = data.get("rows") if isinstance(data.get("rows"), list) else []
    best = None
    for ci, cname in enumerate(cols):
        values = set()
        for row in rows:
            if isinstance(row, list) and ci < len(row):
                values.add(str(row[ci]))
        if not values:
            continue
        hits = sum(1 for c in categories if str(c) in values)
        if best is None or hits > best[0]:
            best = (hits, str(cname))
    if best and best[0] > 0:
        return best[1]
    if not rows:
        return str(cols[0])
    # no column matches verbatim: keep the first column name, it is the index axis
    return str(cols[0])


def _match_column(values, data, cols, exclude=()):
    """Best-matching data column for a set of values (numeric or categorical)."""
    if not cols:
        return ""
    rows = data.get("rows") if isinstance(data.get("rows"), list) else []
    if not rows:
        return ""
    target = set()
    for v in values:
        f = _as_float(v)
        target.add(round(f, 6) if f is not None else str(v))
    exclude = set(str(e) for e in exclude)
    best = None
    for ci, cname in enumerate(cols):
        cname = str(cname)
        if cname in exclude:
            continue
        seen = set()
        for row in rows:
            if isinstance(row, list) and ci < len(row):
                f = _as_float(row[ci])
                seen.add(round(f, 6) if f is not None else str(row[ci]))
        if not seen:
            continue
        hits = len(target & seen)
        if hits and (best is None or hits > best[0]):
            best = (hits, cname)
    return best[1] if best else ""


def _layout_legend(ctx, entries, style, warnings):
    gaps = ctx["gaps"]
    region = ctx["schematic_region"] or ctx["chart_region"] or ctx["content_region"]
    content_w = region["w"]
    avail_w = max(20.0, content_w - 2.0 * gaps["legend_pad"])
    font_pt = style["font_sizes_pt"]["legend"]
    max_label_w = max(10.0, avail_w - gaps["legend_glyph_w"] - gaps["legend_gap"] - 1.0)
    prepared = []
    for it in entries:
        if it["kind"] == "value_scale" and it.get("value") not in (None, ""):
            text = "%s = %s" % (it["label"], it["value"])
        else:
            text = it["label"]
        lines, tw, lh = _text_block(text, font_pt, max_label_w)
        w_item = gaps["legend_glyph_w"] + gaps["legend_gap"] + tw
        prepared.append({"item": it, "lines": lines, "text_w_mm": tw,
                         "w_mm": w_item, "font_pt": font_pt, "line_h_mm": lh,
                         "h_mm": len(lines) * lh + 1.2})
    # greedy horizontal flow with wrapping; row height = tallest item in the row
    rows = []
    cur = []
    x = 0.0
    for p in prepared:
        need = p["w_mm"] + (gaps["legend_sep"] if cur else 0.0)
        if cur and x + need > avail_w:
            rows.append(cur)
            cur = [p]
            x = p["w_mm"]
        else:
            cur.append(p)
            x += need
    if cur:
        rows.append(cur)
    rows = [[p for p in row] for row in rows]
    box_w = min(avail_w + 2.0 * gaps["legend_pad"],
                max([sum(p["w_mm"] for p in row) + gaps["legend_sep"] * (len(row) - 1)
                     for row in rows] or [0.0]) + 2.0 * gaps["legend_pad"])
    box_h = sum(_legend_row_h(r, gaps) for r in rows) + 2.0 * gaps["legend_pad"]
    return {"rows": rows, "box_w_mm": box_w, "h_mm": box_h,
            "avail_w_mm": avail_w, "font_pt": font_pt}


def _legend_row_h(row, gaps):
    return max([max([p["h_mm"] for p in row] or [gaps["legend_row_h"]]), gaps["legend_row_h"]][0],
               gaps["legend_row_h"])


def _place_legend(ctx, legend_plan, style, y_top, x_left):
    gaps = ctx["gaps"]
    out = {"x_mm": x_left, "y_mm": y_top,
           "w_mm": legend_plan["box_w_mm"], "h_mm": legend_plan["h_mm"], "items": []}
    y = y_top + gaps["legend_pad"]
    for row in legend_plan["rows"]:
        row_h = _legend_row_h(row, gaps)
        x = x_left + gaps["legend_pad"]
        for p in row:
            cy = y + row_h / 2.0
            item = p["item"]
            out["items"].append({
                "id": item["id"], "label": item["label"], "kind": item["kind"],
                "value": item.get("value"), "color": item.get("color"),
                "marker": item.get("marker"), "source": item["source"],
                "x_mm": x, "y_mm": y + (row_h - p["h_mm"]) / 2.0,
                "glyph_cy_mm": cy, "glyph_w_mm": gaps["legend_glyph_w"],
                "text_x_mm": x + gaps["legend_glyph_w"] + gaps["legend_gap"],
                "text_w_mm": p["text_w_mm"], "lines": p["lines"],
                "font_pt": p["font_pt"], "w_mm": p["w_mm"],
                "origin": item.get("origin", "legend"),
            })
            x += p["w_mm"] + gaps["legend_sep"]
        y += row_h
    return out


def _title_block(fig, style):
    t = fig.get("title") if isinstance(fig.get("title"), dict) else None
    if not t or not str(t.get("text") or "").strip():
        return None
    font_pt = style["font_sizes_pt"]["title"]
    return {"text": str(t["text"]), "font_pt": font_pt, "source": _src(t.get("source"))}


def _panels_block(model, style):
    arr = model.get("panels")
    if not isinstance(arr, list) or not arr:
        return [], []
    letters = []
    captions = []
    font_pt = style["font_sizes_pt"]["panel"]
    cap_pt = style["font_sizes_pt"]["legend"]
    for i, raw in enumerate(arr):
        if not isinstance(raw, dict):
            continue
        pid = str(raw.get("id") or "").strip()
        if not pid:
            continue
        cap = raw.get("caption") if isinstance(raw.get("caption"), dict) else {}
        cap_text = str(cap.get("text") or "") if cap else ""
        letters.append({"id": pid, "letter": pid, "font_pt": font_pt,
                        "source": _src(cap.get("source")) if cap else _src(None)})
        if cap_text:
            captions.append({"id": "cap:%s" % pid, "panel": pid, "text": cap_text,
                             "font_pt": cap_pt,
                             "source": _src(cap.get("source"))})
    return letters, captions


# --------------------------------------------------------------------------
# emission: logical -> real geometry, edge ports, membrane geometry
# --------------------------------------------------------------------------
def _emit_transform(ctx, rreg):
    """Rotate the finished schematic geometry onto the real drawing region.

    The engine works with ``level = logical x``.  For a ``top_down`` figure the
    drawn flow goes down the page, so every schematic box and point is mapped
    ``real_x = f(logical_y)``, ``real_y = f(logical_x)``.  Page furniture
    (title, legend, captions, chart) is *not* transposed.  The record returned
    here is what ``layout.flow.transposed_regions`` reports.
    """
    if not ctx.get("transposed"):
        return None
    lreg = ctx["schematic_region"]
    nodes = ctx["nodes"]
    bands = ctx["bands"]
    for eid in sorted(nodes):
        n = nodes[eid]
        x, y, w, h = _transpose_rect(n, lreg, rreg)
        n["x_mm"], n["y_mm"], n["w_mm"], n["h_mm"] = x, y, w, h
    for cid in sorted(bands, key=_skey):
        if cid is None:
            continue
        b = bands[cid]
        x, y, w, h = _transpose_rect(b, lreg, rreg)
        b["x_mm"], b["y_mm"], b["w_mm"], b["h_mm"] = x, y, w, h
        if isinstance(b.get("label_anchor"), dict):
            ax, ay = _transpose_pt((b["label_anchor"]["x_mm"],
                                    b["label_anchor"]["y_mm"]), lreg, rreg)
            b["label_anchor"] = {"x_mm": ax, "y_mm": ay}
    return {"orientation": "top_down",
            "logical_region": {k: round(float(lreg[k]), 4) for k in ("x0", "y0", "w", "h")},
            "real_region": {k: round(float(rreg[k]), 4) for k in ("x0", "y0", "w", "h")},
            "swap_axes": True}


def _pt_in_rect(p, box, tol=0.0):
    return (box["x_mm"] - tol <= p[0] <= box["x_mm"] + box["w_mm"] + tol and
            box["y_mm"] - tol <= p[1] <= box["y_mm"] + box["h_mm"] + tol)


def _seg_rect_interval(p1, p2, box, tol=0.0):
    """Liang-Barsky: ``(t0, t1)`` of the part of the segment inside the box."""
    x0, y0 = box["x_mm"] - tol, box["y_mm"] - tol
    x1 = box["x_mm"] + box["w_mm"] + tol
    y1 = box["y_mm"] + box["h_mm"] + tol
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, p1[0] - x0), (dx, x1 - p1[0]),
                 (-dy, p1[1] - y0), (dy, y1 - p1[1])):
        if abs(p) < 1e-12:
            if q < 0:
                return None
            continue
        r = q / p
        if p < 0:
            if r > t1:
                return None
            if r > t0:
                t0 = r
        else:
            if r < t0:
                return None
            if r < t1:
                t1 = r
    if t0 > t1:
        return None
    return (t0, t1)


def _polyline_crosses(points, box, tol=0.0):
    """True when a polyline enters or leaves ``box`` (a real boundary crossing)."""
    if len(points) < 2:
        return False
    inside_start = _pt_in_rect(points[0], box, tol)
    inside_end = _pt_in_rect(points[-1], box, tol)
    if inside_start != inside_end:
        return True
    for i in range(len(points) - 1):
        iv = _seg_rect_interval(points[i], points[i + 1], box, tol)
        if iv and iv[0] > 1e-9 and iv[1] < 1.0 - 1e-9:
            return True                  # passes through and leaves again
    return False


def _port_side(p, q):
    """Which face of a node an endpoint sits on (reserved anchor port)."""
    dx = float(q[0]) - float(p[0])
    dy = float(q[1]) - float(p[1])
    if abs(dx) >= abs(dy):
        return "right" if dx >= 0 else "left"
    return "bottom" if dy >= 0 else "top"


def _edge_geometry(edges, nodes, bands, ctx):
    """Ports, container-boundary crossings and self-loop loops for every edge."""
    boxes = dict((cid, bands[cid]) for cid in bands if cid is not None)
    for e in edges:
        pts = [(float(p[0]), float(p[1])) for p in (e.get("points_mm") or [])]
        if len(pts) >= 2:
            e["anchor_start"] = {"x_mm": round(pts[0][0], 4), "y_mm": round(pts[0][1], 4),
                                 "side": _port_side(pts[0], pts[1])}
            e["anchor_end"] = {"x_mm": round(pts[-1][0], 4), "y_mm": round(pts[-1][1], 4),
                               "side": _port_side(pts[-1], pts[-2])}
        crossed = [cid for cid in sorted(boxes)
                   if _polyline_crosses(pts, boxes[cid])]
        e["crosses_computed"] = crossed
        a = (nodes.get(e["from"]) or {}).get("container")
        b = (nodes.get(e["to"]) or {}).get("container")
        if a != b:
            e["crosses_pair"] = [a, b]


def _membrane_fields(eid, ent, node_box, bands, conts, comp_info, flow):
    """Geometric evidence that a membrane entity sits on its membrane band."""
    out = {
        "membrane_role": ent.get("membrane_role"),
        "container_declared": comp_info["declared_container"].get(eid),
        "container_mode": comp_info["container_mode"].get(eid, "declared"),
    }
    mcid = node_box.get("container")
    band = bands.get(mcid) if mcid else None
    if band is None or not isinstance(band, dict):
        out["membrane_on_band"] = False
        return out
    out["membrane_container"] = mcid
    out["membrane_compartment"] = band.get("compartment")
    out["membrane_on_band"] = all((
        node_box["x_mm"] >= band["x_mm"] - EPS,
        node_box["y_mm"] >= band["y_mm"] - EPS,
        node_box["x_mm"] + node_box["w_mm"] <= band["x_mm"] + band["w_mm"] + EPS,
        node_box["y_mm"] + node_box["h_mm"] <= band["y_mm"] + band["h_mm"] + EPS,
    ))
    iface = (comp_info.get("interfaces") or {}).get(mcid) or {}
    outer = iface.get("outer")
    out["membrane_outer"] = outer
    out["membrane_inner"] = iface.get("inner")
    outward = _outward_dir(iface.get("outward", "before") == "before", flow["orientation"])
    out["membrane_outward"] = outward
    x, y = node_box["x_mm"], node_box["y_mm"]
    w, h = node_box["w_mm"], node_box["h_mm"]
    step = MEMBRANE_BAND_STEP_MM
    if outward == "up":
        edge, probe = (x + w / 2.0, y), (x + w / 2.0, y - step)
    elif outward == "down":
        edge, probe = (x + w / 2.0, y + h), (x + w / 2.0, y + h + step)
    elif outward == "left":
        edge, probe = (x, y + h / 2.0), (x - step, y + h / 2.0)
    else:
        edge, probe = (x + w, y + h / 2.0), (x + w + step, y + h / 2.0)
    out["membrane_domain_out_mm"] = [round(edge[0], 4), round(edge[1], 4)]
    out["membrane_probe_mm"] = [round(probe[0], 4), round(probe[1], 4)]
    oc = bands.get(outer) if outer else None
    if isinstance(oc, dict):
        out["membrane_outer_centre_mm"] = [round(oc["x_mm"] + oc["w_mm"] / 2.0, 4),
                                          round(oc["y_mm"] + oc["h_mm"] / 2.0, 4)]
    return out


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------
def _compartments_out(conts, comp_info, bands_out, flow):
    """Serialisable compartment report: declared compartment -> drawn band geometry.

    Consumed by reviewers (and by anyone re-checking membrane placement) rather than by
    the renderer, so it states both what was declared and what was actually drawn.
    """
    classes = comp_info.get("classes") or {}
    subtypes = comp_info.get("subtypes") or {}
    declared = comp_info.get("declared_container") or {}
    effective = comp_info.get("effective_container") or {}
    bands = {}
    for cid in sorted(bands_out, key=_skey):
        if cid is None:
            continue
        b = bands_out[cid]
        declared_def = conts.get(cid) if isinstance(conts, dict) else {}
        declared_def = declared_def if isinstance(declared_def, dict) else {}
        bands[str(cid)] = {
            "kind": classes.get(cid) or declared_def.get("kind"),
            "compartment": subtypes.get(cid) or declared_def.get("compartment"),
            "label": b.get("label"),
            "parent": b.get("parent"),
            "declared_parent": declared_def.get("parent"),
            "role": b.get("role"),
            "box_mm": [b.get("x_mm"), b.get("y_mm"), b.get("w_mm"), b.get("h_mm")],
            "members": list(b.get("members") or []),
        }
    return {
        "orientation": (flow or {}).get("orientation"),
        "count": len(bands),
        "bands": bands,
        "membrane_bands": sorted(k for k, v in bands.items() if v.get("kind") == "membrane"),
        "placement_errors": list(comp_info.get("placement_errors") or []),
        "declared_container": dict(declared),
        "effective_container": dict(effective),
    }


def layout(model):
    """Deterministic layered layout.  Never raises on malformed input."""
    warnings = []
    transform = None
    if not isinstance(model, dict):
        warnings.append(_w("W_MODEL_TYPE", "model is not an object; defaults used", "model"))
        model = {}
    fig = model.get("figure") if isinstance(model.get("figure"), dict) else {}
    if not fig:
        warnings.append(_w("W_NO_FIGURE", "model.figure missing; defaults used", "figure"))
    style = _style(fig, warnings)
    canvas = _canvas(fig, warnings)
    W = canvas["width_mm"]
    H = canvas["height_mm"]
    ents = _entities(model, warnings)
    relations = _relations(model, ents, warnings)
    conts = _containers(model, ents, warnings)
    flow = _flow_config(fig, warnings)
    levels, feedback = _assign_levels(ents, relations, warnings, flow, conts)
    parent, cont_defs, cont_cycle, warnings = _membership(
        ents, conts, relations, levels, warnings)
    comp_info = _compartments(ents, conts, parent, warnings)
    if cont_cycle:
        warnings.append(_w("W_CONTAINER_CYCLE_FLAG",
                           "container membership graph contained a cycle; "
                           "check_layout reports E_LEVEL_REGRESSION", "containers"))

    kind = str(fig.get("kind") or "relationship_schematic")
    series, data, units = _series(model, warnings)
    has_nodes = bool([e for e in ents if e not in cont_defs])
    has_chart = bool(series) or kind == "chart"
    if kind == "chart" and not series:
        warnings.append(_w("W_CHART_NO_DATA", "figure.kind=chart but no usable data series",
                           "data"))
    has_schematic = has_nodes and kind != "chart"
    if not has_nodes and not has_chart:
        warnings.append(_w("W_EMPTY_FIGURE", "no entities and no chart data", "model"))

    legends = _legend_entries(model, ents, relations, style, warnings)
    for i, s in enumerate(series):
        if not s.get("color"):
            s["color"] = style["palette"][i % len(style["palette"])]
    if series:
        numeric_x = all(_as_float(xv) is not None
                        for s in series for xv, _yv in s["pairs"])
        by_name = {}
        for it in legends:
            for key in (str(it.get("label") or ""), str(it.get("value") or "")):
                key = key.strip().lower()
                if key:
                    by_name.setdefault(key, it)
        for i, s in enumerate(series):
            key = str(s["name"]).strip().lower()
            known = by_name.get(key)
            if known is not None:
                # keep the model's legend entry, but make its colour follow the
                # data mapping so the legend and the drawn marks always agree
                if not known.get("color"):
                    known["color"] = s.get("color")
                continue
            item = {
                "id": "lg_series_%d_%s" % (i, _slug(s["name"])),
                "label": s["name"], "kind": "category", "value": s["name"],
                "color": s.get("color"),
                "marker": "line" if numeric_x else "square",
                "source": s.get("src") or _src(None), "origin": "series",
            }
            legends.append(item)
            by_name[key] = item
    letters, captions = _panels_block(model, style)
    title = _title_block(fig, style)

    margins = BASE_GAPS["margin"]
    title_band = 0.0
    title_lines = []
    if title:
        maxw = max(20.0, W - 2.0 * margins)
        title_lines, tw, tlh = _text_block(title["text"], title["font_pt"], maxw)
        title_band = len(title_lines) * tlh + BASE_GAPS["title_pad"]
    panel_band = BASE_GAPS["panel_band"] if letters else 0.0
    caption_band = 0.0
    caption_lines = []
    if captions:
        cap_pt = captions[0]["font_pt"]
        maxw = max(20.0, W - 2.0 * margins)
        for c in captions:
            lines, tw, tlh = _text_block("%s. %s" % (c["panel"], c["text"]), cap_pt, maxw)
            caption_lines.append({"entry": c, "lines": lines, "line_h_mm": tlh,
                                  "text_w_mm": tw})
        caption_band = sum(len(c["lines"]) * c["line_h_mm"] for c in caption_lines) + 1.6

    # legend sizing (depends on the content width only)
    ctx = {
        "ents": ents, "relations": relations, "levels": levels, "parent": parent,
        "cont_defs": cont_defs, "style": style, "canvas_w": W, "gaps": _scaled_gaps(1.0),
        "grid_columns": False, "chart_series": series,
    }
    # ---- legend <-> figure colour consistency -----------------------------
    # The legend is the colour authority: a category legend item that names an
    # entity label paints that entity, and a line_style item that names a
    # relation type paints that relation.  Entities/legend items that the model
    # left without a colour inherit one from the other, so the legend can always
    # be mapped onto the drawing (and vice versa).
    legend_colors, legend_line_colors = _legend_colour_maps(legends, style, warnings)
    ctx["legend_colors"] = legend_colors
    ctx["legend_line_colors"] = legend_line_colors
    used_colors = set(c.upper() for c in legend_colors.values())
    used_colors |= set(c.upper() for c in legend_line_colors.values())
    kind_colors = _kind_color_map(style, used_colors)
    node_colors = {}
    for eid in sorted(ents):
        node_colors[eid] = _resolve_node_color(eid, ents[eid], style, legend_colors,
                                               legend_line_colors, used_colors, kind_colors)
    for it in legends:
        if _valid_color(it.get("color")):
            continue
        for raw in (it.get("value"), it.get("label")):
            hit = None
            for key in _legend_keys(raw):
                for eid in sorted(node_colors):
                    if key and key in _legend_keys(ents[eid]["label"]):
                        hit = node_colors[eid][0]
                        break
                if hit:
                    break
            if hit:
                it["color"] = hit
                break
    ctx["node_colors"] = node_colors
    size_scale = _abundance_scales(ents, warnings)
    ctx["transposed"] = bool(flow.get("transposed"))
    ctx["comp_info"] = comp_info
    ctx["size_scale"] = size_scale
    directional = any(r["type"] in FLOW_TYPES and r["direction"] == "forward"
                      for r in relations)
    ctx["grid_columns"] = (not directional) and len(ctx["ents"]) - len(cont_defs) >= 4
    content_region = {"x0": margins, "y0": margins + title_band + panel_band,
                      "w": W - 2.0 * margins,
                      "h": max(20.0, H - 2.0 * margins - title_band - panel_band -
                               caption_band - 12.0)}
    ctx["content_region"] = content_region
    ctx["schematic_region"] = content_region
    ctx["chart_region"] = None
    legend_plan = _layout_legend(ctx, legends, style, warnings)
    legend_total = legend_plan["h_mm"] + 2.6

    def _regions(h_total, grow=0.0):
        """Schematic / chart regions for a canvas of height ``h_total`` (mm)."""
        y0 = margins + title_band + panel_band
        ch = max(20.0, h_total - 2.0 * margins - title_band - panel_band -
                 caption_band - legend_total)
        if has_schematic and has_chart:
            chart_h = max(30.0, min(48.0, ch * 0.38))
            sch_h = max(20.0, ch - chart_h - 4.0) + max(0.0, grow)
            sch = {"x0": margins, "y0": y0, "w": W - 2.0 * margins, "h": sch_h}
            chart = {"x0": margins, "y0": y0 + sch_h + 4.0, "w": W - 2.0 * margins,
                     "h": chart_h}
            return sch, chart
        content = {"x0": margins, "y0": y0, "w": W - 2.0 * margins, "h": ch}
        if has_chart:
            return None, content
        return content, None

    schematic_region, chart_region = _regions(H)
    if kind == "chart" and has_nodes:
        warnings.append(_w("W_CHART_IGNORES_SCHEMATIC",
                           "figure.kind=chart: entity boxes are not drawn; the axes and "
                           "series carry the data", "figure.kind"))
    ctx["schematic_region"] = schematic_region
    ctx["chart_region"] = chart_region

    nodes_out = {}
    edges_out = []
    bands_out = {}
    stats = {
        "levels": 1, "max_per_level": 0, "edge_crossings_est": 0,
        "nodes": 0, "containers": 0, "edges": 0, "legend_items": 0,
        "columns": 1, "overlap_warnings": 0, "canvas_overflow": False,
        "canvas_adjusted": None, "compaction_scale": 1.0,
        "container_cycle": bool(cont_cycle),
    }

    if schematic_region is not None:
        transposed = bool(ctx.get("transposed"))

        def _build_at(real_h, sch_real, real_w=None):
            """Build in logical coordinates for a *real* page of this size."""
            w_used = W if real_w is None else real_w
            ctx["schematic_region"] = _logical_region(sch_real, transposed)
            ctx["canvas_w"] = real_h if transposed else w_used
            ctx["canvas_h"] = w_used if transposed else real_h
            _build(ctx)

        chosen = None
        best = None
        for scale in COMPACTION_SCALES:
            ctx["gaps"] = _scaled_gaps(scale)
            _build_at(H, schematic_region)
            required = _flow_extent(ctx)
            avail = _flow_available(schematic_region, transposed)
            best = (scale, required)
            if required <= avail + EPS:
                chosen = scale
                break
        if chosen is None:
            scale, required = best
            avail = _flow_available(schematic_region, transposed)
            need = required - avail
            if transposed:
                # the cross axis of a top_down figure is the page *width*
                new_w = min(W * MAX_CANVAS_GROWTH, W + max(0.0, need) + 1.0)
                grow = new_w - W
                try:
                    sch2, chart2 = _regions(H, w_total=new_w)
                except TypeError:
                    sch2, chart2 = schematic_region, chart_region
                ctx["gaps"] = _scaled_gaps(scale)
                _build_at(H, sch2, new_w)
                required2 = _flow_extent(ctx)
                if grow > EPS and required2 <= _flow_available(sch2, transposed) + EPS:
                    W = new_w
                    schematic_region = sch2
                    chart_region = chart2
                    stats["canvas_adjusted"] = {
                        "requested_width_mm": canvas["width_mm"],
                        "used_width_mm": round(W, 3),
                        "reason": "content did not fit after compaction; width grown",
                    }
                    warnings.append(_w("W_CANVAS_GROWN",
                                       "canvas width grown %.1f -> %.1f mm to fit content"
                                       % (canvas["width_mm"], W), "figure.canvas"))
                else:
                    stats["canvas_overflow"] = True
                    warnings.append(_w("W_CANVAS_OVERFLOW",
                                       "content does not fit the canvas; E_OUT_OF_CANVAS",
                                       "figure.canvas"))
                    ctx["gaps"] = _scaled_gaps(scale)
                    _build_at(H, schematic_region)
            else:
                new_h = min(H * MAX_CANVAS_GROWTH, H + max(0.0, need) + 1.0)
                grow = new_h - H
                sch2, chart2 = _regions(new_h, grow=grow)
                ctx["gaps"] = _scaled_gaps(scale)
                _build_at(new_h, sch2)
                required2 = _flow_extent(ctx)
                if grow > EPS and required2 <= _flow_available(sch2, transposed) + EPS:
                    H = new_h
                    schematic_region = sch2
                    chart_region = chart2
                    stats["canvas_adjusted"] = {
                        "requested_height_mm": canvas["height_mm"],
                        "used_height_mm": round(H, 3),
                        "reason": "content did not fit after compaction; height grown",
                    }
                    warnings.append(_w("W_CANVAS_GROWN",
                                       "canvas height grown %.1f -> %.1f mm to fit content"
                                       % (canvas["height_mm"], H), "figure.canvas"))
                else:
                    stats["canvas_overflow"] = True
                    warnings.append(_w("W_CANVAS_OVERFLOW",
                                       "content does not fit the canvas; E_OUT_OF_CANVAS",
                                       "figure.canvas"))
                    ctx["gaps"] = _scaled_gaps(scale)
                    _build_at(H, schematic_region)
            chosen = scale
        ctx["gaps"] = _scaled_gaps(chosen)
        _build_at(H, schematic_region)
        stats["compaction_scale"] = chosen

        nodes = ctx["nodes"]
        bands = ctx["bands"]
        content = ctx["schematic_region"]
        lreg = content
        rreg = schematic_region
        root = bands[None]
        stats["columns"] = ctx["n_columns"]
        stats["levels"] = max(1, max([n["level"] for n in nodes.values()] or [0]) + 1)
        per = {}
        for eid in sorted(nodes):
            per[nodes[eid]["level"]] = per.get(nodes[eid]["level"], 0) + 1
        stats["max_per_level"] = max(per.values()) if per else 0
        stats["nodes"] = len(nodes)
        # root band y range and the free horizontal lanes used by routing
        root_y0 = root.get("y_top", content["y0"])
        root_y1 = root_y0 + root["height"]
        head = root.get("content_head", 0.0)
        lanes = []
        for pl in root.get("placements", []):
            if pl["kind"] == "child":
                hb = bands[pl["key"]]["height"]
            else:
                hb = _own_height(ctx, None)
            lanes.append(root_y0 + head + pl["y"] - ctx["gaps"]["band_gap"] / 2.0)
            lanes.append(root_y0 + head + pl["y"] + hb + ctx["gaps"]["band_gap"] / 2.0)
        ctx["top_lane"] = max(margins / 2.0, root_y0 - BASE_GAPS["lane_pad"])
        ctx["bottom_lane"] = min(H - margins / 2.0, root_y1 + BASE_GAPS["lane_pad"])
        lanes.append(ctx["top_lane"])
        lanes.append(ctx["bottom_lane"])
        ctx["lanes"] = sorted(set(round(v, 6) for v in lanes))

        # anchors
        anchors = {}
        for eid in sorted(nodes):
            n = nodes[eid]
            anchors[eid] = {
                "id": eid, "x": n["x_mm"], "y": n["y_mm"], "w": n["w_mm"], "h": n["h_mm"],
                "cx": n["x_mm"] + n["w_mm"] / 2.0, "cy": n["y_mm"] + n["h_mm"] / 2.0,
                "left": n["x_mm"], "right": n["x_mm"] + n["w_mm"],
                "top": n["y_mm"], "bottom": n["y_mm"] + n["h_mm"],
                "column": n["column"], "level": n["level"], "band": n["band"],
                "order": n["order"],
            }
        for cid in sorted(bands, key=_skey):
            if cid is None or cid in anchors:
                continue
            b = bands[cid]
            anchors[cid] = {
                "id": cid, "x": b["x_mm"], "y": b["y_mm"], "w": b["w_mm"], "h": b["h_mm"],
                "cx": b["x_mm"] + b["w_mm"] / 2.0,
                "cy": b["y_mm"] + min(b["h_mm"], ctx["gaps"]["cont_label_h"]) / 2.0,
                "left": b["x_mm"], "right": b["x_mm"] + b["w_mm"],
                "top": b["y_mm"], "bottom": b["y_mm"] + b["h_mm"],
                "column": min(ctx["n_columns"] - 1, max(0, levels.get(cid, 0))),
                "level": levels.get(cid, 0), "band": bands[cid]["parent"],
                "order": 0,
            }

        # edges
        for r in relations:
            if r["from"] not in ents and r["from"] not in bands:
                continue
            head = r["arrow"] if r["arrow"] in ("normal", "tee", "none") else ""
            head = head or HEAD_FOR_TYPE.get(r["type"], "none")
            head = {"normal": "arrow"}.get(head, head)
            if head not in ("arrow", "tee", "none"):
                head = "none"
            if r["direction"] == "none":
                head = {"normal": "arrow", "tee": "tee"}.get(r["arrow"], "none")
            head_start = head if r["direction"] == "bidirectional" else "none"
            color = r["color"] or _relation_color(r["type"], style,
                                                  ctx.get("legend_line_colors"))
            points = _route_edge(r, anchors, ctx)
            if not points:
                warnings.append(_w("W_EDGE_UNROUTED",
                                   "relation %s could not be routed" % r["id"],
                                   "relations.%s" % r["id"]))
                continue
            label = r["label"]
            points = _dedupe_points(points)
            is_containment_link = r["type"] in CONTAINMENT_TYPES
            ev = r.get("evidence") or {}
            width_pt = EVIDENCE_WIDTH_PT.get(ev.get("strength"),
                                             style["line_widths_pt"]["edge"])
            edge = {
                "id": r["id"], "from": r["from"], "to": r["to"], "type": r["type"],
                "direction": r["direction"],
                "stroke": "dashed" if (is_containment_link or
                                       r["stroke"] in ("dashed", "dotted")) else "solid",
                "stroke_raw": r["stroke"],
                "arrow_contract": ARROW_FOR_TYPE.get(r["type"], "none"),
                "head_start": head_start, "head_end": head,
                "color": color,
                "width_pt": width_pt,
                "evidence": ev or None,
                "loop": r["from"] == r["to"],
                "crosses_declared": list(r.get("crosses") or []),
                "points_mm": [[round(x, 4), round(y, 4)] for x, y in points],
                "label": label, "label_lines": [], "label_pos_mm": None,
                "label_w_mm": 0.0, "label_h_mm": 0.0,
                "label_anchor": "middle", "font_pt": style["font_sizes_pt"]["label"],
                "feedback": (r["from"], r["to"]) in feedback,
                "source": r["source"], "prov": _prov_of(r["source"])[0],
                "src_kind": _prov_of(r["source"])[1],
                "provenance_kind": _prov_of(r["source"])[1],
            }
            edges_out.append(edge)
        edges_out.sort(key=lambda e: e["id"])
        _offset_parallel_edges(edges_out)
        content = ctx.get("schematic_region") or {}
        c_y0 = _num_or(content.get("y0"), 0.0)
        c_y1 = c_y0 + _num_or(content.get("h"), 0.0)
        for e in edges_out:
            if e["label"]:
                e["label_lines"] = wrap_label(e["label"], MAX_EDGE_LABEL_MM, e["font_pt"])
                pts = [tuple(p) for p in e["points_mm"]]
                probe, _anchor = _polyline_midpoint(pts)
                prefer_below = bool(probe) and probe[1] < c_y0 + (c_y1 - c_y0) * 0.5
                pos, anchor = _polyline_midpoint(pts, prefer_below=prefer_below)
                if pos:
                    e["label_pos_mm"] = [round(pos[0], 4), round(pos[1], 4)]
                    e["label_anchor"] = anchor
                e["label_w_mm"] = round(max(
                    [est_text_width_mm(ln, e["font_pt"]) for ln in e["label_lines"]] or [0.0]), 4)
                e["label_h_mm"] = round(
                    len(e["label_lines"]) * e["font_pt"] * MM_PER_PT * 1.3, 4)
        for e in edges_out:
            if e["type"] in CONTAINMENT_TYPES and e["from"] in bands:
                e["container_link"] = True

        # ---- logical -> real geometry (top_down transposition) -------------
        transform = _emit_transform(ctx, schematic_region)
        if transform:
            lreg = ctx["schematic_region"]
            rreg = schematic_region
            for e in edges_out:
                e["points_mm"] = [[round(v, 4) for v in
                                   _transpose_pt(p, lreg, rreg)] for p in e["points_mm"]]
                if e["label_pos_mm"]:
                    e["label_pos_mm"] = [round(v, 4) for v in
                                         _transpose_pt(e["label_pos_mm"], lreg, rreg)]

        # ---- edge endpoints, container crossings, self loops --------------
        _edge_geometry(edges_out, nodes, bands, ctx)

        nodes_out = {}
        for eid in sorted(nodes):
            n = nodes[eid]
            nodes_out[eid] = {
                "x_mm": round(n["x_mm"], 4), "y_mm": round(n["y_mm"], 4),
                "w_mm": round(n["w_mm"], 4), "h_mm": round(n["h_mm"], 4),
                "level": n["level"], "column": n["column"], "order": n["order"],
                "band": n["band"], "lines": n["lines"], "font_pt": n["font_pt"],
                "line_h_mm": round(n["line_h_mm"], 4), "label": n["label"],
                "kind": n["kind"], "fill": n["fill"], "stroke": n["color"],
                "color_source": n.get("color_source", "kind"),
                "source": n["source"], "container": n["container"],
                "prov": _prov_of(n["source"])[0], "src_kind": _prov_of(n["source"])[1],
            }
            ent = ents.get(eid) or {}
            if ent.get("membrane_role") in MEMBRANE_ROLES:
                # bands_out is still empty at this point (it is filled below); the real
                # band rectangles live in `bands`.
                nodes_out[eid].update(_membrane_fields(eid, ent, nodes_out[eid],
                                                       bands, conts,
                                                       comp_info, flow))
            if ent.get("abundance"):
                nodes_out[eid]["abundance"] = ent["abundance"]
                nodes_out[eid]["size_scale"] = round(size_scale.get(eid, 1.0), 4)
        for cid in sorted(bands, key=_skey):
            if cid is None:
                continue
            b = bands[cid]
            bands_out[cid] = {
                "x_mm": round(b["x_mm"], 4), "y_mm": round(b["y_mm"], 4),
                "w_mm": round(b["w_mm"], 4), "h_mm": round(b["h_mm"], 4),
                "label_anchor": {"x_mm": round(b["label_anchor"]["x_mm"], 4),
                                 "y_mm": round(b["label_anchor"]["y_mm"], 4)},
                "label": b["def"]["label"], "lines": b["label_lines"],
                "font_pt": b["label_font_pt"], "role": b["def"]["role"],
                "element_id": b["def"]["element_id"], "parent": b["parent"],
                "depth": b["depth"], "level_span": b["level_span"],
                "source": b["def"]["source"],
                "prov": _prov_of(b["def"]["source"])[0],
                "src_kind": _prov_of(b["def"]["source"])[1],
                "members": sorted(set(
                    eid for eid in _band_desc_nodes(bands, cid) if eid in nodes)),
                "children": sorted(b["children"]),
            }
        stats["containers"] = len(bands_out)
        stats["edges"] = len(edges_out)
        stats["edge_crossings_est"] = _count_crossings(edges_out)
        ctx["anchors"] = anchors

    # ---- legend placement, title, panels, chart ---------------------------
    legend_y = H - margins - caption_band - legend_plan["h_mm"] - 1.0
    legend_out = _place_legend(ctx, legend_plan, style, legend_y, margins)
    stats["legend_items"] = len(legend_out["items"])

    title_out = None
    if title:
        title_out = {"text": title["text"], "lines": title_lines,
                     "x_mm": W / 2.0, "y_mm": margins + title["font_pt"] * MM_PER_PT * 0.95,
                     "font_pt": title["font_pt"], "anchor": "middle",
                     "source": title["source"],
                     "prov": _prov_of(title["source"])[0],
                     "src_kind": _prov_of(title["source"])[1]}
    panels_out = {}
    panel_x = margins
    for p in letters:
        panels_out[p["id"]] = {
            "x_mm": panel_x, "y_mm": margins + title_band + p["font_pt"] * MM_PER_PT * 0.9,
            "font_pt": p["font_pt"], "letter": p["letter"], "source": p["source"],
            "prov": _prov_of(p["source"])[0], "src_kind": _prov_of(p["source"])[1],
        }
        panel_x += 9.0
    annotations_out = []
    ay = H - margins - caption_band + 1.0
    for c in caption_lines:
        annotations_out.append({
            "id": c["entry"]["id"], "panel": c["entry"]["panel"],
            "lines": c["lines"], "x_mm": margins, "y_mm": ay,
            "font_pt": c["entry"]["font_pt"], "anchor": "start",
            "source": c["entry"]["source"],
            "prov": _prov_of(c["entry"]["source"])[0],
            "src_kind": _prov_of(c["entry"]["source"])[1],
        })
        ay += len(c["lines"]) * c["line_h_mm"]

    chart_out = None
    if chart_region is not None:
        _link_series_to_model(series, legend_out.get("items"), ents)
        chart_out = _chart_plan(model, series, data or {}, units, chart_region, style, warnings)

    out = {
        "schema_version": SCHEMA_VERSION,
        "figure_id": str(fig.get("id") or ""),
        "figure_kind": kind,
        "canvas": {"width_mm": round(W, 4), "height_mm": round(H, 4),
                   "background": style["background"]},
        "nodes": nodes_out,
        "containers": bands_out,
        "edges": edges_out,
        "legend": legend_out,
        "panels": panels_out,
        "stats": stats,
        "style": {
            "font_stack": style["font_stack"],
            "font_sizes_pt": style["font_sizes_pt"],
            "line_widths_pt": style["line_widths_pt"],
            "palette": style["palette"],
            "background": style["background"],
            "color_space": style["color_space"],
        },
        "title": title_out,
        "annotations": annotations_out,
        "chart": chart_out,
        "flow": {
            "orientation": flow["orientation"],
            "requested_orientation": flow.get("requested_orientation"),
            "orientation_fallback": bool(flow.get("orientation_fallback")),
            "transposed": bool(flow["transposed"]),
            "ranks_source": "model" if flow["explicit_ranks"] else "derived",
            "ranks_declared": dict(flow["ranks"]),
            "ranks_used": dict((k, v) for k, v in sorted(levels.items())),
            "feedback_edges": sorted("%s->%s" % e for e in feedback),
            "transposed_regions": transform,
        },
        "compartments": _compartments_out(conts, comp_info, bands_out, flow),
        "metrics": {
            "unit_per_mm": UNIT_PER_MM,
            "mm_per_pt": MM_PER_PT,
            "base_dpi": 96.0,
            "node_pad_x_mm": ctx["gaps"]["node_pad_x"],
            "node_pad_y_mm": ctx["gaps"]["node_pad_y"],
            "legend_pad_mm": ctx["gaps"]["legend_pad"],
            "compaction_scale": stats["compaction_scale"],
            "margin_mm": margins,
            "line_factor": LINE_FACTOR,
            "latin_factor": LATIN_FACTOR,
            "cjk_factor": CJK_FACTOR,
            "level_cols": dict(
                (str(lvl), {"first_column": v[0], "span": v[1]})
                for lvl, v in sorted((ctx.get("level_cols") or {}).items())),
            "flow_scale": stats.get("fit", {}).get("scale", 1.0),
        },
        "warnings": warnings,
    }
    if schematic_region is not None and nodes_out:
        out["regions"] = {"schematic": schematic_region}
    else:
        out["regions"] = {}
    if chart_region is not None:
        out["regions"]["chart"] = chart_region
    return out


def _slug(text):
    import re
    s = re.sub(r"[^0-9A-Za-z]+", "-", str(text)).strip("-").lower()
    return s or "item"


# --------------------------------------------------------------------------
# check_layout
# --------------------------------------------------------------------------
def _rect_overlap(a, b, tol=0.0):
    ax2 = a["x_mm"] + a["w_mm"]
    ay2 = a["y_mm"] + a["h_mm"]
    bx2 = b["x_mm"] + b["w_mm"]
    by2 = b["y_mm"] + b["h_mm"]
    ox = min(ax2, bx2) - max(a["x_mm"], b["x_mm"])
    oy = min(ay2, by2) - max(a["y_mm"], b["y_mm"])
    if ox <= tol or oy <= tol:
        return 0.0
    return ox * oy


def _contains(outer, inner, tol=0.0):
    return (inner["x_mm"] >= outer["x_mm"] - tol and
            inner["y_mm"] >= outer["y_mm"] - tol and
            inner["x_mm"] + inner["w_mm"] <= outer["x_mm"] + outer["w_mm"] + tol and
            inner["y_mm"] + inner["h_mm"] <= outer["y_mm"] + outer["h_mm"] + tol)


def _ancestors_of(cid, containers, guard=64):
    out = []
    cur = containers.get(cid, {}).get("parent")
    n = 0
    while cur is not None and n < guard:
        out.append(cur)
        cur = containers.get(cur, {}).get("parent")
        n += 1
    return out


def check_layout(layout_obj, model, *, strict=True):
    """Independent verification of a layout against its model.

    Errors (frozen codes): ``E_NODE_OVERLAP``, ``E_OUT_OF_CANVAS``,
    ``E_TEXT_OVERFLOW_EST``, ``E_LEVEL_REGRESSION`` (containment contradictions:
    a member outside its container, a foreign node inside a container, a
    container cycle, or a container not inside its parent).

    ``strict=True`` uses a 0.5 % tolerance for estimated text overflow and also
    emits structural warnings (backward/feedback edges, missing routes,
    unreferenced containers).  ``strict=False`` relaxes the text tolerance to 5 %
    and keeps only warnings that do not depend on the estimate.
    """
    errors = []
    warnings = []
    stats = {"nodes": 0, "containers": 0, "edges": 0, "levels": 0,
             "max_per_level": 1, "edge_crossings_est": 0,
             "errors": 0, "warnings": 0}
    if not isinstance(layout_obj, dict):
        errors.append(_e("E_NODE_OVERLAP", "layout is not an object", "layout"))
        return _finish(errors, warnings, stats)

    tol = 0.005 if strict else 0.05
    canvas = layout_obj.get("canvas") if isinstance(layout_obj.get("canvas"), dict) else {}
    W = _as_float(canvas.get("width_mm"))
    H = _as_float(canvas.get("height_mm"))
    nodes = layout_obj.get("nodes") if isinstance(layout_obj.get("nodes"), dict) else {}
    containers = layout_obj.get("containers") if isinstance(layout_obj.get("containers"), dict) else {}
    edges = layout_obj.get("edges") if isinstance(layout_obj.get("edges"), list) else []
    legend = layout_obj.get("legend") if isinstance(layout_obj.get("legend"), dict) else {}
    metrics = layout_obj.get("metrics") if isinstance(layout_obj.get("metrics"), dict) else {}
    pad_x = _as_float(metrics.get("node_pad_x_mm"), BASE_GAPS["node_pad_x"])
    pad_y = _as_float(metrics.get("node_pad_y_mm"), BASE_GAPS["node_pad_y"])
    legend_pad = _as_float(metrics.get("legend_pad_mm"), BASE_GAPS["legend_pad"])

    if not W or not H or W <= 0 or H <= 0:
        errors.append(_e("E_OUT_OF_CANVAS", "layout.canvas has no positive size", "canvas"))
        W = W or 0.0
        H = H or 0.0

    # ---- geometry presence / basics ---------------------------------------
    boxes = []
    for nid in sorted(nodes):
        n = nodes[nid]
        if not isinstance(n, dict):
            warnings.append(_w("W_NODE_TYPE", "node %s is not an object" % nid, "nodes.%s" % nid))
            continue
        vals = [_as_float(n.get(k)) for k in ("x_mm", "y_mm", "w_mm", "h_mm")]
        if any(v is None for v in vals):
            errors.append(_e("E_OUT_OF_CANVAS",
                             "node %s has no numeric box" % nid, "nodes.%s" % nid))
            continue
        box = {"id": nid, "x_mm": vals[0], "y_mm": vals[1], "w_mm": vals[2], "h_mm": vals[3],
               "kind": "node", "level": n.get("level")}
        if box["w_mm"] <= 0 or box["h_mm"] <= 0:
            errors.append(_e("E_OUT_OF_CANVAS",
                             "node %s has a non-positive box" % nid, "nodes.%s" % nid))
            continue
        boxes.append(box)
        if (box["x_mm"] < -EPS or box["y_mm"] < -EPS or
                box["x_mm"] + box["w_mm"] > W + EPS or box["y_mm"] + box["h_mm"] > H + EPS):
            errors.append(_e("E_OUT_OF_CANVAS",
                             "node %s lies outside the canvas" % nid, "nodes.%s" % nid))
        # text fit (independent re-estimate from the model label)
        font_pt = _as_float(n.get("font_pt"))
        label = n.get("label")
        ent = ((model or {}).get("entities") or []) if isinstance(model, dict) else []
        for raw in (ent if isinstance(ent, list) else []):
            if isinstance(raw, dict) and str(raw.get("id")) == nid:
                if label in (None, ""):
                    label = raw.get("label")
                break
        if label not in (None, ""):
            if not font_pt:
                font_pt = DEFAULT_FONT_SIZES_PT["label"]
            inner = box["w_mm"] - 2.0 * pad_x
            # the wrap limit carries the estimate tolerance, otherwise a line
            # that fits exactly could re-wrap one character wider here
            lines = wrap_label(label, max(0.5, inner * (1.0 + tol)), font_pt)
            tw = max([est_text_width_mm(ln, font_pt) for ln in lines] or [0.0])
            if inner <= 0 or tw > inner * (1.0 + tol) + EPS:
                errors.append(_e("E_TEXT_OVERFLOW_EST",
                                 "node %s label wider than its box" % nid, "nodes.%s" % nid))
            line_h = font_pt * MM_PER_PT * LINE_FACTOR
            if len(lines) * line_h + 2.0 * pad_y > box["h_mm"] * (1.0 + tol) + EPS:
                errors.append(_e("E_TEXT_OVERFLOW_EST",
                                 "node %s label taller than its box" % nid, "nodes.%s" % nid))

    cboxes = []
    for cid in sorted(containers):
        c = containers[cid]
        if not isinstance(c, dict):
            continue
        vals = [_as_float(c.get(k)) for k in ("x_mm", "y_mm", "w_mm", "h_mm")]
        if any(v is None for v in vals):
            errors.append(_e("E_OUT_OF_CANVAS",
                             "container %s has no numeric box" % cid, "containers.%s" % cid))
            continue
        box = {"id": cid, "x_mm": vals[0], "y_mm": vals[1], "w_mm": vals[2], "h_mm": vals[3],
               "kind": "container", "parent": c.get("parent"), "role": c.get("role")}
        cboxes.append(box)
        if (box["x_mm"] < -EPS or box["y_mm"] < -EPS or
                box["x_mm"] + box["w_mm"] > W + EPS or box["y_mm"] + box["h_mm"] > H + EPS):
            errors.append(_e("E_OUT_OF_CANVAS",
                             "container %s lies outside the canvas" % cid,
                             "containers.%s" % cid))
        # label fits the container width (re-wrap it the way layout.py would)
        label = c.get("label")
        font_pt = _as_float(c.get("font_pt"), 7.0)
        if label:
            inner = max(1.0, box["w_mm"] - 2.0 * pad_x)
            lines = c.get("lines")
            if not isinstance(lines, list) or not lines:
                lines = wrap_label(label, inner * (1.0 + tol), font_pt)
            tw = max([est_text_width_mm(ln, font_pt) for ln in lines] or [0.0])
            if tw > inner * (1.0 + tol) + EPS:
                errors.append(_e("E_TEXT_OVERFLOW_EST",
                                 "container %s label wider than the box" % cid,
                                 "containers.%s" % cid))

    # ---- overlaps ---------------------------------------------------------
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            if _rect_overlap(boxes[i], boxes[j], EPS) > EPS:
                errors.append(_e("E_NODE_OVERLAP",
                                 "nodes %s and %s overlap" % (boxes[i]["id"], boxes[j]["id"]),
                                 "nodes.%s" % boxes[i]["id"]))
    for i in range(len(cboxes)):
        for j in range(i + 1, len(cboxes)):
            a, b = cboxes[i], cboxes[j]
            if a["id"] in _ancestors_of(b["id"], containers) or \
                    b["id"] in _ancestors_of(a["id"], containers):
                continue
            if _rect_overlap(a, b, EPS) > EPS:
                errors.append(_e("E_NODE_OVERLAP",
                                 "containers %s and %s overlap" % (a["id"], b["id"]),
                                 "containers.%s" % a["id"]))

    # ---- containment semantics (E_LEVEL_REGRESSION) -----------------------
    cmap = dict((c["id"], c) for c in cboxes)
    for box in boxes:
        nid = box["id"]
        n = nodes.get(nid, {})
        cid = n.get("container")
        if cid and cid in cmap:
            if not _contains(cmap[cid], box, EPS):
                errors.append(_e("E_LEVEL_REGRESSION",
                                 "node %s is not inside its container %s (level regression)"
                                 % (nid, cid), "nodes.%s" % nid))
        for other in cboxes:
            if other["id"] == cid:
                continue
            if other["id"] in _ancestors_of(cid, containers):
                continue
            if _contains(other, box, -EPS):
                errors.append(_e("E_LEVEL_REGRESSION",
                                 "node %s sits inside container %s without being a member"
                                 % (nid, other["id"]), "nodes.%s" % nid))
    for c in cboxes:
        pid = c.get("parent")
        if pid is not None and pid in cmap:
            if not _contains(cmap[pid], c, EPS):
                errors.append(_e("E_LEVEL_REGRESSION",
                                 "container %s is not inside its parent %s" % (c["id"], pid),
                                 "containers.%s" % c["id"]))
    # container cycles from the model
    if isinstance(model, dict):
        cyc = _model_container_cycle(model)
        if cyc:
            errors.append(_e("E_LEVEL_REGRESSION",
                             "container membership cycle: %s" % " -> ".join(cyc),
                             "containers"))
        for r in _iter_list(model.get("relations")):
            if str(r.get("type")) not in CONTAINMENT_TYPES:
                continue
            a, b = str(r.get("from") or ""), str(r.get("to") or "")
            if a in containers and b in nodes:
                cbox = cmap.get(a)
                nbox = dict((x["id"], x) for x in boxes).get(b)
                if cbox and nbox and not _contains(cbox, nbox, EPS):
                    errors.append(_e("E_LEVEL_REGRESSION",
                                     "containment relation %s: %s is outside %s"
                                     % (r.get("id"), b, a), "relations.%s" % r.get("id")))

    # ---- levels ------------------------------------------------------------
    # ---- legend <-> figure colour map --------------------------------------
    if legend:
        node_colour = {}
        node_label = {}
        for nid in sorted(nodes):
            stroke = _valid_color((nodes[nid] or {}).get("stroke"))
            if stroke:
                node_colour[nid] = stroke.upper()
            node_label[nid] = (nodes[nid] or {}).get("label") or nid
        category_colours = {}
        for item in legend.get("items") or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("kind") or "") in ("category", "marker", "value_scale"):
                colour = _valid_color(item.get("color"))
                if colour:
                    category_colours.setdefault(colour.upper(), []).append(item.get("id"))
        for item in legend.get("items") or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("kind") or "") not in ("category", "marker", "value_scale"):
                continue
            colour = _valid_color(item.get("color"))
            if not colour:
                continue
            keys = []
            for raw in (item.get("value"), item.get("label")):
                keys.extend(_legend_keys(raw))
            hit = None
            for nid in sorted(node_label):
                nkeys = _legend_keys(node_label[nid])
                if any(k and k in nkeys for k in keys):
                    hit = nid
                    break
            if hit and node_colour.get(hit) != colour.upper():
                warnings.append(_w("W_LEGEND_COLOR_MISMATCH",
                                   "legend item %s colour %s does not match node %s (%s)"
                                   % (item.get("id"), colour, hit, node_colour.get(hit)),
                                   "legend.items"))
        # a colour carrying two meanings cannot be mapped back to the legend
        matched_colours = set()
        for item in legend.get("items") or []:
            if isinstance(item, dict) and _valid_color(item.get("color")):
                for raw in (item.get("value"), item.get("label")):
                    keys = _legend_keys(raw)
                    for nid in sorted(node_label):
                        if any(k and k in _legend_keys(node_label[nid]) for k in keys):
                            matched_colours.add(item["color"].upper())
                            break
        for nid in sorted(node_colour):
            c = node_colour[nid]
            if c in category_colours and c not in matched_colours:
                warnings.append(_w("W_LEGEND_COLOR_COLLISION",
                                   "node %s uses colour %s which the legend maps to %s"
                                   % (nid, c, ",".join(sorted(category_colours[c]))),
                                   "legend.items"))
    lvl = {}
    for nid in sorted(nodes):
        v = _as_float((nodes[nid] or {}).get("level"))
        if v is not None:
            lvl[nid] = int(v)
    for cid in sorted(containers):
        for m in (containers[cid].get("members") or []) if isinstance(containers[cid], dict) else []:
            pass
    stats["levels"] = (max(lvl.values()) + 1) if lvl else 0
    per = {}
    for nid in sorted(lvl):
        per[lvl[nid]] = per.get(lvl[nid], 0) + 1
    stats["max_per_level"] = max(per.values()) if per else 0
    node_by_id = dict((b["id"], b) for b in boxes)
    edge_by_id = {}
    for e in edges:
        if not isinstance(e, dict):
            continue
        edge_by_id[str(e.get("id"))] = e
    if isinstance(model, dict):
        for r in _iter_list(model.get("relations")):
            rtype = str(r.get("type") or "")
            direction = str(r.get("direction") or "")
            a, b = str(r.get("from") or ""), str(r.get("to") or "")
            if a not in lvl or b not in lvl:
                continue
            if rtype in DIRECTIONAL_TYPES and direction == "forward":
                if lvl[b] < lvl[a]:
                    e = edge_by_id.get(str(r.get("id") or ""))
                    if e is not None and e.get("feedback"):
                        if strict:
                            warnings.append(_w("W_BACKWARD_EDGE",
                                               "relation %s is drawn as a routed feedback edge "
                                               "(%s L%d -> %s L%d)" % (r.get("id"), a, lvl[a],
                                                                       b, lvl[b]),
                                               "relations.%s" % r.get("id")))
                    else:
                        errors.append(_e("E_LEVEL_REGRESSION",
                                         "forward %s edge %s goes from level %d back to level %d"
                                         % (rtype, r.get("id"), lvl[a], lvl[b]),
                                         "relations.%s" % r.get("id")))
            if rtype in CONTAINMENT_TYPES and a in containers and b in node_by_id:
                cbox = cmap.get(a)
                if cbox and not _contains(cbox, node_by_id[b], EPS):
                    errors.append(_e("E_LEVEL_REGRESSION",
                                     "containment %s: %s is not inside %s" % (r.get("id"), b, a),
                                     "relations.%s" % r.get("id")))
    for e in edges:
        if not isinstance(e, dict):
            continue
        pts = e.get("points_mm")
        if not isinstance(pts, list) or len(pts) < 2:
            if strict:
                warnings.append(_w("W_EDGE_UNROUTED", "edge %s has no polyline" % e.get("id"),
                                   "edges.%s" % e.get("id")))
            continue
        for p in pts:
            if not isinstance(p, (list, tuple)) or len(p) < 2:
                continue
            x = _as_float(p[0])
            y = _as_float(p[1])
            if x is None or y is None:
                continue
            if x < -EPS or y < -EPS or x > W + EPS or y > H + EPS:
                errors.append(_e("E_OUT_OF_CANVAS",
                                 "edge %s leaves the canvas" % e.get("id"),
                                 "edges.%s" % e.get("id")))
                break
    # legend inside canvas
    if legend:
        lx, ly = _as_float(legend.get("x_mm")), _as_float(legend.get("y_mm"))
        lw, lh = _as_float(legend.get("w_mm")), _as_float(legend.get("h_mm"))
        if None not in (lx, ly, lw, lh):
            if lx < -EPS or ly < -EPS or lx + lw > W + EPS or ly + lh > H + EPS:
                errors.append(_e("E_OUT_OF_CANVAS", "legend box leaves the canvas", "legend"))
        for item in legend.get("items") or []:
            if not isinstance(item, dict):
                continue
            tx = _as_float(item.get("text_x_mm"))
            tw = _as_float(item.get("text_w_mm"))
            if tx is None or tw is None:
                continue
            if tx + tw > W + EPS:
                errors.append(_e("E_TEXT_OVERFLOW_EST",
                                 "legend item %s text leaves the canvas" % item.get("id"),
                                 "legend.items"))
    # chart inside canvas
    chart = layout_obj.get("chart")
    if isinstance(chart, dict):
        plot = chart.get("plot") if isinstance(chart.get("plot"), dict) else {}
        px, py = _as_float(plot.get("x")), _as_float(plot.get("y"))
        pw, ph = _as_float(plot.get("w")), _as_float(plot.get("h"))
        if None not in (px, py, pw, ph):
            if px < -EPS or py < -EPS or px + pw > W + EPS or py + ph > H + EPS:
                errors.append(_e("E_OUT_OF_CANVAS", "chart plot area leaves the canvas",
                                 "chart.plot"))
        # a bar encodes its value by length: a truncated baseline misstates ratios
        yspec = chart.get("y") if isinstance(chart.get("y"), dict) else {}
        bars = [s for s in (chart.get("series") or [])
                if isinstance(s, dict) and str(s.get("shape")) == "bar"]
        y_min = _as_float(yspec.get("min"))
        if bars and y_min is not None and y_min > 0:
            warnings.append(_w("W_BAR_BASELINE_TRUNCATED",
                               "bar chart value axis starts at %s, not 0: bar lengths no "
                               "longer encode the data ratios" % y_min, "chart.y"))
    stats["nodes"] = len(boxes)
    stats["containers"] = len(cboxes)
    stats["edges"] = len([e for e in edges if isinstance(e, dict)])
    stats["edge_crossings_est"] = _as_float(layout_obj.get("stats", {}).get("edge_crossings_est")
                                            if isinstance(layout_obj.get("stats"), dict) else None,
                                            0) or 0
    if strict:
        for c in cboxes:
            if not (containers.get(c["id"], {}).get("members")):
                warnings.append(_w("W_EMPTY_CONTAINER",
                                   "container %s has no members" % c["id"],
                                   "containers.%s" % c["id"]))
    return _finish(errors, warnings, stats)


def _iter_list(value):
    """Iterate a model field that must be a list; never raise on a bad type."""
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]
    return []


def _model_container_cycle(model):
    """Detect a membership cycle straight from the model (independent of layout)."""
    ents = set()
    for raw in _iter_list(model.get("entities")):
        if raw.get("id"):
            ents.add(str(raw["id"]))
    parent = {}
    for raw in _iter_list(model.get("containers")):
        cid = str(raw.get("id") or "")
        members = raw.get("members") if isinstance(raw.get("members"), list) else []
        for m in members:
            m = str(m)
            if m and m != cid:
                parent.setdefault(m, cid)
    for raw in _iter_list(model.get("entities")):
        cid = raw.get("id")
        c = raw.get("container")
        if isinstance(cid, str) and isinstance(c, str) and c:
            parent.setdefault(cid, c)
    for raw in _iter_list(model.get("relations")):
        if str(raw.get("type")) not in CONTAINMENT_TYPES:
            continue
        a, b = str(raw.get("from") or ""), str(raw.get("to") or "")
        if a and b and a != b:
            parent.setdefault(b, a)
    for start in sorted(parent):
        seen = []
        cur = start
        guard = 0
        while cur is not None and guard < 128:
            if cur in seen:
                return sorted(seen[seen.index(cur):])
            seen.append(cur)
            cur = parent.get(cur)
            guard += 1
    return []


def _e(code, message, where=""):
    return {"code": code, "message": message, "where": where}


def _finish(errors, warnings, stats):
    stats["errors"] = len(errors)
    stats["warnings"] = len(warnings)
    return {"errors": errors, "warnings": warnings, "stats": stats}


# --------------------------------------------------------------------------
# tiny CLI: python layout.py model.json  -> layout.json on stdout
# --------------------------------------------------------------------------
def _main(argv):
    import json
    import sys
    if len(argv) < 2:
        sys.stderr.write("usage: layout.py <model.json> [layout-out.json]\n")
        return 2
    with open(argv[1], "r", encoding="utf-8") as fh:
        model = json.load(fh)
    lay = layout(model)
    text = json.dumps(lay, ensure_ascii=False, indent=2)
    if len(argv) > 2:
        with open(argv[2], "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text + "\n")
    else:
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_main(sys.argv))
