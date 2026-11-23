# -*- coding: utf-8 -*-
"""Input discovery, source inventory extraction and review-batch construction.

Frozen API (CONTRACT.md section 4.2):
    discover(input_dir) -> dict
    extract_sources(case_manifest) -> dict
    build_review_batch(case_manifest, inventory, draft_model) -> dict
    write_artifacts(work_dir, case_manifest, inventory, draft_model, review_batch) -> dict

Design invariants:
  * standard library only;
  * never write into the input tree (``/input`` is read-only material);
  * a missing / empty / wrongly-encoded input tree still yields a valid manifest
    with ``warnings`` and a best-effort ``case_id`` (never an exception);
  * PDF/office material that has no text extractor is *skipped with a warning*,
    never fabricated.

This module also owns the single shared text-normalisation and source-index used
by ``model.validate_model`` (imported from here, so the two modules can never
disagree about what "the quote is in the source" means).
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
from copy import deepcopy

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import common  # noqa: E402  (path bootstrap above)
import mech  # noqa: E402  (frozen mechanism ontology; see CONTRACT section 3)

SCHEMA_VERSION = common.SCHEMA_VERSION

# --------------------------------------------------------------------------
# Biological verb lexicon (frozen; mirrored in references/extraction_rules.md)
#
# One class per frozen relation family (CONTRACT 3.4).  More specific families
# come first in :data:`CUE_CLASS_ORDER`: "磷酸化并激活 X" is primarily a
# modification, "入核" is primarily a transport, and a bare "激活" stays
# activation.  A cue may legitimately support more than one asserted type -
# that ambiguity is resolved in :data:`model.TYPE_CANDIDATES`, never by
# rejecting the relation.
# --------------------------------------------------------------------------
VERB_LEXICON = {
    "activation": ["激活", "促进", "诱导", "上调", "增强", "激动", "活化", "刺激",
                   "activate", "activates", "activated", "promotes", "promoted",
                   "induces", "induced", "upregulates", "upregulated", "enhances",
                   "stimulates"],
    "inhibition": ["抑制", "阻断", "下调", "负调控", "沉默", "敲低", "拮抗", "降低",
                   "inhibits", "inhibited", "suppresses", "suppressed", "blocks",
                   "blocked", "downregulates", "represses", "knockdown", "reduces",
                   "reduced"],
    "modification": ["磷酸化", "去磷酸化", "泛素化", "去泛素化", "乙酰化", "去乙酰化",
                     "甲基化", "去甲基化", "糖基化", "羟基化", "硝基化", "sumo化",
                     "phosphorylates", "phosphorylated", "phosphorylation",
                     "dephosphorylation", "dephosphorylates", "ubiquitinates",
                     "ubiquitinated", "ubiquitination", "acetylates", "acetylated",
                     "acetylation", "deacetylates", "deacetylated", "deacetylation",
                     "methylates", "methylated", "methylation", "glycosylates",
                     "glycosylation", "autophosphorylates", "autophosphorylation",
                     "sumoylates", "hydroxylates", "nitrosylates"],
    "binding": ["结合", "互作", "相互作用", "偶联", "募集", "binds", "binding", "bound",
                "docks", "associates with", "recruits", "recruited", "complexes with"],
    "transport": ["转运", "转位", "入核", "出核", "分泌", "内吞", "外排", "胞吞",
                  "transports", "transported", "transport", "translocates",
                  "translocated", "translocation", "imports", "exported", "exports",
                  "secreted", "secretes", "efflux", "influx", "shuttles"],
    "transcription": ["转录", "启动子", "transcribes", "transcribed", "transcription",
                      "promoter", "transcriptionally"],
    "translation": ["翻译", "translates", "translated", "translation"],
    "feedback": ["反馈", "负反馈", "正反馈", "feedback", "feed-back"],
    "containment": ["包含", "属于", "构成", "组成", "分为", "归入", "包括",
                    "contains", "consists", "comprises", "belongs"],
    "causation": ["导致", "引起", "因此", "从而", "致使", "造成", "causes", "leads to",
                  "results in", "thereby"],
    "sequence": ["上游", "下游", "随后", "进而", "接着", "之后", "随后再", "先于",
                 "upstream", "downstream", "subsequently", "followed by"],
    "membership": ["属于", "归入", "归类", "成員", "成员", "belongs"],
    "association": ["关联", "相关", "共表达", "interacts", "associates", "correlates"],
}
BIDIRECTIONAL_CUES = ["双向", "相互", "互相", "互为", "bidirectional", "mutual"]

#: order used when several cue families occur in one sentence: the most specific
#: mechanism family wins the endpoint-binding role, the generic ones come last
CUE_CLASS_ORDER = ["containment", "feedback", "modification", "transport",
                   "transcription", "translation", "binding", "inhibition",
                   "activation", "causation", "sequence", "membership", "association"]

RELATION_TYPES = mech.RELATION_TYPES

# --------------------------------------------------------------------------
# Text normalisation: whitespace / full-width / CJK-punctuation forgiving,
# but never a fuzzy (edit-distance) match.
# --------------------------------------------------------------------------
_FULLWIDTH = {c: c - 0xFEE0 for c in range(0xFF01, 0xFF5F)}
_PUNCT_VARIANTS = {
    0x3000: 0x20,   # ideographic space
    0x00A0: 0x20, 0x2002: 0x20, 0x2003: 0x20, 0x2009: 0x20, 0x202F: 0x20,
    0x3002: 0x2E,   # 。
    0x3001: 0x2C,   # 、
    0x300A: 0x3C, 0x300B: 0x3E,      # 《》
    0x3010: 0x5B, 0x3011: 0x5D,      # 【】
    0x2018: 0x27, 0x2019: 0x27, 0x201C: 0x22, 0x201D: 0x22, 0x2032: 0x27,
    0x2010: 0x2D, 0x2011: 0x2D, 0x2012: 0x2D, 0x2013: 0x2D, 0x2014: 0x2D,
    0x2015: 0x2D, 0x2212: 0x2D, 0xFE58: 0x2D, 0xFE63: 0x2D,
    0x2026: 0x2E,   # …
    0x00B7: 0x2E, 0x2022: 0x2E, 0x30FB: 0x2E,
    0x00D7: 0x78, 0x00F7: 0x2F,
}
_WS_RE = re.compile(r"\s+")

#: decorations stripped before a label is looked up in the source
_DECOR_RE = re.compile(r"[（(\[【][^）)\]】]*[）)\]】]|[:：\-—–,，;；]+$|^[:：\-—–,，;；]+")


def _trans(s):
    out = []
    for ch in str(s):
        cp = ord(ch)
        if cp in _PUNCT_VARIANTS:
            out.append(chr(_PUNCT_VARIANTS[cp]))
        elif cp in _FULLWIDTH:
            out.append(chr(_FULLWIDTH[cp]))
        else:
            out.append(ch)
    return "".join(out)


def normalise_text(text):
    """Canonical comparison form: half-width, unified punctuation, no spaces, casefolded."""
    return _WS_RE.sub("", _trans(text)).casefold()


def strip_decorations(label):
    """Remove bracketed decoration / edge punctuation from a display label."""
    s = str(label)
    for _ in range(4):
        new = _DECOR_RE.sub("", s).strip()
        if new == s:
            break
        s = new
    return s or str(label).strip()


_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def numbers_in_text(text):
    return _NUM_RE.findall(str(text))


def parse_locator(locator):
    """Return (kind, start, end) for 'L12', 'L12-L18', 'p3', 'table:col'."""
    s = str(locator or "").strip()
    if not s:
        return (None, None, None)
    m = re.match(r"^[Ll](\d+)\s*(?:-\s*[Ll]?(\d+))?$", s)
    if m:
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else a
        return ("line", min(a, b), max(a, b))
    m = re.match(r"^[Pp](\d+)$", s)
    if m:
        return ("page", int(m.group(1)), int(m.group(1)))
    if s.lower().startswith("table:"):
        return ("table", s.split(":", 1)[1], None)
    if s.lower().startswith("fig:"):
        return ("fig", s.split(":", 1)[1], None)
    return (None, None, None)


def cues_in_text(text):
    """Map cue family -> cues actually present in `text` (normalised match)."""
    t = normalise_text(text)
    found = {}
    for cls in CUE_CLASS_ORDER:
        for cue in VERB_LEXICON.get(cls, ()):
            if normalise_text(cue) and normalise_text(cue) in t:
                found.setdefault(cls, []).append(cue)
    for cue in BIDIRECTIONAL_CUES:
        if normalise_text(cue) in t:
            found.setdefault("bidirectional", []).append(cue)
    return found


# --------------------------------------------------------------------------
# Source index (shared by validator and draft extractor)
# --------------------------------------------------------------------------
def table_text(table):
    parts = list(table.get("columns") or [])
    for row in table.get("rows") or []:
        parts.extend(str(c) for c in row)
    parts.extend("%s%s" % (k, v) for k, v in (table.get("units") or {}).items() if v)
    return " | ".join(parts)


class SourceIndex:
    """Lookup surface over a `source_inventory.json` object."""

    def __init__(self, inventory):
        self.inventory = inventory if isinstance(inventory, dict) else {}
        self.paths = set()
        self.units_by_path = {}
        self.tables_by_path = {}
        self._text_by_path = {}
        self._table_text = {}
        self._haystack_parts = []
        self._numbers = set()
        self._number_values = set()

        for source in (self.inventory.get("units") or [],
                       self.inventory.get("structured_units") or []):
            for unit in source:
                if not isinstance(unit, dict):
                    continue
                path = str(unit.get("path") or "")
                self.paths.add(path)
                self.units_by_path.setdefault(path, []).append(unit)
                self._haystack_parts.append(str(unit.get("text") or ""))
        for table in self.inventory.get("tables") or []:
            if not isinstance(table, dict):
                continue
            path = str(table.get("path") or "")
            self.paths.add(path)
            self.tables_by_path.setdefault(path, []).append(table)
            txt = table_text(table)
            self._table_text[id(table)] = txt
            self._haystack_parts.append(txt)
        for path, units in self.units_by_path.items():
            units.sort(key=lambda u: (u.get("line") or 0, str(u.get("locator") or "")))
            self._text_by_path[path] = normalise_text(
                " ".join(str(u.get("text") or "") for u in units))

        self.haystack = normalise_text(" ".join(self._haystack_parts))
        self._raw_haystack = "\n".join(self._haystack_parts)
        for tok in _NUM_RE.findall(self._raw_haystack):
            self._numbers.add(tok)
            try:
                self._number_values.add(float(tok))
            except ValueError:
                pass

    # -- files -------------------------------------------------------------
    def has_path(self, path):
        return str(path or "") in self.paths

    # -- quotes ------------------------------------------------------------
    def _range_units(self, units, locator):
        kind, start, end = parse_locator(locator)
        if kind != "line":
            return []
        out = []
        for u in units:
            line = u.get("line")
            if isinstance(line, int) and start <= line <= end:
                out.append(u)
        return out

    def find_quote(self, path, locator, quote):
        q = normalise_text(quote)
        if not q:
            return False
        path = str(path or "")
        units = self.units_by_path.get(path)
        if units:
            exact = [u for u in units if str(u.get("locator") or "") == str(locator or "")]
            if not exact:
                exact = self._range_units(units, locator)
            for u in (exact or units):
                if q in normalise_text(u.get("text") or ""):
                    return True
            if q in self._text_by_path.get(path, ""):
                return True
        for table in self.tables_by_path.get(path) or []:
            if q in normalise_text(self._table_text.get(id(table), "")):
                return True
            kind, col, _ = parse_locator(locator)
            if kind == "table" and col:
                cols = [str(c) for c in (table.get("columns") or [])]
                idx = cols.index(col) if col in cols else None
                idx = idx if idx is not None else (int(col) if col.lstrip("-").isdigit() else None)
                chunks = [] if idx is None else [cols[idx]]
                if idx is not None:
                    for row in table.get("rows") or []:
                        if isinstance(row, (list, tuple)) and idx < len(row):
                            chunks.append(str(row[idx]))
                if any(q in normalise_text(c) for c in chunks):
                    return True
        return False

    def unit_texts(self, path, locator=None):
        path = str(path or "")
        units = self.units_by_path.get(path) or []
        if locator:
            exact = [u for u in units if str(u.get("locator") or "") == str(locator)]
            if not exact:
                exact = self._range_units(units, locator)
            if exact:
                return [str(u.get("text") or "") for u in exact]
        if units:
            return [str(u.get("text") or "") for u in units]
        return [self._table_text.get(id(t), "") for t in self.tables_by_path.get(path) or []]

    def has_text(self, text):
        """True when `text` (whitespace/punctuation normalised) occurs in the inventory."""
        t = normalise_text(text)
        return bool(t) and t in self.haystack

    def has_number(self, token):
        tok = str(token).strip()
        if not tok:
            return False
        if tok in self._numbers:
            return True
        try:
            return float(tok) in self._number_values
        except ValueError:
            return False

    def paths_with_units(self):
        return sorted(self.units_by_path)


# --------------------------------------------------------------------------
# discover()
# --------------------------------------------------------------------------
def _load_json_soft(path, warnings):
    p = str(path)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:  # noqa: BLE001 - any failure is soft here
        warnings.append("cannot parse JSON %s: %s" % (os.path.basename(p), exc))
        return None


def _slug_case_id(text):
    s = common.slug(text, fallback="")
    return s


def _case_id_from_task(text):
    """First level-1 markdown heading -> slug (contract fallback #2)."""
    for line in str(text or "").splitlines():
        m = re.match(r"^\s*#\s+(.+?)\s*$", line)
        if m:
            return _slug_case_id(m.group(1))
    return ""


_MATERIAL_ROLES = {"text": "material", "table": "material", "pdf": "material",
                   "image": "material", "office": "material", "binary": "unknown"}

#: the seven keys the platform's output contract mandates (task.md section
#: "Runtime contract" + resources/output-contract.md).  `case.json` ships them
#: either as a list of names or as a dict of name -> "".
DEFAULT_OUTPUT_CONTRACT_FIELDS = ("case_id", "status", "editable_source",
                                  "export_artifact", "content_map",
                                  "compliance_checks", "exceptions")


def normalise_output_contract(raw):
    """Normalise `output_contract` to ``({key: ""}, keys, note)``.

    Accepts the platform's ``list[str]`` shape and the dict shape used by the
    bundled examples.  Any other value is reported rather than silently dropped.
    """
    if isinstance(raw, dict):
        out = deepcopy(raw)
        keys = [str(k) for k in out.keys()]
        for key in DEFAULT_OUTPUT_CONTRACT_FIELDS:
            out.setdefault(key, "")
        return out, keys, ""
    if isinstance(raw, list):
        keys = [str(k) for k in raw if str(k).strip()]
        if not keys:
            return {k: "" for k in DEFAULT_OUTPUT_CONTRACT_FIELDS}, [], \
                "case.json output_contract list was empty; platform defaults used"
        out = {k: "" for k in keys}
        for key in DEFAULT_OUTPUT_CONTRACT_FIELDS:
            out.setdefault(key, "")
        note = ""
        missing = [k for k in DEFAULT_OUTPUT_CONTRACT_FIELDS if k not in keys]
        if missing:
            note = ("case.json output_contract list is missing the mandated field(s) %s; "
                    "they were added as empty strings" % missing)
        return out, keys, note
    if raw is None:
        return {k: "" for k in DEFAULT_OUTPUT_CONTRACT_FIELDS}, [], \
            "case.json has no output_contract; the platform's seven mandated keys are used"
    return ({k: "" for k in DEFAULT_OUTPUT_CONTRACT_FIELDS}, [],
            "case.json output_contract has an unsupported type %s; platform defaults used"
            % type(raw).__name__)


def discover(input_dir):
    """Build the `case_manifest.json` object for an input tree. Never raises."""
    warnings = []
    raw_dir = str(input_dir) if input_dir else ""
    input_dir_abs = os.path.abspath(raw_dir) if raw_dir else os.path.abspath(".")

    if not raw_dir:
        warnings.append("no input directory supplied")
    elif not os.path.isdir(input_dir_abs):
        warnings.append("input directory not found or not a directory: %s" % raw_dir)

    files = []
    for path in common.iter_files(input_dir_abs):
        try:
            rel = common.safe_relpath(input_dir_abs, path)
        except common.SkillError:
            warnings.append("skipped path outside input root: %s" % path)
            continue
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError as exc:
            warnings.append("unreadable file %s: %s" % (rel, exc))
            continue
        kind = common.detect_kind(path)
        files.append({
            "rel": rel,
            "bytes": len(data),
            "sha256": common.sha256_bytes(data),
            "kind": kind,
            "role": "metadata" if kind == "metadata" else _MATERIAL_ROLES.get(kind, "unknown"),
        })
    files.sort(key=lambda f: f["rel"])

    case_obj = _load_json_soft(os.path.join(input_dir_abs, "case.json"), warnings)
    if case_obj is None:
        for alt in ("case.yaml", "case.yml"):
            case_obj = _load_json_soft(os.path.join(input_dir_abs, alt), warnings)
            if case_obj is not None:
                break
    if case_obj is not None and not isinstance(case_obj, dict):
        warnings.append("case.json is not a JSON object; ignored")
        case_obj = None
    case_obj = case_obj or {}

    # The platform publishes `output_contract` in TWO shapes (the organiser's
    # dataset resource ships a list of the seven mandated keys, our own examples
    # ship a dict of key -> "").  Both are normalised to `{key: ""}` here so the
    # seven keys can never be silently dropped.
    output_contract, contract_keys, contract_note = normalise_output_contract(
        case_obj.get("output_contract"))
    if contract_note:
        warnings.append(contract_note)

    required_fields = case_obj.get("required_fields")
    if not isinstance(required_fields, list):
        if required_fields is not None:
            warnings.append("case.json required_fields is not a list; using []")
        required_fields = list(DEFAULT_OUTPUT_CONTRACT_FIELDS)
    required_fields = [str(f) for f in required_fields]
    if not required_fields:
        required_fields = list(contract_keys or DEFAULT_OUTPUT_CONTRACT_FIELDS)
    for key in required_fields:
        output_contract.setdefault(key, "")
    if contract_keys and set(required_fields) != set(contract_keys):
        warnings.append("case.json required_fields %s differ from the output_contract keys %s; "
                        "both are kept" % (sorted(required_fields), sorted(contract_keys)))

    # task.md / task text
    task_rel = ""
    task_text = ""
    for cand in ("task.md", "TASK.md", "task.txt", "README.md"):
        if os.path.isfile(os.path.join(input_dir_abs, cand)):
            task_rel = cand
            try:
                task_text = common.read_text(os.path.join(input_dir_abs, cand))
            except Exception as exc:  # noqa: BLE001
                warnings.append("cannot read %s: %s" % (cand, exc))
            break
    if task_text and len(task_text) > 100_000:
        warnings.append("task text truncated to 100000 chars for the manifest")
        task_text = task_text[:100_000]
    if not task_rel:
        warnings.append("no task.md found in input tree")

    case_id = case_obj.get("case_id") or case_obj.get("id") or case_obj.get("caseId") or ""
    if not isinstance(case_id, str):
        case_id = str(case_id or "")
    case_id = case_id.strip()
    if not case_id:
        case_id = _case_id_from_task(task_text)
        if case_id:
            warnings.append("case.json has no case_id; fell back to task.md heading slug")
    if not case_id:
        case_id = "unknown-case"
        warnings.append("no case_id could be derived; fell back to 'unknown-case'")

    materials = case_obj.get("materials")
    if not isinstance(materials, list):
        materials = []
    materials = [str(m).replace("\\", "/").lstrip("./") for m in materials]

    figure_hint = case_obj.get("figure")
    if not isinstance(figure_hint, dict):
        figure_hint = {}

    notes = case_obj.get("notes")
    if notes is not None and not isinstance(notes, str):
        notes = str(notes)

    meta_count = sum(1 for f in files if f["role"] == "metadata")
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "case_id": case_id,
        "input_dir": input_dir_abs,
        "output_contract": output_contract,
        "output_contract_keys": sorted(output_contract.keys()),
        "output_contract_shape": ("list" if isinstance(case_obj.get("output_contract"), list)
                                  else "dict" if isinstance(case_obj.get("output_contract"), dict)
                                  else "default"),
        "required_fields": required_fields,
        "files": files,
        "task_path": task_rel,
        "task_text": task_text,
        "notes": notes,
        "warnings": warnings,
        # convenience extras (internal evidence only, never required by run.py)
        "materials": materials,
        "figure_hint": figure_hint,
        "task": case_obj.get("task") if isinstance(case_obj.get("task"), str) else "",
        "stats": {"files": len(files), "metadata_files": meta_count,
                  "materials_declared": len(materials)},
    }
    return manifest


# --------------------------------------------------------------------------
# extract_sources()
# --------------------------------------------------------------------------
_TABLE_UNIT_RE = re.compile(r"[（(\[]\s*([^）)\]]{1,24})\s*[）)\]]")
_UNIT_HINT_RE = re.compile(
    r"(fold change|mg/?mL|µg/?mL|ug/?mL|ng/?mL|pg/?mL|mmol/?L|µmol/?L|umol/?L|"
    r"nmol/?L|pmol/?L|mol/?L|%|percent|nM|µM|uM|mM|pM|min|hours?|days?|weeks?|"
    r"秒|分钟|小时|天|周|倍|相对表达量|表达量|浓度|时间|温度|℃|°C|rpm|g|kg|"
    r"mm|cm|µm|um|nm|Hz|kHz|mg|µg|ug|ng|pg)", re.I)


def _split_delimited(text):
    sample = "\n".join(l for l in text.splitlines() if l.strip())[:4096]
    delim = ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delim = dialect.delimiter
    except Exception:  # noqa: BLE001 - fall back to comma
        if sample.count("\t") > sample.count(","):
            delim = "\t"
        elif sample.count(";") > sample.count(","):
            delim = ";"
    reader = csv.reader(text.splitlines(), delimiter=delim)
    rows = [list(r) for r in reader if any(str(c).strip() for c in r)]
    return rows, delim


def _parse_table(path, rel, file_sha, warnings):
    text = common.read_text(path)
    rows, delim = _split_delimited(text)
    if not rows:
        warnings.append("table %s has no rows" % rel)
    header = [str(c).strip() for c in (rows[0] if rows else [])]
    body = [[str(c).strip() for c in r] for r in rows[1:]]
    units = {}
    clean_header = []
    for col in header:
        m = _TABLE_UNIT_RE.search(col)
        if m:
            units[col] = m.group(1).strip()
        clean_header.append(col)
    # a units row immediately below the header is a common convention
    if body and any(_UNIT_HINT_RE.fullmatch(c) for c in body[0] if c):
        for i, col in enumerate(clean_header):
            if i < len(body[0]) and body[0][i] and col not in units:
                units[col] = body[0][i]
        body = body[1:]
    # infer units from cell content when the header carries none
    for i, col in enumerate(clean_header):
        if col in units:
            continue
        for row in body[:20]:
            if i < len(row):
                m = _UNIT_HINT_RE.search(row[i])
                if m and re.search(r"\d", row[i]):
                    units[col] = m.group(1)
                    break
    units = dict(units)
    unit_status = {}
    for col in clean_header:
        declared = str(units.get(col) or "").strip()
        if declared:
            unit_status[col] = "declared"
            units[col] = declared
            continue
        from_header = mech.unit_from_header(col)
        if from_header:
            # the header literally declares the unit (time_h -> h): not invented
            units[col] = from_header
            unit_status[col] = "declared_in_header"
        elif mech.is_dimensionless_column(col):
            units[col] = None            # explicitly dimensionless, not "missing"
            unit_status[col] = "dimensionless"
        else:
            unit_status[col] = "unknown"
    keys = []
    for i, col in enumerate(clean_header):
        vals = [r[i] for r in body if i < len(r)]
        non_empty = [v for v in vals if v]
        if non_empty and len(set(non_empty)) <= max(2, len(non_empty) // 2):
            if not all(_NUM_RE.fullmatch(v) for v in non_empty):
                keys.append(col)
    table = {
        "id": "",
        "path": rel,
        "sha256": file_sha,
        "columns": clean_header,
        "rows": body,
        "units": units,
        "unit_status": unit_status,
        "keys": keys,
        "delimiter": delim,
        "n_rows": len(body),
    }
    return table


def _units_from_text(text, rel, kind):
    units = []
    for i, line in enumerate(str(text).splitlines(), start=1):
        if not line.strip():
            continue
        units.append({
            "id": "",
            "path": rel,
            "locator": "L%d" % i,
            "kind": kind,
            "text": line,
            "sha256": common.sha256_text(line),
            "chars": len(line),
            "line": i,
        })
    return units


def _json_fragment(**pairs):
    """Compact `"key":value` fragments that occur verbatim in the source file."""
    parts = []
    for key, value in pairs.items():
        if value is None:
            continue
        parts.append('"%s":%s' % (key, json.dumps(value, ensure_ascii=False,
                                                  separators=(",", ":"))))
    return ",".join(parts)


#: entity `kind` spellings seen in real workorders -> frozen ontology spellings
_WORKORDER_KIND_ALIASES = {
    "molecule": "metabolite", "metabolite": "metabolite", "small_molecule": "metabolite",
    "transcription_factor": "protein", "tf": "protein", "kinase": "protein",
    "phosphatase": "protein", "receptor": "protein", "enzyme": "protein",
    "cytokine": "protein", "growth_factor": "protein", "ligand": "protein",
    "protein_complex": "complex", "complex": "complex",
    "organelle": "organelle", "compartment": "organelle", "cell_type": "cell_type",
    "celltype": "cell_type", "cell": "cell_type", "cell_line": "cell_type",
    "modification_site": "modification_site", "site": "modification_site",
    "stimulus": "stimulus", "stress": "stimulus", "condition": "stimulus",
    "drug": "drug", "inhibitor": "drug", "compound": "drug", "treatment": "drug",
    "gene": "gene", "gene_or_protein": "gene", "transcript": "gene", "mrna": "gene",
    "protein": "protein", "process": "process", "pathway": "process",
    "category": "category", "axis": "axis", "concept": "concept", "sample": "sample",
}


def _workorder_kind(value, label, warnings):
    raw = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    if raw in _WORKORDER_KIND_ALIASES:
        return _WORKORDER_KIND_ALIASES[raw]
    if raw:
        warnings.append("workorder kind %r is not in the ontology; kept verbatim" % raw)
        return raw
    return "concept"


def _relation_default_direction(rtype):
    if rtype in ("binding", "association", "containment", "membership"):
        return "none"
    return "forward"


def _parse_figure_json(path, rel, file_sha, warnings):
    """Parse a `figure-workorder.json` / `figure03-structure.json` material.

    Returns ``(workorder, structured_units)`` or ``(None, [])`` when the document
    does not look like a figure workorder.  Nothing is invented: every value is
    taken from the document, and every element gets a locator + verbatim quote
    fragment pointing back into that document.
    """
    obj = _load_json_soft(path, warnings)
    if not isinstance(obj, dict):
        return None, []
    looks_like_workorder = any(k in obj for k in ("entities", "relations", "containers",
                                                 "chart", "legend_encoding", "figure_kind"))
    if not looks_like_workorder:
        return None, []

    units = []

    def unit(pointer, element):
        text = json.dumps(element, ensure_ascii=False, separators=(",", ":"))
        units.append({
            "id": "", "path": rel, "locator": "json:%s" % pointer, "kind": "json_object",
            "text": text, "sha256": common.sha256_text(text), "chars": len(text),
            "line": None, "structured": True, "pointer": pointer,
        })
        return text

    wo = {
        "path": rel,
        "sha256": file_sha,
        "figure_id": obj.get("figure_id") or obj.get("figureId") or "",
        "figure_kind": obj.get("figure_kind") or obj.get("figure_kind_hint") or "",
        "orientation": obj.get("orientation") or "",
        "scale": obj.get("scale") if isinstance(obj.get("scale"), dict) else {},
        "note": str(obj.get("note") or "") if obj.get("note") is not None else "",
        "containers": [],
        "entities": [],
        "relations": [],
        "implied_entities": [],
        "chart": obj.get("chart") if isinstance(obj.get("chart"), dict) else None,
        "legend_encoding": [e for e in (obj.get("legend_encoding") or [])
                            if isinstance(e, dict)],
        "required_panels": [str(p) for p in (obj.get("required_panels") or [])
                            if str(p).strip()],
    }

    used_con = set()
    for i, raw in enumerate(obj.get("containers") or []):
        if not isinstance(raw, dict):
            continue
        cid = str(raw.get("id") or raw.get("name") or "").strip()
        label = str(raw.get("label") or cid).strip()
        if not cid:
            cid = common.slug(label, fallback="container_%d" % i)
        if cid in used_con:
            warnings.append("workorder container id %r is duplicated; later entry ignored" % cid)
            continue
        used_con.add(cid)
        kind = str(raw.get("kind") or "compartment").strip()
        if kind not in ("compartment", "membrane", "cell", "group"):
            warnings.append("workorder container kind %r is not in the ontology; used as "
                            "'group'" % kind)
            kind = "group"
        canon = mech.canonical_container(cid) if kind == "compartment" else ""
        entry = {
            "id": cid, "label": label, "kind": kind,
            "canonical": canon,
            "parent": str(raw.get("parent") or "") or None,
            "members": [str(m) for m in (raw.get("members") or [])],
            "source": {"path": rel, "locator": "json:containers/%s" % cid, "kind": "explicit",
                       "quote": unit("containers/%s" % cid, raw)},
        }
        wo["containers"].append(entry)

    declared_ids = set()
    for i, raw in enumerate(obj.get("entities") or []):
        if not isinstance(raw, dict):
            continue
        eid = str(raw.get("id") or raw.get("name") or "").strip()
        label = str(raw.get("label") or raw.get("name") or eid).strip()
        if not eid:
            eid = common.slug(label, fallback="entity_%d" % i)
        if eid in declared_ids:
            warnings.append("workorder entity id %r is duplicated; later entry ignored" % eid)
            continue
        declared_ids.add(eid)
        container = raw.get("container") or raw.get("compartment") or raw.get("location")
        container = str(container).strip() if container not in (None, "") else None
        kind = _workorder_kind(raw.get("kind") or raw.get("type"), label, warnings)
        role = raw.get("membrane_role") or raw.get("membraneRole")
        role = str(role).strip() if role not in (None, "") else None
        if role and role not in mech.MEMBRANE_ROLES:
            warnings.append("workorder membrane_role %r for entity %s is not in the frozen "
                            "enum; kept verbatim" % (role, eid))
        attrs = raw.get("attributes") if isinstance(raw.get("attributes"), dict) else {}
        attrs = dict(attrs)
        if raw.get("modification_site") and "modification_site" not in attrs:
            attrs["modification_site"] = raw["modification_site"]
        if kind == "gene" and "normalized_symbol" not in attrs:
            sym = mech.normalize_symbol(label)
            if sym:
                attrs["normalized_symbol"] = sym
        entry = {
            "id": eid, "label": label, "kind": kind, "container": container,
            "membrane_role": role, "attributes": attrs,
            "source": {"path": rel, "locator": "json:entities/%s" % eid, "kind": "explicit",
                       "quote": _json_fragment(label=label)},
        }
        for key in ("value", "unit", "abundance", "domains"):
            if raw.get(key) not in (None, "", [], {}):
                entry[key] = raw[key]
        unit("entities/%s" % eid, raw)
        wo["entities"].append(entry)

    used_rel = set()
    for i, raw in enumerate(obj.get("relations") or []):
        if not isinstance(raw, dict):
            continue
        frm = str(raw.get("from") or raw.get("source") or raw.get("subject") or "").strip()
        to = str(raw.get("to") or raw.get("target") or raw.get("object") or "").strip()
        rtype = str(raw.get("type") or raw.get("kind") or raw.get("relation") or "").strip()
        if not frm or not to or not rtype:
            warnings.append("workorder relation %d is unusable (from/to/type): skipped, not "
                            "guessed" % i)
            continue
        if rtype not in mech.RELATION_TYPES:
            warnings.append("workorder relation type %r is not in the frozen enum; kept "
                            "verbatim and will be reported by the model gate" % rtype)
        rid = str(raw.get("id") or "").strip() or "%s__%s__%s" % (frm, to, rtype)
        if rid in used_rel:
            rid = "%s_%d" % (rid, i + 1)
        used_rel.add(rid)
        entry = {
            "id": rid, "from": frm, "to": to, "type": rtype,
            "direction": str(raw.get("direction") or _relation_default_direction(rtype)),
            "label": str(raw.get("label") or "").strip(),
            "source": {"path": rel, "locator": "json:relations/%s" % rid, "kind": "explicit",
                       "quote": unit("relations/%s" % rid, raw)},
        }
        if isinstance(raw.get("evidence"), dict):
            entry["evidence"] = dict(raw["evidence"])
        if isinstance(raw.get("crosses"), list):
            entry["crosses"] = [str(c) for c in raw["crosses"]]
        wo["relations"].append(entry)

    # endpoints referenced but not declared: keep them explicit instead of dropping
    # the edge (the workorder is itself a material, so the name is source-bound)
    for rel_entry in wo["relations"]:
        for side in ("from", "to"):
            node = rel_entry[side]
            if node in declared_ids or node in {e["id"] for e in wo["implied_entities"]}:
                continue
            wo["implied_entities"].append({
                "id": node, "label": node,
                "kind": "concept", "container": None, "membrane_role": None,
                "attributes": {}, "implied": True,
                "source": {"path": rel, "locator": rel_entry["source"]["locator"],
                           "kind": "explicit",
                           "quote": _json_fragment(**{side: node})},
            })
    if wo["implied_entities"]:
        warnings.append("workorder lists %d relation endpoint(s) that are not declared as "
                        "entities (%s); they were kept as explicit 'concept' placeholders "
                        "instead of dropping the edges"
                        % (len(wo["implied_entities"]),
                           ", ".join(e["id"] for e in wo["implied_entities"])))
    return wo, units


def _pdf_content_streams(raw):
    """Yield (page_number, decoded_stream) for decodable PDF content streams.

    Conservative: uncompressed and FlateDecode only. LZW / DCT / encrypted content
    is skipped rather than guessed at.
    """
    import bisect
    import zlib
    page_offsets = [m.start() for m in re.finditer(rb"/Type\s*/Page[^s]", raw)]
    for m in re.finditer(rb"stream\r?\n", raw):
        start = m.end()
        end = raw.find(b"endstream", start)
        if end < 0:
            continue
        chunk = raw[start:end].rstrip(b"\r\n")
        # the stream dictionary is the text between the nearest "obj" and "stream";
        # a fixed-size window would pick up the *previous* object's /Filter
        obj_pos = raw.rfind(b"obj", max(0, m.start() - 1200), m.start())
        head = raw[obj_pos:m.start()] if obj_pos > 0 else raw[max(0, m.start() - 400):m.start()]
        if b"FlateDecode" in head:
            try:
                chunk = zlib.decompress(chunk)
            except Exception:  # noqa: BLE001 - not a decodable stream
                continue
        elif b"Filter" in head:
            continue  # unsupported filter: never guess
        if b"BT" not in chunk or (b"Tj" not in chunk and b"TJ" not in chunk):
            continue
        pno = max(1, bisect.bisect_left(page_offsets, m.start()))
        yield pno, chunk


def _pdf_show_text(stream):
    """Extract the shown text of a content stream (``Tj`` / ``TJ`` operands)."""
    out = []
    for m in re.finditer(rb"\((?:\\.|[^\\()])*\)|<[0-9A-Fa-f\s]+>", stream):
        tok = m.group(0)
        if tok.startswith(b"("):
            s = tok[1:-1]
            s = re.sub(rb"\\([()\\])", rb"\1", s)
            s = s.replace(b"\\n", b" ").replace(b"\\r", b" ").replace(b"\\t", b" ")
            s = re.sub(rb"\\[0-7]{1,3}", b"", s)
            out.append(s.decode("latin-1"))
        else:
            hexs = re.sub(rb"\s+", b"", tok[1:-1])
            try:
                data = bytes.fromhex(hexs.decode("ascii"))
            except Exception:  # noqa: BLE001
                continue
            out.append(data.decode("utf-16-be", "ignore") if len(data) % 2 == 0
                       else data.decode("latin-1"))
    return "".join(out)


def _pdf_units_stdlib(path, rel, warnings):
    """Last-resort stdlib PDF text: uncompressed/Flate content streams only."""
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        warnings.append("cannot read pdf %s: %s" % (rel, exc))
        return []
    if b"/Encrypt" in raw:
        warnings.append("pdf %s is encrypted: text not extracted" % rel)
        return []
    units = []
    for pno, stream in _pdf_content_streams(raw):
        text = _pdf_show_text(stream)
        for line in re.split(r"[\r\n]+", text):
            line = re.sub(r"\s{2,}", " ", line).strip()
            if not line:
                continue
            units.append({"id": "", "path": rel, "locator": "p%d" % pno, "kind": "pdf",
                          "text": line, "sha256": common.sha256_text(line),
                          "chars": len(line), "line": len(units) + 1, "page": pno})
    return units


def _pdf_units(path, rel, warnings, extractors):
    """PDF text via pypdf when genuinely available, else a stdlib fallback.

    Whatever cannot be decoded is reported, never fabricated.
    """
    if common.have("pypdf"):
        try:
            from pypdf import PdfReader
            reader = PdfReader(path)
            units = []
            for pno, page in enumerate(reader.pages, start=1):
                text = page.extract_text() or ""
                for line in text.splitlines():
                    if not line.strip():
                        continue
                    units.append({
                        "id": "", "path": rel, "locator": "p%d" % pno, "kind": "pdf",
                        "text": line, "sha256": common.sha256_text(line),
                        "chars": len(line), "line": pno, "page": pno,
                    })
            extractors.append({"name": "pdf_text", "version": str(common.module_version("pypdf")),
                               "applies": "pdf", "status": "ok"})
            return units
        except Exception as exc:  # noqa: BLE001
            warnings.append("pdf text extraction failed for %s: %s" % (rel, exc))

    units = _pdf_units_stdlib(path, rel, warnings)
    if units:
        warnings.append("pdf %s parsed by the stdlib fallback (FlateDecode content streams "
                        "only): verify coverage before citing it" % rel)
        extractors.append({"name": "pdf_text_stdlib", "version": "1.0", "applies": "pdf",
                           "status": "partial",
                           "description": "uncompressed/Flate content streams, Tj/TJ only"})
        return units
    warnings.append("pdf %s skipped: no usable text layer could be decoded "
                    "(pypdf %s, stdlib fallback empty); content not fabricated"
                    % (rel, "available" if common.have("pypdf") else "unavailable"))
    extractors.append({"name": "pdf_text", "version": None, "applies": "pdf",
                       "status": "unavailable"})
    return []


def extract_sources(case_manifest):
    """Build the `source_inventory.json` object from a case manifest."""
    warnings = list(case_manifest.get("warnings") or []) if isinstance(case_manifest, dict) else []
    root = str((case_manifest or {}).get("input_dir") or "")
    units = []
    tables = []
    structured_units = []
    workorders = []
    extractors = [
        {"name": "line_units", "version": "1.0", "applies": "text|metadata", "status": "ok",
         "description": "one unit per non-empty line; locator L<n>"},
        {"name": "delimited_table", "version": "1.0", "applies": "csv|tsv", "status": "ok",
         "description": "header/rows/units/keys; locator table:<column>"},
        {"name": "figure_workorder", "version": "1.0", "applies": "json", "status": "ok",
         "description": ("entities/relations/containers/chart/legend_encoding parsed as an "
                         "authoritative workorder; locator json:<pointer>")},
    ]
    seen_pdf_warn = False

    for entry in (case_manifest or {}).get("files") or []:
        rel = str(entry.get("rel") or "")
        kind = str(entry.get("kind") or "")
        sha = entry.get("sha256")
        path = os.path.join(root, rel.replace("/", os.sep))
        if not os.path.isfile(path):
            warnings.append("declared file missing on disk: %s" % rel)
            continue
        if kind == "table" and os.path.splitext(rel)[1].lower() in (".csv", ".tsv", ".txt"):
            try:
                tables.append(_parse_table(path, rel, sha, warnings))
            except Exception as exc:  # noqa: BLE001
                warnings.append("cannot parse table %s: %s" % (rel, exc))
        elif kind == "table":
            warnings.append("table %s not parsed: only csv/tsv are supported without "
                            "third-party readers; content not fabricated" % rel)
            extractors.append({"name": "xlsx_reader", "version": None,
                               "applies": "xlsx", "status": "unavailable"})
        elif kind in ("text", "metadata"):
            try:
                text = common.read_text(path)
            except Exception as exc:  # noqa: BLE001
                warnings.append("cannot read %s: %s" % (rel, exc))
                continue
            if not text.strip():
                warnings.append("empty text file: %s" % rel)
            units.extend(_units_from_text(text, rel, kind))
            if rel.lower().endswith(".json"):
                wo, s_units = _parse_figure_json(path, rel, sha, warnings)
                if wo is not None:
                    workorders.append(wo)
                    structured_units.extend(s_units)
        elif kind == "pdf":
            units.extend(_pdf_units(path, rel, warnings, extractors))
        elif kind == "office":
            warnings.append("office file %s not parsed: stdlib cannot read docx/pptx; "
                            "content not fabricated" % rel)
        elif kind in ("image", "binary"):
            warnings.append("non-text material listed but not extracted: %s (%s)" % (rel, kind))

    for i, u in enumerate(units, start=1):
        u["id"] = "u_%04d" % i
    for i, u in enumerate(structured_units, start=1):
        u["id"] = "su_%04d" % i
    for i, t in enumerate(tables, start=1):
        t["id"] = "t_%02d" % i
    for i, wo in enumerate(workorders, start=1):
        wo["id"] = "wo_%02d" % i

    if not units and not tables:
        warnings.append("source inventory is empty: no text units and no tables could be "
                        "extracted from the input tree")

    inventory = {
        "schema_version": SCHEMA_VERSION,
        "case_id": (case_manifest or {}).get("case_id", "unknown-case"),
        "input_dir": root,
        "units": units,
        "structured_units": structured_units,
        "workorders": workorders,
        "tables": tables,
        "extractors": extractors,
        "warnings": warnings,
        "stats": {
            "units": len(units),
            "structured_units": len(structured_units),
            "workorders": len(workorders),
            "tables": len(tables),
            "table_rows": sum(len(t.get("rows") or []) for t in tables),
            "chars": sum(u.get("chars") or 0 for u in units),
        },
    }
    return inventory


# --------------------------------------------------------------------------
# build_review_batch()
# --------------------------------------------------------------------------
MAX_SEGMENT_CHARS = 600
MAX_TOTAL_CHARS = 24000


def _clip(text, limit=MAX_SEGMENT_CHARS):
    s = str(text or "")
    if len(s) <= limit:
        return s
    return s[: max(0, limit - 1)] + "…"


def _excerpt_for(path, inventory, limit=MAX_SEGMENT_CHARS):
    """Bounded head-of-file excerpt: consecutive units joined until the budget."""
    chunks = []
    used = 0
    for u in inventory.get("units") or []:
        if str(u.get("path") or "") != str(path):
            continue
        text = str(u.get("text") or "")
        if not text.strip():
            continue
        room = limit - used
        if room <= 0:
            break
        piece = text if len(text) <= room else text[:room]
        chunks.append(piece)
        used += len(piece) + 1
    if chunks:
        return _clip("\n".join(chunks), limit)
    for t in inventory.get("tables") or []:
        if str(t.get("path") or "") == str(path):
            head = " | ".join(str(c) for c in (t.get("columns") or []))
            rows = [" | ".join(str(c) for c in row)
                    for row in (t.get("rows") or [])[:6] if isinstance(row, (list, tuple))]
            return _clip("\n".join([head] + rows), limit)
    return ""


def _draft_view(draft_model):
    draft = draft_model if isinstance(draft_model, dict) else {}
    view = {"entities": [], "relations": [], "containers": [], "legend": []}
    for e in draft.get("entities") or []:
        if isinstance(e, dict):
            view["entities"].append({"id": e.get("id"), "label": e.get("label"),
                                     "kind": e.get("kind"),
                                     "source_kind": (e.get("source") or {}).get("kind")
                                     if isinstance(e.get("source"), dict) else None})
    for r in draft.get("relations") or []:
        if isinstance(r, dict):
            view["relations"].append({"id": r.get("id"), "from": r.get("from"),
                                      "to": r.get("to"), "type": r.get("type"),
                                      "direction": r.get("direction"),
                                      "label": r.get("label")})
    for c in draft.get("containers") or []:
        if isinstance(c, dict):
            view["containers"].append({"id": c.get("id"), "label": c.get("label"),
                                       "members": c.get("members")})
    for lg in draft.get("legend") or []:
        if isinstance(lg, dict):
            view["legend"].append({"id": lg.get("id"), "label": lg.get("label"),
                                   "kind": lg.get("kind"), "color": lg.get("color")})
    return view


def build_review_batch(case_manifest, inventory, draft_model):
    """Single-file hand-off for the Agent: bounded materials + must-decide items."""
    case_manifest = case_manifest if isinstance(case_manifest, dict) else {}
    inventory = inventory if isinstance(inventory, dict) else {}
    draft_model = draft_model if isinstance(draft_model, dict) else {}
    limited = []

    materials = []
    total = 0
    index = SourceIndex(inventory)
    meta_kind = {}
    for f in case_manifest.get("files") or []:
        if isinstance(f, dict):
            meta_kind[str(f.get("rel") or "")] = str(f.get("role") or "")
    unit_paths = sorted(index.paths_with_units(),
                        key=lambda p: (meta_kind.get(p) == "metadata", p))
    for unit_path in unit_paths:
        is_meta = meta_kind.get(unit_path) == "metadata"
        excerpt = _excerpt_for(unit_path, inventory, 240 if is_meta else MAX_SEGMENT_CHARS)
        seg = {"path": unit_path, "kind": "metadata" if is_meta else "text",
               "locator_example": "L1",
               "chars": sum(u.get("chars") or 0
                            for u in inventory.get("units") or []
                            if u.get("path") == unit_path),
               "excerpt": excerpt}
        if is_meta:
            seg["note"] = ("metadata only: the task/case descriptors are NOT scientific "
                           "source text and must not be cited as evidence")
        size = len(excerpt)
        if total + size > MAX_TOTAL_CHARS:
            limited.append(unit_path)
            seg["excerpt"] = ""
            seg["note"] = "omitted: total excerpt budget reached; read the file directly"
        total += size
        materials.append(seg)
    for table in inventory.get("tables") or []:
        seg = {"path": table.get("path"), "kind": "table",
               "locator_example": "table:%s" % ((table.get("columns") or ["col"])[0]),
               "columns": table.get("columns"), "n_rows": table.get("n_rows"),
               "units": table.get("units"), "keys": table.get("keys"),
               "unit_status": table.get("unit_status"),
               "excerpt": _clip(table_text(table))}
        size = len(seg["excerpt"])
        if total + size > MAX_TOTAL_CHARS:
            limited.append(str(table.get("path")))
            seg["excerpt"] = ""
        total += size
        materials.append(seg)

    draft = _draft_view(draft_model)
    workorder_view = []
    for wo in inventory.get("workorders") or []:
        if not isinstance(wo, dict):
            continue
        workorder_view.append({
            "path": wo.get("path"),
            "figure_id": wo.get("figure_id"),
            "figure_kind": wo.get("figure_kind"),
            "orientation": wo.get("orientation"),
            "note": _clip(wo.get("note") or "", 240),
            "containers": [{"id": c.get("id"), "kind": c.get("kind"), "label": c.get("label")}
                           for c in (wo.get("containers") or [])],
            "entities": [{"id": e.get("id"), "label": e.get("label"), "kind": e.get("kind"),
                          "container": e.get("container"),
                          "membrane_role": e.get("membrane_role")}
                         for e in (wo.get("entities") or [])],
            "relations": [{"id": r.get("id"), "from": r.get("from"), "to": r.get("to"),
                           "type": r.get("type"), "direction": r.get("direction"),
                           "label": r.get("label")}
                          for r in (wo.get("relations") or [])],
            "legend_encoding": wo.get("legend_encoding") or [],
            "chart": wo.get("chart"),
        })
    must_decide = []
    seen_q = set()

    def add(qid, question, why, where, options, default):
        if qid in seen_q or len(must_decide) >= 12:
            return
        seen_q.add(qid)
        must_decide.append({"id": qid, "question": question, "why": why, "where": where,
                            "options": options, "suggested_default": default})
    if workorder_view:
        add("Q_workorder", "来源工作单已给出实体/关系/区室清单，逐条核对后绑定到图面。",
            "工作单是材料本身，声明的是应有结构；材料未声明的实体、关系、数值一律不得补造。",
            "materials/*workorder*.json",
            ["逐条采用工作单声明", "对与正文矛盾之处记录 uncertainty"],
            "adopt the workorder structure, keep every source locator json:<pointer>")
    for table in inventory.get("tables") or []:
        status = table.get("unit_status") if isinstance(table.get("unit_status"), dict) else {}
        dimensionless = [c for c, s in status.items() if s == "dimensionless"]
        declared = [c for c, s in status.items()
                    if s == "declared_in_header"]
        if dimensionless:
            add("Q_unit_dimensionless", "无量纲列 %s 按惯例处理为 unit=null（材料未给单位）。"
                % ", ".join(dimensionless),
                "这些列（p 值/倍数变化/计数等）按惯例无量纲；保留 data.units[<列>]=null 与 "
                "data.unit_status[<列>]=\"dimensionless\"，不要补一个单位，也不要当成缺单位。",
                "data.units", ["保留 null + dimensionless", "若材料给出单位则逐字引用"],
                "keep unit=null and unit_status=dimensionless")
        if declared:
            add("Q_unit_from_header", "列 %s 的单位取自列名本身，需在材料中逐字复核。"
                % ", ".join(declared),
                "列名声明了单位（如 time_h -> h）；若材料另有单位说明则以材料为准。",
                "data.units", ["逐字引用材料中的单位", "保留列名单位"],
                "cite the unit verbatim from the material")
    if not draft["entities"]:
        add("Q_entities", "材料中应抽取哪些科学实体（基因/蛋白/过程/处理/样本）？",
            "自动抽取未得到任何实体；必须由 Agent 依据材料确定，禁止凭常识补造。",
            "entities", ["从材料逐条列举", "只保留材料中逐字出现的名称"],
            "decide from materials, then bind each entity to a quote")
    for e in draft["entities"]:
        if e.get("source_kind") != "explicit":
            add("Q_ent_%s" % e.get("id"), "实体 %s(%s) 的来源不足，如何处置？"
                % (e.get("label"), e.get("id")),
                "该实体没有逐字来源；图中出现无来源专名会被溯源门禁拦下。",
                "entities.%s" % e.get("id"),
                ["补一条逐字 quote", "标为 unsupported", "从图中删除"],
                "delete or mark unsupported unless a verbatim quote exists")

    # direction/type ambiguity: units carrying cues from conflicting families
    ambiguity_count = 0
    for unit in inventory.get("units") or []:
        text = str(unit.get("text") or "")
        cues = cues_in_text(text)
        if len([c for c in cues if c in ("activation", "inhibition")]) > 1 and ambiguity_count < 5:
            ambiguity_count += 1
            add("Q_dir_%s" % unit.get("locator"),
                "单元 %s#%s 同时含激活类与抑制类动词，各关系的 type/direction 如何绑定到具体实体对？"
                % (unit.get("path"), unit.get("locator")),
                "同一句里既有激活也有抑制时，机器无法判定每条箭头对应哪个动词，"
                "而方向画反是本题最重的失分形态。",
                "%s#%s" % (unit.get("path"), unit.get("locator")),
                ["逐关系引用只含单一动词的逐字片段", "标为 derived 并列出 derived_from"],
                "quote the minimal verbatim fragment that contains exactly one cue family")

    data = draft_model.get("data") if isinstance(draft_model.get("data"), dict) else None
    if data:
        legend = [l for l in (draft_model.get("legend") or []) if isinstance(l, dict)]
        legend_cats = [l for l in legend if l.get("kind") == "category"]
        cats = [s.get("name") for s in (data.get("series") or []) if isinstance(s, dict)]
        if not legend_cats and cats:
            add("Q_legend", "图例如何与数据分类一一对应？",
                "存在数据系列但草稿图例为空；图例项数必须等于数据分类数。",
                "legend", ["为每个系列建一条 category 图例并给出颜色", "补齐颜色映射"],
                "one legend item per data series, colours identical to series colours")
        series_unit_ok = bool(data.get("series")) and all(
            str(s.get("unit") or "").strip()
            for s in (data.get("series") or []) if isinstance(s, dict))
        cols = [str(c) for c in (data.get("columns") or [])]
        rows = [r for r in (data.get("rows") or []) if isinstance(r, (list, tuple))]
        for idx, col in enumerate(cols):
            vals = [r[idx] for r in rows if idx < len(r)]
            numeric = [v for v in vals if re.fullmatch(r"\s*-?\d+(?:\.\d+)?\s*", str(v))]
            if not numeric:
                continue
            if str((data.get("units") or {}).get(col) or "").strip() or series_unit_ok:
                continue
            add("Q_unit_%s" % col, "数值列 %s 的单位是什么？" % col,
                "数值列必须有显式单位（data.units 或 series.unit），否则 E_UNIT_MISSING。",
                "data.units.%s" % col, ["从材料中找出单位并逐字引用", "标为未知并降级"],
                "locate the unit verbatim in the materials; do not invent one")
        if len(set(cats)) != len(legend_cats) and legend_cats:
            add("Q_legend_count", "图例分类项数为 %d 而数据分类数为 %d，如何对齐？"
                % (len(legend_cats), len(set(cats))),
                "图例 category 项与数据分类数目不一致是 E_LEGEND_DATA_MISMATCH。",
                "legend/data", ["增删图例项以匹配数据", "增删数据系列以匹配图例"],
                "make legend categories exactly equal the data categories")
    kind = ((draft_model.get("figure") or {}).get("kind")
            if isinstance(draft_model.get("figure"), dict) else None)
    if kind not in ("relationship_schematic", "chart", "flowchart", "mixed"):
        add("Q_figure_kind", "本案例应交付哪类图（机制/关系示意图、流程图、数据图或混合）？",
            "图型决定布局与导出预设。", "figure.kind",
            ["relationship_schematic", "chart", "flowchart", "mixed"],
            "relationship_schematic when the materials describe a mechanism")

    # draft self-reported uncertainties come last and are de-duplicated: the structural
    # questions above are higher-value, so they must not be crowded out of the cap
    unc_added = 0
    seen_unc = set()
    for u in draft_model.get("uncertainty") or []:
        if not isinstance(u, dict) or unc_added >= 4:
            break
        issue = str(u.get("issue") or "未决问题")
        key = re.sub(r"\d+", "#", issue)
        if key in seen_unc:
            continue
        seen_unc.add(key)
        unc_added += 1
        add("Q_unc_%d" % unc_added, issue, "草稿自报的不确定项。",
            str(u.get("where") or "uncertainty"),
            [str(u.get("action") or "由 Agent 裁决")], str(u.get("action") or ""))

    tools = {
        "pdf_text": common.have("pypdf"),
        "matplotlib": common.have("matplotlib"),
        "pillow": common.have("PIL"),
        "xlsx": common.have("openpyxl"),
    }

    batch = {
        "schema_version": SCHEMA_VERSION,
        "case_id": case_manifest.get("case_id", "unknown-case"),
        "generated_utc": common.now_utc(),
        "task": _clip(case_manifest.get("task") or case_manifest.get("task_text") or "", 1200),
        "materials": materials,
        "inventory": {
            "files": case_manifest.get("files", []),
            "units": len(inventory.get("units") or []),
            "tables": len(inventory.get("tables") or []),
            "warnings": inventory.get("warnings", []),
        },
        "draft": draft,
        "workorder": workorder_view,
        "must_decide": must_decide,
        "uncertainty": draft_model.get("uncertainty") or [],
        "output_contract": deepcopy(case_manifest.get("output_contract") or {}),
        "required_fields": list(case_manifest.get("required_fields") or []),
        "tools": tools,
        "limits": {"max_segment_chars": MAX_SEGMENT_CHARS, "max_total_chars": MAX_TOTAL_CHARS,
                   "used_chars": total, "truncated_segments": limited},
        "how_to_respond": {
            "step_1": "read figure_model.draft.json",
            "step_2": "answer every item in must_decide using verbatim quotes from materials",
            "step_3": "write the revised model to /app/work/figure_model.json",
            "step_4": "run `run.py render`; fix any error-level issue in figure_issues.json",
            "rules": ["no entity/number/unit may enter the figure without a verbatim source",
                      "suppressed vs activated arrows must match the source verb",
                      "legend categories must equal data categories with matching colours",
                      "gene symbols and protein names must not be interchanged; a "
                      "transmembrane entity must stay in a kind='membrane' container",
                      "closing a loop requires an explicit type='feedback' arc"],
        },
    }
    return batch


# --------------------------------------------------------------------------
# write_artifacts()
# --------------------------------------------------------------------------
def write_artifacts(work_dir, case_manifest, inventory, draft_model, review_batch):
    """Persist the four prepare-stage artifacts; returns {name: absolute path}."""
    work = common.ensure_dir(work_dir)
    paths = {
        "case_manifest": common.write_json(os.path.join(work, "case_manifest.json"), case_manifest),
        "source_inventory": common.write_json(os.path.join(work, "source_inventory.json"), inventory),
        "draft_model": common.write_json(os.path.join(work, "figure_model.draft.json"), draft_model),
        "review_batch": common.write_json(os.path.join(work, "REVIEW_BATCH.json"), review_batch),
    }
    return paths


def _main(argv):
    """Direct smoke entry point: `python ingest.py <input_dir> <work_dir>`.

    The authoritative stage wrapper is ``scripts/run.py``; this only exists so the
    ingest stage can be exercised on its own.
    """
    if len(argv) < 3:
        common.log("usage: ingest.py <input_dir> <work_dir>")
        return common.CONFIG
    input_dir, work_dir = argv[1], argv[2]
    case_manifest = discover(input_dir)
    inventory = extract_sources(case_manifest)
    draft = _draft_for(case_manifest, inventory)
    batch = build_review_batch(case_manifest, inventory, draft)
    paths = write_artifacts(work_dir, case_manifest, inventory, draft, batch)
    common.emit({
        "status": "drafted",
        "case_id": case_manifest.get("case_id"),
        "files": len(case_manifest.get("files") or []),
        "units": len(inventory.get("units") or []),
        "tables": len(inventory.get("tables") or []),
        "warnings": (case_manifest.get("warnings") or []) + (inventory.get("warnings") or []),
        "artifacts": paths,
    })
    return common.OK


def _draft_for(case_manifest, inventory):
    """Late import to avoid a circular import at module load time."""
    import model  # noqa: PLC0415 - intentional lazy import
    return model.draft_model(case_manifest, inventory)


if __name__ == "__main__":
    sys.exit(_main(sys.argv))


__all__ = [
    "VERB_LEXICON", "BIDIRECTIONAL_CUES", "CUE_CLASS_ORDER", "RELATION_TYPES",
    "SCHEMA_VERSION", "SourceIndex", "normalise_text", "strip_decorations",
    "numbers_in_text", "parse_locator", "cues_in_text", "table_text",
    "discover", "extract_sources", "build_review_batch", "write_artifacts",
    "MAX_SEGMENT_CHARS", "MAX_TOTAL_CHARS", "DEFAULT_OUTPUT_CONTRACT_FIELDS",
    "normalise_output_contract", "_parse_figure_json", "mech",
]
