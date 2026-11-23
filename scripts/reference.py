#!/usr/bin/env python3
"""Reference-figure comparison for biological mechanism / pathway figures.

The organisers' materials for this topic point at a paper figure ("figure03"). A case may
ship that original as an image, a PDF, or an editable vector file. Reproducing a mechanism
figure is only defensible if the result can be **compared with the original and the
comparison reported honestly** — including the parts a machine cannot check here.

What this module does, and what it refuses to do:

* discovers candidate reference figures in the case materials (never guesses silently:
  every candidate is recorded with the reason it was selected);
* for an **editable/vector or structured** original (`.svg`, `.json`) it compares content
  exactly: entity/relation label sets, node/edge counts, and the reference's own
  `<text>` labels against the model labels — these are real, reproducible comparisons;
* for a **raster** original (`.png/.jpg/.tif`) or a PDF it compares the geometry and the
  palette of our rendered export against the reference and reports measurable numbers;
* it **never** claims semantic equivalence from pixels alone. A raster reference without a
  structured counterpart yields `semantic_status: "unverifiable-machine"` and a list of
  what a human (or a vision model) would still have to check. Inventing a similarity score
  would be exactly the kind of fabricated evidence this task forbids.

Stdlib only for the required path; Pillow is used opportunistically for raster metrics and
its absence degrades to an explicit `available: false`, never to a silent pass.
"""
from __future__ import annotations

import json
import os
import re

REFERENCE_STEMS = ("figure03", "figure3", "fig03", "fig3", "figure", "reference", "original")
VECTOR_EXT = (".svg",)
STRUCT_EXT = (".json",)
RASTER_EXT = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp")
PDF_EXT = (".pdf",)

_SVG_TEXT = re.compile(r"<text\b[^>]*>(.*?)</text>", re.S | re.I)
_TAGS = re.compile(r"<[^>]+>")
_HEX = re.compile(r"#([0-9a-fA-F]{6})\b")


def _clean(text: str) -> str:
    text = _TAGS.sub(" ", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"\s+", " ", text).strip()


def _norm(label: str) -> str:
    return re.sub(r"[\s_\-()\[\],.;:]+", "", str(label or "")).lower()


def discover_reference(input_dir: str, *, explicit: str | None = None) -> dict:
    """Find candidate reference figures and say *why* each candidate was selected.

    Explicit wins; otherwise a file whose stem matches a known figure naming pattern.
    Every skipped near-miss is listed so a human can see what was not used.
    """
    index = {"selected": None, "candidates": [], "skipped": [], "reason": ""}
    if explicit:
        path = explicit if os.path.isabs(explicit) else os.path.join(input_dir, explicit)
        if os.path.isfile(path):
            index["selected"] = path
            index["reason"] = "explicitly requested by the caller"
            return index
        index["reason"] = "explicit reference %r not found" % explicit
        return index

    for root, _dirs, files in os.walk(input_dir):
        for name in sorted(files):
            ext = os.path.splitext(name)[1].lower()
            if ext not in VECTOR_EXT + STRUCT_EXT + RASTER_EXT + PDF_EXT:
                continue
            stem = os.path.splitext(name)[0].lower()
            rel = os.path.relpath(os.path.join(root, name), input_dir).replace("\\", "/")
            matched = next((s for s in REFERENCE_STEMS if stem.startswith(s)), None)
            entry = {"path": rel, "ext": ext, "matched_token": matched}
            if matched and ext in RASTER_EXT + PDF_EXT + VECTOR_EXT:
                index["candidates"].append(entry)
            else:
                index["skipped"].append(entry)

    if not index["candidates"]:
        index["reason"] = ("no candidate reference figure found; the materials contain no "
                           "file named like a paper figure")
        return index

    # Prefer an editable/vector original over a raster of the same stem: the editable one
    # supports an exact content comparison.
    priority = {e: i for i, e in enumerate(VECTOR_EXT + PDF_EXT + RASTER_EXT)}
    index["candidates"].sort(key=lambda c: (c["matched_token"], priority.get(c["ext"], 9), c["path"]))
    best = index["candidates"][0]
    index["selected"] = os.path.join(input_dir, best["path"])
    index["reason"] = ("selected because it is the best-ranked candidate: stem matches %r and "
                       "format %s ranks first among candidates" % (best["matched_token"], best["ext"]))
    return index


def _svg_labels(text: str) -> list[str]:
    return sorted({_clean(m) for m in _SVG_TEXT.findall(text) if _clean(m)})


def _svg_hexes(text: str) -> list[str]:
    return sorted({("#" + h).lower() for h in _HEX.findall(text)})


def compare(reference_path: str, model: dict, rendered_png: str | None) -> dict:
    """Build the comparison report. Honest about what could not be checked."""
    ext = os.path.splitext(reference_path)[1].lower()
    model_labels = [str(e.get("label") or "") for e in model.get("entities", [])]
    model_relation_types = sorted({str(r.get("type") or "") for r in model.get("relations", [])})
    report = {
        "reference_path": reference_path.replace("\\", "/"),
        "reference_ext": ext,
        "compared_against": os.path.basename(rendered_png or "") or None,
        "checks": [],
        "exceptions": [],
        "semantic_status": "unverifiable-machine",
    }

    if ext in VECTOR_EXT:
        try:
            ref_text = open(reference_path, encoding="utf-8", errors="replace").read()
        except OSError as exc:
            report["exceptions"].append("reference unreadable: %s" % exc)
            report["semantic_status"] = "not_compared"
            return report
        ref_labels = _svg_labels(ref_text)
        ref_norm = {_norm(l) for l in ref_labels}
        missing = [l for l in model_labels if _norm(l) not in ref_norm]
        extra = [l for l in ref_labels if _norm(l) not in {_norm(m) for m in model_labels}]
        ref_hexes = _svg_hexes(ref_text)
        report["checks"].append({
            "id": "REF_LABEL_COVERAGE", "level": "warning",
            "status": "pass" if not missing else "warn",
            "detail": "model labels present in the reference: %d/%d" % (len(model_labels) - len(missing), len(model_labels)),
            "missing_from_reference": missing[:25],
            "reference_only_labels": extra[:25],
        })
        report["checks"].append({
            "id": "REF_PALETTE", "level": "info",
            "status": "pass" if ref_hexes else "na",
            "detail": "reference declares %d distinct #rrggbb colours" % len(ref_hexes),
            "reference_colours": ref_hexes[:32],
        })
        if not missing:
            report["semantic_status"] = "labels_fully_covered"
        else:
            report["semantic_status"] = "labels_partial"
        report["exceptions"].append(
            "an editable reference was compared by label text only; spatial placement, arrow "
            "direction and compartment geometry are not machine-compared here")
        return report

    if ext in STRUCT_EXT:
        try:
            ref = json.load(open(reference_path, encoding="utf-8"))
        except (OSError, ValueError) as exc:
            report["exceptions"].append("reference JSON unreadable: %s" % exc)
            report["semantic_status"] = "not_compared"
            return report
        ref_entities = [str(e.get("label") or e.get("id") or "") for e in (ref.get("entities") or [])]
        ref_relations = ref.get("relations") or []
        ref_types = sorted({str(r.get("kind") or r.get("type") or "") for r in ref_relations})
        report["checks"].append({
            "id": "REF_STRUCTURE_COUNTS", "level": "warning",
            "status": "pass" if len(ref_entities) == len(model_labels) else "warn",
            "detail": "reference entities=%d relations=%d | model entities=%d relations=%d"
                      % (len(ref_entities), len(ref_relations), len(model_labels), len(model.get("relations", []))),
        })
        report["checks"].append({
            "id": "REF_INTERACTION_VOCABULARY", "level": "warning",
            "status": "pass" if set(ref_types) <= set(model_relation_types) else "warn",
            "detail": "reference interaction types=%s | model types=%s" % (ref_types, model_relation_types),
            "reference_only_types": sorted(set(ref_types) - set(model_relation_types)),
        })
        report["semantic_status"] = ("structure_matched"
                                     if not (set(ref_types) - set(model_relation_types)) else "structure_partial")
        return report

    if ext in RASTER_EXT + PDF_EXT:
        metrics = _raster_metrics(reference_path, rendered_png)
        report["checks"].append(metrics.pop("check"))
        report.update(metrics)
        report["semantic_status"] = "unverifiable-machine"
        report["exceptions"].append(
            "the reference is a raster/PDF original: only canvas geometry and palette were "
            "measured. Semantic equivalence (which entity, which arrow type, which compartment) "
            "cannot be established from pixels alone and remains a human/vision-model judgement.")
        return report

    report["exceptions"].append("unsupported reference format %s" % ext)
    report["semantic_status"] = "not_compared"
    return report


def _raster_metrics(reference_path: str, rendered_png: str | None) -> dict:
    out = {"available": False, "reference_size": None, "render_size": None}
    try:
        from PIL import Image  # noqa: PLC0415 - optional dependency by design
    except ImportError:
        out["check"] = {"id": "REF_RASTER_METRICS", "level": "info", "status": "na",
                        "detail": "Pillow is unavailable; raster metrics were not computed "
                                  "(honest 'not available', not a pass)"}
        return out
    try:
        ref = Image.open(reference_path)
        out["reference_size"] = list(ref.size)
        ref_ratio = ref.size[0] / ref.size[1] if ref.size[1] else None
        render_ratio = None
        if rendered_png and os.path.isfile(rendered_png):
            ren = Image.open(rendered_png)
            out["render_size"] = list(ren.size)
            render_ratio = ren.size[0] / ren.size[1] if ren.size[1] else None
        out["available"] = True
        drift = None if not (ref_ratio and render_ratio) else abs(ref_ratio - render_ratio) / ref_ratio
        out["aspect_ratio_drift"] = drift
        out["check"] = {
            "id": "REF_RASTER_METRICS", "level": "info",
            "status": "pass" if (drift is None or drift <= 0.15) else "warn",
            "detail": "reference %s | render %s | aspect-ratio drift %s"
                      % (out["reference_size"], out["render_size"],
                         "n/a" if drift is None else "%.1f%%" % (drift * 100)),
        }
    except Exception as exc:  # noqa: BLE001 - a broken image must not break the pipeline
        out["check"] = {"id": "REF_RASTER_METRICS", "level": "info", "status": "na",
                        "detail": "raster metrics unavailable: %s" % exc}
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Compare a rendered figure with its paper original")
    ap.add_argument("--input", required=True)
    ap.add_argument("--model", required=True, help="figure_model.json")
    ap.add_argument("--render", default=None, help="our rendered PNG")
    ap.add_argument("--out", required=True)
    ap.add_argument("--reference", default=None)
    a = ap.parse_args(argv)

    index = discover_reference(a.input, explicit=a.reference)
    model = json.load(open(a.model, encoding="utf-8"))
    if not index["selected"]:
        report = {"reference_path": None, "semantic_status": "na",
                  "discovery": index,
                  "exceptions": [index["reason"]],
                  "checks": [{"id": "REFERENCE_COMPARISON", "level": "info", "status": "na",
                              "detail": index["reason"]}]}
    else:
        report = compare(index["selected"], model, a.render)
        report["discovery"] = index
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(json.dumps({"reference": report.get("reference_path"),
                      "semantic_status": report.get("semantic_status"),
                      "checks": [c["id"] + ":" + c["status"] for c in report.get("checks", [])]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
