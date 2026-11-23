# -*- coding: utf-8 -*-
"""mech.py - frozen mechanism / pathway semantics (CONTRACT.md section 3).

This module is the *ontology + judgement* layer of the skill.  It owns:

  * the entity / container / relation vocabularies and the frozen style table
    (CONTRACT 3.2 / 3.3 / 3.4), in one place, so the schema, the extractor and
    the validator can never drift apart;
  * gene-vs-protein adjudication (``E_GENE_PROTEIN_CONFUSION``);
  * species-prefix / synonym normalisation;
  * compartment + membrane adjudication (``E_MEMBRANE_PLACEMENT``);
  * flow ranks, directed-cycle detection and direction checking
    (``E_FLOW_DIRECTION``);
  * dimensionless-column and unit-from-header inference used by ``ingest`` /
    ``model`` when a table header carries no explicit unit.

Everything here is pure standard library and side-effect free: the functions
take plain dicts (already-parsed model/inventory objects) and return plain
lists of ``{"code", "message", "where"}`` issue dicts, exactly like
``model.validate_model``.

Design rule (anti-fabrication): every function either *derives* a value from
data already present in the model/inventory, or reports an issue.  None of them
invents a biological fact, a number or a unit.
"""

from __future__ import annotations

import re

ONTOLOGY_VERSION = "1.1"

# --------------------------------------------------------------------------
# 3.1 figure.kind  /  3.2 entities[].kind  /  3.3 containers[].kind
# --------------------------------------------------------------------------
LEGACY_FIGURE_KINDS = ("relationship_schematic", "chart", "flowchart", "mixed")
FIGURE_KINDS = LEGACY_FIGURE_KINDS + ("mechanism_pathway",)

LEGACY_ENTITY_KINDS = ("gene", "protein", "process", "treatment", "sample", "category",
                       "axis", "concept", "compound", "cell", "condition")
MECH_ENTITY_KINDS = ("complex", "organelle", "cell_type", "metabolite",
                     "modification_site", "stimulus", "drug")
ENTITY_KINDS = LEGACY_ENTITY_KINDS + MECH_ENTITY_KINDS

CONTAINER_KINDS = ("compartment", "membrane", "cell", "group")
COMPARTMENTS = ("nucleus", "cytosol", "mitochondrion", "er", "golgi", "lysosome",
                "extracellular", "cytoplasm")

#: canonical spelling + accepted aliases seen in real workorders / papers
COMPARTMENT_ALIASES = {
    "nucleus": "nucleus", "nuclear": "nucleus", "nucleoplasm": "nucleus",
    "nucleus_transcription": "nucleus", "intranuclear": "nucleus",
    "cytosol": "cytosol", "cytosolic": "cytosol", "cytoplasm": "cytoplasm",
    "cytoplasmic": "cytoplasm", "intracellular": "cytoplasm",
    "mitochondrion": "mitochondrion", "mitochondria": "mitochondrion",
    "mitochondrial": "mitochondrion", "mitochondrial_matrix": "mitochondrion",
    "er": "er", "endoplasmic_reticulum": "er", "er_lumen": "er",
    "golgi": "golgi", "golgi_apparatus": "golgi",
    "lysosome": "lysosome", "lysosomal": "lysosome",
    "extracellular": "extracellular", "extracellular_space": "extracellular",
    "extracellular_matrix": "extracellular", "medium": "extracellular",
    "plasma_membrane": "plasma_membrane", "membrane": "plasma_membrane",
    "cell_membrane": "plasma_membrane", "plasmalemma": "plasma_membrane",
    "inner_membrane": "inner_membrane", "outer_membrane": "outer_membrane",
}

#: rough outside -> inside ordering used by the layer check of 3.5
COMPARTMENT_TIER = {
    "extracellular": 0, "plasma_membrane": 0, "outer_membrane": 0,
    "cytoplasm": 1, "cytosol": 1, "mitochondrion": 1, "er": 1, "golgi": 1,
    "lysosome": 1, "inner_membrane": 1,
    "nucleus": 2,
}
TIER_CHAIN = ("extracellular", "membrane", "cytosol", "nucleus")

MEMBRANE_ROLES = ("transmembrane", "membrane_anchored", "luminal", "cytosolic",
                  "extracellular", "na")
MEMBRANE_ON_BAND_ROLES = ("transmembrane", "membrane_anchored")

#: documented relaxations of the literal CONTRACT wording (each is reported to the
#: Lead in the hand-off; they exist because real workorders use these shapes):
#:   * membrane_anchored: a peripheral/anchored protein (RAS-GTP) is legitimately
#:     drawn in the *cytosolic* compartment while touching the membrane band.
#:   * binding across a membrane: ligand (extracellular) - receptor (membrane) is
#:     the canonical binding pair; it is not a same-compartment binding.
#:   * self-edge: EGFR autophosphorylation (from == to) carries no rank change.
POLICIES = {
    "membrane_anchored_container": "membrane_or_adjacent_compartment",
    "binding_compartment": "membrane_adjacent_allowed",
    "self_edge_rank": "exempt",
    "transcription_origin": "nucleus_or_declared_crossing",
}

# --------------------------------------------------------------------------
# 3.4 relations[].type - frozen style table
# --------------------------------------------------------------------------
LEGACY_RELATION_TYPES = ("activation", "inhibition", "containment", "sequence",
                         "causation", "association", "membership")
MECH_RELATION_TYPES = ("binding", "modification", "transport", "transcription",
                       "translation", "feedback")
RELATION_TYPES = LEGACY_RELATION_TYPES + MECH_RELATION_TYPES

#: type -> {"arrow", "stroke"}  (CONTRACT 3.4; style may not be improvised)
RELATION_STYLE = {
    "activation": {"arrow": "normal", "stroke": "solid"},
    "inhibition": {"arrow": "tee", "stroke": "solid"},
    "binding": {"arrow": "none", "stroke": "solid"},
    "modification": {"arrow": "normal", "stroke": "dashed"},
    "transport": {"arrow": "normal", "stroke": "solid"},
    "transcription": {"arrow": "normal", "stroke": "solid"},
    "translation": {"arrow": "normal", "stroke": "solid"},
    "feedback": {"arrow": "normal", "stroke": "dashed"},
    "association": {"arrow": "none", "stroke": "dotted"},
    "containment": {"arrow": "none", "stroke": "dotted"},
    "membership": {"arrow": "none", "stroke": "dotted"},
    "sequence": {"arrow": "normal", "stroke": "solid"},
    "causation": {"arrow": "normal", "stroke": "solid"},
}

#: the legend entry CONTRACT 3.4 requires once a type appears on the figure
RELATION_LEGEND_LABEL = {
    "activation": "箭头=激活",
    "inhibition": "平头(⊥)=抑制",
    "binding": "无箭头实线=结合",
    "modification": "虚线箭头=修饰",
    "transport": "跨边界箭头=转运",
    "transcription": "箭头=转录激活",
    "translation": "箭头=翻译",
    "feedback": "虚线=反馈",
    "association": "点线=关联（无方向）",
    "containment": "虚线框=区室",
    "membership": "虚线框=区室",
    "sequence": "箭头=顺序/因果",
    "causation": "箭头=顺序/因果",
}

#: types whose arrow implies an order (rank must increase), and the two that
#: carry no direction at all
DIRECTIONAL_RELATION_TYPES = ("activation", "inhibition", "sequence", "causation",
                              "modification", "transport", "transcription",
                              "translation")
UNDIRECTED_RELATION_TYPES = ("binding", "association")
STRUCTURAL_RELATION_TYPES = ("containment", "membership")
#: excluded from rank derivation / cycle detection (a feedback arc is the licence
#: to close a loop; see CONTRACT 3.5)
FEEDBACK_RELATION_TYPES = ("feedback",)

#: notation colour per family (stable, deterministic; visual only)
RELATION_COLOR = {
    "activation": "#0072B2", "sequence": "#0072B2", "causation": "#0072B2",
    "inhibition": "#D55E00", "modification": "#D55E00", "feedback": "#D55E00",
    "binding": "#009E73", "transport": "#009E73", "translation": "#009E73",
    "transcription": "#CC79A7", "association": "#56B4E9",
    "containment": "#8C97A3", "membership": "#8C97A3",
}

#: CONTRACT 3.6 frozen line-width mapping for evidence strength
EVIDENCE_WIDTH_PT = {"high": 1.4, "medium": 1.0, "low": 0.6}
EVIDENCE_STRENGTHS = ("high", "medium", "low")
EVIDENCE_KINDS = ("direct", "indirect", "inferred")

#: cues that satisfy "modification label must name the modification kind"
MODIFICATION_CUES = ("phosphorylation", "phosphorylated", "phospho", "dephosphorylation",
                     "ubiquitination", "ubiquitylation", "acetylation", "deacetylation",
                     "methylation", "demethylation", "glycosylation", "sumoylation",
                     "hydroxylation", "nitrosylation", "palmitoylation", "prenylation",
                     "磷酸化", "去磷酸化", "泛素化", "乙酰化", "去乙酰化", "甲基化",
                     "糖基化", "sumo化", "羟基化", "硝基化", "棕榈酰化")

#: cues that name a transport event (kept here for the extractor)
TRANSPORT_CUES = ("transport", "translocat", "import", "export", "secret", "efflux",
                  "influx", "shuttle", "转运", "转位", "入核", "出核", "分泌", "内吞")
TRANSCRIPTION_CUES = ("transcription", "transcribes", "promoter", "mrna", "转录")
TRANSLATION_CUES = ("translation", "translates", "protein synthesis", "翻译")
BINDING_CUES = ("binds", "binding", "bound", "docks", "associates with", "结合", "互作")
FEEDBACK_CUES = ("feedback", "feedback loop", "负反馈", "正反馈", "反馈")


def relation_style(rtype):
    """Frozen ``{"arrow", "stroke"}`` for a relation type (or None if unknown)."""
    st = RELATION_STYLE.get(str(rtype))
    return dict(st) if st else None


def relation_color(rtype):
    return RELATION_COLOR.get(str(rtype), "#333333")


# --------------------------------------------------------------------------
# species prefix / synonym normalisation (CONTRACT 3.2)
# --------------------------------------------------------------------------
_SPECIES_PREFIXES = ("human", "homo sapiens", "mouse", "mus musculus", "rat",
                     "rattus norvegicus", "horse", "bovine", "zebrafish")
_SPECIES_ABBREV = ("hs", "hs.", "h", "mm", "mm.", "m", "rn", "r", "dr")
_PROTEIN_SUFFIX_RE = re.compile(r"(?:\s*\(?\s*(?:his|flag|ha|gfp|myc|v5|gst)\s*tag\s*\)?)$",
                                re.I)
_MODIFICATION_DECOR_RE = re.compile(
    r"(?:\(\s*(?:[a-z]{1,3}\d{1,4}(?:-[a-z]{1,2})?|[a-z]{1,3}\d{1,4}\s*-\s*p|p[a-z]{1,3}\d{1,4})"
    r"\s*\)"                                   # (Ser293-P) / (pTyr1068) / (S293)
    r"|[-\s]p(?:ser|thr|tyr)\d{0,4}\b"         # p-Ser293 / pSer
    r"|\bser\d{1,4}\s*-\s*p\b"                 # Ser293-P
    r"|\(\s*phospho\s*\)|\bphospho-|\bp-tyr|\bp-ser"
    r"|\b[a-z]+\d{1,4}\s*-\s*p\b"              # Tyr1068-P
    r")", re.I)
_PROTEIN_WORD_RE = re.compile(r"(?:^|[\s\-_])protein(?:$|[\s\-_])", re.I)
_RNA_WORD_RE = re.compile(r"(?:^|[\s\-_])(?:mrna|messenger rna|transcript|转录本)(?:$|[\s\-_])",
                          re.I)


def strip_species_prefix(label):
    """Return ``(prefix, core)``; prefix is '' when the label carries none.

    ``human HIF1A`` / ``Hs. HIF1A`` / ``mouse Nqo1`` are all split so that the
    synonym table can keep the prefix while the symbol stays comparable.
    """
    s = str(label or "").strip()
    low = s.lower()
    for pre in sorted(_SPECIES_PREFIXES, key=len, reverse=True):
        for sep in (" ", ":", "-", "_"):
            if low.startswith(pre + sep):
                return (s[:len(pre)], s[len(pre) + 1:].strip())
    m = re.match(r"^([A-Za-z]{1,3})\.?\s+(\S.*)$", s)
    if m and m.group(1).lower() in _SPECIES_ABBREV:
        return (m.group(1), m.group(2).strip())
    return ("", s)


def modification_decoration(label):
    """The protein-modification decoration inside a label, or None."""
    m = _MODIFICATION_DECOR_RE.search(str(label or ""))
    return m.group(0).strip() if m else None


def looks_like_transcript(label):
    return bool(_RNA_WORD_RE.search(str(label or "")))


def looks_like_protein_name(label):
    """Conservative positive signal that a label names a protein, not a gene."""
    s = str(label or "")
    if modification_decoration(s) or _PROTEIN_WORD_RE.search(s):
        return True
    if re.search(r"[-–](?:alpha|beta|gamma|delta|epsilon)\b", s, re.I):
        return True
    if _PROTEIN_SUFFIX_RE.search(s):
        return True
    return False


def gene_protein_confusion(ent):
    """Return an issue message when one entity confuses a gene with a protein.

    Only the *asserted* kind is adjudicated against the label; a bare symbol is
    never guessed at here (the extractor reports that separately).
    """
    if not isinstance(ent, dict):
        return None
    kind = str(ent.get("kind") or "")
    label = str(ent.get("label") or "")
    dec = modification_decoration(label)
    if kind == "gene":
        if dec:
            return ("kind=gene but the label carries the protein modification "
                    "decoration %r: a gene/protein decision is required" % dec)
        if _PROTEIN_WORD_RE.search(label):
            return ("kind=gene but the label names a protein (%r): write the gene "
                    "symbol, or change kind to 'protein'" % label)
        if _PROTEIN_SUFFIX_RE.search(label):
            return ("kind=gene but the label carries a protein tag (%r)" % label)
    if kind == "protein" and looks_like_transcript(label):
        return ("kind=protein but the label names a transcript (%r): it is an mRNA "
                "species, not a protein" % label)
    return None


def check_gene_protein(entities):
    """``E_GENE_PROTEIN_CONFUSION`` for entities[] (CONTRACT 3.2)."""
    issues = []
    by_symbol = {}
    for i, ent in enumerate(entities or []):
        if not isinstance(ent, dict):
            continue
        eid = ent.get("id") or ("entities[%d]" % i)
        where = "entities.%s" % eid
        msg = gene_protein_confusion(ent)
        if msg:
            issues.append({"code": "E_GENE_PROTEIN_CONFUSION", "message": msg, "where": where})
        sym = normalized_symbol(ent)
        if not sym:
            continue
        by_symbol.setdefault(sym, []).append(ent)
    # the same symbol may be both a gene and a protein, but the two labels must
    # be tellable apart and both must be source-bound (CONTRACT 3.2 last bullet)
    for sym, group in sorted(by_symbol.items()):
        kinds = {str(e.get("kind") or "") for e in group}
        if len(kinds) < 2:
            continue
        labels = [normalise_key(e.get("label")) for e in group]
        if len(set(labels)) != len(labels) or len(set(labels)) == 1:
            issues.append({
                "code": "E_GENE_PROTEIN_CONFUSION",
                "message": ("symbol %r is carried by both a gene and a protein but the "
                            "labels are not distinguishable (%s): a reader cannot tell "
                            "which node is which"
                            % (sym, ", ".join(sorted(str(e.get("label")) for e in group)))),
                "where": "entities.%s" % (group[0].get("id") or sym)})
    return issues


def normalized_symbol(ent):
    """Stable symbol key for an entity: explicit attribute, else derived label."""
    if not isinstance(ent, dict):
        return ""
    attrs = ent.get("attributes") if isinstance(ent.get("attributes"), dict) else {}
    sym = attrs.get("normalized_symbol") or attrs.get("gene_symbol") or attrs.get("symbol")
    if sym:
        return normalise_key(sym)
    label = str(ent.get("label") or "")
    dec = modification_decoration(label)
    if dec:
        label = label.replace(dec, " ")
    label = _PROTEIN_WORD_RE.sub(" ", label)
    label = _RNA_WORD_RE.sub(" ", label)
    _, core = strip_species_prefix(label)
    stem = re.split(r"[\s(（\[,，;；]", core.strip())[0]
    return normalise_key(stem)


def normalize_symbol(label):
    """Public helper: species prefix stripped, decoration removed, key normalised."""
    return normalized_symbol({"label": label})


def synonyms_of(ent):
    """Declared synonyms + species prefix, as a deduplicated list."""
    out = []
    if not isinstance(ent, dict):
        return out
    attrs = ent.get("attributes") if isinstance(ent.get("attributes"), dict) else {}
    for item in attrs.get("synonyms") or []:
        if str(item).strip():
            out.append(str(item).strip())
    prefix, _ = strip_species_prefix(str(ent.get("label") or ""))
    if prefix:
        out.append(prefix)
    return list(dict.fromkeys(out))


def normalise_key(text):
    """Comparison key: casefolded, punctuation/space insensitive."""
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(text or "").casefold())


# --------------------------------------------------------------------------
# containers / membranes (CONTRACT 3.3)
# --------------------------------------------------------------------------
def canonical_container(value):
    """Canonical container spelling for a workorder-supplied name."""
    key = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return COMPARTMENT_ALIASES.get(key, key)


def container_kind(container_id, containers):
    for con in containers or []:
        if isinstance(con, dict) and str(con.get("id") or "") == str(container_id or ""):
            return str(con.get("kind") or "")
    return ""


def compartment_of(container_id, containers):
    """Compartment *name* of a container (id -> record -> compartment name).

    ``canonical_container`` expects a compartment name, but a workorder may use
    container ids such as ``c_nucleus`` / ``mem_plasma``.  The resolution
    therefore goes through the container record first (its explicit
    ``compartment`` / ``canonical`` field, then its label) and only falls back to
    the id spelling.  Passing a raw id to ``canonical_container`` made a nuclear
    entity look non-nuclear (false ``W_TRANSCRIPTION_ORIGIN``) and an anchored
    protein look unanchored (false ``E_MEMBRANE_PLACEMENT``).
    """
    cid = str(container_id or "")
    for con in containers or []:
        if not isinstance(con, dict) or str(con.get("id") or "") != cid:
            continue
        for key in ("compartment", "canonical"):
            value = con.get(key)
            if isinstance(value, str) and value.strip():
                return canonical_container(value)
        label = con.get("label")
        if isinstance(label, str) and label.strip():
            mapped = COMPARTMENT_ALIASES.get(
                label.strip().lower().replace("-", "_").replace(" ", "_"))
            if mapped:
                return mapped
        if str(con.get("kind") or "") == "membrane":
            return "plasma_membrane"
        if str(con.get("kind") or "") == "cell":
            return "cell"
        break
    return canonical_container(cid)


def container_tier(container_id, containers):
    """Outside->inside tier of a container (membrane bands share the outer tier)."""
    kind = container_kind(container_id, containers)
    if kind == "membrane":
        return 0
    if kind == "cell":
        return 0
    return COMPARTMENT_TIER.get(compartment_of(container_id, containers), 1)


def is_membrane_container(container_id, containers):
    return container_kind(container_id, containers) == "membrane"


def check_membrane_placement(entities, containers):
    """``E_MEMBRANE_PLACEMENT`` (CONTRACT 3.3).

    ``transmembrane`` must live in a ``kind=="membrane"`` container; a
    ``membrane_anchored`` entity may additionally sit in the adjacent cytosolic
    compartment (documented policy, see ``POLICIES``).
    """
    issues = []
    membrane_ids = {str(c.get("id")) for c in (containers or [])
                    if isinstance(c, dict) and str(c.get("kind")) == "membrane"}
    for i, ent in enumerate(entities or []):
        if not isinstance(ent, dict):
            continue
        where = "entities.%s" % (ent.get("id") or i)
        role = ent.get("membrane_role")
        if role in (None, ""):
            if ent.get("container") in membrane_ids and ent.get("container"):
                issues.append({
                    "code": "W_MEMBRANE_ROLE_MISSING",
                    "level": "warning",
                    "message": ("entity sits in the membrane container %r but declares no "
                                "membrane_role; a reader cannot tell a transmembrane "
                                "receptor from a peripheral protein"
                                % ent.get("container")),
                    "where": where})
            continue
        if role not in MEMBRANE_ROLES:
            issues.append({
                "code": "E_MEMBRANE_PLACEMENT",
                "message": ("membrane_role %r is not in the frozen enum %s"
                            % (role, list(MEMBRANE_ROLES))),
                "where": where})
            continue
        cid = ent.get("container")
        kind = container_kind(cid, containers)
        if role == "transmembrane":
            if kind != "membrane":
                issues.append({
                    "code": "E_MEMBRANE_PLACEMENT",
                    "message": ("membrane_role=transmembrane requires a kind='membrane' "
                                "container; entity is in %r (kind=%r). A transmembrane "
                                "receptor drawn inside a compartment is a wrong "
                                "mechanism statement" % (cid, kind or "none")),
                    "where": where})
        elif role == "membrane_anchored":
            allowed = kind == "membrane" or compartment_of(cid, containers) in (
                "cytosol", "cytoplasm", "plasma_membrane", "extracellular")
            if not allowed:
                issues.append({
                    "code": "E_MEMBRANE_PLACEMENT",
                    "message": ("membrane_role=membrane_anchored requires the membrane "
                                "band or an adjacent compartment; entity is in %r "
                                "(kind=%r)" % (cid, kind or "none")),
                    "where": where})
        elif role in ("luminal", "cytosolic", "extracellular"):
            if kind == "membrane":
                issues.append({
                    "code": "W_MEMBRANE_ROLE_CONTAINER",
                    "level": "warning",
                    "message": ("membrane_role=%r means the entity is on one side of the "
                                "bilayer, but its container %r is the membrane band "
                                "itself" % (role, cid)),
                    "where": where})
    return issues


# --------------------------------------------------------------------------
# flow ranks / direction / cycles (CONTRACT 3.5)
# --------------------------------------------------------------------------
def rank_edges(relations):
    """Non-feedback, non-structural, directed edges used for ranks."""
    out = []
    for rel in relations or []:
        if not isinstance(rel, dict):
            continue
        rtype = str(rel.get("type") or "")
        frm, to = rel.get("from"), rel.get("to")
        if not frm or not to or frm == to:
            continue                      # self-edge: no rank change (policy)
        if rtype in FEEDBACK_RELATION_TYPES or rtype in UNDIRECTED_RELATION_TYPES \
                or rtype in STRUCTURAL_RELATION_TYPES:
            continue
        if str(rel.get("direction") or "forward") == "none":
            continue
        out.append((str(rel.get("id") or ""), str(frm), str(to)))
    return out


def derive_ranks(entity_ids, relations, containers=None):
    """Longest-path ranks over the non-feedback edges; deterministic.

    Ranks are a *derived* topological order, not a biological claim: the tiers of
    the compartments only break ties so that extracellular stays above cytosol
    when the model declares no edge between two nodes.
    """
    ids = [str(e) for e in (entity_ids or [])]
    idset = set(ids)
    adj = dict((i, []) for i in ids)
    indeg = dict((i, 0) for i in ids)
    for _rid, a, b in rank_edges(relations):
        if a not in idset or b not in idset or b in adj[a]:
            continue
        adj[a].append(b)
        indeg[b] += 1
    for i in ids:
        adj[i] = sorted(set(adj[i]))
    rank = {}
    queue = sorted(i for i in ids if indeg[i] == 0)
    seen = set()
    # Kahn; if a cycle survives the feedback exclusion it is reported separately,
    # and the nodes on it still need a deterministic rank.
    while queue:
        nxt = []
        for u in queue:
            if u in seen:
                continue
            seen.add(u)
            base = rank.get(u, 0)
            for v in adj[u]:
                rank[v] = max(rank.get(v, 0), base + 1)
                indeg[v] -= 1
                if indeg[v] <= 0:
                    nxt.append(v)
        queue = sorted(set(nxt))
    for i in ids:
        if i not in rank:
            rank[i] = 0
    return rank


def directed_cycles(relations, entity_ids=None, limit=8):
    """Cycles made only of non-feedback edges, each as an ordered id path."""
    ids = [str(e) for e in (entity_ids or [])]
    idset = set(ids) if ids else None
    adj = {}
    for _rid, a, b in rank_edges(relations):
        if idset is not None and (a not in idset or b not in idset):
            continue
        adj.setdefault(a, [])
        if b not in adj[a]:
            adj[a].append(b)
    for k in adj:
        adj[k] = sorted(adj[k])
    found = []
    seen_shapes = set()

    def walk(node, stack):
        if len(found) >= limit:
            return
        for nxt in adj.get(node, []):
            if nxt in stack:
                path = stack[stack.index(nxt):] + [nxt]
                shape = tuple(sorted(set(path)))
                if shape not in seen_shapes:
                    seen_shapes.add(shape)
                    found.append(path)
                continue
            if len(stack) > 64:
                continue
            walk(nxt, stack + [nxt])

    for node in sorted(adj):
        walk(node, [node])
        if len(found) >= limit:
            break
    return found


def check_flow_direction(entities, relations, ranks=None, containers=None):
    """``E_FLOW_DIRECTION`` (CONTRACT 3.5).

    Three frozen judgements:
      1. every non-feedback directed edge must raise the rank
         (same rank tolerated only for binding / association);
      2. a directed cycle among non-feedback edges must not exist - closing a loop
         requires labelling the arc ``feedback``;
      3. the receptor->cytosol->nucleus layering must be monotone.
    """
    issues = []
    ents = [e for e in (entities or []) if isinstance(e, dict)]
    ids = [str(e.get("id")) for e in ents if e.get("id")]
    ranks = ranks if isinstance(ranks, dict) else derive_ranks(ids, relations, containers)
    ranks = dict((str(k), v) for k, v in ranks.items())

    for rel in relations or []:
        if not isinstance(rel, dict):
            continue
        rtype = str(rel.get("type") or "")
        frm, to = str(rel.get("from") or ""), str(rel.get("to") or "")
        where = "relations.%s" % (rel.get("id") or "%s->%s" % (frm, to))
        if rtype in FEEDBACK_RELATION_TYPES:
            # CONTRACT 3.4: a feedback arc participates in a loop, so it must point
            # backwards (from a rank that is at least as deep as its target)
            if frm and to and frm != to and frm in ranks and to in ranks \
                    and ranks[frm] < ranks[to]:
                issues.append({
                    "code": "E_FLOW_DIRECTION",
                    "message": ("feedback arc %s->%s runs forward (rank %s < %s): a feedback "
                                "edge must close a loop, i.e. point from the downstream "
                                "back to the upstream node" % (frm, to, ranks[frm], ranks[to])),
                    "where": where})
            continue
        if rtype in STRUCTURAL_RELATION_TYPES:
            continue
        if rtype in UNDIRECTED_RELATION_TYPES:
            continue                   # no order to check (policy: same rank allowed)
        if not frm or not to or frm == to:
            continue                   # self-edge exempt (policy)
        if str(rel.get("direction") or "forward") == "none":
            continue
        if frm not in ranks or to not in ranks:
            continue
        if ranks[to] <= ranks[frm]:
            issues.append({
                "code": "E_FLOW_DIRECTION",
                "message": ("edge %s->%s (%s) does not advance the flow: rank[%s]=%s <= "
                            "rank[%s]=%s. Upstream/downstream is reversed or flat; if the "
                            "arc is a loop closure mark it type='feedback'"
                            % (frm, to, rtype or "?", to, ranks[to], frm, ranks[frm])),
                "where": where})

    for cycle in directed_cycles(relations, ids):
        issues.append({
            "code": "E_FLOW_DIRECTION",
            "message": ("directed cycle %s built from non-feedback edges: a loop must be "
                        "expressed as an explicit type='feedback' arc, otherwise the "
                        "layout has no defined direction" % " -> ".join(cycle)),
            "where": "relations.%s" % cycle[0]})

    # layer chain: extracellular -> membrane -> cytosol -> nucleus must be monotone
    # (only where the model actually asserts a directed path between two layers;
    # a ligand that binds a receptor is not a layered direction)
    adj = {}
    for _rid, a, b in rank_edges(relations):
        adj.setdefault(a, set()).add(b)

    def reachable(start):
        seen, stack = set(), [start]
        while stack:
            node = stack.pop()
            for nxt in adj.get(node, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return seen

    reps = {}
    for ent in ents:
        cid = ent.get("container")
        key = "membrane" if is_membrane_container(cid, containers) \
            else compartment_of(cid, containers)
        if key in TIER_CHAIN and key not in reps:
            reps[key] = str(ent.get("id") or "")
    order = [k for k in TIER_CHAIN if k in reps]
    for a, b in zip(order, order[1:]):
        ra, rb = ranks.get(reps[a]), ranks.get(reps[b])
        if ra is None or rb is None:
            continue
        if reps[b] not in reachable(reps[a]):
            continue              # no asserted upstream/downstream relation between them
        if rb <= ra:
            issues.append({
                "code": "E_FLOW_DIRECTION",
                "message": ("compartment layer %s(%s) must sit below %s(%s) but rank is "
                            "%s >= %s: the receptor->cytosol->nucleus hierarchy is "
                            "inverted" % (a, reps[a], b, reps[b], rb, ra)),
                "where": "entities.%s" % reps[b]})
    return issues


# --------------------------------------------------------------------------
# 3.4 style / legend-entry gate
# --------------------------------------------------------------------------
def check_relation_styles(relations, legend=None):
    """``E_INTERACTION_STYLE_MISMATCH`` (CONTRACT 3.4).

    The rendered ``(arrow, stroke)`` must equal the frozen table, and every type
    that appears on the figure must have its required legend entry.
    """
    issues = []
    types_present = []
    for rel in relations or []:
        if not isinstance(rel, dict):
            continue
        rtype = str(rel.get("type") or "")
        where = "relations.%s" % (rel.get("id") or generate_relation_id(rel))
        if rtype not in RELATION_STYLE:
            continue
        types_present.append(rtype)
        style = rel.get("style") if isinstance(rel.get("style"), dict) else {}
        want = RELATION_STYLE[rtype]
        for key in ("arrow", "stroke"):
            got = style.get(key)
            if got is None:
                continue
            if str(got) != want[key]:
                issues.append({
                    "code": "E_INTERACTION_STYLE_MISMATCH",
                    "message": ("relation type %r must be drawn %s=%r, got %r (frozen "
                                "style table, CONTRACT 3.4)" % (rtype, key, want[key], got)),
                    "where": where})
    needed = {t for t in types_present if t not in STRUCTURAL_RELATION_TYPES}
    if needed and legend:
        have = set()
        for item in legend:
            if not isinstance(item, dict):
                continue
            val = str(item.get("value") or "").casefold()
            label = str(item.get("label") or "")
            for t in needed:
                want_label = RELATION_LEGEND_LABEL.get(t, "")
                if val == t.casefold() or (want_label and want_label in label):
                    have.add(t)
        for t in sorted(needed - have):
            issues.append({
                "code": "E_INTERACTION_STYLE_MISMATCH",
                "message": ("relation type %r is drawn on the figure but the legend has "
                            "no entry for it (required: %r)"
                            % (t, RELATION_LEGEND_LABEL.get(t, t))),
                "where": "legend"})
    return issues


def generate_relation_id(rel):
    return "%s_%s_%s" % (rel.get("from"), rel.get("to"), rel.get("type"))


def required_legend_types(relations):
    """Relation types present on the figure that need a legend entry."""
    out = []
    for rel in relations or []:
        if isinstance(rel, dict):
            t = str(rel.get("type") or "")
            if t in RELATION_STYLE and t not in STRUCTURAL_RELATION_TYPES and t not in out:
                out.append(t)
    return out


def check_compartment_match(entities, relations, containers):
    """``E_COMPARTMENT_MISMATCH`` for ``binding`` (CONTRACT 3.4)."""
    issues = []
    by_id = {}
    for ent in entities or []:
        if isinstance(ent, dict) and ent.get("id"):
            by_id[str(ent["id"])] = ent
    for rel in relations or []:
        if not isinstance(rel, dict) or str(rel.get("type") or "") != "binding":
            continue
        a, b = by_id.get(str(rel.get("from") or "")), by_id.get(str(rel.get("to") or ""))
        if a is None or b is None:
            continue
        ca, cb = a.get("container"), b.get("container")
        if ca == cb or ca is None or cb is None:
            continue
        # a membrane-resident partner is adjacent to both the outer and the inner
        # side, so ligand-receptor binding across the bilayer is legitimate
        if is_membrane_container(ca, containers) or is_membrane_container(cb, containers):
            continue
        issues.append({
            "code": "E_COMPARTMENT_MISMATCH",
            "message": ("binding %s<->%s joins two different compartments (%s vs %s): a "
                        "physical binding needs both partners in the same compartment; "
                        "use type='transport' if the complex moves"
                        % (rel.get("from"), rel.get("to"), ca, cb)),
            "where": "relations.%s" % (rel.get("id") or generate_relation_id(rel))})
    return issues


def modification_kind_in(label):
    """True when a modification label names the modification species."""
    low = str(label or "").casefold()
    if not low.strip():
        return False
    return any(cue.casefold() in low for cue in MODIFICATION_CUES)


def check_relation_constraints(entities, relations, containers):
    """Remaining frozen 3.4 constraints (transcription / translation / transport)."""
    issues = []
    by_id = {}
    for ent in entities or []:
        if isinstance(ent, dict) and ent.get("id"):
            by_id[str(ent["id"])] = ent
    for rel in relations or []:
        if not isinstance(rel, dict):
            continue
        rtype = str(rel.get("type") or "")
        where = "relations.%s" % (rel.get("id") or generate_relation_id(rel))
        a, b = by_id.get(str(rel.get("from") or "")), by_id.get(str(rel.get("to") or ""))
        if rtype == "modification":
            if not modification_kind_in(rel.get("label")):
                issues.append({
                    "code": "E_MODIFICATION_UNNAMED",
                    "message": ("a modification edge must name the modification kind in "
                                "its label (phosphorylation / ubiquitination / ...); got "
                                "%r" % (rel.get("label") or "")),
                    "where": where})
        elif rtype == "translation":
            if a is not None and str(a.get("kind")) != "gene":
                issues.append({"code": "E_TYPE_CONSTRAINT_VIOLATION",
                               "message": "translation must start at a kind='gene' node",
                               "where": where})
            if b is not None and str(b.get("kind")) != "protein":
                issues.append({"code": "E_TYPE_CONSTRAINT_VIOLATION",
                               "message": "translation must end at a kind='protein' node",
                               "where": where})
        elif rtype == "transcription":
            if b is not None and str(b.get("kind")) not in ("gene", "concept"):
                issues.append({"code": "E_TYPE_CONSTRAINT_VIOLATION",
                               "message": ("transcription must end at a kind='gene' node, "
                                           "got %r" % b.get("kind")), "where": where})
            if a is not None and str(a.get("kind")) not in ("protein", "complex",
                                                            "transcription_factor",
                                                            "concept"):
                issues.append({"code": "E_TYPE_CONSTRAINT_VIOLATION",
                               "message": ("transcription must start at a transcription "
                                           "factor / protein, got %r" % a.get("kind")),
                               "where": where})
            if a is not None:
                a_in_nucleus = (compartment_of(a.get("container"), containers) == "nucleus")
                crosses = [compartment_of(c, containers)
                           for c in (rel.get("crosses") or [])]
                if not a_in_nucleus and "nucleus" not in crosses:
                    issues.append({
                        "code": "W_TRANSCRIPTION_ORIGIN",
                        "level": "warning",
                        "message": ("transcription factor %s is drawn in %r (not the nucleus) "
                                    "and the edge declares no crossing: a reader cannot tell "
                                    "whether the factor is nuclear"
                                    % (rel.get("from"), a.get("container"))),
                        "where": where})
        elif rtype == "transport":
            crosses = rel.get("crosses")
            same_container = (a is not None and b is not None
                              and a.get("container") == b.get("container"))
            if same_container:
                issues.append({"code": "E_TYPE_CONSTRAINT_VIOLATION",
                               "message": ("transport must cross at least one container "
                                           "boundary but both endpoints are in %r"
                                           % a.get("container")),
                               "where": where})
            elif not (isinstance(crosses, list) and len(crosses) >= 2):
                issues.append({
                    "code": "W_TRANSPORT_CROSSES_MISSING",
                    "level": "warning",
                    "message": ("transport does not declare crosses:[fromContainer,"
                                "toContainer]; the boundary is only implied by the two "
                                "endpoint containers (%s -> %s)"
                                % (a.get("container") if a else "?",
                                   b.get("container") if b else "?")),
                    "where": where})
    return issues


# --------------------------------------------------------------------------
# 3.6 evidence / abundance / legend encoding
# --------------------------------------------------------------------------
def evidence_width(rel):
    """Frozen line width for a relation's evidence strength (or None)."""
    ev = rel.get("evidence") if isinstance(rel, dict) and isinstance(rel.get("evidence"), dict) \
        else None
    if not ev:
        return None
    strength = str(ev.get("strength") or "")
    return EVIDENCE_WIDTH_PT.get(strength)


def check_evidence(relations):
    issues = []
    for rel in relations or []:
        if not isinstance(rel, dict):
            continue
        ev = rel.get("evidence")
        if ev is None:
            continue
        where = "relations.%s.evidence" % (rel.get("id") or generate_relation_id(rel))
        if not isinstance(ev, dict):
            issues.append({"code": "E_CONTRACT_KEY_MISSING",
                           "message": "evidence must be an object", "where": where})
            continue
        if str(ev.get("strength") or "") not in EVIDENCE_STRENGTHS:
            issues.append({"code": "E_CONTRACT_KEY_MISSING",
                           "message": "evidence.strength must be one of %s"
                                      % list(EVIDENCE_STRENGTHS), "where": where})
        if str(ev.get("kind") or "") not in EVIDENCE_KINDS:
            issues.append({"code": "E_CONTRACT_KEY_MISSING",
                           "message": "evidence.kind must be one of %s"
                                      % list(EVIDENCE_KINDS), "where": where})
    return issues


def generate_legend_encoding(model):
    """Derive ``legend[].encoding`` entries from the model content (CONTRACT 3.6).

    This is the generator the model layer uses; ``encodings_consistent`` below is
    the gate.  Nothing is invented: an entry is produced only when the channel is
    actually used by the model.
    """
    model = model if isinstance(model, dict) else {}
    relations = [r for r in (model.get("relations") or []) if isinstance(r, dict)]
    entities = [e for e in (model.get("entities") or []) if isinstance(e, dict)]
    data = model.get("data") if isinstance(model.get("data"), dict) else {}
    out = []

    strengths = []
    for rel in relations:
        ev = rel.get("evidence") if isinstance(rel.get("evidence"), dict) else None
        st = str((ev or {}).get("strength") or "")
        if st and st not in strengths:
            strengths.append(st)
    if len(strengths) >= 2:
        mapping = [{"value": st, "visual": EVIDENCE_WIDTH_PT[st]}
                   for st in EVIDENCE_STRENGTHS if st in strengths]
        out.append({"channel": "line_width", "field": "relations[].evidence.strength",
                    "unit": "pt", "mapping": mapping})

    series = [s for s in (data.get("series") or []) if isinstance(s, dict)]
    group_field = None
    for enc in _material_encodings(model):
        if enc.get("channel") == "color" and enc.get("field"):
            group_field = str(enc.get("field"))
    if series:
        field = group_field or str(data.get("group_field") or "series")
        mapping = []
        for s in series:
            name = str(s.get("name") or "")
            color = str(s.get("color") or "")
            if name and color:
                mapping.append({"value": name, "visual": color})
        if mapping:
            unit = str(series[0].get("unit") or "") if series else ""
            out.append({"channel": "color", "field": field, "unit": unit, "mapping": mapping})

    node_size = []
    for ent in entities:
        ab = ent.get("abundance") if isinstance(ent.get("abundance"), dict) else None
        if ab and ab.get("value") is not None and str(ab.get("unit") or "").strip():
            node_size.append({"value": ab.get("value"), "visual": "area"})
    if node_size:
        unit = ""
        for ent in entities:
            ab = ent.get("abundance") if isinstance(ent.get("abundance"), dict) else None
            if ab and str(ab.get("unit") or "").strip():
                unit = str(ab["unit"])
                break
        out.append({"channel": "node_size", "field": "entities[].abundance", "unit": unit,
                    "mapping": node_size})

    styles = []
    for rel in relations:
        rtype = str(rel.get("type") or "")
        want = RELATION_STYLE.get(rtype)
        if not want:
            continue
        entry = {"value": rtype, "visual": want["stroke"]}
        if entry not in styles:
            styles.append(entry)
    if len(styles) >= 2:
        out.append({"channel": "line_style", "field": "relations[].type", "unit": "",
                    "mapping": styles})
    return out


def _material_encodings(model):
    """Workorder-declared encodings carried on the model (never hand-written)."""
    enc = model.get("legend_encoding")
    return [e for e in enc if isinstance(e, dict)] if isinstance(enc, list) else []


def encodings_consistent(model):
    """``E_LEGEND_DATA_MISMATCH`` for legend[].encoding (CONTRACT 3.6).

    The value set of every mapping must equal the values really used on the
    figure, which must equal the values present in the data.  One entry too many
    or too few is a failure.
    """
    issues = []
    model = model if isinstance(model, dict) else {}
    legend = [it for it in (model.get("legend") or []) if isinstance(it, dict)]
    relations = [r for r in (model.get("relations") or []) if isinstance(r, dict)]
    entities = [e for e in (model.get("entities") or []) if isinstance(e, dict)]
    data = model.get("data") if isinstance(model.get("data"), dict) else {}
    series = [s for s in (data.get("series") or []) if isinstance(s, dict)]
    columns = [str(c) for c in (data.get("columns") or [])]
    rows = [r for r in (data.get("rows") or []) if isinstance(r, (list, tuple))]

    entries = []
    for item in legend:
        enc = item.get("encoding") if isinstance(item.get("encoding"), dict) else None
        if enc:
            entries.append(("legend.%s" % (item.get("id") or "?"), enc))
    for i, enc in enumerate(_material_encodings(model)):
        entries.append(("legend_encoding[%d]" % i, enc))

    for where, enc in entries:
        channel = str(enc.get("channel") or "")
        field = str(enc.get("field") or "")
        mapping = [m for m in (enc.get("mapping") or []) if isinstance(m, dict)]
        values = [m.get("value") for m in mapping]

        def bad(msg):
            issues.append({"code": "E_LEGEND_DATA_MISMATCH", "message": msg, "where": where})

        if not channel or not mapping:
            bad("encoding needs a channel and a non-empty mapping[]")
            continue
        if channel == "color":
            names = [str(s.get("name")) for s in series if s.get("name")]
            if names and set(map(str, values)) != set(names):
                bad("colour mapping values %s do not equal the data categories %s"
                    % (sorted(map(str, values)), sorted(names)))
            for s in series:
                name = str(s.get("name"))
                hit = [m for m in mapping if str(m.get("value")) == name]
                if hit and str(hit[0].get("visual") or "").lower() != str(s.get("color") or "").lower():
                    bad("colour mapping says %r %r but the series is drawn %r"
                        % (name, hit[0].get("visual"), s.get("color")))
            for item in legend:
                if str(item.get("kind")) != "category":
                    continue
                val = str(item.get("value") or item.get("label") or "")
                hit = [m for m in mapping if str(m.get("value")) == val]
                if hit and str(item.get("color") or "").lower() != str(hit[0].get("visual") or "").lower():
                    bad("legend swatch for %r is %r but the encoding maps it to %r"
                        % (val, item.get("color"), hit[0].get("visual")))
            if field and columns and field in columns and rows:
                idx = columns.index(field)
                real = sorted({str(r[idx]) for r in rows if idx < len(r)})
                if real and set(map(str, values)) != set(real):
                    bad("colour mapping values %s do not equal the %r column values %s"
                        % (sorted(map(str, values)), field, real))
        elif channel == "line_width":
            if field in columns and rows:
                # the channel encodes a *data* column (e.g. evidence_tier)
                idx = columns.index(field)
                real = sorted({str(r[idx]) for r in rows if idx < len(r) and str(r[idx]).strip()})
                if real and set(map(str, values)) != set(real):
                    bad("line-width mapping values %s do not equal the %r column values %s"
                        % (sorted(map(str, values)), field, real))
                used = sorted({s.get("width_pt") for s in series if s.get("width_pt") is not None})
                visuals = sorted({m.get("visual") for m in mapping
                                  if isinstance(m.get("visual"), (int, float))})
                if used and visuals and set(visuals) != set(used):
                    bad("line-width mapping visuals %s do not equal the widths really drawn "
                        "on the series %s" % (visuals, used))
            elif "evidence" in field:
                real = sorted({str((r.get("evidence") or {}).get("strength"))
                               for r in relations if isinstance(r.get("evidence"), dict)})
                real = [x for x in real if x and x != "None"]
                if real and set(map(str, values)) != set(real):
                    bad("line-width mapping values %s do not equal the evidence strengths "
                        "actually used %s" % (sorted(map(str, values)), sorted(real)))
                used = sorted({evidence_width(r) for r in relations if evidence_width(r)})
                visuals = sorted({m.get("visual") for m in mapping})
                if used and set(visuals) != set(used):
                    bad("line-width mapping visuals %s do not equal the widths really drawn "
                        "%s" % (visuals, used))
        elif channel == "node_size":
            real = [e.get("abundance", {}).get("value") for e in entities
                    if isinstance(e.get("abundance"), dict)]
            real = sorted({v for v in real if v is not None})
            if real and set(map(str, values)) != set(map(str, real)):
                bad("node-size mapping values %s do not equal the abundances present %s"
                    % (sorted(map(str, values)), real))
        elif channel == "line_style":
            real = sorted({str(r.get("type")) for r in relations if r.get("type")})
            if real and set(map(str, values)) != set(real):
                bad("line-style mapping values %s do not equal the relation types drawn %s"
                    % (sorted(map(str, values)), real))
            for r in relations:
                hit = [m for m in mapping if str(m.get("value")) == str(r.get("type"))]
                want = RELATION_STYLE.get(str(r.get("type")))
                if hit and want and str(hit[0].get("visual")) != want["stroke"]:
                    bad("line-style mapping for %r is %r but the frozen table requires %r"
                        % (r.get("type"), hit[0].get("visual"), want["stroke"]))
    return issues


def check_abundance(entities):
    """``E_UNIT_MISSING`` for ``entities[].abundance`` without a unit."""
    issues = []
    for i, ent in enumerate(entities or []):
        if not isinstance(ent, dict):
            continue
        ab = ent.get("abundance")
        if ab is None:
            continue
        where = "entities.%s.abundance" % (ent.get("id") or i)
        if not isinstance(ab, dict):
            issues.append({"code": "E_UNIT_MISSING",
                           "message": "abundance must be {value, unit, source}",
                           "where": where})
            continue
        if ab.get("value") is None:
            issues.append({"code": "E_UNIT_MISSING", "message": "abundance.value missing",
                           "where": where})
        if not str(ab.get("unit") or "").strip():
            issues.append({"code": "E_UNIT_MISSING",
                           "message": ("abundance has a value but no unit: a node-size "
                                       "encoding without a unit is unreadable"),
                           "where": where})
    return issues


# --------------------------------------------------------------------------
# unit inference for tabular material (used by ingest / model)
# --------------------------------------------------------------------------
#: normalised column names whose values are conventionally dimensionless
DIMENSIONLESS_COLUMNS = {
    "p", "pvalue", "padj", "padjusted", "pval", "q", "qvalue", "qval", "fdr", "bh",
    "adjp", "adjustedp", "ratio", "foldchange", "log2foldchange", "log2fc", "logfc",
    "fc", "count", "counts", "n", "ncell", "ncells", "nreplicate", "nreplicates",
    "percent", "percentage", "pct", "fraction", "proportion", "score", "zscore",
    "r2", "rsquared", "rho", "pearson", "spearman", "oddsratio", "hr", "hazardratio",
    "sem", "cv", "sd", "stdev", "variance", "index", "rank", "au", "auc", "t",
    "residual", "effect", "cohensd", "delta", "logratio", "abundance", "relative",
    "normalized", "correlation", "coefficient", "probability", "prob", "fishers",
}

_COLUMN_UNIT_SUFFIXES = (
    ("time_h", "h"), ("time_hr", "h"), ("timehr", "h"), ("time_hours", "h"),
    ("hours", "h"), ("hour", "h"), ("hrs", "h"), ("hr", "h"), ("h", "h"),
    ("time_min", "min"), ("minutes", "min"), ("minute", "min"), ("mins", "min"),
    ("time_s", "s"), ("seconds", "s"), ("sec", "s"), ("days", "d"), ("day", "d"),
    ("weeks", "wk"), ("week", "wk"), ("ms", "ms"), ("age_years", "years"),
    ("temperature_c", "°C"), ("temp_c", "°C"), ("celsius", "°C"),
    ("concentration_nm", "nM"), ("concentration_um", "µM"), ("concentration_mm", "mM"),
    ("dose_nm", "nM"), ("dose_um", "µM"), ("dose_mg_kg", "mg/kg"),
    ("mass_mg", "mg"), ("mass_g", "g"), ("volume_ul", "µL"), ("volume_ml", "mL"),
    ("length_mm", "mm"), ("length_um", "µm"), ("length_nm", "nm"), ("kb", "kb"),
    ("bp", "bp"), ("kda", "kDa"), ("rpm", "rpm"), ("dpi", "dpi"), ("ratio_pt", "pt"),
)


def column_key(column):
    """Normalised comparison key for a column name (case/separator insensitive)."""
    return re.sub(r"[^a-z0-9]+", "", str(column or "").casefold())


def is_dimensionless_column(column):
    """True when a column is conventionally unitless (p_value, fold_change, ...)."""
    key = column_key(column)
    if not key:
        return False
    if key in DIMENSIONLESS_COLUMNS:
        return True
    # 'p_value_adj', 'log2fc_rep1', 'fold_change_24h' ...
    for stem in sorted(DIMENSIONLESS_COLUMNS, key=len, reverse=True):
        if len(stem) >= 3 and key.startswith(stem):
            rest = key[len(stem):]
            if rest and (rest[0].isdigit() or rest in ("adj", "adjusted", "rep", "mean",
                                                       "value", "log", "ratio")):
                return True
    return False


def unit_from_header(column):
    """Unit literally declared by a column name (``time_h`` -> ``h``), or None."""
    key = re.sub(r"[^a-z0-9]+", "_", str(column or "").casefold()).strip("_")
    flat = key.replace("_", "")
    for name, unit in _COLUMN_UNIT_SUFFIXES:
        if key == name or flat == name.replace("_", ""):
            return unit
        if key.endswith("_" + name) or flat.endswith(name.replace("_", "")):
            return unit
    m = re.match(r"^(?:time|duration|age|dose|conc(?:entration)?)[_ ]?(\d*)([a-zµ]+)$", key)
    if m and m.group(2) in ("h", "hr", "hrs", "min", "mins", "s", "sec", "d", "days",
                            "wk", "nm", "um", "mm", "pm", "nm"):
        return m.group(2)
    return None


def unit_status_for(column):
    """``"dimensionless"`` | ``"declared"`` | ``"unknown"`` for one column."""
    if unit_from_header(column):
        return "declared"
    if is_dimensionless_column(column):
        return "dimensionless"
    return "unknown"


__all__ = [
    "ONTOLOGY_VERSION", "FIGURE_KINDS", "LEGACY_FIGURE_KINDS", "ENTITY_KINDS",
    "LEGACY_ENTITY_KINDS", "MECH_ENTITY_KINDS", "CONTAINER_KINDS", "COMPARTMENTS",
    "COMPARTMENT_ALIASES", "COMPARTMENT_TIER", "MEMBRANE_ROLES", "POLICIES",
    "RELATION_TYPES", "LEGACY_RELATION_TYPES", "MECH_RELATION_TYPES",
    "RELATION_STYLE", "RELATION_LEGEND_LABEL", "RELATION_COLOR",
    "DIRECTIONAL_RELATION_TYPES", "UNDIRECTED_RELATION_TYPES",
    "STRUCTURAL_RELATION_TYPES", "FEEDBACK_RELATION_TYPES",
    "EVIDENCE_WIDTH_PT", "EVIDENCE_STRENGTHS", "EVIDENCE_KINDS", "MODIFICATION_CUES",
    "relation_style", "relation_color", "canonical_container", "container_kind",
    "container_tier", "is_membrane_container", "strip_species_prefix",
    "modification_decoration", "looks_like_protein_name", "looks_like_transcript",
    "gene_protein_confusion", "check_gene_protein", "normalized_symbol",
    "normalize_symbol", "synonyms_of", "normalise_key", "check_membrane_placement",
    "rank_edges", "derive_ranks", "directed_cycles", "check_flow_direction",
    "check_relation_styles", "required_legend_types", "check_compartment_match",
    "check_relation_constraints", "modification_kind_in", "evidence_width",
    "check_evidence", "generate_legend_encoding", "encodings_consistent",
    "check_abundance", "DIMENSIONLESS_COLUMNS", "is_dimensionless_column",
    "unit_from_header", "unit_status_for", "column_key", "generate_relation_id",
]
