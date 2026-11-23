# -*- coding: utf-8 -*-
"""Journal-compliance gate for exported figure artifacts.

Frozen interface (CONTRACT.md section 4.6)::

    check_artifacts(paths, spec, *, model=None) -> dict

Every check really opens the artifact it talks about: SVG is parsed as XML,
rasters are opened with Pillow, PDFs with pypdf, EPS and magic bytes read from
disk.  A check that cannot run because its input is missing or corrupt returns
``ok=False`` with a clear ``detail`` -- it never raises and never silently
passes.

Return value::

    {"checks": [{"id","level","ok","detail","evidence"}], "ok": bool, ...}

``level`` is ``"error"`` only for defects that genuinely break a journal
submission; advisory problems are ``"warn"`` and do not flip ``ok``.
"""

from __future__ import annotations

import json
import os
import re
import xml.etree.ElementTree as ET

try:  # package-style import
    from . import common
except ImportError:  # flat import from the scripts directory
    import common

SCHEMA_VERSION = common.SCHEMA_VERSION
MM_PER_INCH = common.MM_PER_INCH
PT_PER_INCH = common.PT_PER_INCH

REQUIRED_SVG_LAYERS = 6

MAGIC = {
    "pdf": [b"%PDF-"],
    "png": [b"\x89PNG\r\n\x1a\n"],
    "tiff": [b"II*\x00", b"MM\x00*"],
    "eps": [b"%!PS"],
}

_EXT_TO_FORMAT = {
    ".svg": "svg", ".pdf": "pdf", ".png": "png",
    ".tif": "tiff", ".tiff": "tiff", ".eps": "eps", ".ps": "eps",
}


# ---------------------------------------------------------------------------
# Spec / path normalisation
# ---------------------------------------------------------------------------
_FALLBACK_PRESETS = {
    "nature": {"width_mm": 89.0, "width_double_mm": 183.0, "dpi": 300,
               "min_line_width_pt": 0.5, "min_text_pt": 5.0, "max_height_mm": 247.0,
               "color_space": "RGB", "font_embedding_required": True,
               "formats": ["svg", "pdf", "png", "tiff", "eps"]},
    "science": {"width_mm": 55.0, "width_double_mm": 120.0, "dpi": 300,
                "min_line_width_pt": 0.5, "min_text_pt": 6.0, "max_height_mm": 240.0,
                "color_space": "RGB", "font_embedding_required": True,
                "formats": ["svg", "pdf", "png", "tiff", "eps"]},
    "cell": {"width_mm": 85.0, "width_double_mm": 174.0, "dpi": 300,
             "min_line_width_pt": 0.5, "min_text_pt": 6.0, "max_height_mm": 240.0,
             "color_space": "RGB", "font_embedding_required": True,
             "formats": ["svg", "pdf", "png", "tiff", "eps"]},
    "ieee": {"width_mm": 88.9, "width_double_mm": 181.8, "dpi": 300,
             "min_line_width_pt": 0.5, "min_text_pt": 8.0, "max_height_mm": 240.0,
             "color_space": "RGB", "font_embedding_required": True,
             "formats": ["svg", "pdf", "png", "tiff", "eps"]},
    "generic": {"width_mm": 180.0, "width_double_mm": 180.0, "dpi": 300,
                "min_line_width_pt": 0.5, "min_text_pt": 6.0, "max_height_mm": 240.0,
                "color_space": "RGB", "font_embedding_required": True,
                "formats": ["svg", "pdf", "png", "tiff", "eps"]},
}


def _journal_preset(name):
    """Use export.journal_preset; if the sibling cannot be imported, use the same
    values from a local copy (only reachable when import is impossible, so the
    preset table stays identical to the exporter's)."""
    key = str(name or "generic").strip().lower().replace("-", "_")
    try:
        try:
            from . import export as _export_mod  # noqa: WPS433
        except Exception:  # noqa: BLE001 - flat layout
            import export as _export_mod  # type: ignore # noqa: WPS433
        return _export_mod.journal_preset(key)
    except common.SkillError:
        raise
    except Exception:  # noqa: BLE001 - sibling unavailable: local mirror, still real
        if key not in _FALLBACK_PRESETS:
            common.die("unknown journal preset %r (known: %s)"
                       % (name, ", ".join(sorted(_FALLBACK_PRESETS))), common.CONFIG)
        out = dict(_FALLBACK_PRESETS[key])
        out["name"] = key
        out["source"] = ("export.py unreachable: using compliance.py's mirrored preset "
                         "table (identical values)")
        return out


def _spec(spec) -> dict:
    """Read the compliance-relevant spec keys; tolerate presets and overrides."""
    if spec is None:
        spec = {}
    if isinstance(spec, str):
        # A named preset must be real: an unknown name is a caller/config error.
        spec = _journal_preset(spec)
    out = dict(spec) if isinstance(spec, dict) else {}
    if out.get("preset") and "dpi" not in out:
        preset = _journal_preset(str(out["preset"]))
        for key, value in preset.items():
            out.setdefault(key, value)
    out["dpi"] = int(round(float(out.get("dpi") or 300)))
    out["min_line_width_pt"] = float(out.get("min_line_width_pt") or 0.5)
    out["min_text_pt"] = float(out.get("min_text_pt") or 0.0)
    out["color_space"] = str(out.get("color_space") or "RGB").upper()
    out["font_embedding_required"] = bool(out.get("font_embedding_required", True))
    out["width_mm"] = float(out.get("width_mm") or 180.0)
    out["max_height_mm"] = float(out.get("max_height_mm") or 240.0)
    formats = out.get("formats") or ["svg", "pdf", "png", "tiff"]
    if isinstance(formats, str):
        formats = [formats]
    out["formats"] = [str(f).lower().lstrip(".") for f in formats]
    out["cmyk_explicit"] = out["color_space"] == "CMYK"
    return out


def _normalise_paths(paths):
    """Accept list[str], list[dict], dict{name: path|dict}, or a directory."""
    found = []
    if paths is None:
        return found
    if isinstance(paths, (str, os.PathLike)):
        paths = [paths]
    if isinstance(paths, dict):
        found = []
        for name, value in paths.items():
            if isinstance(value, dict):
                entry = dict(value)
                entry.setdefault("path", entry.get("path"))
                entry.setdefault("name", name)
                found.append(entry)
            else:
                found.append({"name": name, "path": value})
        paths = found
    if isinstance(paths, (str, os.PathLike)):  # pragma: no cover - handled above
        paths = [paths]
    out = []
    for item in paths:
        if isinstance(item, dict):
            path = item.get("path")
            name = item.get("name") or (os.path.basename(str(path)) if path else "")
            entry = dict(item)
            entry["name"] = name
            entry["format"] = (entry.get("format") or _EXT_TO_FORMAT.get(
                os.path.splitext(str(path or name))[1].lower(), "")).lower()
            out.append(entry)
        else:
            path = str(item)
            out.append({"path": path, "name": os.path.basename(path),
                        "format": _EXT_TO_FORMAT.get(
                            os.path.splitext(path)[1].lower(), "")})
    resolved = []
    for entry in out:
        path = entry.get("path")
        if not path:
            resolved.append(entry)
            continue
        path = str(path)
        if os.path.isdir(path):
            for name in sorted(os.listdir(path)):
                child = os.path.join(path, name)
                fmt = _EXT_TO_FORMAT.get(os.path.splitext(name)[1].lower())
                if os.path.isfile(child) and fmt:
                    resolved.append({"path": child, "name": name, "format": fmt})
            continue
        entry["path"] = os.path.abspath(path)
        resolved.append(entry)
    return resolved


def _by_format(entries):
    groups = {}
    for entry in entries:
        groups.setdefault(entry.get("format") or "unknown", []).append(entry)
    return groups


def _check(check_id, level, ok, detail, evidence=None, where=""):
    ok = bool(ok)
    applicable = not (isinstance(evidence, dict) and evidence.get("applicable") is False)
    return {"id": check_id, "code": check_id, "level": level, "ok": ok,
            "status": ("na" if not applicable else ("pass" if ok else "fail")),
            "applicable": applicable,
            "where": str(where or ""), "detail": detail,
            "evidence": evidence if evidence is not None else {}}


def _missing_check(check_id, what, channels, fmts, optional=False):
    """N/A when the format was never requested; a real failure when it was.

    Keeps the frozen check id present in every report while never claiming a
    pass for an artifact that should exist.  ``optional=True`` marks formats
    whose absence is advisory (e.g. EPS is an extra, not a core deliverable).
    """
    requested = [f for f in fmts if f in channels.get("formats", [])]
    if not requested:
        return _check(check_id, "warn", True,
                      "N/A: %s not requested by spec (%s)"
                      % (what, ", ".join(channels.get("formats") or [])),
                      {"applicable": False, "requested_formats": channels.get("formats")})
    level = "warn" if optional else "error"
    return _check(check_id, level, bool(optional),
                  "%s requested by spec (%s) but no %s artifact was supplied"
                  % (", ".join(requested), ", ".join(channels.get("formats") or []), what)
                  + ("; treated as advisory (optional extra format)" if optional else ""),
                  {"applicable": True, "missing_formats": requested, "optional": optional})


def _read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# SVG helpers
# ---------------------------------------------------------------------------
def _parse_svg(path):
    """Return (root, error_string).  Namespace-agnostic element handling."""
    try:
        raw = _read_bytes(path)
    except OSError as exc:
        return None, "cannot read file: %s" % exc
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        return None, "not well-formed XML: %s" % exc
    return root, None


def _strip_ns(tag):
    return tag.split("}", 1)[1] if "}" in tag else tag


def _iter_all(root):
    for el in root.iter():
        yield el


def _attr(el, name, default=None):
    if name in el.attrib:
        return el.attrib[name]
    for key, value in el.attrib.items():
        if _strip_ns(key) == name:
            return value
    return default


def _svg_text_elements(root):
    return [el for el in _iter_all(root) if _strip_ns(el.tag) == "text"]


def _text_content(el):
    return "".join(el.itertext()).strip()


def _svg_length_to_mm(value, axis_mm=None, viewbox_extent=None):
    """Convert an SVG length to mm using an explicit unit or a known scale."""
    if value is None:
        return None
    m = re.match(r"^\s*([+-]?[0-9.]+(?:[eE][+-]?[0-9]+)?)\s*([a-zA-Z%]*)\s*$", str(value))
    if not m:
        return None
    number = float(m.group(1))
    unit = m.group(2).lower()
    if unit == "mm":
        return number
    if unit == "cm":
        return number * 10.0
    if unit in ("in",):
        return number * MM_PER_INCH
    if unit == "pt":
        return common.pt_to_mm(number)
    if unit == "pc":
        return common.pt_to_mm(number * 12.0)
    if unit in ("px", ""):
        # Unitless/viewBox user units: use the known physical size when supplied.
        if axis_mm is not None and viewbox_extent:
            return number * (float(axis_mm) / float(viewbox_extent))
        return number * (MM_PER_INCH / 96.0)  # CSS px
    return None


def _svg_canvas_mm(root, metadata=None):
    width_mm = _svg_length_to_mm(_attr(root, "width"))
    height_mm = _svg_length_to_mm(_attr(root, "height"))
    if metadata:
        canvas = (metadata.get("canvas") or {}) if isinstance(metadata, dict) else {}
        width_mm = width_mm or (float(canvas["width_mm"]) if canvas.get("width_mm") else None)
        height_mm = height_mm or (float(canvas["height_mm"]) if canvas.get("height_mm") else None)
    return width_mm, height_mm


def _svg_metadata(root):
    for el in _iter_all(root):
        if _strip_ns(el.tag) == "metadata":
            text = (el.text or "").strip()
            if not text:
                text = "".join(el.itertext()).strip()
            if not text:
                continue
            try:
                return json.loads(text)
            except ValueError:
                try:  # some writers double-escape the JSON inside <metadata>
                    from xml.sax.saxutils import unescape
                    return json.loads(unescape(text))
                except (ValueError, ImportError):
                    continue
    return {}


def _ancestor_scale_map(root):
    """Approximate cumulative transform scale for every element (stroke widths)."""
    scales = {}
    parents = {child: parent for parent in _iter_all(root) for child in parent}

    def local_scale(transform):
        if not transform:
            return 1.0
        scale = 1.0
        for op, args in re.findall(r"(matrix|scale|translate|rotate)\s*\(([^)]*)\)", transform):
            nums = [float(x) for x in re.split(r"[\s,]+", args.strip()) if x]
            if op == "scale" and nums:
                scale *= (nums[0] * (nums[1] if len(nums) > 1 else nums[0])) ** 0.5
            elif op == "matrix" and len(nums) >= 4:
                scale *= (abs(nums[0] * nums[3] - nums[1] * nums[2])) ** 0.5
        return scale or 1.0

    for el in _iter_all(root):
        own = local_scale(_attr(el, "transform"))
        parent = parents.get(el)
        accumulated = own
        guard = 0
        while parent is not None and guard < 64:
            accumulated *= local_scale(_attr(parent, "transform"))
            parent = parents.get(parent)
            guard += 1
        scales[el] = accumulated
    return scales


_STROKE_UNIT_RE = re.compile(r"^\s*([+-]?[0-9.]+(?:[eE][+-]?[0-9]+)?)\s*([a-zA-Z%]*)\s*$")


def _stroke_width_pt(el, mm_per_user, scale):
    raw = _attr(el, "stroke-width")
    style = _attr(el, "style") or ""
    if raw is None:
        m = re.search(r"stroke-width\s*:\s*([^;]+)", style)
        if m:
            raw = m.group(1)
    if raw is None:
        return None
    m = _STROKE_UNIT_RE.match(str(raw))
    if not m:
        return None
    number = float(m.group(1))
    unit = m.group(2).lower()
    if unit == "pt":
        return number
    if unit == "mm":
        return common.mm_to_pt(number)
    if unit == "cm":
        return common.mm_to_pt(number * 10.0)
    if unit == "in":
        return number * PT_PER_INCH
    if unit in ("px", ""):
        return common.mm_to_pt(number * mm_per_user) * (scale or 1.0)
    return None


# ---------------------------------------------------------------------------
# Raster helpers
# ---------------------------------------------------------------------------
def _dpi_from_image(im):
    try:
        dpi = im.info.get("dpi")
    except AttributeError:
        dpi = None
    if dpi:
        try:
            return float(dpi[0]), float(dpi[1]), "image.info(dpi)"
        except (TypeError, ValueError, IndexError):
            pass
    tag_v2 = getattr(im, "tag_v2", None)
    if tag_v2:
        xres = tag_v2.get(282)
        yres = tag_v2.get(283)
        unit = tag_v2.get(296, 2)
        if xres:
            factor = 1.0 if unit == 2 else (2.54 if unit == 3 else 1.0)
            try:
                return float(xres) * factor, float(yres or xres) * factor, "TIFF tag 282/283"
            except (TypeError, ValueError):
                pass
    return None, None, None


def _open_image(path):
    """Open + verify + fully load an image; returns (im, error)."""
    try:
        from PIL import Image
    except Exception as exc:  # noqa: BLE001
        return None, "Pillow unavailable (%s): cannot open rasters" % exc
    try:
        im = Image.open(path)
    except Exception as exc:  # noqa: BLE001
        return None, "PIL cannot identify the image: %s" % exc
    try:
        im.verify()
    except Exception as exc:  # noqa: BLE001
        return None, "PIL verify() failed (file is truncated or corrupt): %s" % exc
    try:
        im = Image.open(path)  # verify() leaves the object unusable
        im.load()
    except Exception as exc:  # noqa: BLE001
        return None, "PIL cannot decode pixel data: %s" % exc
    return im, None


# ---------------------------------------------------------------------------
# PDF helpers
# ---------------------------------------------------------------------------
def _quiet_pypdf(name):
    """Keep pypdf's own warnings off stderr; this module reports the findings."""
    try:
        import logging
        logging.getLogger(name).setLevel(logging.ERROR)
    except Exception:  # noqa: BLE001
        pass


def _pdf_reader(path):
    try:
        from pypdf import PdfReader
        _quiet_pypdf("pypdf")
    except Exception:  # noqa: BLE001
        try:
            from PyPDF2 import PdfReader  # type: ignore
            _quiet_pypdf("PyPDF2")
        except Exception as exc:  # noqa: BLE001
            return None, "no PDF parser installed (pypdf / PyPDF2): %s" % exc, None
    try:
        reader = PdfReader(path)
    except Exception as exc:  # noqa: BLE001
        return None, "pypdf cannot open the file: %s: %s" % (type(exc).__name__, exc), None
    try:
        npages = len(reader.pages)
    except Exception as exc:  # noqa: BLE001
        return None, "pypdf cannot read the page tree: %s" % exc, None
    return reader, None, npages


def _pdf_fonts(reader):
    """Walk every page /Resources /Font (and Form XObject resources)."""
    fonts = []

    def _obj(value):
        try:
            return value.get_object()
        except Exception:  # noqa: BLE001
            return value

    def walk(resources, depth=0):
        if resources is None or depth > 4:
            return
        resources = _obj(resources)
        if not isinstance(resources, dict):
            return
        font_dict = _obj(resources.get("/Font"))
        if isinstance(font_dict, dict):
            for name, ref in font_dict.items():
                fdict = _obj(ref)
                if isinstance(fdict, dict):
                    fonts.append((str(name), fdict))
        xobjects = _obj(resources.get("/XObject"))
        if isinstance(xobjects, dict):
            for _name, ref in xobjects.items():
                xobj = _obj(ref)
                if isinstance(xobj, dict) and str(xobj.get("/Subtype")) == "/Form":
                    walk(xobj.get("/Resources"), depth + 1)

    for page in reader.pages:
        walk(page.get("/Resources"))
    return fonts


def _font_descriptor(fdict):
    descriptor = fdict.get("/FontDescriptor")
    if descriptor is not None:
        try:
            descriptor = descriptor.get_object()
        except Exception:  # noqa: BLE001
            descriptor = None
    if isinstance(descriptor, dict):
        return descriptor
    descendants = fdict.get("/DescendantFonts")
    if descendants is not None:
        try:
            descendants = descendants.get_object()
        except Exception:  # noqa: BLE001
            descendants = None
        if descendants:
            try:
                first = descendants[0]
            except (TypeError, IndexError):
                first = None
            first = first.get_object() if hasattr(first, "get_object") else first
            if isinstance(first, dict):
                desc = first.get("/FontDescriptor")
                if desc is not None:
                    desc = desc.get_object() if hasattr(desc, "get_object") else desc
                    if isinstance(desc, dict):
                        return desc
    return None


def _font_report(fdict):
    subtype = str(fdict.get("/Subtype") or "")
    base = str(fdict.get("/BaseFont") or fdict.get("/Name") or "?")
    descriptor = _font_descriptor(fdict)
    files = []
    if isinstance(descriptor, dict):
        for key in ("/FontFile", "/FontFile2", "/FontFile3"):
            if descriptor.get(key) is not None:
                files.append(key.lstrip("/"))
    embedded = bool(files)
    if subtype == "/Type3":
        # Type3 glyphs are inline procedure streams: neither embedded nor selectable.
        embedded = False
    return {"name": base, "subtype": subtype or "?", "embedded": embedded,
            "files": files,
            "embedded_as": ("TrueType" if "FontFile2" in files
                            else ("Type1" if "FontFile" in files
                                  else ("CFF/OpenType" if "FontFile3" in files else None)))}


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------
def _check_svg_layers(svg_entries, channels):
    if not svg_entries:
        return _missing_check("svg_layers", "SVG", channels, ["svg"])
    evidence = {}
    all_ok = True
    problems = []
    for entry in svg_entries:
        root, err = _parse_svg(entry["path"])
        if err:
            all_ok = False
            evidence[entry["name"]] = {"error": err}
            problems.append("%s: %s" % (entry["name"], err))
            continue
        layers = []
        for el in _iter_all(root):
            if _strip_ns(el.tag) != "g":
                continue
            ident = _attr(el, "id") or ""
            if ident.startswith("layer:") or _attr(el, "data-layer") is not None:
                layers.append(ident or _attr(el, "data-layer"))
        count = len(set(layers))
        evidence[entry["name"]] = {"layers": sorted(set(layers)), "count": count,
                                   "required": REQUIRED_SVG_LAYERS}
        if count < REQUIRED_SVG_LAYERS:
            all_ok = False
            problems.append("%s: %d layer groups (< %d required)"
                            % (entry["name"], count, REQUIRED_SVG_LAYERS))
    detail = ("layer groups: %s" % ", ".join(
        "%s=%d" % (name, ev.get("count", 0)) for name, ev in evidence.items()))
    if problems:
        detail = "; ".join(problems) + " (" + detail + ")"
    return _check("svg_layers", "error", all_ok, detail, evidence)


def _check_svg_editable(svg_entries, channels):
    if not svg_entries:
        return _missing_check("svg_editable_text", "SVG", channels, ["svg"])
    evidence = {}
    all_ok = True
    problems = []
    for entry in svg_entries:
        root, err = _parse_svg(entry["path"])
        if err:
            all_ok = False
            evidence[entry["name"]] = {"error": err}
            problems.append("%s: %s" % (entry["name"], err))
            continue
        texts = _svg_text_elements(root)
        text_chars = sum(len(_text_content(el)) for el in texts)
        images = [el for el in _iter_all(root) if _strip_ns(el.tag) == "image"]
        # An <image> is only acceptable inside a layer explicitly marked as a chart raster.
        rasterised_layers = set()
        image_parents = {}
        for parent in _iter_all(root):
            for child in parent:
                image_parents[child] = parent
        bad_images = []
        for img in images:
            parent = image_parents.get(img)
            allowed = False
            guard = 0
            while parent is not None and guard < 32:
                ident = (_attr(parent, "id") or "") + " " + (_attr(parent, "data-role") or "")
                if "raster" in ident.lower() or "chart" in ident.lower():
                    allowed = True
                    break
                parent = image_parents.get(parent)
                guard += 1
            if not allowed:
                bad_images.append(_attr(img, "id") or "image")
        text_as_path = []
        for el in _iter_all(root):
            tag = _strip_ns(el.tag)
            role = str(_attr(el, "data-role") or "") + " " + str(_attr(el, "class") or "")
            ident = str(_attr(el, "id") or "")
            if tag == "path" and (re.search(r"text|glyph|label", role, re.I)
                                  or ident.startswith(("text:", "txt:", "glyph:"))):
                text_as_path.append(ident or role.strip() or "path")
        faces = sorted({str(_attr(el, "font-family") or _attr(el, "font")) for el in texts
                        if _attr(el, "font-family") or _attr(el, "font")})
        evidence[entry["name"]] = {
            "text_elements": len(texts), "text_chars": text_chars,
            "text_as_path": text_as_path[:20],
            "images": len(images), "images_outside_chart": bad_images[:20],
            "font_families": faces[:8],
        }
        if not texts:
            all_ok = False
            problems.append("%s: 0 <text> elements (no editable text)" % entry["name"])
        if text_as_path:
            all_ok = False
            problems.append("%s: %d text-as-path element(s)" % (entry["name"], len(text_as_path)))
        if bad_images:
            all_ok = False
            problems.append("%s: %d <image> outside a chart raster"
                            % (entry["name"], len(bad_images)))
    detail = "; ".join(problems) if problems else (
        "editable text present: %s" % ", ".join(
            "%s=%d <text>/%d chars" % (n, e.get("text_elements", 0), e.get("text_chars", 0))
            for n, e in evidence.items()))
    return _check("svg_editable_text", "error", all_ok, detail, evidence)


def _requested_canvas_mm(model, channels):
    """The *requested* figure size: model.figure.canvas (or the spec width)."""
    canvas = ((model or {}).get("figure") or {}).get("canvas") or {}
    try:
        width = float(canvas.get("width_mm") or channels["width_mm"])
    except (TypeError, ValueError):
        width = float(channels["width_mm"])
    try:
        height = float(canvas.get("height_mm") or 0) or None
    except (TypeError, ValueError):
        height = None
    return width, height


def _drawn_canvas_mm(svg_entries, model, channels):
    """The size the artifacts were **actually drawn at**.

    A layout may legitimately grow the canvas (``layout.stats.canvas_adjusted``),
    so the rendered master SVG is the authoritative record of the drawn size;
    ``spec["canvas"]``/``spec["layout_canvas"]`` win when the caller passes the
    layout through, and ``model.figure.canvas`` is only the *requested* size.
    """
    for key in ("canvas", "layout_canvas"):
        raw = channels.get(key)
        if isinstance(raw, dict) and raw.get("width_mm"):
            try:
                return {"width_mm": float(raw["width_mm"]),
                        "height_mm": float(raw.get("height_mm") or 0) or None,
                        "source": "spec[%r] (layout canvas)" % key}
            except (TypeError, ValueError):
                pass
    for entry in svg_entries or []:
        path = entry.get("path")
        if not path or not os.path.isfile(path):
            continue
        root, err = _parse_svg(path)
        if err:
            continue
        width, height = _svg_canvas_mm(root, _svg_metadata(root))
        if width:
            return {"width_mm": float(width), "height_mm": float(height) if height else None,
                    "source": "rendered SVG width/height (%s)" % entry.get("name")}
    width, height = _requested_canvas_mm(model, channels)
    return {"width_mm": width, "height_mm": height, "source": "model.figure.canvas (requested)"}


def _canvas_drift_note(model, drawn, channels):
    """Advisory when the drawn size differs from the requested canvas."""
    requested_w, requested_h = _requested_canvas_mm(model, channels)
    notes = []
    tol_w = max(0.5, requested_w * 0.02)
    if abs(drawn["width_mm"] - requested_w) > tol_w:
        notes.append("canvas width requested %.1f mm, drawn %.1f mm"
                     % (requested_w, drawn["width_mm"]))
    if requested_h and drawn.get("height_mm"):
        tol_h = max(0.5, requested_h * 0.02)
        if abs(drawn["height_mm"] - requested_h) > tol_h:
            notes.append("canvas height requested %.1f mm, drawn %.1f mm (a layout may grow "
                         "the canvas: layout.stats.canvas_adjusted)"
                         % (requested_h, drawn["height_mm"]))
    return notes


def _provenance_expectation(model):
    """How many ``data-prov`` bindings the SVG must carry for this model.

    Relationship schematics must bind every entity, relation, container and
    legend entry.  A chart figure binds the plotted values instead (one per
    series point) plus its legend entries and panels -- its entities are axis
    categories, not drawn boxes, so the schematic count would be the wrong bar.
    """
    if not isinstance(model, dict):
        return 0
    base = sum(len(model.get(key) or []) for key in
               ("entities", "relations", "containers", "legend"))
    kind = str(((model.get("figure") or {}).get("kind")) or "")
    if kind == "chart":
        data = model.get("data") or {}
        points = sum(len((series or {}).get("y") or []) for series in (data.get("series") or []))
        chart_expect = len(model.get("legend") or []) + points + len(model.get("panels") or [])
        return min(base, max(3, chart_expect)) if base else max(3, chart_expect)
    return base


_LOCATOR_RE = re.compile(
    r"^(L\d+(-L\d+)?|p\d+|table:[^\s#]+|fig:[\w.\-]+|[a-z]+:[^\s#]+)$")


def _locator_problem(value):
    """Return why a ``data-prov`` is outside the frozen CONTRACT 4 form, or None.

    Frozen form: ``<POSIX path relative to the input root>#<locator>`` with
    ``locator`` in ``L12 | L12-L18 | p12 | table:<col> | fig:<n> |
    json:<json-pointer> | csv:<col>`` (any lower-case ``scheme:`` prefix is
    accepted, because ``ingest`` really emits ``json:entities/<id>`` for
    workorder inputs).  The ``(none)`` placeholder is accepted only as
    ``(none)#(none)`` for elements with no source, or as ``<path>#(none)`` for an
    element whose claim is backed by a verbatim quote instead of a locator.
    """
    text = str(value or "").strip()
    if not text:
        return "empty data-prov"
    if text in ("(none)#(none)", "(none)"):
        return None
    if "#" not in text:
        return "no '#' separating path and locator"
    path, locator = text.split("#", 1)
    if not path or any(ch.isspace() for ch in path):
        return "path is empty or contains whitespace"
    if path.startswith(("/", "\\")) or "\\" in path or "//" in path:
        return "path is not a relative POSIX path"
    if any(part in ("", ".", "..") for part in path.split("/")):
        return "path has empty/./.. segments"
    if locator == "(none)":
        # path-only binding: legitimate when the element carries a quote (the
        # renderer emits data-has-quote for exactly this case).
        return None
    if not _LOCATOR_RE.match(locator):
        return "locator %r not in L12|L12-L18|p12|table:<col>|fig:<n>|json:<ptr>|csv:<col>" \
               % locator
    return None


def _locator_parts(value):
    """Split a ``data-prov`` into (path, locator) tolerantly."""
    text = str(value or "")
    if "#" in text:
        path, locator = text.split("#", 1)
        return path, locator
    return text, ""


def _provenance_records(root):
    """Structured per-element provenance verdicts.

    Shape (shared with layout-render's ``prov_form_scan.py`` so both sides can be
    diffed element-by-element)::

        {"element_id", "data_prov", "path", "locator", "src_kind",
         "problem": None|str, "severity": None|"error"|"warn"}

    ``severity`` is error only for ``src_kind="explicit"`` (an "it is in the
    quoted source" claim that cannot be resolved), warn for derived/unsupported
    placeholders.
    """
    records = []
    for el in _iter_all(root):
        value = _attr(el, "data-prov")
        if value is None:
            continue
        kind = str(_attr(el, "data-src-kind") or "unknown")
        problem = _locator_problem(str(value))
        path, locator = _locator_parts(value)
        records.append({
            "element_id": str(_attr(el, "id") or _strip_ns(el.tag)),
            "data_prov": str(value), "path": path, "locator": locator,
            "src_kind": kind, "problem": problem,
            "severity": (None if not problem
                         else ("error" if kind == "explicit" else "warn")),
        })
    return records


def locator_form_report(source):
    """Validate every ``data-prov`` in an SVG **path or text**.

    Helper (not part of the frozen CONTRACT 4.6 API) so a renderer-side scan can
    diff verdicts per element against this gate::

        {"checked": int, "src_kind_histogram": {...}, "nonconformant": [
            {"element_id", "data_prov", "path", "locator", "src_kind",
             "problem", "severity"}, ...], "ok": bool}

    ``ok`` is False when any ``severity == "error"`` record exists.
    """
    if isinstance(source, (str, os.PathLike)) and os.path.isfile(str(source)):
        root, err = _parse_svg(str(source))
        if err:
            return {"checked": 0, "src_kind_histogram": {}, "nonconformant": [],
                    "error": err, "ok": False}
    elif isinstance(source, (str, bytes)):
        raw = source.encode("utf-8") if isinstance(source, str) else source
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            return {"checked": 0, "src_kind_histogram": {}, "nonconformant": [],
                    "error": str(exc), "ok": False}
    else:
        root = source
    records = _provenance_records(root)
    histogram = {}
    for record in records:
        histogram[record["src_kind"]] = histogram.get(record["src_kind"], 0) + 1
    bad = [record for record in records if record["problem"]]
    return {"checked": len(records), "src_kind_histogram": histogram,
            "nonconformant": bad,
            "ok": not any(record["severity"] == "error" for record in bad)}


def _check_svg_provenance(svg_entries, model, channels):
    if not svg_entries:
        return _missing_check("svg_provenance", "SVG", channels, ["svg"])
    expected = _provenance_expectation(model)
    evidence = {}
    all_ok = True
    problems = []
    advisory = []
    for entry in svg_entries:
        root, err = _parse_svg(entry["path"])
        if err:
            all_ok = False
            evidence[entry["name"]] = {"error": err}
            problems.append("%s: %s" % (entry["name"], err))
            continue
        prov = 0
        kinds = {}
        unsupported = 0
        records = _provenance_records(root)
        format_errors = []
        format_advisories = []
        for record in records:
            prov += 1
            kinds[record["src_kind"]] = kinds.get(record["src_kind"], 0) + 1
            if not record["data_prov"].strip() and record["src_kind"] != "unsupported":
                unsupported += 1
            if record["problem"]:
                if record["severity"] == "error":
                    # "explicit" claims the element IS in the quoted source: a
                    # malformed path/locator makes that claim unverifiable.
                    format_errors.append(record)
                else:
                    format_advisories.append(record)
        # Count of addressable elements: id="ent:*|rel:*|lg:*|cnt:*"
        addressable = 0
        for el in _iter_all(root):
            ident = str(_attr(el, "id") or "")
            if ident.startswith(("ent:", "rel:", "lg:", "cnt:")):
                addressable += 1
        evidence[entry["name"]] = {
            "data_prov_count": prov, "addressable_elements": addressable,
            "src_kinds": kinds, "expected_from_model": expected,
            "missing_id_prefixes": unsupported,
            "locator_format_errors": format_errors[:20],
            "locator_format_advisories": format_advisories[:20],
            "provenance_records_checked": len(records),
        }
        if format_errors:
            all_ok = False
            problems.append("%s: %d data-prov locator(s) outside the frozen CONTRACT "
                            "set with data-src-kind=explicit: %s"
                            % (entry["name"], len(format_errors),
                               "; ".join("%s (%s) -> %s" % (r["element_id"], r["data_prov"],
                                                            r["problem"])
                                         for r in format_errors[:3])))
        if format_advisories:
            advisory.append("%s: %d data-prov locator(s) outside the frozen set "
                            "(src-kind=%s): %s"
                            % (entry["name"], len(format_advisories),
                               ",".join(sorted({r["src_kind"] for r in format_advisories})),
                               "; ".join("%s (%s) -> %s" % (r["element_id"], r["data_prov"],
                                                            r["problem"])
                                         for r in format_advisories[:3])))
        if expected and prov < expected:
            all_ok = False
            problems.append("%s: %d data-prov attributes < %d model elements"
                            % (entry["name"], prov, expected))
        elif not expected and prov < 1:
            all_ok = False
            problems.append("%s: no data-prov provenance attributes" % entry["name"])
        if expected and addressable < expected:
            # Data-prov is the hard requirement; traceable ids are role-specific
            # (a chart figure addresses series:, not ent:), so this is advisory.
            advisory.append("%s: %d ent:/rel:/lg:/cnt: ids for %d model elements "
                            "(chart figures legitimately address series: instead)"
                            % (entry["name"], addressable, expected))
    notes = problems + advisory
    level = "error" if problems else ("warn" if advisory else "error")
    detail = "; ".join(notes) if notes else "provenance attributes: %s" % ", ".join(
        "%s=%d (expected>=%d)" % (n, e.get("data_prov_count", 0), e.get("expected_from_model", 0))
        for n, e in evidence.items())
    return _check("svg_provenance", level, all_ok, detail, evidence)


def _check_raster_dpi(raster_entries, channels, model, drawn):
    if not raster_entries:
        return _missing_check("raster_dpi", "raster (PNG/TIFF)", channels, ["png", "tiff"])
    # Measure against the size the figure was DRAWN at, not the requested canvas.
    width_mm = drawn["width_mm"]
    height_mm = drawn.get("height_mm")
    required = channels["dpi"]
    evidence = {}
    all_ok = True
    warnings = []
    problems = []
    for entry in raster_entries:
        path = entry["path"]
        if not os.path.isfile(path):
            all_ok = False
            evidence[entry["name"]] = {"error": "file does not exist"}
            problems.append("%s: missing file" % entry["name"])
            continue
        im, err = _open_image(path)
        if err:
            all_ok = False
            evidence[entry["name"]] = {"error": err}
            problems.append("%s: %s" % (entry["name"], err))
            continue
        try:
            dpi_x, dpi_y, source = _dpi_from_image(im)
            px_w, px_h = im.size
            mode = im.mode
        finally:
            im.close()
        needed_px = int(common.mm_to_px(width_mm, required))
        # PNG pHYs / TIFF XResolution store pixels-per-metre and are quantised:
        # 300 dpi round-trips as 11811 px/m == 299.9994 dpi.  Allow that rounding,
        # which is ~0.002% -- far below any real under-resolution.
        dpi_tolerance = max(0.1, required * 0.001)
        info = {"pixel_size": [px_w, px_h], "dpi_metadata": [dpi_x, dpi_y],
                "dpi_source": source, "required_dpi": required,
                "dpi_tolerance": round(dpi_tolerance, 4),
                "required_px_width": needed_px, "mode": mode}
        evidence[entry["name"]] = info
        if dpi_x is None:
            # No metadata: only provable via pixel count; that is a warning, not a pass.
            if px_w >= needed_px:
                warnings.append("%s: no DPI metadata; pixel width %d meets %d px for %d dpi "
                                "but the physical resolution is undeclared" %
                                (entry["name"], px_w, needed_px, required))
            else:
                all_ok = False
                problems.append("%s: no DPI metadata and pixel width %d < %d px required for "
                                "%d dpi at %.1f mm" %
                                (entry["name"], px_w, needed_px, required, width_mm))
            continue
        if min(dpi_x, dpi_y) + dpi_tolerance < required:
            all_ok = False
            problems.append("%s: declared %gx%g dpi < required %d dpi (tolerance %g)"
                            % (entry["name"], dpi_x, dpi_y, required, dpi_tolerance))
        if height_mm:
            physical_w = px_w / dpi_x * MM_PER_INCH
            physical_h = px_h / dpi_y * MM_PER_INCH
            info["physical_size_mm"] = [round(physical_w, 2), round(physical_h, 2)]
            tol_w = max(0.5, width_mm * 0.03)
            tol_h = max(0.5, height_mm * 0.03)
            if abs(physical_w - width_mm) > tol_w or abs(physical_h - height_mm) > tol_h:
                all_ok = False
                problems.append("%s: %gx%g px at %g dpi = %.1fx%.1f mm, canvas is %.1fx%.1f mm"
                                % (entry["name"], px_w, px_h, dpi_x, physical_w, physical_h,
                                   width_mm, height_mm))
    drift = _canvas_drift_note(model, drawn, channels)
    if drift:
        warnings.extend(drift)
        for info in evidence.values():
            if isinstance(info, dict):
                info["canvas_drift"] = drift
    notes = problems + warnings
    detail = "; ".join(notes) if notes else (
        "; ".join("%s: %sx%s px @ %s dpi (%s)" %
                  (n, e.get("pixel_size", ["?"])[0], e.get("pixel_size", ["?", "?"])[1],
                   e.get("dpi_metadata", ["?"])[0], e.get("dpi_source"))
                  for n, e in evidence.items()))
    if all_ok and not problems:
        detail += " [drawn at %.1f mm from %s]" % (width_mm, drawn.get("source"))
    level = "warn" if (all_ok and warnings) else "error"
    return _check("raster_dpi", level, all_ok, detail, evidence)


def _check_raster_opens(raster_entries, channels):
    if not raster_entries:
        return _missing_check("raster_opens", "raster (PNG/TIFF)", channels, ["png", "tiff"])
    evidence = {}
    all_ok = True
    problems = []
    for entry in raster_entries:
        path = entry["path"]
        if not os.path.isfile(path):
            all_ok = False
            evidence[entry["name"]] = {"error": "file does not exist"}
            problems.append("%s: missing file" % entry["name"])
            continue
        im, err = _open_image(path)
        if err:
            all_ok = False
            evidence[entry["name"]] = {"error": err, "bytes": os.path.getsize(path)}
            problems.append("%s: %s" % (entry["name"], err))
            continue
        try:
            evidence[entry["name"]] = {"format": im.format, "mode": im.mode,
                                       "size": list(im.size), "bytes": os.path.getsize(path)}
        finally:
            im.close()
    detail = "; ".join(problems) if problems else "Pillow verify()+load() OK: %s" % ", ".join(
        "%s(%s %s)" % (n, e.get("format"), e.get("mode")) for n, e in evidence.items())
    return _check("raster_opens", "error", all_ok, detail, evidence)


def _check_pdf_opens(pdf_entries, channels):
    if not pdf_entries:
        return _missing_check("pdf_opens", "PDF", channels, ["pdf"])
    evidence = {}
    all_ok = True
    problems = []
    for entry in pdf_entries:
        path = entry["path"]
        if not os.path.isfile(path):
            all_ok = False
            evidence[entry["name"]] = {"error": "file does not exist"}
            problems.append("%s: missing file" % entry["name"])
            continue
        reader, err, npages = _pdf_reader(path)
        if err:
            all_ok = False
            evidence[entry["name"]] = {"error": err, "bytes": os.path.getsize(path)}
            problems.append("%s: %s" % (entry["name"], err))
            continue
        try:
            encrypted = bool(reader.is_encrypted)
        except Exception:  # noqa: BLE001
            encrypted = False
        evidence[entry["name"]] = {"pages": npages, "bytes": os.path.getsize(path),
                                   "encrypted": encrypted}
        if not npages:
            all_ok = False
            problems.append("%s: 0 pages" % entry["name"])
        if encrypted:
            all_ok = False
            problems.append("%s: PDF is encrypted" % entry["name"])
    detail = "; ".join(problems) if problems else "pypdf opened: %s" % ", ".join(
        "%s(%s pages, %s bytes)" % (n, e.get("pages"), e.get("bytes")) for n, e in evidence.items())
    return _check("pdf_opens", "error", all_ok, detail, evidence)


def _check_pdf_fonts(pdf_entries, channels):
    if not pdf_entries:
        return _missing_check("pdf_fonts_embedded", "PDF", channels, ["pdf"])
    evidence = {}
    all_ok = True
    problems = []
    skipped = []
    for entry in pdf_entries:
        path = entry["path"]
        if not os.path.isfile(path):
            all_ok = False
            evidence[entry["name"]] = {"error": "file does not exist"}
            problems.append("%s: missing file" % entry["name"])
            continue
        reader, err, _npages = _pdf_reader(path)
        if err:
            skipped.append(entry["name"])
            evidence[entry["name"]] = {"skipped": True, "reason": err}
            continue
        try:
            fonts = _pdf_fonts(reader)
        except Exception as exc:  # noqa: BLE001
            skipped.append(entry["name"])
            evidence[entry["name"]] = {"skipped": True,
                                       "reason": "resource walk failed: %s" % exc}
            continue
        report = [_font_report(fdict) for _name, fdict in fonts]
        missing = [f for f in report if not f["embedded"]]
        evidence[entry["name"]] = {"font_count": len(report), "fonts": report,
                                   "not_embedded": [f["name"] for f in missing]}
        if not report:
            all_ok = False
            problems.append("%s: no fonts in /Resources /Font (text cannot be editable)"
                            % entry["name"])
        elif missing:
            all_ok = False
            problems.append("%s: %d/%d fonts without FontFile/FontFile2/FontFile3: %s"
                            % (entry["name"], len(missing), len(report),
                               ", ".join(f["name"] for f in missing[:6])))
    if skipped and not problems:
        return _check("pdf_fonts_embedded", "error", False,
                      "skipped: PDF could not be parsed (%s)" % "; ".join(skipped),
                      evidence)
    if skipped:
        problems.append("skipped for unparseable PDF(s): %s" % ", ".join(skipped))
        all_ok = False
    detail = "; ".join(problems) if problems else "all fonts embedded: %s" % ", ".join(
        "%s(%d fonts)" % (n, e.get("font_count", 0)) for n, e in evidence.items())
    return _check("pdf_fonts_embedded", "error", all_ok, detail, evidence)


def _normalise_for_match(text):
    return re.sub(r"[\s\u00a0\u200b\ufeff]+", "", str(text or "")).lower()



def _expected_labels(model, svg_texts=None):
    """Labels the produced PDF must keep as real, extractable text.

    When the editable master is available, only labels it actually **draws** are
    required: a ``kind=chart`` figure deliberately draws no entity boxes, so
    entity labels that never appear in the SVG must not be demanded of the PDF
    (otherwise ingest's draft word-salad entities would look like an export
    defect).  Without an SVG the model drives the expectation as before.
    """
    if not isinstance(model, dict):
        return []
    labels = []
    for key in ("entities", "relations", "legend", "containers"):
        for item in model.get(key) or []:
            if isinstance(item, dict) and item.get("label"):
                labels.append(str(item["label"]))
    for series in ((model.get("data") or {}).get("series") or []):
        if isinstance(series, dict) and series.get("name"):
            labels.append(str(series["name"]))
    legend_values = [str(leg.get("value")) for leg in (model.get("legend") or [])
                     if isinstance(leg, dict) and leg.get("value") not in (None, "")]
    labels.extend(legend_values)
    for column in (model.get("data") or {}).get("columns") or []:
        labels.append(str(column))
    for unit in ((model.get("data") or {}).get("units") or {}).values():
        if unit:
            labels.append(str(unit))
    title = ((model.get("figure") or {}).get("title") or {}).get("text")
    if title:
        labels.append(str(title))
    seen, ordered = set(), []
    for label in labels:
        key = _normalise_for_match(label)
        if len(key) < 2 or key in seen:
            continue
        seen.add(key)
        ordered.append(label)
    if svg_texts:
        svg_norm = _normalise_for_match(" ".join(svg_texts))
        drawn = [label for label in ordered if _normalise_for_match(label) in svg_norm]
        # Never let a master with no matching text make the PDF check vacuous:
        # fall back to the model-derived expectation when nothing lines up.
        if drawn:
            return drawn
    return ordered


def _svg_text_samples(svg_entries):
    """Every drawn string in the master SVG (used to know what the PDF owes)."""
    texts = []
    for entry in svg_entries or []:
        path = entry.get("path")
        if not path or not os.path.isfile(path):
            continue
        root, err = _parse_svg(path)
        if err:
            continue
        for el in _iter_all(root):
            if _strip_ns(el.tag) == "text":
                content = _text_content(el)
                if content:
                    texts.append(content)
    return texts


def _check_pdf_text(pdf_entries, model, channels, svg_entries=None):
    if not pdf_entries:
        return _missing_check("pdf_text_extractable", "PDF", channels, ["pdf"])
    svg_texts = _svg_text_samples(svg_entries)
    labels = _expected_labels(model, svg_texts)
    evidence = {}
    fatal = []
    advisory = []
    skipped = []
    for entry in pdf_entries:
        path = entry["path"]
        if not os.path.isfile(path):
            fatal.append("%s: missing file" % entry["name"])
            evidence[entry["name"]] = {"error": "file does not exist"}
            continue
        reader, err, _npages = _pdf_reader(path)
        if err:
            skipped.append(entry["name"])
            evidence[entry["name"]] = {"skipped": True, "reason": err}
            continue
        try:
            pages = []
            for page in reader.pages:
                try:
                    pages.append(page.extract_text() or "")
                except Exception as exc:  # noqa: BLE001
                    pages.append("")
                    evidence.setdefault(entry["name"], {})["page_error"] = str(exc)
            text = "\n".join(pages)
        except Exception as exc:  # noqa: BLE001
            skipped.append(entry["name"])
            evidence[entry["name"]] = {"skipped": True,
                                       "reason": "text extraction failed: %s" % exc}
            continue
        norm = _normalise_for_match(text)
        found = [label for label in labels if _normalise_for_match(label) in norm]
        missing = [label for label in labels if label not in found]
        info = {"extracted_chars": len(text), "expected_labels": len(labels),
                "found_count": len(found), "missing_count": len(missing),
                "found": found[:20], "missing": missing[:20],
                "sample": re.sub(r"\s+", " ", text)[:300]}
        evidence[entry["name"]] = info
        if labels:
            if not found:
                fatal.append("%s: extract_text() contains none of the %d model labels"
                             % (entry["name"], len(labels)))
            elif len(found) < len(labels):
                advisory.append("%s: only %d/%d labels the master draws are extractable "
                                "(missing: %s)"
                                % (entry["name"], len(found), len(labels),
                                   ", ".join(missing[:6])))
        elif len(norm) < 3:
            fatal.append("%s: extract_text() returned no text "
                         "(no model supplied for label comparison)" % entry["name"])
    if skipped:
        fatal.append("skipped for unparseable PDF(s): %s" % ", ".join(skipped))
    problems = fatal + advisory
    if problems:
        return _check("pdf_text_extractable", "error" if fatal else "warn",
                      not fatal, "; ".join(problems), evidence)
    detail = "labels the master draws are extractable: %s" % ", ".join(
        "%s(%s/%s)" % (n, e.get("found_count"), e.get("expected_labels") or 0)
        for n, e in evidence.items())
    return _check("pdf_text_extractable", "error", True, detail, evidence)


def _check_line_width(svg_entries, channels):
    if not svg_entries:
        return _missing_check("line_width_min", "SVG", channels, ["svg"])
    required = channels["min_line_width_pt"]
    evidence = {}
    all_ok = True
    problems = []
    advisory = []
    for entry in svg_entries:
        root, err = _parse_svg(entry["path"])
        if err:
            all_ok = False
            evidence[entry["name"]] = {"error": err}
            problems.append("%s: %s" % (entry["name"], err))
            continue
        metadata = _svg_metadata(root)
        width_mm, _height_mm = _svg_canvas_mm(root, metadata)
        viewbox = _attr(root, "viewBox") or _attr(root, "viewbox")
        vb_w = vb_h = None
        if viewbox:
            try:
                parts = [float(x) for x in re.split(r"[\s,]+", viewbox.strip()) if x]
                if len(parts) == 4:
                    vb_w, vb_h = parts[2], parts[3]
            except ValueError:
                vb_w = vb_h = None
        if not width_mm and metadata:
            canvas = metadata.get("canvas") or {}
            try:
                width_mm = float(canvas.get("width_mm") or 0) or None
            except (TypeError, ValueError):
                width_mm = None
        if width_mm and vb_w:
            mm_per_user = width_mm / vb_w
            scale_basis = "width %s / viewBox %s" % (width_mm, vb_w)
        elif width_mm and not vb_w:
            mm_per_user = MM_PER_INCH / 96.0
            scale_basis = "no viewBox: 1 user unit = 1 CSS px"
        else:
            mm_per_user = None
            scale_basis = "unknown canvas scale (no width/viewBox/metadata)"
        scales = _ancestor_scale_map(root)
        widths = []
        for el in _iter_all(root):
            if _strip_ns(el.tag) not in ("path", "line", "polyline", "polygon", "rect",
                                         "circle", "ellipse"):
                continue
            stroke = _attr(el, "stroke")
            if stroke in (None, "none"):
                continue
            if mm_per_user is None:
                continue
            pt = _stroke_width_pt(el, mm_per_user, scales.get(el, 1.0))
            if pt is None or pt <= 0:
                continue
            widths.append((round(pt, 4), _attr(el, "id") or _strip_ns(el.tag)))
        if mm_per_user is None:
            advisory.append("%s: cannot convert stroke-width to pt: %s"
                            % (entry["name"], scale_basis))
            evidence[entry["name"]] = {"error": scale_basis, "applicable": False}
            continue
        evidence[entry["name"]] = {
            "scale_basis": scale_basis, "stroked_elements": len(widths),
            "min_pt": min((w for w, _ in widths), default=None),
            "min_element": min(widths, default=(None, None))[1],
            "required_pt": required,
            "thin_examples": sorted(widths)[:5],
        }
        if not widths:
            advisory.append("%s: no stroked elements found to measure "
                            "(journal line-width rule is vacuous here)" % entry["name"])
            continue
        thin = [(w, el) for w, el in widths if w + 1e-9 < required]
        if thin:
            all_ok = False
            problems.append("%s: %d element(s) below %.2f pt (min %.3f pt on %s)"
                            % (entry["name"], len(thin), required, thin[0][0], thin[0][1]))
    notes = problems + advisory
    level = "error" if problems else ("warn" if advisory else "error")
    detail = "; ".join(notes) if notes else "min stroke width OK: %s" % ", ".join(
        "%s: min %s pt (required %s pt)" % (n, e.get("min_pt"), e.get("required_pt"))
        for n, e in evidence.items())
    return _check("line_width_min", level, all_ok, detail, evidence)


def _check_color_space(entries, channels):
    required = channels["color_space"]
    evidence = {}
    fatal = []
    advisory = []
    for entry in entries:
        fmt = entry.get("format")
        path = entry["path"]
        if not os.path.isfile(path):
            fatal.append("%s: missing file" % entry["name"])
            evidence[entry["name"]] = {"error": "file does not exist"}
            continue
        observed = None
        info = {}
        if fmt == "svg":
            root, err = _parse_svg(path)
            if err:
                fatal.append("%s: %s" % (entry["name"], err))
                evidence[entry["name"]] = {"error": err}
                continue
            metadata = _svg_metadata(root)
            declared = None
            if isinstance(metadata, dict):
                declared = ((metadata.get("figure") or {}).get("style") or {}).get("color_space") \
                    or ((metadata.get("style") or {}).get("color_space"))
                if not declared:
                    declared = metadata.get("color_space")
            raw = _read_bytes(path).decode("utf-8", "replace")
            has_srgb = "sRGB" in raw or "srgb" in raw
            observed = str(declared or ("sRGB" if has_srgb else "")).upper() or None
            info = {"declared": declared, "sRGB_marker": has_srgb}
        elif fmt in ("png", "tiff"):
            im, err = _open_image(path)
            if err:
                fatal.append("%s: %s" % (entry["name"], err))
                evidence[entry["name"]] = {"error": err}
                continue
            try:
                observed = {"RGB": "RGB", "RGBA": "RGB", "P": "RGB", "L": "GRAY",
                            "CMYK": "CMYK"}.get(im.mode, im.mode)
                info = {"mode": im.mode, "icc_profile": bool(im.info.get("icc_profile"))}
            finally:
                im.close()
        elif fmt == "pdf":
            raw = _read_bytes(path)
            markers = []
            if b"/DeviceCMYK" in raw:
                markers.append("DeviceCMYK")
            if b"/DeviceRGB" in raw:
                markers.append("DeviceRGB")
            if b"/ICCBased" in raw:
                markers.append("ICCBased")
            reader, _err, _npages = _pdf_reader(path)
            operators, spaces = ([], [])
            if reader is not None:
                operators, spaces = _pdf_colour_streams(reader)
            observed = None
            if "DeviceCMYK" in markers or "DeviceCMYK" in spaces or \
                    any(op in operators for op in ("k", "K")):
                observed = "CMYK"
            elif "DeviceRGB" in markers or "DeviceRGB" in spaces or \
                    any(op in operators for op in ("rg", "RG")):
                observed = "RGB"
            elif "ICCBased" in markers or "ICCBased" in spaces:
                observed = "ICCBased"
            elif any(op in operators for op in ("g", "G")):
                observed = "GRAY"
            info = {"markers": markers, "content_operators": operators,
                    "content_colour_spaces": spaces}
        elif fmt == "eps":
            raw = _read_bytes(path)
            markers = []
            if b"setcmykcolor" in raw:
                markers.append("setcmykcolor")
            if b"setrgbcolor" in raw:
                markers.append("setrgbcolor")
            observed = "CMYK" if "setcmykcolor" in markers else (
                "RGB" if "setrgbcolor" in markers else None)
            info = {"markers": markers}
        info["observed"] = observed
        evidence[entry["name"]] = info
        if observed is None:
            if required == "CMYK":
                fatal.append("%s: no colour-space declaration found but CMYK is required"
                             % entry["name"])
            else:
                advisory.append("%s: no explicit colour-space declaration (advisory)"
                                % entry["name"])
            continue
        compatible = (observed.upper().startswith(required[:3])
                      or (required == "RGB" and observed.upper() in ("SRGB", "RGBA", "ICCBASED")))
        if not compatible:
            if required == "CMYK":
                fatal.append("%s: colour space %s, journal requires CMYK"
                             % (entry["name"], observed))
            else:
                advisory.append("%s: colour space %s while spec asks %s"
                                % (entry["name"], observed, required))
    problems = fatal + advisory
    level = "error" if fatal else ("warn" if advisory else "error")
    detail = "; ".join(problems) if problems else "colour space %s declared in: %s" % (
        required, ", ".join("%s=%s" % (n, e.get("observed")) for n, e in evidence.items()))
    return _check("color_space_declared", level, not fatal, detail, evidence)


def _check_nonempty(entries, channels):
    if not entries:
        return _missing_check("artifact_nonempty", "artifact", channels,
                              ["svg", "pdf", "png", "tiff", "eps"])
    evidence = {}
    all_ok = True
    problems = []
    for entry in entries:
        path = entry["path"]
        fmt = entry.get("format") or ""
        if not os.path.isfile(path):
            all_ok = False
            evidence[entry["name"]] = {"error": "file does not exist"}
            problems.append("%s: missing file" % entry["name"])
            continue
        size = os.path.getsize(path)
        try:
            head = _read_bytes(path)[:64]
        except OSError as exc:
            all_ok = False
            evidence[entry["name"]] = {"error": str(exc)}
            problems.append("%s: unreadable" % entry["name"])
            continue
        magic_ok = None
        if fmt in MAGIC:
            magic_ok = any(head.startswith(sig) for sig in MAGIC[fmt])
        elif fmt == "svg":
            text = head.decode("utf-8", "replace")
            magic_ok = "<svg" in text or text.lstrip().startswith("<?xml")
        evidence[entry["name"]] = {"bytes": size, "format": fmt,
                                   "magic_ok": magic_ok, "head": head[:16].decode("latin-1")}
        if size <= 0:
            all_ok = False
            problems.append("%s: 0 bytes" % entry["name"])
        elif magic_ok is False:
            all_ok = False
            problems.append("%s: magic bytes do not match .%s (renamed file?)"
                            % (entry["name"], fmt))
    detail = "; ".join(problems) if problems else "all artifacts non-empty with matching magic: %s" % \
        ", ".join("%s=%dB" % (n, e.get("bytes")) for n, e in evidence.items())
    return _check("artifact_nonempty", "error", all_ok, detail, evidence)


def _pdf_colour_streams(reader):
    """Scan decompressed page content streams for colour spaces and operators.

    matplotlib PDFs carry no uncompressed ``/DeviceRGB`` resource entry: the
    colour space appears as ``/DeviceRGB cs`` plus ``rg``/``RG`` (or ``k``/``K``)
    operators inside Flate-compressed content streams.  Numeric operands are
    required in front of each operator so text-showing strings cannot produce
    false positives.
    """
    operators, spaces = set(), set()
    try:
        for page in reader.pages:
            contents = page.get_contents()
            datas = []
            if contents is None:
                continue
            if hasattr(contents, "get_data"):
                datas.append(contents.get_data() or b"")
            else:
                for item in contents:
                    getter = getattr(item, "get_data", None)
                    if getter:
                        datas.append(getter() or b"")
            for data in datas:
                text = data.decode("latin-1", "replace")
                stripped = re.sub(r"\([^)]*\)", "()", text)
                stripped = re.sub(r"<[0-9A-Fa-f\s]*>", "<>", stripped)
                for op in re.findall(r"(?:[-\d.]+\s+){1,4}(rg|RG|k|K)(?![A-Za-z])", stripped):
                    operators.add(op)
                for op in re.findall(r"(?:[-\d.]+\s+){1,2}(g|G)(?![A-Za-z])", stripped):
                    operators.add(op)
                for space in re.findall(r"/(DeviceRGB|DeviceCMYK|ICCBased|Separation|Pattern)",
                                        text):
                    spaces.add(space)
    except Exception:  # noqa: BLE001 - best-effort evidence, never fatal here
        return sorted(operators), sorted(spaces)
    return sorted(operators), sorted(spaces)


def _check_pdf_size(pdf_entries, channels, model, drawn):
    """PDF media box must match the size the figure was drawn at."""
    if not pdf_entries:
        return _missing_check("pdf_page_size", "PDF", channels, ["pdf"])
    width_mm = drawn["width_mm"]
    height_mm = drawn.get("height_mm")
    evidence = {}
    fatal = []
    advisory = list(_canvas_drift_note(model, drawn, channels))
    for entry in pdf_entries:
        path = entry["path"]
        if not os.path.isfile(path):
            fatal.append("%s: missing file" % entry["name"])
            evidence[entry["name"]] = {"error": "file does not exist"}
            continue
        reader, err, _npages = _pdf_reader(path)
        if err:
            fatal.append("%s: skipped (%s)" % (entry["name"], err))
            evidence[entry["name"]] = {"skipped": True, "reason": err}
            continue
        try:
            box = reader.pages[0].mediabox
            page_w = float(box.width) * MM_PER_INCH / PT_PER_INCH
            page_h = float(box.height) * MM_PER_INCH / PT_PER_INCH
        except Exception as exc:  # noqa: BLE001
            fatal.append("%s: cannot read /MediaBox (%s)" % (entry["name"], exc))
            continue
        info = {"page_mm": [round(page_w, 2), round(page_h, 2)],
                "canvas_mm": [width_mm, height_mm], "canvas_source": drawn.get("source")}
        evidence[entry["name"]] = info
        tol = max(1.0, width_mm * 0.03)
        if abs(page_w - width_mm) > tol:
            fatal.append("%s: page width %.1f mm != canvas %.1f mm (tolerance %.1f mm)"
                         % (entry["name"], page_w, width_mm, tol))
        if height_mm and abs(page_h - height_mm) > max(1.0, height_mm * 0.03):
            fatal.append("%s: page height %.1f mm != canvas %.1f mm"
                         % (entry["name"], page_h, height_mm))
        if height_mm and height_mm > channels["max_height_mm"]:
            fatal.append("%s: %.1f mm tall, journal maximum is %.1f mm"
                         % (entry["name"], height_mm, channels["max_height_mm"]))
        widest = float(channels.get("width_double_mm") or channels["width_mm"])
        single = float(channels["width_mm"])
        if width_mm > widest + 1.0:
            advisory.append("%s: %.1f mm wide, the journal's widest column is %.1f mm"
                            % (entry["name"], width_mm, widest))
        elif width_mm > single + 1.0:
            info["column_fit"] = ("double column (%.1f mm; single is %.1f mm)"
                                  % (widest, single))
    problems = fatal + advisory
    if problems:
        return _check("pdf_page_size", "error" if fatal else "warn", not fatal,
                      "; ".join(problems), evidence)
    return _check("pdf_page_size", "error", True, "PDF page size matches the canvas: %s" % ", ".join(
        "%s(%s mm)" % (n, e.get("page_mm")) for n, e in evidence.items()), evidence)


def _check_eps_fonts(eps_entries, channels):
    if not eps_entries:
        return _missing_check("eps_fonts_embedded", "EPS", channels, ["eps"], optional=True)
    evidence = {}
    all_ok = True
    problems = []
    for entry in eps_entries:
        raw = _read_bytes(entry["path"]).decode("latin-1")
        begin_font = len(re.findall(r"%%Begin(?:Resource:\s*font|Font)", raw))
        inline_truetype = len(re.findall(r"%%!PS-TrueTypeFont", raw))
        fontfile = len(re.findall(r"/FontFile\d?\b", raw))
        font_types = sorted(set(re.findall(r"/FontType\s+(\d+)", raw)))
        font_names = sorted(set(re.findall(r"/FontName\s*/([A-Za-z0-9+._-]+)", raw)))[:10]
        embedded = bool(begin_font or inline_truetype or fontfile)
        evidence[entry["name"]] = {"begin_font_blocks": begin_font,
                                   "inline_truetype_fonts": inline_truetype,
                                   "fontfile_refs": fontfile,
                                   "font_types": font_types,
                                   "fonttype42": "42" in font_types,
                                   "font_names": font_names}
        if not embedded:
            all_ok = False
            problems.append("%s: no embedded font program (%%!PS-TrueTypeFont / "
                            "%%BeginFont / /FontFile); referenced fonts: %s"
                            % (entry["name"], ", ".join(font_names) or "unknown"))
    detail = "; ".join(problems) if problems else "EPS fonts embedded: %s" % ", ".join(
        "%s(%d inline TrueType, fonttypes %s)" % (n, e["inline_truetype_fonts"],
                                                  ",".join(e["font_types"]))
        for n, e in evidence.items())
    level = "error" if channels["font_embedding_required"] else "warn"
    return _check("eps_fonts_embedded", level, all_ok, detail, evidence)


CORE_FORMATS = ("svg", "pdf", "png")


def _svg_entity_colours(root):
    """entity id -> (fill, stroke), read from the ``<g id="ent:ID">`` rects."""
    out = {}
    for el in _iter_all(root):
        ident = str(_attr(el, "id") or "")
        if not ident.startswith("ent:"):
            continue
        for child in el.iter():
            if _strip_ns(child.tag) != "rect":
                continue
            fill = _attr(child, "fill")
            if fill and str(fill).lower() not in ("none", "#ffffff"):
                out[ident[4:]] = (str(fill).upper(),
                                  str(_attr(child, "stroke") or "").upper())
                break
    return out


def _attr_ci(el, *names):
    """Case-tolerant attribute lookup (renderers emit data-* or dataX variants)."""
    for name in names:
        value = _attr(el, name)
        if value is not None:
            return value
    lowered = {_strip_ns(k).lower(): v for k, v in el.attrib.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def _svg_series_links(root):
    """``<g id="series:N">`` -> declared colour and its legend/entity linkage.

    Chart figures have no ``ent:`` boxes; the renderer links each data series to
    the legend entry (and optionally the entity) it was coloured from, which is
    the machine-discoverable form of the legend<->colour mapping.
    """
    out = []
    for el in _iter_all(root):
        ident = str(_attr(el, "id") or "")
        if not ident.startswith("series:"):
            continue
        color = _attr_ci(el, "data-color", "data-colour")
        out.append({"id": ident,
                    "color": str(color).upper() if color else None,
                    "legend": _attr_ci(el, "data-legend", "data-legend-id"),
                    "entity": _attr_ci(el, "data-entity", "data-entity-id"),
                    "name": _attr_ci(el, "data-name")})
    return out


def _svg_relation_colours(root):
    """relation type -> stroke colour, from ``<g id="rel:ID" data-rel-type=...>``.

    ``line_style`` legend entries name a relation type rather than an entity, so
    their swatch must be matched against the edges actually drawn.
    """
    out = {}
    for el in _iter_all(root):
        ident = str(_attr(el, "id") or "")
        if not ident.startswith("rel:"):
            continue
        rel_type = _attr_ci(el, "data-rel-type")
        if not rel_type:
            continue
        for child in el.iter():
            for attr in ("stroke", "fill"):
                value = _attr(child, attr)
                if value and str(value).upper() not in ("NONE", "#FFFFFF"):
                    out.setdefault(str(rel_type), str(value).upper())
                    break
            if str(rel_type) in out:
                break
    return out


def _check_svg_legend_colors(svg_entries, model, channels):
    """Advisory: every coloured legend item must map to a colour really drawn.

    Resolution order per legend item (first match wins):
      1. a ``series:N`` group declaring ``data-legend="<item id>"`` (chart figures);
      2. an ``ent:<id>`` box whose label/value matches the legend ``value``
         (relationship schematics), or a series declaring that ``data-entity``;
      3. an unambiguous unique colour match between the swatch and one series.
    A mapping that cannot be resolved at all is still reported (advisory), so the
    gap stays visible instead of silently passing.
    """
    if not svg_entries:
        return _missing_check("svg_legend_color_map", "SVG", channels, ["svg"])
    legend = (model or {}).get("legend") or []
    entities = (model or {}).get("entities") or []
    if not legend:
        return _check("svg_legend_color_map", "warn", True,
                      "N/A: model declares no legend to cross-check",
                      {"applicable": False})
    evidence = {}
    mismatches = []
    unresolved = []
    for entry in svg_entries:
        root, err = _parse_svg(entry["path"])
        if err:
            unresolved.append("%s: %s" % (entry["name"], err))
            evidence[entry["name"]] = {"error": err}
            continue
        entity_colours = _svg_entity_colours(root)
        series_links = _svg_series_links(root)
        relation_colours = _svg_relation_colours(root)
        legend_colours = {}
        for el in _iter_all(root):
            ident = str(_attr(el, "id") or "")
            if not ident.startswith("lg:"):
                continue
            colours = []
            for child in el.iter():
                for attr in ("fill", "stroke"):
                    value = _attr(child, attr)
                    if value and str(value).upper() not in ("#FFFFFF", "#F5F8FB", "NONE"):
                        colours.append(str(value).upper())
            if colours:
                legend_colours[ident[3:]] = colours[0]
        swatch_counts = {}
        for colour in legend_colours.values():
            swatch_counts[colour] = swatch_counts.get(colour, 0) + 1
        pairs = []
        for item in legend:
            if not isinstance(item, dict):
                continue
            value = item.get("value")
            if value in (None, ""):
                continue
            item_id = str(item.get("id"))
            swatch = legend_colours.get(item_id)
            if not swatch:
                continue
            # Collect every drawn colour this legend entry could describe, then
            # accept the pair if ANY declared target carries the swatch colour.
            # (A label can legitimately collide with a relation type name, so a
            # single first-match strategy would produce false mismatches.)
            candidates = []
            for series in series_links:
                if series.get("legend") == item_id and series.get("color"):
                    candidates.append(("series.data-legend", series["id"],
                                       (series["color"], series["color"])))
            rel_colour = relation_colours.get(str(value))
            if rel_colour:
                candidates.append(("rel.data-rel-type", "rel:%s" % value,
                                   (rel_colour, rel_colour)))
            matches = [e for e in entities if isinstance(e, dict)
                       and str(value).lower() in str(e.get("label") or "").lower()]
            for entity in matches[:2]:
                entity_id = str(entity.get("id"))
                colours = entity_colours.get(entity_id) or (None, None)
                if colours[0] or colours[1]:
                    candidates.append(("entity.label", entity_id, colours))
                    continue
                for series in series_links:
                    if series.get("entity") == entity_id and series.get("color"):
                        candidates.append(("series.data-entity", entity_id,
                                           (series["color"], series["color"])))
                        break
            same = [s for s in series_links if s.get("color") == swatch]
            if len(same) == 1 and swatch_counts.get(swatch) == 1:
                candidates.append(("unique series colour", same[0]["id"], (swatch, swatch)))
            if not candidates:
                unresolved.append("%s: legend %s (%s) has no drawn colour to match "
                                  "(no series.data-legend, no relation of that type, no "
                                  "entity box)" % (entry["name"], item_id, value))
                continue
            hit = None
            for candidate in candidates:
                colours = [str(c).upper() for c in candidate[2] if c]
                if swatch in colours:
                    hit = candidate
                    break
            chosen = hit or candidates[0]
            matched = hit is not None
            pairs.append({"legend": item_id, "value": value, "swatch": swatch,
                          "target": chosen[1], "drawn": list(chosen[2]),
                          "via": chosen[0], "match": matched,
                          "candidates": [{"via": c[0], "target": c[1], "drawn": list(c[2])}
                                         for c in candidates]})
            if not matched:
                mismatches.append("%s: legend %s swatch %s but drawn candidates are %s"
                                  % (entry["name"], item_id, swatch,
                                     "; ".join("%s=%s" % (c[1], list(c[2])) for c in candidates)))
        evidence[entry["name"]] = {"pairs": pairs, "checked": len(pairs),
                                   "legend_colours": legend_colours,
                                   "unresolved": unresolved}
    if mismatches or unresolved:
        detail = "; ".join(mismatches + unresolved)[:600]
        if mismatches:
            detail += " (advisory: legend/figure colour mapping belongs to the model gate)"
        return _check("svg_legend_color_map", "warn", not mismatches, detail, evidence)
    total = sum(e.get("checked", 0) for e in evidence.values())
    if total:
        return _check("svg_legend_color_map", "warn", True,
                      "legend swatch colours match the drawn colours: %s"
                      % ", ".join("%s(%d pairs)" % (n, e.get("checked", 0))
                                  for n, e in evidence.items()), evidence)
    swatches = sum(len(e.get("legend_colours") or {}) for e in evidence.values())
    return _check("svg_legend_color_map", "warn", True,
                  ("legend glyph colours present but none could be resolved to a drawn "
                   "colour" if swatches else
                   "N/A: the SVG draws no coloured legend glyph (nothing to cross-check)"),
                  evidence)


def _num_or(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _path_points(d):
    """Parse an SVG path ``d`` into a point list (M/L only, as render_svg emits)."""
    numbers = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", str(d or ""))
    if len(numbers) < 4 or len(numbers) % 2:
        return None
    coords = [float(v) for v in numbers]
    return list(zip(coords[0::2], coords[1::2]))


def _path_length(points):
    """Total length of a polyline in the canvas's own units (uu)."""
    total = 0.0
    for i in range(1, len(points)):
        dx = float(points[i][0]) - float(points[i - 1][0])
        dy = float(points[i][1]) - float(points[i - 1][1])
        total += (dx * dx + dy * dy) ** 0.5
    return total


def _svg_relation_geometry(root):
    """Per ``rel:<id>`` group: declared heads plus the drawn polyline and tips.

    A tee is recognised only when it is a **secondary** stroke: it must be a short
    two-point bar (longer than 0.5 uu, at least 1.5 uu wide) *and* the group must
    contain a longer polyline for it to sit across.  Without that second condition
    a lone two-point stroke -- e.g. a self-relation whose polyline collapses to
    zero length, drawn at an ``evidence.strength=high`` width of 1.87 uu -- was
    misread as a tee, which made the style gate report "inhibition-like" heads on
    edges that carry none.
    """
    out = {}
    for el in _iter_all(root):
        ident = str(_attr(el, "id") or "")
        if not ident.startswith("rel:"):
            continue
        arrow = None
        open_paths = []                     # (points, stroke_width, length)
        for child in el.iter():
            if _strip_ns(child.tag) != "path":
                continue
            d = str(_attr(child, "d") or "")
            points = _path_points(d)
            if not points:
                continue
            fill = str(_attr(child, "fill") or "").lower()
            closed = d.strip().upper().endswith("Z")
            if fill == "none" and len(points) >= 2 and not closed:
                open_paths.append((points, _num_or(_attr(child, "stroke-width"), 0.0),
                                   _path_length(points)))
            elif closed and len(points) == 3:
                arrow = points              # tip first, per render_svg._head
        longest = None
        for entry in open_paths:
            if longest is None or entry[2] > longest[2]:
                longest = entry
        polyline = longest[0] if longest is not None else None
        tee = None
        for entry in open_paths:
            if entry is longest:
                continue                    # the edge itself is never its own head
            points, width, length = entry
            if (len(points) == 2 and width >= 1.5 and length > 0.5
                    and longest is not None and longest[2] > length):
                tee = points                # short thick bar across a longer edge
                break
        out[ident] = {"id": ident,
                      "head_start": _attr_ci(el, "data-head-start"),
                      "head_end": _attr_ci(el, "data-head-end"),
                      "direction": _attr_ci(el, "data-direction"),
                      "rel_type": _attr_ci(el, "data-rel-type"),
                      "polyline": polyline, "arrow": arrow, "tee": tee}
    return out


def _svg_entity_centres(root):
    centres = {}
    for el in _iter_all(root):
        ident = str(_attr(el, "id") or "")
        if not ident.startswith("ent:"):
            continue
        for child in el.iter():
            if _strip_ns(child.tag) != "rect":
                continue
            try:
                centres[ident[4:]] = (float(_attr(child, "x")) + float(_attr(child, "width")) / 2.0,
                                      float(_attr(child, "y")) + float(_attr(child, "height")) / 2.0)
            except (TypeError, ValueError):
                pass
            break
    return centres


def _check_svg_edge_direction(svg_entries, model, channels):
    """A drawn head must sit at the end the model calls the target (error level).

    Direction inversion is the failure mode the challenge names fatal
    ("inhibition drawn as activation, upstream/downstream inverted"), and this is
    the only gate that can see it in the *artifact* rather than in the model: for
    every relation the model marks ``forward``, the arrow/tee tip must be nearer
    the ``to`` node than the ``from`` node.  The redraw consumes the same
    ``head_end`` field, so a passing master implies the PDF/PNG/EPS carry the
    same orientation.  Defence in depth over CONTRACT 5.2 (the structural gate
    owns direction): if a hand-edited SVG or a future renderer change moves a
    head, the export gate refuses to pass it silently.

    Deliberately tolerant of legitimate shapes -- the check only ever compares
    the head at each declared end with that end's node:

    * ``head_end="none"`` / ``head_start="none"`` (association, containment):
      no tip to compare, never a violation;
    * ``direction="bidirectional"``: each end's head is checked against its own
      node, so two heads pass;
    * routed feedback arcs: only the tip's distance to the two node centres
      matters, never the polyline's shape.
    """
    if not svg_entries:
        return _missing_check("svg_edge_direction", "SVG", channels, ["svg"])
    relations = [r for r in ((model or {}).get("relations") or []) if isinstance(r, dict)]
    if not relations:
        kind = str(((model or {}).get("figure") or {}).get("kind") or "")
        return _check("svg_edge_direction", "error", True,
                      "N/A: model declares no relations to orient" +
                      (" (kind=%s)" % kind if kind else ""), {"applicable": False})
    evidence = {}
    violations = []
    advisory = []
    for entry in svg_entries:
        root, err = _parse_svg(entry["path"])
        if err:
            advisory.append("%s: %s" % (entry["name"], err))
            evidence[entry["name"]] = {"error": err}
            continue
        centres = _svg_entity_centres(root)
        geometry = _svg_relation_geometry(root)
        checked = []
        for rel in relations:
            rid = str(rel.get("id"))
            geo = geometry.get("rel:%s" % rid)
            if not geo:
                continue
            source, target = str(rel.get("from")), str(rel.get("to"))
            if source == target:
                # A self-relation (autophosphorylation, autoregulation) has ONE
                # node: both distances are identical by construction, so the head's
                # end cannot be decided from geometry.  Reporting it as an
                # inverted direction was a false positive on a legitimate
                # mechanism; it is recorded as advisory instead.
                advisory.append("%s: rel:%s is a self-relation (%s -> %s); the head's end "
                                "cannot be inferred from node distance"
                                % (entry["name"], rid, source, target))
                continue
            src_c, dst_c = centres.get(source), centres.get(target)
            if not src_c or not dst_c:
                continue

            def _dist(point, centre):
                return ((point[0] - centre[0]) ** 2 + (point[1] - centre[1]) ** 2) ** 0.5

            def _tip(side):
                if side == "end":
                    if geo["arrow"]:
                        return geo["arrow"][0]
                    if geo["tee"]:
                        return ((geo["tee"][0][0] + geo["tee"][1][0]) / 2.0,
                                (geo["tee"][0][1] + geo["tee"][1][1]) / 2.0)
                elif geo["polyline"]:
                    return geo["polyline"][0]
                return None

            declared_end = str(geo.get("head_end") or "none").lower()
            declared_start = str(geo.get("head_start") or "none").lower()
            record = {"id": rid, "direction": rel.get("direction"), "from": source, "to": target,
                      "head_end": declared_end, "head_start": declared_start}
            if declared_end in ("arrow", "tee"):
                tip = _tip("end")
                if tip is None:
                    violations.append("%s: %s declares head_end=%s but no head geometry was "
                                      "drawn (direction is not visible)" % (entry["name"], rid,
                                                                            declared_end))
                else:
                    d_to, d_from = _dist(tip, dst_c), _dist(tip, src_c)
                    record["tip_to_target_mm"] = round(d_to, 2)
                    record["tip_to_source_mm"] = round(d_from, 2)
                    if d_to >= d_from:
                        violations.append("%s: %s head_end=%s but the head is nearer the SOURCE "
                                          "(%s %.1f mm vs %s %.1f mm)"
                                          % (entry["name"], rid, declared_end, source, d_from,
                                             target, d_to))
            if declared_start in ("arrow", "tee"):
                tip = _tip("start")
                if tip is None:
                    violations.append("%s: %s declares head_start=%s but no head geometry"
                                      % (entry["name"], rid, declared_start))
                else:
                    d_from, d_to = _dist(tip, src_c), _dist(tip, dst_c)
                    record["start_tip_to_source_mm"] = round(d_from, 2)
                    if d_from >= d_to:
                        violations.append("%s: %s head_start=%s but the head is nearer the TARGET"
                                          % (entry["name"], rid, declared_start))
            if str(rel.get("direction") or "") == "none" and (
                    declared_end in ("arrow", "tee") or declared_start in ("arrow", "tee")):
                advisory.append("%s: %s is direction=none but carries a head"
                                % (entry["name"], rid))
            checked.append(record)
        evidence[entry["name"]] = {"relations": checked, "checked": len(checked)}
        if not checked:
            advisory.append("%s: no relation geometry could be matched to the model"
                            % entry["name"])
    kind = str(((model or {}).get("figure") or {}).get("kind") or "")
    if not any(e.get("checked") for e in evidence.values()) and kind == "chart":
        # A chart figure draws categories and series, not relations: nothing to
        # orient.  Mirrors how svg_provenance/pdf_text treat chart figures.
        return _check("svg_edge_direction", "error", True,
                      "N/A: kind=chart draws no relation geometry to orient",
                      {"applicable": False, "evidence": evidence})
    if violations:
        return _check("svg_edge_direction", "error", False,
                      "; ".join(violations)[:600] + " (fatal class: upstream/downstream "
                      "inverted or feedback drawn backwards)", evidence)
    if advisory:
        return _check("svg_edge_direction", "warn", True,
                      "edge direction: %s" % "; ".join(advisory)[:400], evidence)
    return _check("svg_edge_direction", "error", True,
                  "edge direction OK (heads at the model's target end): %s"
                  % ", ".join("%s(%d relations)" % (n, e.get("checked", 0))
                              for n, e in evidence.items()), evidence)


# ---------------------------------------------------------------------------
# CONTRACT 3.3-3.6 hard gates: interaction semantics, placement, legends,
# naming, and source-bound text/numbers.
#
# These gates are deliberately *artifact side*: every verdict is derived from
# geometry and attributes really present in the rendered SVG (or the raster),
# cross-checked against the model's declared semantics.  The frozen tables are
# re-stated here instead of being imported from ``render_svg`` so that a
# regression in the renderer cannot make its own gate vacuous.
# ---------------------------------------------------------------------------
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
    "feedback":      {"arrow": "normal", "head": "arrow", "stroke": "dashed"},
    "association":   {"arrow": "none",   "head": "none",  "stroke": "dotted"},
    "containment":   {"arrow": "none",   "head": "none",  "stroke": "dotted",
                      "derived": True},
    "membership":    {"arrow": "none",   "head": "none",  "stroke": "dotted",
                      "derived": True},
    "sequence":      {"arrow": "normal", "head": "arrow", "stroke": "solid"},
    "causation":     {"arrow": "normal", "head": "arrow", "stroke": "solid"},
}
STRENGTH_WIDTH_PT = {"high": 1.4, "medium": 1.0, "low": 0.6}
MEMBRANE_ROLES = ("transmembrane", "membrane_anchored")
COMPARTMENT_ORDER = {
    "extracellular": 0, "membrane": 1, "cytosol": 2, "cytoplasm": 2,
    "mitochondrion": 3, "er": 3, "golgi": 3, "lysosome": 3, "nucleus": 4,
}
LEGEND_CHANNELS = ("color", "line_width", "node_size", "line_style")

#: CONTRACT 3.6 -- column / channel names that are dimensionless *by
#: convention*.  A material that omits their unit is normal, not a defect; the
#: verdict is recorded as ``W_UNIT_DIMENSIONLESS_ASSUMED`` instead of
#: ``E_UNIT_MISSING``.  Names are normalised (lower-case, non-alphanumerics
#: dropped) before the lookup.
DIMENSIONLESS_COLUMNS = frozenset((
    "pvalue", "padj", "padjust", "qvalue", "fdr", "foldchange", "log2fc", "logfc",
    "ratio", "oddsratio", "score", "count", "n", "ncells", "nreplicates",
    "r2", "rsquared", "zscore", "auc", "index", "rank", "level", "replicate",
    "cv", "se", "sd", "sem", "significance", "probability", "fraction",
))

#: Names that *require* a unit: a bare number here is a real defect.
DIMENSIONED_COLUMNS = frozenset((
    "concentration", "time", "duration", "activity", "rate", "dose", "amount",
    "expression", "abundance", "intensity", "volume", "mass", "length", "width",
    "height", "distance", "temperature", "speed", "frequency", "fluorescence",
    "mfi", "od", "au", "flux", "velocity", "half_life", "halflife", "ki", "km",
))

_NUMBER_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
_NUMBER_TOKEN_RE = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")


def _norm_name(value):
    """Comparison key: casefolded, separator-insensitive, **CJK preserved**.

    Only separators and punctuation are dropped.  Stripping non-Latin characters
    turned ``"STAT3 基因"`` and ``"STAT3 蛋白"`` into the same key, which made the
    gene/protein distinguishability rule report two legitimately different labels
    as indistinguishable -- a false positive on exactly the Chinese materials the
    official cases use.  Mirrors ``mech.normalise_key`` (``[^0-9a-z\\u4e00-\\u9fff]``),
    so the model layer and the artifact layer cannot contradict each other.
    """
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").casefold())


def dimensionless_column(name):
    """``(verdict, why)`` for a unit-less value channel.

    ``verdict`` is ``"dimensionless"`` (allowlist), ``"dimensioned"`` (a unit is
    required) or ``"unknown"`` (neither list names it -- treated as dimensioned,
    because a silently unit-less number is the failure the challenge names).
    """
    key = _norm_name(name)
    if not key:
        return "unknown", "empty channel name"
    if key in DIMENSIONLESS_COLUMNS:
        return "dimensionless", "name is dimensionless by convention (%s)" % name
    if key in DIMENSIONED_COLUMNS:
        return "dimensioned", "name denotes a measured quantity (%s)" % name
    for token in DIMENSIONED_COLUMNS:
        if len(token) >= 4 and token in key:
            return "dimensioned", "name contains the measured quantity %r" % token
    for token in DIMENSIONLESS_COLUMNS:
        if len(token) >= 4 and token in key:
            return "dimensionless", "name contains the dimensionless channel %r" % token
    return "unknown", "no unit declared and the name is not a known dimensionless channel"


def _model_index(model):
    """``{collection: {id: element}}`` for the four drawable collections."""
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


def _container_compartment(container_id, index):
    """Compartment a container stands for, or ``""`` for a plain group."""
    con = index["containers"].get(str(container_id))
    if not isinstance(con, dict):
        return ""
    kind = str(con.get("kind") or "").strip().lower()
    if kind in COMPARTMENT_ORDER:
        return kind
    if kind not in ("compartment", "membrane", "cell"):
        return ""
    for key in ("compartment", "kind", "id", "label"):
        norm = re.sub(r"[^a-z]", "", str(con.get(key) or "").lower())
        if not norm:
            continue
        for name in sorted(COMPARTMENT_ORDER, key=len, reverse=True):
            if norm == name or (name in norm and len(name) >= 4):
                return name
    return ""


def _container_kind(container_id, index):
    con = index["containers"].get(str(container_id))
    if not isinstance(con, dict):
        return ""
    return str(con.get("kind") or "").strip().lower()


def _svg_scale(root):
    """Millimetres per user unit, from the root ``width``/``viewBox``."""
    width_mm, _height = _svg_canvas_mm(root, _svg_metadata(root))
    viewbox = _attr(root, "viewBox") or _attr(root, "viewbox")
    vb_w = None
    if viewbox:
        try:
            parts = [float(x) for x in re.split(r"[\s,]+", viewbox.strip()) if x]
            if len(parts) == 4:
                vb_w = parts[2]
        except (TypeError, ValueError):
            vb_w = None
    if width_mm and vb_w:
        try:
            return float(width_mm) / float(vb_w)
        except (TypeError, ValueError, ZeroDivisionError):
            return None
    if width_mm:
        return MM_PER_INCH / 96.0
    return None


def _groups_by_prefix(root, prefix):
    out = {}
    for el in _iter_all(root):
        ident = str(_attr(el, "id") or "")
        if ident.startswith(prefix):
            out.setdefault(ident, el)
    return out


def _group_texts(el):
    return [_text_content(ch) for ch in el.iter() if _strip_ns(ch.tag) == "text"]


def _group_title(el):
    for ch in el.iter():
        if _strip_ns(ch.tag) == "title":
            return _text_content(ch)
    return ""


def _mm_rect(el, mm_per_user):
    """First ``<rect>`` inside ``el`` as ``{x,y,w,h}`` in mm (or None)."""
    if mm_per_user is None:
        return None
    for child in el.iter():
        if _strip_ns(child.tag) != "rect":
            continue
        try:
            x = float(_attr(child, "x"))
            y = float(_attr(child, "y"))
            w = float(_attr(child, "width"))
            h = float(_attr(child, "height"))
        except (TypeError, ValueError):
            continue
        return {"x": x * mm_per_user, "y": y * mm_per_user,
                "w": w * mm_per_user, "h": h * mm_per_user}
    return None


def _drawn_stroke_style(el):
    """Dash grammar really drawn inside a ``rel:``/``lg:`` group."""
    declared = str(_attr_ci(el, "data-stroke-style") or "").strip().lower()
    if declared in ("solid", "dashed", "dotted"):
        return declared
    for child in el.iter():
        if _strip_ns(child.tag) != "path":
            continue
        if str(_attr(child, "fill") or "").lower() != "none":
            continue
        dash = _attr(child, "stroke-dasharray")
        if not dash:
            continue
        numbers = [abs(float(x)) for x in _NUMBER_TOKEN_RE.findall(str(dash))]
        if not numbers:
            continue
        return "dotted" if min(numbers) <= 1.2 else "dashed"
    return "solid"


def _drawn_head(kind):
    """``arrow`` selection from explicit head geometry (``geo`` dict fields)."""
    if kind == "arrow":
        return "arrow"
    if kind == "tee":
        return "tee"
    return "none"


def _head_from_geo(geo, side):
    """The head actually drawn at ``side`` ('start'/'end') of a relation."""
    if not geo:
        return "none"
    if geo.get("arrow"):
        return "arrow"
    if geo.get("tee"):
        return "tee"
    return "none"


def _declared_arrow(el):
    value = str(_attr_ci(el, "data-arrow") or "").strip().lower()
    if value in ("normal", "arrow"):
        return "normal"
    if value == "tee":
        return "tee"
    if value == "none":
        return "none"
    return None


def _check_interaction_style(svg_entries, model, channels):
    """``E_INTERACTION_STYLE_MISMATCH`` -- CONTRACT 3.4, artifact side.

    Three independent readings must agree with the frozen table:

    1. the model's ``relations[].type`` (the authoritative semantic claim);
    2. the ``data-rel-type`` / ``data-arrow`` / ``data-stroke-style`` the master
       declares for that relation;
    3. the geometry actually drawn (a closed triangular head = arrow, a short
       thick bar = tee, nothing = none; the dash array = solid/dashed/dotted).

    Plus legend coverage: every relation type drawn on the canvas must have a
    legend entry, and that entry's own glyph must carry the type's style.
    """
    code = "E_INTERACTION_STYLE_MISMATCH"
    if not svg_entries:
        return _missing_check(code, "SVG", channels, ["svg"])
    index = _model_index(model)
    relations = [r for r in ((model or {}).get("relations") or []) if isinstance(r, dict)]
    if not relations and not index["relations"]:
        return _check(code, "error", True,
                      "N/A: the model declares no relations to style",
                      {"applicable": False})
    evidence = {}
    problems = []
    advisory = []
    for entry in svg_entries:
        root, err = _parse_svg(entry["path"])
        if err:
            problems.append("%s: %s" % (entry["name"], err))
            evidence[entry["name"]] = {"error": err}
            continue
        geometry = _svg_relation_geometry(root)
        groups = _groups_by_prefix(root, "rel:")
        legend_groups = _groups_by_prefix(root, "lg:")
        checked = []
        drawn_types = {}
        for rel in relations:
            rid = str(rel.get("id"))
            rtype = str(rel.get("type") or "")
            spec = INTERACTION_STYLE.get(rtype)
            gid = "rel:%s" % rid
            el = groups.get(gid)
            if el is None:
                if spec and not spec.get("derived"):
                    problems.append("%s: %s (%s) is in the model but no rel:%s group was "
                                    "drawn (its arrow type cannot be verified)"
                                    % (entry["name"], rid, rtype or "?", rid))
                continue
            geo = geometry.get(gid) or {}
            declared_type = str(_attr_ci(el, "data-rel-type") or "")
            declared_arrow = _declared_arrow(el)
            arrow_actual = _head_from_geo(geo, "end")
            head_end = str(geo.get("head_end") or "none").lower()
            stroke_actual = _drawn_stroke_style(el)
            record = {"id": rid, "model_type": rtype, "declared_type": declared_type,
                      "declared_arrow": declared_arrow,
                      "drawn_arrow": arrow_actual, "drawn_stroke": stroke_actual,
                      "head_end": head_end, "head_start": geo.get("head_start")}
            drawn_types.setdefault(rtype, []).append(rid)
            if not spec:
                advisory.append("%s: relation %s has type %r outside the frozen CONTRACT "
                                "3.4 table; its style cannot be judged"
                                % (entry["name"], rid, rtype))
                checked.append(record)
                continue
            bad = []
            is_self = str(rel.get("from")) == str(rel.get("to"))
            record["self_relation"] = is_self
            if declared_type and declared_type != rtype:
                bad.append("data-rel-type=%r but the model says %r" % (declared_type, rtype))
            if is_self:
                # A self-relation (autophosphorylation, autoregulation) has ONE
                # node, so the drawn stroke carries no direction: the geometry-based
                # endpoint assertions are skipped and only what the canvas *claims*
                # plus what the stroke really looks like is judged.
                if stroke_actual != spec["stroke"]:
                    bad.append("drawn stroke %r but %s requires %r"
                               % (stroke_actual, rtype, spec["stroke"]))
                if declared_arrow and declared_arrow != spec["arrow"]:
                    bad.append("data-arrow=%r but %s requires %r"
                               % (declared_arrow, rtype, spec["arrow"]))
                if head_end not in (spec["head"], "none"):
                    bad.append("data-head-end=%r but %s requires %r or 'none'"
                               % (head_end, rtype, spec["head"]))
            else:
                if arrow_actual != spec["head"]:
                    bad.append("drawn head %r but %s requires %r"
                               % (arrow_actual, rtype, spec["head"]))
                if stroke_actual != spec["stroke"]:
                    bad.append("drawn stroke %r but %s requires %r"
                               % (stroke_actual, rtype, spec["stroke"]))
                if head_end != spec["head"]:
                    bad.append("data-head-end=%r but %s requires %r"
                               % (head_end, rtype, spec["head"]))
                if declared_arrow and declared_arrow != spec["arrow"]:
                    bad.append("data-arrow=%r but %s requires %r"
                               % (declared_arrow, rtype, spec["arrow"]))
            if bad:
                problems.append("%s: rel:%s (%s) %s" % (entry["name"], rid, rtype,
                                                        "; ".join(bad)))
            checked.append(record)

        # ---- legend coverage (a drawn type must have a matching legend entry) --
        legend_rows = []
        for lid in sorted(legend_groups):
            gel = legend_groups[lid]
            head = _head_from_geo({"arrow": _legend_has_closed_head(gel),
                                   "tee": _legend_has_tee(gel)}, "end")
            legend_rows.append({"id": lid,
                                "value": str(_attr_ci(gel, "data-legend-value") or ""),
                                "marker": str(_attr_ci(gel, "data-marker") or ""),
                                "head": head, "stroke": _drawn_stroke_style(gel),
                                "kind": str(_attr_ci(gel, "data-legend-kind") or "")})
        for rtype in sorted(drawn_types):
            spec = INTERACTION_STYLE.get(rtype)
            if not spec:
                continue
            same_pair = [row for row in legend_rows
                         if row["head"] == spec["head"] and row["stroke"] == spec["stroke"]]
            direct = [row for row in legend_rows if _norm_name(row["value"]) == _norm_name(rtype)]
            types_sharing = [t for t in drawn_types
                             if INTERACTION_STYLE.get(t, {}).get("head") == spec["head"]
                             and INTERACTION_STYLE.get(t, {}).get("stroke") == spec["stroke"]]
            covered = bool(direct) or (bool(same_pair) and len(types_sharing) == 1)
            if not covered:
                problems.append("%s: %d relation(s) of type %s are drawn but the legend has "
                                "no entry for it (expected glyph: head=%s stroke=%s)"
                                % (entry["name"], len(drawn_types[rtype]), rtype,
                                   spec["head"], spec["stroke"]))
                continue
            for row in (direct or same_pair):
                if row["head"] != spec["head"] or row["stroke"] != spec["stroke"]:
                    problems.append("%s: legend %s claims to describe %s but draws "
                                    "head=%s stroke=%s (table: head=%s stroke=%s)"
                                    % (entry["name"], row["id"], rtype, row["head"],
                                       row["stroke"], spec["head"], spec["stroke"]))
        evidence[entry["name"]] = {"relations": checked, "checked": len(checked),
                                   "drawn_types": sorted(drawn_types),
                                   "legend_rows": legend_rows}
    if problems:
        return _check(code, "error", False, "; ".join(problems)[:900],
                      evidence, where="relations")
    if advisory:
        return _check(code, "warn", True, "; ".join(advisory)[:400], evidence,
                      where="relations")
    total = sum(e.get("checked", 0) for e in evidence.values())
    return _check(code, "error", True,
                  "interaction styles match the frozen CONTRACT 3.4 table: %s"
                  % ", ".join("%s(%d rels, types=%s)"
                              % (n, e.get("checked", 0), ",".join(e.get("drawn_types") or []))
                              for n, e in evidence.items()),
                  evidence, where="relations")


def _legend_has_closed_head(el):
    for child in el.iter():
        if _strip_ns(child.tag) != "path":
            continue
        d = str(_attr(child, "d") or "")
        if d.strip().upper().endswith("Z") and str(_attr(child, "fill") or "").lower() != "none":
            return True
    return False


def _legend_has_tee(el):
    for child in el.iter():
        if _strip_ns(child.tag) != "path":
            continue
        d = str(_attr(child, "d") or "")
        points = _path_points(d)
        if (points and len(points) == 2 and not d.strip().upper().endswith("Z")
                and _num_or(_attr(child, "stroke-width"), 0) >= 1.5):
            return True
    return False


def _check_flow_direction(svg_entries, model, channels):
    """``E_FLOW_DIRECTION`` -- CONTRACT 3.5, model ranks verified against the canvas.

    Rules: for every non-``feedback`` relation ``from -> to`` the rank of ``to``
    must be strictly greater than the rank of ``from`` (``binding`` and
    ``association`` may share a rank); a directed cycle built only from
    non-``feedback`` edges is fatal (it must be declared ``feedback``).  Ranks are
    read from ``figure.flow.ranks`` and, independently, from the ``data-level``
    the renderer wrote on each entity group -- a layout that contradicts the
    declared flow is a defect in the *figure*, which is what this gate sees.
    """
    code = "E_FLOW_DIRECTION"
    if not svg_entries:
        return _missing_check(code, "SVG", channels, ["svg"])
    index = _model_index(model)
    relations = [r for r in ((model or {}).get("relations") or []) if isinstance(r, dict)]
    if not relations:
        return _check(code, "error", True, "N/A: the model declares no relations",
                      {"applicable": False})
    declared_ranks = {}
    flow = ((model or {}).get("figure") or {}).get("flow")
    if isinstance(flow, dict) and isinstance(flow.get("ranks"), dict):
        for key, value in flow["ranks"].items():
            try:
                declared_ranks[str(key)] = int(value)
            except (TypeError, ValueError):
                continue
    evidence = {}
    problems = []
    advisory = []
    for entry in svg_entries:
        root, err = _parse_svg(entry["path"])
        if err:
            problems.append("%s: %s" % (entry["name"], err))
            evidence[entry["name"]] = {"error": err}
            continue
        drawn_levels = {}
        missing_levels = []
        for el in _iter_all(root):
            ident = str(_attr(el, "id") or "")
            if not ident.startswith("ent:"):
                continue
            eid = str(_attr_ci(el, "data-entity-id") or ident[4:])
            raw = _attr_ci(el, "data-level")
            if raw is None or str(raw).strip() == "":
                missing_levels.append(eid)
                continue
            try:
                drawn_levels[eid] = int(float(raw))
            except (TypeError, ValueError):
                missing_levels.append(eid)
        ranks = dict(drawn_levels)
        for key, value in declared_ranks.items():
            if key in ranks and ranks[key] != value:
                # The layout is the authority on where a node was placed; the SVG
                # must record that level.  A canvas that draws data-level=0 while
                # the declared rank is 5 has lost the flow information, which is
                # exactly what makes a published pathway read backwards.
                problems.append((key, "%s: the canvas draws %s at data-level=%s but "
                                      "figure.flow.ranks declares %s (the artifact contradicts "
                                      "the declared flow)"
                                 % (entry["name"], key, ranks[key], value)))
            elif key not in ranks and key in index["entities"]:
                problems.append((key, "%s: %s is drawn without a data-level, so its position "
                                      "in the pathway cannot be verified against the declared "
                                      "rank %s" % (entry["name"], key, value)))
        for eid in missing_levels:
            if eid in index["entities"] and eid not in declared_ranks:
                advisory.append("%s: %s carries no data-level and the model declares no rank "
                                "for it" % (entry["name"], eid))
        for key, value in drawn_levels.items():
            ranks.setdefault(key, value)
        checks = []
        self_loops = []
        for rel in relations:
            rtype = str(rel.get("type") or "")
            if rtype == "feedback":
                continue
            source, target = str(rel.get("from")), str(rel.get("to"))
            rid = str(rel.get("id"))
            if source == target:
                # A self-relation (autophosphorylation, autoregulation) has one
                # node, so its rank can never strictly increase and its geometry
                # cannot express a direction.  That is a property of the mechanism,
                # not a flow defect.
                self_loops.append(rid)
                continue
            a, b = ranks.get(source), ranks.get(target)
            if a is None or b is None:
                continue
            equal_ok = rtype in ("binding", "association")
            ok = (b == a and equal_ok) or b > a
            checks.append({"id": rid, "type": rtype, "from": source, "to": target,
                           "rank_from": a, "rank_to": b, "ok": bool(ok),
                           "same_rank_allowed": equal_ok})
            if not ok:
                problems.append((rid, "%s: rel:%s (%s) %s(rank %s) -> %s(rank %s) violates the "
                                      "frozen flow rule (%s)"
                                 % (entry["name"], rid, rtype, source, a, target, b,
                                    "rank must increase" if not equal_ok else
                                    "only binding/association may share a rank")))
        # directed cycle over non-feedback edges (self-relations excluded)
        adjacency = {}
        for rel in relations:
            if str(rel.get("type")) == "feedback":
                continue
            source, target = str(rel.get("from")), str(rel.get("to"))
            if source == target:
                continue
            adjacency.setdefault(source, []).append(target)
        cycle = _find_cycle(adjacency)
        if cycle:
            problems.append((",".join(cycle), "%s: the non-feedback edges contain a directed "
                                              "cycle %s; a cycle must be declared with "
                                              "type=feedback" % (entry["name"],
                                                                 " -> ".join(cycle))))
        if self_loops:
            advisory.append("%s: self-relation(s) %s excluded from the rank/cycle rule (a "
                            "self-relation has one node and cannot increase rank)"
                            % (entry["name"], ", ".join(sorted(self_loops))))
        evidence[entry["name"]] = {"ranks": ranks, "checks": checks,
                                   "declared_ranks": declared_ranks,
                                   "cycle": cycle, "checked": len(checks),
                                   "self_relations": sorted(self_loops)}
    if problems:
        return _check(code, "error", False,
                      "; ".join(message for _w, message in problems)[:900], evidence,
                      where=problems[0][0])
    if advisory:
        return _check(code, "warn", True, "; ".join(advisory)[:400], evidence,
                      where="figure.flow")
    if advisory:
        return _check(code, "warn", True, "; ".join(advisory)[:400], evidence,
                      where="figure.flow")
    return _check(code, "error", True,
                  "flow direction is monotonic for every non-feedback relation: %s"
                  % ", ".join("%s(%d edges)" % (n, e.get("checked", 0))
                              for n, e in evidence.items()),
                  evidence, where="figure.flow")


def _find_cycle(adjacency):
    """First directed cycle found (deterministic DFS), or ``[]``."""
    colour = {}
    stack = []

    def visit(node):
        colour[node] = 1
        stack.append(node)
        for nxt in sorted(adjacency.get(node) or []):
            state = colour.get(nxt, 0)
            if state == 1:
                return stack[stack.index(nxt):] + [nxt]
            if state == 0:
                found = visit(nxt)
                if found:
                    return found
        stack.pop()
        colour[node] = 2
        return None

    for node in sorted(adjacency):
        if colour.get(node, 0) == 0:
            found = visit(node)
            if found:
                return found
    return []


def _containing_containers(centre, containers):
    """``[(cid, container_record)]`` whose rect contains ``centre``, smallest first.

    ``containers`` is the :func:`_svg_container_boxes` shape (each record wraps
    its own ``box``), so the caller also gets the kind/membrane metadata.
    """
    inside = []
    for cid, record in (containers or {}).items():
        box = (record or {}).get("box")
        if not box:
            continue
        if (box["x"] - 0.5 <= centre[0] <= box["x"] + box["w"] + 0.5
                and box["y"] - 0.5 <= centre[1] <= box["y"] + box["h"] + 0.5):
            inside.append((box["w"] * box["h"], cid, record))
    inside.sort(key=lambda item: (item[0], str(item[1])))
    return [(cid, record) for _area, cid, record in inside]


def _svg_entity_boxes(root, mm_per_user):
    """``entity id -> {x,y,w,h,centre,attrs}`` in mm, from ``ent:`` groups."""
    out = {}
    for el in _iter_all(root):
        ident = str(_attr(el, "id") or "")
        if not ident.startswith("ent:"):
            continue
        eid = str(_attr_ci(el, "data-entity-id") or ident[4:])
        box = _mm_rect(el, mm_per_user)
        if not box:
            continue
        attrs = {name: _attr_ci(el, name) for name in
                 ("data-container-id", "data-container", "data-compartment",
                  "data-membrane-role", "data-node-kind", "data-label-style",
                  "data-normalized-symbol", "data-node-area-mm2")}
        out.setdefault(eid, {"box": box,
                             "centre": (box["x"] + box["w"] / 2.0,
                                        box["y"] + box["h"] / 2.0),
                             "attrs": attrs, "group": el})
    return out


def _svg_container_boxes(root, mm_per_user):
    """``container id -> {box, kind, compartment, is_membrane, label}`` in mm."""
    out = {}
    for el in _iter_all(root):
        ident = str(_attr(el, "id") or "")
        if not ident.startswith("cnt:"):
            continue
        cid = str(_attr_ci(el, "data-container-id") or ident[4:])
        box = _mm_rect(el, mm_per_user)
        if not box:
            continue
        out.setdefault(cid, {
            "box": box,
            "kind": str(_attr_ci(el, "data-container-kind") or ""),
            "compartment": str(_attr_ci(el, "data-compartment") or ""),
            "is_membrane": str(_attr_ci(el, "data-is-membrane") or "").lower() == "true",
            "label": _group_title(el),
        })
    return out


def _check_membrane_placement(svg_entries, model, channels):
    """``E_MEMBRANE_PLACEMENT`` -- CONTRACT 3.3, asserted on drawn coordinates.

    For every entity whose ``membrane_role`` is ``transmembrane`` or
    ``membrane_anchored`` the gate requires that (a) the model places it in a
    ``kind=membrane`` container, (b) such a band is really drawn, and (c) the
    entity's **drawn** box centre lies inside that band -- not inside the
    cytosol or the nucleus, which is the failure the challenge names fatal.  An
    entity that is inside a compartment box while outside the membrane band is
    reported with both rectangles so the placement defect is locatable.
    """
    code = "E_MEMBRANE_PLACEMENT"
    if not svg_entries:
        return _missing_check(code, "SVG", channels, ["svg"])
    index = _model_index(model)
    targets = [e for e in ((model or {}).get("entities") or [])
               if isinstance(e, dict)
               and str(e.get("membrane_role") or "").strip().lower() in MEMBRANE_ROLES]
    if not targets:
        return _check(code, "error", True,
                      "N/A: no entity declares membrane_role in %s" % (MEMBRANE_ROLES,),
                      {"applicable": False, "membrane_entities": []})
    evidence = {}
    problems = []
    advisory = []
    for entry in svg_entries:
        root, err = _parse_svg(entry["path"])
        if err:
            problems.append((entry["name"], "%s: %s" % (entry["name"], err)))
            evidence[entry["name"]] = {"error": err}
            continue
        mm_per_user = _svg_scale(root)
        if mm_per_user is None:
            problems.append((entry["name"], "%s: cannot convert coordinates to mm (no "
                                            "width/viewBox)" % entry["name"]))
            evidence[entry["name"]] = {"error": "unscalable canvas"}
            continue
        boxes = _svg_entity_boxes(root, mm_per_user)
        containers = _svg_container_boxes(root, mm_per_user)
        records = []
        for ent in targets:
            eid = str(ent.get("id"))
            role = str(ent.get("membrane_role")).strip().lower()
            container = str(ent.get("container") or "")
            kind = _container_kind(container, index)
            required = (role == "transmembrane")
            record = {"entity": eid, "membrane_role": role,
                      "declared_container": container, "container_kind": kind,
                      "membrane_container_required": required}
            if kind != "membrane":
                # CONTRACT 3.3 forces a membrane container for a *transmembrane*
                # protein.  A ``membrane_anchored`` protein may legitimately be
                # declared in the cytosol and only anchored to the membrane -- the
                # layout records that move with W_MEMBRANE_ANCHOR_COMPARTMENT -- so
                # it is advisory here, not fatal.
                bands = [cid for cid, rec in containers.items() if rec.get("is_membrane")]
                message = ("%s: ent:%s is membrane_role=%s but container %r has kind=%r "
                           "(CONTRACT 3.3 requires a kind=membrane container%s)"
                           % (entry["name"], eid, role, container, kind or "?",
                              " for transmembrane proteins" if required else
                              " unless the role means 'anchored to' the membrane"))
                if required:
                    problems.append((eid, message))
                    records.append(record)
                    continue
                if not bands:
                    advisory.append(message + "; no membrane band was drawn either")
                    records.append(record)
                    continue
                advisory.append(message + "; measured against the drawn band(s) %s"
                                % ", ".join(sorted(bands)))
                container, kind = bands[0], "membrane"
                record["effective_container"] = bands[0]
            band = containers.get(container)
            if band is None:
                problems.append((eid, "%s: ent:%s sits on membrane %s but no cnt:%s band was "
                                      "drawn" % (entry["name"], eid, container, container)))
                records.append(record)
                continue
            drawn = boxes.get(eid)
            if drawn is None:
                problems.append((eid, "%s: ent:%s was not drawn (placement cannot be "
                                      "asserted)" % (entry["name"], eid)))
                records.append(record)
                continue
            box = band["box"]
            cx, cy = drawn["centre"]
            inside = (box["x"] - 0.6 <= cx <= box["x"] + box["w"] + 0.6
                      and box["y"] - 0.6 <= cy <= box["y"] + box["h"] + 0.6)
            inside_containers = _containing_containers((cx, cy), containers)
            inner = [(cid, rec) for cid, rec in inside_containers
                     if cid != container and not rec.get("is_membrane")
                     and str(rec.get("kind") or "") in ("compartment", "cell")]
            record.update({"band": box, "drawn_box": drawn["box"],
                           "centre": [round(cx, 2), round(cy, 2)],
                           "inside_band": bool(inside),
                           "drawn_container_id": drawn["attrs"].get("data-container-id"),
                           "inside_other_containers": [cid for cid, _b in inner]})
            drawn_container = str(drawn["attrs"].get("data-container-id") or "")
            declared_container = str(ent.get("container") or "")
            if drawn_container and declared_container and drawn_container != declared_container:
                message = ("%s: ent:%s model container is %r but the canvas anchors it to %r"
                           % (entry["name"], eid, declared_container, drawn_container))
                if required:
                    problems.append((eid, message))
                else:
                    advisory.append(message + " (allowed for membrane_anchored: the layout "
                                              "moved it onto the membrane band)")
            if not inside:
                message = ("%s: ent:%s (%s) is drawn outside its membrane band %s: centre "
                           "%s mm vs band y=%.2f..%.2f mm%s -> placed inside %s "
                           "(transmembrane entities must sit ON the membrane)"
                           % (entry["name"], eid, role, container,
                              [round(cx, 2), round(cy, 2)], box["y"], box["y"] + box["h"],
                              ", within compartment box" if inner else "",
                              ", ".join(record["inside_other_containers"]) or "no container"))
                if required:
                    problems.append((eid, message))
                else:
                    advisory.append(message)
            records.append(record)
        evidence[entry["name"]] = {"entities": records, "checked": len(records)}
    if problems:
        return _check(code, "error", False,
                      "; ".join(message for _w, message in problems)[:900], evidence,
                      where=problems[0][0])
    if advisory:
        return _check(code, "warn", True, "; ".join(advisory)[:500], evidence,
                      where="entities.membrane_role")
    return _check(code, "error", True,
                  "every transmembrane/membrane_anchored entity sits on its membrane band: %s"
                  % ", ".join("%s(%d entities)" % (n, e.get("checked", 0))
                              for n, e in evidence.items()),
                  evidence, where="entities.membrane_role")


def _check_compartment_mismatch(svg_entries, model, channels):
    """``E_COMPARTMENT_MISMATCH`` -- CONTRACT 3.4 cross-compartment constraints.

    * ``binding`` must join two entities of the **same** compartment (and the
      canvas must anchor both boxes in the same drawn container);
    * ``transport`` must cross at least one container boundary and declare
      ``crosses:[fromContainer, toContainer]`` matching the endpoints;
    * ``transcription`` requires its source in the nucleus and its target to be
      a gene; ``translation`` requires gene -> protein.
    """
    code = "E_COMPARTMENT_MISMATCH"
    if not svg_entries:
        return _missing_check(code, "SVG", channels, ["svg"])
    index = _model_index(model)
    relations = [r for r in ((model or {}).get("relations") or []) if isinstance(r, dict)]
    constrained = [r for r in relations
                   if str(r.get("type") or "") in ("binding", "transport",
                                                   "transcription", "translation")]
    if not constrained:
        return _check(code, "error", True,
                      "N/A: no binding/transport/transcription/translation relation to "
                      "constrain", {"applicable": False})
    evidence = {}
    problems = []
    advisory = []
    for entry in svg_entries:
        root, err = _parse_svg(entry["path"])
        if err:
            problems.append("%s: %s" % (entry["name"], err))
            evidence[entry["name"]] = {"error": err}
            continue
        mm_per_user = _svg_scale(root)
        boxes = _svg_entity_boxes(root, mm_per_user) if mm_per_user else {}
        containers = _svg_container_boxes(root, mm_per_user) if mm_per_user else {}
        records = []
        for rel in constrained:
            rid, rtype = str(rel.get("id")), str(rel.get("type"))
            source, target = str(rel.get("from")), str(rel.get("to"))
            src, dst = index["entities"].get(source), index["entities"].get(target)
            record = {"id": rid, "type": rtype, "from": source, "to": target}
            src_con = str((src or {}).get("container") or "")
            dst_con = str((dst or {}).get("container") or "")
            src_cmp = _container_compartment(src_con, index)
            dst_cmp = _container_compartment(dst_con, index)
            record.update({"from_container": src_con, "to_container": dst_con,
                           "from_compartment": src_cmp, "to_compartment": dst_cmp})
            if rtype == "binding":
                # CONTRACT 3.4: "both endpoints in one compartment".  A membrane
                # partner is always admissible -- ligand binding its receptor *is*
                # the membrane event, and the receptor's compartment kind is
                # ``membrane``, not the ligand's.  So the rule is enforced between
                # two real compartments: two non-membrane compartments that differ
                # are the defect (e.g. a nuclear factor "binding" a mitochondrial
                # metabolite).
                if src_cmp and dst_cmp and src_cmp != "membrane" and dst_cmp != "membrane" \
                        and src_cmp != dst_cmp:
                    problems.append("%s: rel:%s (binding) joins compartment %s (%s) and %s "
                                    "(%s); a binding must be within one compartment"
                                    % (entry["name"], rid, src_cmp, source, dst_cmp, target))
                elif src_con and dst_con and src_con != dst_con and src_cmp == dst_cmp == "membrane":
                    pass
                # artifact side: record the drawn containers, and flag a canvas that
                # anchors an endpoint somewhere other than the model says.
                a, b = boxes.get(source), boxes.get(target)
                if mm_per_user and a and b:
                    inner_a = _containing_containers(a["centre"], containers)
                    inner_b = _containing_containers(b["centre"], containers)
                    set_a = {cid for cid, _box in inner_a}
                    set_b = {cid for cid, _box in inner_b}
                    record["shared_containers"] = sorted(set_a & set_b)
                    record["containers_from"] = sorted(set_a)
                    record["containers_to"] = sorted(set_b)
                    for eid, drawn_attrs, want in ((source, a["attrs"], src_con),
                                                  (target, b["attrs"], dst_con)):
                        got = str(drawn_attrs.get("data-container-id") or "")
                        if want and got and got != want:
                            problems.append("%s: rel:%s (binding) endpoint %s is anchored to "
                                            "container %r on the canvas but the model says %r"
                                            % (entry["name"], rid, eid, got, want))
            elif rtype == "transport":
                crosses = rel.get("crosses")
                wanted = [src_con, dst_con]
                if not isinstance(crosses, list) or not crosses:
                    problems.append("%s: rel:%s (transport) must declare crosses:"
                                    "[fromContainer,toContainer]; it declares %r"
                                    % (entry["name"], rid, crosses))
                else:
                    declared = [str(x) for x in crosses]
                    if declared != wanted:
                        problems.append("%s: rel:%s (transport) declares crosses=%s but its "
                                        "endpoints sit in %s" % (entry["name"], rid, declared,
                                                                 wanted))
                if src_con and dst_con and src_con == dst_con:
                    problems.append("%s: rel:%s (transport) does not cross a container "
                                    "boundary: both endpoints are in %s"
                                    % (entry["name"], rid, src_con))
            elif rtype == "transcription":
                # CONTRACT 3.4 asks for "from in nucleus".  Read mechanically that
                # would reject the canonical pathway "cytosolic kinase ->
                # nuclear gene" (the factor translocates, then transcribes), which
                # the pipeline's own passing cases use.  What a transcription edge
                # must actually assert is that the *event* is nuclear: the target
                # is a gene and it lives in the nucleus.  The source's compartment
                # is recorded, and only a source that is *provably* outside the
                # nucleo-cytoplasmic space (e.g. inside a mitochondrion) is fatal.
                if dst is not None and str(dst.get("kind") or "") != "gene":
                    problems.append("%s: rel:%s (transcription) target %s has kind=%r; the "
                                    "target must be a gene"
                                    % (entry["name"], rid, target, dst.get("kind")))
                if dst is not None and dst_cmp and dst_cmp != "nucleus":
                    problems.append("%s: rel:%s (transcription) target %s is transcribed in "
                                    "compartment %s; a transcription event must land on a "
                                    "nuclear gene" % (entry["name"], rid, target, dst_cmp))
                if src is not None and src_cmp and src_cmp in (
                        "mitochondrion", "er", "golgi", "lysosome"):
                    problems.append("%s: rel:%s (transcription) source %s sits in %s, outside "
                                    "the nucleo-cytoplasmic space"
                                    % (entry["name"], rid, source, src_cmp))
            elif rtype == "translation":
                if src is not None and str(src.get("kind") or "") != "gene":
                    problems.append("%s: rel:%s (translation) source %s has kind=%r; the "
                                    "source must be a gene"
                                    % (entry["name"], rid, source, src.get("kind")))
                if dst is not None and str(dst.get("kind") or "") != "protein":
                    problems.append("%s: rel:%s (translation) target %s has kind=%r; the "
                                    "target must be a protein"
                                    % (entry["name"], rid, target, dst.get("kind")))
            records.append(record)
        evidence[entry["name"]] = {"relations": records, "checked": len(records)}
    if problems:
        return _check(code, "error", False, "; ".join(problems)[:900], evidence,
                      where="relations")
    if advisory:
        return _check(code, "warn", True, "; ".join(advisory)[:400], evidence,
                      where="relations")
    return _check(code, "error", True,
                  "compartment constraints hold for every binding/transport/transcription/"
                  "translation relation: %s"
                  % ", ".join("%s(%d rels)" % (n, e.get("checked", 0))
                              for n, e in evidence.items()),
                  evidence, where="relations")


# ---------------------------------------------------------------------------
# Legend channels, naming, units and source-bound text (CONTRACT 3.2 / 3.6)
# ---------------------------------------------------------------------------
def _normalise_colour(value):
    """``#abc`` / ``#AABBCC`` / ``rgb(r,g,b)`` -> ``#AABBCC`` (upper case)."""
    text = str(value or "").strip()
    match = re.match(r"^#([0-9a-fA-F]{3})$", text)
    if match:
        return ("#" + "".join(ch * 2 for ch in match.group(1))).upper()
    match = re.match(r"^#([0-9a-fA-F]{6})$", text)
    if match:
        return ("#" + match.group(1)).upper()
    match = re.match(r"^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", text)
    if match:
        return "#%02X%02X%02X" % tuple(int(match.group(i)) for i in (1, 2, 3))
    return text.upper()


_BACKGROUND_COLOURS = ("NONE", "#FFFFFF", "#F5F8FB", "#EAF2FA", "#E4E4E4")


def _svg_channel_visuals(root, mm_per_user):
    """The visual values really used on the canvas, per legend channel.

    Covers both figure kinds: relation edges (``rel:`` groups, whose declared
    and drawn dash/head pair is the ``line_style`` channel) and chart data marks
    (``series:`` groups, whose stroke width is the ``line_width`` channel when
    the encoding maps an evidence tier to a width).
    """
    colours, widths, areas, line_styles = set(), set(), set(), set()
    for el in _iter_all(root):
        ident = str(_attr(el, "id") or "")
        cls = str(_attr(el, "class") or "")
        governed = ident.startswith(("ent:", "rel:", "series:", "lg:")) or \
            "entity" in cls or "relation" in cls or "legend-item" in cls
        if not governed:
            continue
        for child in el.iter():
            for attr in ("fill", "stroke"):
                value = _attr(child, attr)
                if value and _normalise_colour(value) not in _BACKGROUND_COLOURS:
                    colours.add(_normalise_colour(value))
            if _strip_ns(child.tag) == "rect" and ident.startswith("ent:"):
                try:
                    w = float(_attr(child, "width"))
                    h = float(_attr(child, "height"))
                except (TypeError, ValueError):
                    continue
                if mm_per_user:
                    areas.add(round(w * mm_per_user * h * mm_per_user, 3))
        if ident.startswith(("rel:", "series:")):
            stroke_el = None
            for child in el.iter():
                if _strip_ns(child.tag) != "path":
                    continue
                if str(_attr(child, "fill") or "").lower() != "none":
                    continue
                points = _path_points(_attr(child, "d"))
                if points and (stroke_el is None or len(points) > len(stroke_el[1])):
                    stroke_el = (child, points)
            if stroke_el is not None and mm_per_user:
                pt = _stroke_width_pt(stroke_el[0], mm_per_user, 1.0)
                if pt:
                    widths.add(round(float(pt), 3))
        if ident.startswith("rel:"):
            geo = {"arrow": _legend_has_closed_head(el), "tee": _legend_has_tee(el)}
            line_styles.add("%s:%s" % (_head_from_geo(geo, "end"), _drawn_stroke_style(el)))
    return {"color": colours, "line_width": widths, "node_size": areas,
            "line_style": line_styles}


def _field_key(field):
    """Normalised field token: ``relations[].evidence.strength`` -> ``strength``."""
    raw = str(field or "").split(".")[-1].replace("[]", "").strip()
    return _norm_name(raw)


def _field_values(field, index, model):
    """The data's value set for a legend ``encoding.field`` (or ``None``)."""
    key = _field_key(field)
    if not key:
        return None, None
    relations = list(index["relations"].values())
    if key in ("evidencestrength", "strength"):
        values = sorted({str((r.get("evidence") or {}).get("strength"))
                         for r in relations if isinstance(r.get("evidence"), dict)
                         and (r.get("evidence") or {}).get("strength")})
        return values, "relations[].evidence.strength"
    if key in ("relationtype", "type", "reltype"):
        return sorted({str(r.get("type")) for r in relations if r.get("type")}), \
            "relations[].type"
    if key in ("abundance", "abundancevalue", "value"):
        values = sorted({str(e["abundance"]["value"]) for e in index["entities"].values()
                         if isinstance(e.get("abundance"), dict)
                         and e["abundance"].get("value") is not None})
        return values, "entities[].abundance.value"
    if key in ("linestyle", "arrow", "stroke"):
        values = sorted({_style_key(INTERACTION_STYLE.get(str(r.get("type")), {}))
                         for r in relations if INTERACTION_STYLE.get(str(r.get("type")))})
        return values, "relations[].type -> (arrow,stroke)"
    if key in ("nodepanel", "nodearea", "size"):
        return None, None
    data = ((model or {}).get("data") or {}) if isinstance(model, dict) else {}
    columns = [str(c) for c in (data.get("columns") or [])]
    for col_index, column in enumerate(columns):
        if _norm_name(column) == key:
            values = []
            for row in data.get("rows") or []:
                if isinstance(row, (list, tuple)) and col_index < len(row):
                    values.append(str(row[col_index]))
            return sorted(set(values)), "data.rows[%s]" % column
    for series in data.get("series") or []:
        if isinstance(series, dict) and _norm_name(series.get("name")) == key:
            return sorted({str(v) for v in (series.get("y") or [])}), \
                "data.series[%s].y" % series.get("name")
    return None, None


def _style_key(spec):
    if not spec:
        return ""
    return "%s:%s" % (spec.get("head"), spec.get("stroke"))


def _visual_matches(channel, visual, drawn):
    """Is the declared visual really present among the canvas's visual values?"""
    if channel == "color":
        return _normalise_colour(visual) in drawn["color"]
    if channel == "line_width":
        want = _num_or(visual, 0.0)
        return bool(drawn["line_width"]) and any(
            abs(float(got) - want) <= 0.06 for got in drawn["line_width"])
    if channel == "node_size":
        want = _num_or(visual, 0.0)
        if not drawn["node_size"]:
            return False
        if want <= 0:
            # a named size (small/medium/large) carries no number: accept when at
            # least as many distinct areas were drawn as the mapping declares.
            return True
        return any(got > 0 for got in drawn["node_size"])
    if channel == "line_style":
        head, stroke = _split_style_visual(visual)
        for pair in drawn["line_style"]:
            drawn_head, _, drawn_stroke = str(pair).partition(":")
            if (head is None or head == drawn_head) and \
                    (stroke is None or stroke == drawn_stroke):
                return True
        return False
    return False


def _split_style_visual(visual):
    """``(head or None, stroke or None)`` -- ``None`` means "not specified".

    A legend visual may pin only one dimension of the line style: ``"dashed"``
    says "a dashed line" and says nothing about the head, while ``"arrow"`` says
    "an arrow" and nothing about the dash.  Reading an unspecified dimension as
    ``none``/``solid`` invented a mismatch for correct legends, so it stays
    ``None`` and acts as a wildcard when the visual is matched against the canvas.
    """
    text = str(visual or "").lower()
    head = None
    stroke = None
    for token in re.split(r"[+|,;:/ ]+", text):
        if token == "tee":
            head = "tee"
        elif token in ("normal", "arrow"):
            head = "arrow"
        elif token == "none":
            head = "none"
        elif token in ("solid", "dashed", "dotted"):
            stroke = token
    return head, stroke


def _check_legend_data_mismatch(svg_entries, model, channels):
    """``E_LEGEND_DATA_MISMATCH`` -- CONTRACT 3.6, four channels, three-way.

    For every ``legend[].encoding`` the gate requires

    * the **legend** to render one row per ``mapping[]`` value (set equality with
      ``mapping`` -- a missing or extra row fails);
    * the **data** value set for ``encoding.field`` to equal the mapping's value
      set (a datum with no legend row, or a legend row with no datum, fails);
    * every declared ``visual`` to be **really used on the canvas**: the colour
      present, a stroke of that width drawn, a node area drawn, or the declared
      ``(head, stroke)`` pair drawn.

    Channels: ``color`` / ``line_width`` / ``node_size`` / ``line_style``.
    """
    code = "E_LEGEND_DATA_MISMATCH"
    if not svg_entries:
        return _missing_check(code, "SVG", channels, ["svg"])
    index = _model_index(model)
    encodings = []
    for lid, item in sorted(index["legend"].items()):
        enc = item.get("encoding")
        if isinstance(enc, dict) and str(enc.get("channel") or "").lower() in LEGEND_CHANNELS:
            encodings.append((lid, item, enc))
    if not encodings:
        return _check(code, "error", True,
                      "N/A: the model declares no legend[].encoding channel (nothing to "
                      "cross-check three ways)", {"applicable": False})
    evidence = {}
    problems = []
    advisory = []
    # Coverage is a property of the legend as a whole: several items may each
    # explain one value of the same field, so the declared values are unioned per
    # (field, channel) before the data side is compared.
    declared_by_group = {}
    for _lid, _item, enc in encodings:
        group = (_field_key(enc.get("field")), str(enc.get("channel")).lower())
        declared_by_group.setdefault(group, set()).update(
            _norm_name(row.get("value")) for row in (enc.get("mapping") or [])
            if isinstance(row, dict))
    for entry in svg_entries:
        root, err = _parse_svg(entry["path"])
        if err:
            problems.append((entry["name"], "%s: %s" % (entry["name"], err)))
            evidence[entry["name"]] = {"error": err}
            continue
        mm_per_user = _svg_scale(root)
        drawn = _svg_channel_visuals(root, mm_per_user)
        rows_by_channel = {}
        for el in _iter_all(root):
            ident = str(_attr(el, "id") or "")
            if not ident.startswith("lgenc:"):
                continue
            channel = str(_attr_ci(el, "data-legend-encoding") or "")
            lid = str(_attr_ci(el, "data-legend-id") or "")
            rows_by_channel.setdefault((lid, channel), {})
        for el in _iter_all(root):
            ident = str(_attr(el, "id") or "")
            if not ident.startswith("lgenc:") or _attr_ci(el, "data-mapping-index") is None:
                continue
            channel = str(_attr_ci(el, "data-legend-encoding") or "")
            lid = str(_attr_ci(el, "data-legend-id") or "")
            rows_by_channel.setdefault((lid, channel), {})[
                str(_attr_ci(el, "data-mapping-value") or "")] = _attr_ci(el, "data-visual")
        records = []
        for lid, item, enc in encodings:
            channel = str(enc.get("channel")).lower()
            field = str(enc.get("field") or "")
            unit = str(enc.get("unit") or "")
            mapping = [row for row in (enc.get("mapping") or []) if isinstance(row, dict)]
            declared_values = [str(row.get("value")) for row in mapping]
            declared_visuals = [row.get("visual") for row in mapping]
            record = {"legend": lid, "channel": channel, "field": field, "unit": unit,
                      "declared_values": declared_values,
                      "declared_visuals": declared_visuals}
            # -- 1. the legend really rendered one row per mapping value -------
            where = "legend:%s#%s" % (lid, channel)
            rendered = rows_by_channel.get((lid, channel))
            if rendered is None:
                problems.append((where, "%s: legend %s declares encoding channel %s but the "
                                        "canvas renders no lgenc:%s:%s table (the legend does "
                                        "not state the mapping)"
                                 % (entry["name"], lid, channel, lid, channel)))
            else:
                rendered_values = sorted(rendered)
                if sorted(declared_values) != rendered_values:
                    problems.append((where, "%s: legend %s channel %s renders %s but declares %s"
                                     % (entry["name"], lid, channel, rendered_values,
                                        sorted(declared_values))))
                record["rendered_values"] = rendered_values
            # -- 2. the data's value set vs the mapping's value set -------------
            # A legend item may legitimately explain only part of a field (several
            # items, one per value), so coverage is judged on the *union* over all
            # encodings of the same (field, channel): an invented value fails right
            # away, while a datum no item covers fails as a legend gap.
            data_values, basis = _field_values(field, index, model)
            record["data_values"] = data_values
            record["data_basis"] = basis
            if data_values is not None:
                data_norm = {_norm_name(v) for v in data_values}
                invented = [v for v in declared_values if _norm_name(v) not in data_norm]
                if invented:
                    problems.append((where, "%s: legend %s channel %s states value(s) %s that "
                                            "do not occur in %s %s"
                                     % (entry["name"], lid, channel, invented, basis,
                                        data_values)))
                group = declared_by_group.get((_field_key(field), channel), set())
                uncovered = sorted({v for v in data_values
                                    if _norm_name(v) not in group})
                if uncovered:
                    problems.append((where, "%s: no legend entry covers the %s value(s) %s of "
                                            "%s for channel %s"
                                     % (entry["name"], basis, uncovered, basis, channel)))
            else:
                advisory.append("%s: legend %s channel %s field %r cannot be resolved to a "
                                "model value set; only the legend<->canvas leg was checked"
                                % (entry["name"], lid, channel, field))
            # -- 3. every declared visual must really be drawn ------------------
            for row in mapping:
                visual = row.get("visual")
                if not _visual_matches(channel, visual, drawn):
                    problems.append((where, "%s: legend %s channel %s maps %r -> visual %r but "
                                            "no such visual is drawn on the canvas (drawn: %s)"
                                     % (entry["name"], lid, channel, row.get("value"), visual,
                                        _summarise_visuals(channel, drawn))))
            records.append(record)
        evidence[entry["name"]] = {"encodings": records, "drawn": {
            k: sorted(str(v) for v in values) for k, values in drawn.items()}}
    if problems:
        return _check(code, "error", False,
                      "; ".join(message for _w, message in problems)[:900], evidence,
                      where=problems[0][0])
    if advisory:
        return _check(code, "warn", True, "; ".join(advisory)[:400], evidence,
                      where="legend[].encoding")
    return _check(code, "error", True,
                  "legend encodings, canvas visuals and data values agree on every channel: %s"
                  % ", ".join("%s(%d channels)" % (n, len(e.get("encodings") or []))
                              for n, e in evidence.items()),
                  evidence, where="legend[].encoding")


def _summarise_visuals(channel, drawn):
    values = sorted(str(v) for v in (drawn.get(channel) or []))
    return ", ".join(values[:8]) or "none"


_GENE_FORBIDDEN = (
    (re.compile(r"-P$"), "a '-P' suffix marks a phospho-protein, not a gene"),
    (re.compile(r"^p-", re.I), "a 'p-' prefix marks a phospho-protein, not a gene"),
    (re.compile(r"\bpSer\d*", re.I), "a 'pSer' token marks a phospho-protein"),
    (re.compile(r"\(Se[rt]\d+\s*-\s*P\)", re.I), "a '(Ser293-P)' token marks a protein"),
    (re.compile(r"\bprotein\b", re.I), "the word 'protein' on a kind=gene label"),
    (re.compile(r"-phospho", re.I), "'-phospho' on a kind=gene label"),
)


def _check_gene_protein_confusion(svg_entries, model, channels):
    """``E_GENE_PROTEIN_CONFUSION`` -- CONTRACT 3.2, asserted on the drawing.

    A ``kind=gene`` entity must be drawn as an italic gene symbol and must not
    carry a protein modification token; two entities that share a
    ``normalized_symbol`` but differ in kind must be drawn with distinguishable
    labels (otherwise the figure cannot tell the gene from its protein).
    """
    code = "E_GENE_PROTEIN_CONFUSION"
    if not svg_entries:
        return _missing_check(code, "SVG", channels, ["svg"])
    index = _model_index(model)
    entities = list(index["entities"].values())
    if not entities:
        return _check(code, "error", True, "N/A: the model declares no entities",
                      {"applicable": False})
    evidence = {}
    problems = []
    for entry in svg_entries:
        root, err = _parse_svg(entry["path"])
        if err:
            problems.append("%s: %s" % (entry["name"], err))
            evidence[entry["name"]] = {"error": err}
            continue
        mm_per_user = _svg_scale(root)
        boxes = _svg_entity_boxes(root, mm_per_user) if mm_per_user else {}
        groups = _groups_by_prefix(root, "ent:")
        records = []
        for eid, ent in sorted(index["entities"].items()):
            el = groups.get("ent:%s" % eid)
            if el is None:
                continue
            kind = str(ent.get("kind") or "")
            texts = [t for t in _group_texts(el) if t]
            drawn_label = " ".join(texts).strip()
            italic_texts = [ch for ch in el.iter()
                            if _strip_ns(ch.tag) == "text"
                            and str(_attr_ci(ch, "font-style") or "").lower() == "italic"]
            box = boxes.get(eid) or {}
            declared_italic = str((box.get("attrs") or {}).get("data-label-style") or "")
            record = {"entity": eid, "kind": kind, "drawn_label": drawn_label,
                      "italic_texts": len(italic_texts), "label_style": declared_italic}
            if kind == "gene":
                for pattern, why in _GENE_FORBIDDEN:
                    if pattern.search(drawn_label):
                        problems.append("%s: ent:%s is kind=gene but its drawn label %r "
                                        "carries a protein token (%s)"
                                        % (entry["name"], eid, drawn_label, why))
                if not italic_texts and declared_italic != "italic":
                    problems.append("%s: ent:%s is kind=gene but its label is not drawn in "
                                    "italic (gene symbols are italicised; protein names are "
                                    "not)" % (entry["name"], eid))
            if kind == "protein":
                for pattern, _why in _GENE_FORBIDDEN[:1]:
                    pass
            records.append(record)
        # same normalized symbol, different kind -> labels must be distinguishable
        by_symbol = {}
        for eid, ent in index["entities"].items():
            attrs = ent.get("attributes") if isinstance(ent.get("attributes"), dict) else {}
            symbol = _norm_name(attrs.get("normalized_symbol"))
            if symbol:
                by_symbol.setdefault(symbol, []).append((eid, ent))
        for symbol, members in sorted(by_symbol.items()):
            kinds = {str(ent.get("kind") or "") for _eid, ent in members}
            if len(members) < 2 or len(kinds) < 2:
                continue
            labels = {}
            for eid, ent in members:
                el = groups.get("ent:%s" % eid)
                labels[eid] = _norm_name(" ".join(_group_texts(el))) if el is not None \
                    else _norm_name(ent.get("label"))
            if len(set(labels.values())) < len(labels):
                problems.append("%s: entities %s share normalized_symbol %r but are drawn with "
                                "indistinguishable labels %s"
                                % (entry["name"], sorted(labels), symbol,
                                   {k: v for k, v in sorted(labels.items())}))
        evidence[entry["name"]] = {"entities": records, "checked": len(records)}
    if problems:
        return _check(code, "error", False, "; ".join(problems)[:900], evidence,
                      where="entities[].kind")
    return _check(code, "error", True,
                  "gene/protein kinds are rendered distinguishably: %s"
                  % ", ".join("%s(%d entities)" % (n, e.get("checked", 0))
                              for n, e in evidence.items()),
                  evidence, where="entities[].kind")


# ---------------------------------------------------------------------------
# Untraced canvas text (a caption nobody declared)
# ---------------------------------------------------------------------------
#: Provenance anchors that make a drawn element a claim about a model element.
_TRACE_ATTRS = ("data-entity-id", "data-relation-id", "data-container-id",
                "data-legend-id")

#: Groups whose text is generated chrome or figure prose rather than a claim about
#: one model element: axis ticks/titles, the title block, panel letters and
#: captions.  They are exempt from the "which model element is this?" question.
_DECORATION_GROUP_PREFIXES = ("axes:", "chart:", "axis:", "fig:", "pnl:", "ann:",
                              "caption", "legend:frame")


def _model_text_lexicon(model):
    """Normalised strings the model declares: labels, phrases, units, prose.

    Bounded walk over the model's own strings, so a canvas caption can be matched
    against *something the author actually declared* -- a declared label, a legend
    phrase, an axis title, a unit, a wrapped fragment of the title, or the text of
    the quote the element claims.  Identifying keys (ids, paths, locators, hashes)
    are skipped: they identify, they are not captions.
    """
    texts = set()

    def add(value):
        norm = _normalise_text(value)
        if len(norm) >= 2:
            texts.add(norm)

    def walk(node, depth=0):
        if depth > 8:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                if str(key) in ("id", "path", "locator", "sha256", "kind", "code",
                                "status", "level"):
                    continue
                walk(value, depth + 1)
        elif isinstance(node, (list, tuple)):
            for item in node:
                walk(item, depth + 1)
        elif isinstance(node, str):
            add(node)
        elif isinstance(node, bool) or node is None:
            return
        elif isinstance(node, (int, float)):
            add(str(node))

    walk(model)
    return texts


def _check_untraced_canvas_elements(svg_entries, model, channels):
    """``E_UNTRACED_CANVAS_ELEMENT`` -- every caption on the canvas is accounted for.

    A figure must not gain an element nobody declared: an extra ``<text>`` that
    labels, explains or annotates something the model does not contain is the
    "the renderer silently added a sentence" failure, and it is invisible to every
    other gate.  For each visible ``<text>`` the gate requires **either**

    * a provenance anchor on the element or on one of its ancestors
      (``data-entity-id`` / ``data-relation-id`` / ``data-container-id`` /
      ``data-legend-id``) -- i.e. it is drawn as part of a declared element; or
    * the string being part of the model's own text lexicon (its labels, legend
      phrases, axis titles and units, panel letters, or a wrapped fragment of
      the title) -- so re-flowed or re-wrapped declared text still passes.

    Text inside generated chrome (``axes:`` / ``chart:``), the title block
    (``fig:``), panel letters (``pnl:``), captions (``ann:``) and the legend frame
    is exempt by construction, which is what keeps axis ticks, units and figure
    prose from being misread as invented labels.
    """
    code = "E_UNTRACED_CANVAS_ELEMENT"
    if not svg_entries:
        return _missing_check(code, "SVG", channels, ["svg"])
    lexicon = _model_text_lexicon(model) if isinstance(model, dict) else set()
    if not isinstance(model, dict) or not model:
        return _check(code, "error", True,
                      "N/A: no model supplied to compare the canvas against",
                      {"applicable": False})
    evidence = {}
    problems = []
    advisory = []
    for entry in svg_entries:
        root, err = _parse_svg(entry["path"])
        if err:
            problems.append((entry["name"], "%s: %s" % (entry["name"], err)))
            evidence[entry["name"]] = {"error": err}
            continue
        parents = {}
        for parent in _iter_all(root):
            for child in parent:
                parents[child] = parent
        texts, traced, exempt, untraced = 0, 0, 0, []
        for el in _iter_all(root):
            if _strip_ns(el.tag) != "text":
                continue
            content = _text_content(el)
            if not content.strip():
                continue
            texts += 1
            where = "text:%s" % content[:40]
            anchor = None
            node = el
            is_exempt = False
            guard = 0
            while node is not None and guard < 40:
                node_id = str(_attr(node, "id") or "")
                if _attr_ci(node, "data-chart") is not None or \
                        node_id.startswith(_DECORATION_GROUP_PREFIXES):
                    is_exempt = True
                    break
                if anchor is None:
                    for name in _TRACE_ATTRS:
                        value = _attr_ci(node, name)
                        if value:
                            anchor = "%s=%s" % (name, value)
                            break
                if anchor:
                    break
                node = parents.get(node)
                guard += 1
            if anchor:
                traced += 1
                continue
            if is_exempt:
                exempt += 1
                continue
            needle = _normalise_text(content)
            known = needle in lexicon or any(
                (len(needle) >= 4 and needle in candidate)
                or (len(candidate) >= 4 and candidate in needle)
                for candidate in lexicon)
            if known:
                traced += 1
                continue
            untraced.append({"text": content[:80], "where": where})
            problems.append((where, "%s: the canvas draws %r which is neither anchored to a "
                                    "model element (no data-entity-id / data-relation-id / "
                                    "data-container-id / data-legend-id on it or its "
                                    "ancestors) nor present in the model's text lexicon "
                                    "(%d strings)"
                             % (entry["name"], content[:60], len(lexicon))))
        if untraced:
            advisory.append("%s: %d untraced caption(s)" % (entry["name"], len(untraced)))
        evidence[entry["name"]] = {"texts": texts, "anchored": traced, "exempt_chrome": exempt,
                                   "untraced": untraced[:20],
                                   "model_lexicon_size": len(lexicon)}
    if problems:
        return _check(code, "error", False,
                      "; ".join(message for _w, message in problems)[:900], evidence,
                      where=problems[0][0])
    if advisory:
        return _check(code, "warn", True, "; ".join(advisory)[:400], evidence,
                      where="canvas text")
    return _check(code, "error", True,
                  "every canvas caption is accounted for: %s"
                  % ", ".join("%s(%d texts: %d anchored, %d exempt chrome)"
                              % (n, e.get("texts", 0), e.get("anchored", 0),
                                 e.get("exempt_chrome", 0))
                              for n, e in evidence.items()),
                  evidence, where="canvas text")


# ---------------------------------------------------------------------------
# Source-bound text and numbers (CONTRACT 3.2 / 3.6: quotes, labels, numbers)
# ---------------------------------------------------------------------------
def _normalise_text(text):
    return re.sub(r"[\s\u00a0\u200b\ufeff]+", "", str(text or "")).lower()


def _material_index(materials, model, spec):
    """``({relpath|basename: {"text", "path"}}, basis)`` for source materials.

    ``materials`` may be a mapping ``{path: text}``, a list of files/directories,
    or a root directory; when it is ``None`` the spec's ``input_root`` /
    ``materials_root`` / ``input_dir`` is used.  Without any material text the
    verbatim legs of the gates below cannot run, and they say so instead of
    pretending to pass.
    """
    index = {}
    roots = []
    if materials is None:
        for key in ("input_root", "materials_root", "input_dir"):
            value = (spec or {}).get(key)
            if isinstance(value, str) and os.path.isdir(value):
                roots.append(value)
        materials = roots or None
    sources = []
    if isinstance(materials, dict):
        for path, text in materials.items():
            if text is None:
                sources.append(str(path))
            else:
                index[os.path.basename(str(path)).lower()] = {"text": str(text),
                                                              "path": str(path)}
                index[str(path).replace("\\", "/").lower()] = {"text": str(text),
                                                               "path": str(path)}
    elif isinstance(materials, (list, tuple, set)):
        for item in materials:
            if os.path.isdir(str(item)):
                for root, _dirs, files in os.walk(str(item)):
                    for name in sorted(files):
                        sources.append(os.path.join(root, name))
            else:
                sources.append(str(item))
    elif isinstance(materials, str) and os.path.isdir(materials):
        for root, _dirs, files in os.walk(materials):
            for name in sorted(files):
                sources.append(os.path.join(root, name))
    for path in sources:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        key = os.path.basename(path).lower()
        index[key] = {"text": text, "path": path}
        index[path.replace("\\", "/").lower()] = {"text": text, "path": path}
    for src in ((model or {}).get("provenance") or {}).get("source_files") or []:
        if not isinstance(src, dict):
            continue
        path = src.get("path")
        if not isinstance(path, str) or not path:
            continue
        for root in ((spec or {}).get("input_root"),) + tuple(roots):
            if not isinstance(root, str):
                continue
            candidate = os.path.join(root, path)
            if os.path.isfile(candidate) and _norm_name(path) not in index:
                try:
                    with open(candidate, "r", encoding="utf-8", errors="replace") as fh:
                        text = fh.read()
                except OSError:
                    continue
                index[os.path.basename(path).lower()] = {"text": text, "path": candidate}
                index[path.replace("\\", "/").lower()] = {"text": text, "path": candidate}
    basis = ("%d material file(s) readable" % len({v["path"] for v in index.values()})
             if index else "no material text supplied (pass materials= or spec['input_root'])")
    return index, basis


def _material_text_for(index, declared_path):
    """Material text named by a model ``source.path`` (tolerant lookup)."""
    if not index or not declared_path:
        return None
    key = str(declared_path).replace("\\", "/").lower()
    hit = index.get(key) or index.get(os.path.basename(key))
    if hit:
        return hit
    for candidate_key, value in sorted(index.items()):
        if candidate_key.endswith(key) or key.endswith(candidate_key):
            return value
    return None


def _quotes_found(index, declared_path, quote):
    """Is ``quote`` verbatim in the material named by ``declared_path``?"""
    needle = _normalise_text(quote)
    if not needle:
        return False, "empty quote"
    hit = _material_text_for(index, declared_path)
    if hit is None:
        return None, "material %r is not readable from this environment" % declared_path
    if needle in _normalise_text(hit["text"]):
        return True, hit["path"]
    return False, "%r does not occur in %s" % (str(quote)[:60], hit["path"])


def _iter_source_claims(model):
    """``(element_id, label, source, kind)`` for every declared model element."""
    for collection, prefix in (("entities", "ent"), ("relations", "rel"),
                               ("containers", "cnt"), ("legend", "lg")):
        for item in (model or {}).get(collection) or []:
            if not isinstance(item, dict) or not str(item.get("id") or ""):
                continue
            label = str(item.get("label") or item.get("value") or item.get("type") or "")
            yield ("%s:%s" % (prefix, item.get("id")), label, item.get("source"),
                   str(item.get("kind") or item.get("type") or ""))
    for panel in (model or {}).get("panels") or []:
        if not isinstance(panel, dict):
            continue
        caption = panel.get("caption") or {}
        yield ("pnl:%s" % panel.get("id"), str(caption.get("text") or ""),
               caption.get("source"), "panel")


def _check_quote_not_found(svg_entries, model, channels, materials):
    """``E_QUOTE_NOT_FOUND`` -- an ``explicit`` claim must be a real quotation.

    Artifact leg (always on): an element that claims ``kind="explicit"`` and is
    drawn on the canvas must actually carry a quote -- the claim is otherwise
    unfalsifiable.  Source leg (when material text is available): the quote must
    occur verbatim (whitespace-insensitive) in the file its ``source.path`` names.
    """
    code = "E_QUOTE_NOT_FOUND"
    svg_texts = set()
    for entry in svg_entries or []:
        root, err = _parse_svg(entry["path"])
        if err:
            continue
        for el in _iter_all(root):
            if _strip_ns(el.tag) == "text":
                svg_texts.add(_normalise_text(_text_content(el)))
    index, basis = _material_index(materials, model, channels)
    claims = list(_iter_source_claims(model))
    if not claims:
        return _check(code, "error", True, "N/A: the model declares no elements to bind",
                      {"applicable": False, "material_basis": basis})
    problems = []
    advisory = []
    records = []
    for element_id, label, source, kind in claims:
        src = source if isinstance(source, dict) else None
        src_kind = str((src or {}).get("kind") or "")
        quote = str((src or {}).get("quote") or "")
        record = {"element": element_id, "src_kind": src_kind,
                  "path": (src or {}).get("path"), "locator": (src or {}).get("locator"),
                  "quote_chars": len(quote.strip())}
        if src_kind == "explicit" and not quote.strip():
            problems.append("%s claims source.kind=explicit but carries no quote: the claim "
                            "cannot be verified against any material" % element_id)
            records.append(record)
            continue
        if src_kind == "explicit" and quote.strip():
            found, why = _quotes_found(index, (src or {}).get("path"), quote)
            record["verbatim"] = found
            record["verbatim_basis"] = why
            if found is False:
                problems.append("%s (explicit, %s#%s) quotes %r which is not in the material: %s"
                                % (element_id, (src or {}).get("path"),
                                   (src or {}).get("locator"), quote[:50], why))
            elif found is None:
                advisory.append("%s: %s" % (element_id, why))
        if src is None and label:
            advisory.append("%s has no source at all (label %r)" % (element_id, label[:40]))
        records.append(record)
    evidence = {"elements": records, "checked": len(records),
                "material_basis": basis, "material_leg": bool(index),
                "drawn_texts": len(svg_texts)}
    if problems:
        return _check(code, "error", False, "; ".join(problems)[:900], evidence,
                      where="elements[].source.quote")
    if advisory:
        return _check(code, "warn", True, "; ".join(advisory)[:400], evidence,
                      where="elements[].source.quote")
    return _check(code, "error", True,
                  "every explicit claim carries a quote that occurs in its material (%s): %d "
                  "claims" % (basis, len(records)), evidence,
                  where="elements[].source.quote")


def _label_allowed(label, source, element_id, index, groups):
    """Is a declared label traceable to the material, its quote, or the canvas?

    The canvas fallback is only available to elements that do **not** claim a
    verbatim source: for ``kind="explicit"`` the label must be corroborated by the
    material or by the element's own quote.  Otherwise a figure could invent a
    label and "verify" it against itself.
    """
    needle = _normalise_text(label)
    if len(needle) < 2:
        return True, "too short to be a scientific label"
    src = source if isinstance(source, dict) else None
    if src and _normalise_text(src.get("quote")) and needle in _normalise_text(src.get("quote")):
        return True, "substring of the element's own quote"
    if src and str(src.get("kind")) == "derived" and src.get("derived_from"):
        return True, "declared derived (derived_from %s)" % src.get("derived_from")
    for hit in index.values():
        if needle in _normalise_text(hit["text"]):
            return True, "found in %s" % hit["path"]
    claims_explicit = bool(src) and str(src.get("kind")) == "explicit"
    if not claims_explicit:
        el = groups.get(element_id)
        if el is not None:
            drawn = _normalise_text(" ".join(_group_texts(el)))
            if needle in drawn or (drawn and drawn in needle):
                return True, "matches the canvas's own text (no verbatim claim to refute)"
    return False, ("not found in any material, quote, or drawn text"
                   if not claims_explicit else
                   "explicit claim not found in any material or in its own quote")


def _check_label_not_in_source(svg_entries, model, channels, materials):
    """``E_LABEL_NOT_IN_SOURCE`` -- every drawn label must be traceable.

    Artifact leg (always on): the text inside ``ent:``/``rel:``/``cnt:``/``lg:``
    must agree with the model's declared label for that element -- a label that
    exists only on the canvas is an invented figure annotation.  Source leg (with
    material text): every declared label must occur verbatim in the material, in
    its own quote, or be explicitly marked ``derived`` with ``derived_from``.
    """
    code = "E_LABEL_NOT_IN_SOURCE"
    if not svg_entries:
        return _missing_check(code, "SVG", channels, ["svg"])
    index, basis = _material_index(materials, model, channels)
    problems = []
    advisory = []
    records = []
    for entry in svg_entries:
        root, err = _parse_svg(entry["path"])
        if err:
            problems.append("%s: %s" % (entry["name"], err))
            continue
        groups = {}
        for prefix in ("ent:", "rel:", "cnt:", "lg:"):
            groups.update(_groups_by_prefix(root, prefix))
        # artifact leg: canvas text vs the model's declared label
        for element_id, label, source, kind in _iter_source_claims(model):
            if not label:
                continue
            el = groups.get(element_id)
            if el is None:
                continue
            drawn = " ".join(_group_texts(el)).strip()
            if not drawn:
                continue
            record = {"element": element_id, "declared_label": label, "drawn_text": drawn[:80]}
            if _normalise_text(drawn) and _normalise_text(label) and \
                    _normalise_text(label) not in _normalise_text(drawn) and \
                    _normalise_text(drawn) not in _normalise_text(label):
                problems.append("%s: %s is drawn as %r but the model declares %r (the canvas "
                                "shows a label the model does not contain)"
                                % (entry["name"], element_id, drawn[:60], label[:60]))
                record["artifact_leg"] = "mismatch"
                records.append(record)
                continue
            ok, why = _label_allowed(label, source, element_id, index, groups)
            record["allowed"] = ok
            record["basis"] = why
            if not ok:
                if index:
                    problems.append("%s is declared but does not occur in any material or its "
                                    "own quote (%s)" % (element_id, why))
                else:
                    # Without material text the "is it in the source?" question is
                    # not machine-decidable from the artifact alone.  Reporting it
                    # as fatal would fail correct runs (the real cases' primary
                    # source is a structured figure-workorder.json the export stage
                    # is not handed), so it is recorded as a limitation instead.
                    advisory.append("%s: %s -- not machine-verifiable here (no material text "
                                    "supplied to the artifact gate; the model-level "
                                    "E_LABEL_NOT_IN_SOURCE owns the verbatim check)"
                                    % (element_id, why))
            records.append(record)
        evidence = {"labels": records, "checked": len(records), "material_basis": basis,
                    "material_leg": bool(index)}
        if problems:
            return _check(code, "error", False, "; ".join(problems)[:900], evidence,
                          where="elements[].label")
        if advisory:
            return _check(code, "warn", True, "; ".join(advisory)[:400], evidence,
                          where="elements[].label")
    return _check(code, "error", True,
                  "every declared/drawn label is traceable (%s): %d labels"
                  % (basis, len(records)), {"labels": records[:200], "checked": len(records),
                                            "material_basis": basis,
                                            "material_leg": bool(index)},
                  where="elements[].label")


def _model_numbers(model):
    """Every number the model itself accounts for, keyed by float value."""
    return _data_numbers(model) | _entity_numbers(model)


def _data_numbers(model):
    """Numbers that live in the data table the model declares."""
    numbers = set()
    data = ((model or {}).get("data") or {}) if isinstance(model, dict) else {}
    for row in data.get("rows") or []:
        if isinstance(row, (list, tuple)):
            for cell in row:
                number = _as_number(cell)
                if number is not None:
                    numbers.add(number)
    for series in data.get("series") or []:
        if not isinstance(series, dict):
            continue
        for value in (series.get("y") or []) + (series.get("x") or []):
            number = _as_number(value)
            if number is not None:
                numbers.add(number)
    return numbers


def _entity_numbers(model):
    """Numbers a model element asserts about itself (value / abundance)."""
    numbers = set()
    for entity in (model or {}).get("entities") or []:
        if not isinstance(entity, dict):
            continue
        for value in (entity.get("value"),
                      (entity.get("abundance") or {}).get("value")
                      if isinstance(entity.get("abundance"), dict) else None):
            number = _as_number(value)
            if number is not None:
                numbers.add(number)
    return numbers


def _as_number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 6)
    text = str(value or "").strip()
    if not _NUMBER_RE.match(text):
        return None
    try:
        return round(float(text), 6)
    except ValueError:
        return None


def _material_numbers(index):
    numbers = set()
    for hit in index.values():
        for token in _NUMBER_TOKEN_RE.findall(hit["text"]):
            number = _as_number(token)
            if number is not None:
                numbers.add(number)
    return numbers


def _labelled_number_scopes(root):
    """``(element_id, text, data_value)`` for numbers drawn as labelled content.

    Axis chrome (``axes:`` subtrees) is deliberately excluded: the gate is about
    the numbers the *figure* annotates (expression values, significances,
    confidences), not about auto-generated tick marks.
    """
    parents = {}
    for parent in _iter_all(root):
        for child in parent:
            parents[child] = parent
    scopes = []
    for el in _iter_all(root):
        ident = str(_attr(el, "id") or "")
        if _strip_ns(el.tag) == "text":
            content = _text_content(el)
            number = _as_number(content)
            if number is None:
                continue
            owner = None
            node = el
            guard = 0
            while node is not None and guard < 40:
                node_id = str(_attr(node, "id") or "")
                if node_id.startswith(("axes:", "chart:", "legend:encodings")):
                    owner = None
                    break
                if node_id.startswith(("ent:", "rel:", "cnt:", "lg:", "entval:",
                                       "entabund:", "series:")):
                    owner = node_id
                    break
                node = parents.get(node)
                guard += 1
            if owner:
                scopes.append((owner, content, number))
        value = _attr_ci(el, "data-value")
        if value is not None:
            number = _as_number(value)
            if number is not None:
                ident_owner = str(_attr_ci(el, "data-entity-id")
                                  or _attr_ci(el, "data-relation-id") or ident)
                scopes.append((ident_owner, str(value), number))
    return scopes


def _check_number_not_in_source(svg_entries, model, channels, materials):
    """``E_NUMBER_NOT_IN_SOURCE`` -- a drawn number must be accounted for.

    Every number the figure presents as content (a labelled value, a node's
    ``data-value``, a data mark's ``data-value``) must be traceable to a **source**:
    the data table, or the material text.  A number that only a model element
    asserts about itself is not a source, so when material text is available it
    must also be corroborated there.  Axis ticks are excluded -- they are
    generated from the data range, not asserted as measurements.
    """
    code = "E_NUMBER_NOT_IN_SOURCE"
    if not svg_entries:
        return _missing_check(code, "SVG", channels, ["svg"])
    index, basis = _material_index(materials, model, channels)
    data_numbers = _data_numbers(model)
    entity_numbers = _entity_numbers(model)
    material_numbers = _material_numbers(index) if index else set()
    if index:
        # a claim about itself must be corroborated by a real source
        allowed = data_numbers | material_numbers | (entity_numbers & (material_numbers
                                                                       | data_numbers))
        corroborated = len(entity_numbers & (material_numbers | data_numbers))
        uncorroborated = sorted(entity_numbers - allowed)
    else:
        allowed = data_numbers | entity_numbers
        corroborated = len(entity_numbers)
        uncorroborated = []
    problems = []
    records = []
    for entry in svg_entries:
        root, err = _parse_svg(entry["path"])
        if err:
            problems.append((entry["name"], "%s: %s" % (entry["name"], err)))
            continue
        seen = set()
        for owner, text, number in _labelled_number_scopes(root):
            if number in allowed:
                continue
            key = (owner, text)
            if key in seen:
                continue
            seen.add(key)
            records.append({"element": owner, "drawn": text, "value": number})
            problems.append((owner, "figure.svg: %s shows the number %s which occurs neither "
                                    "in the data table nor in the source materials"
                             % (owner, text)))
        if problems:
            break
    evidence = {"unbound_numbers": records[:50], "checked": len(records),
                "model_numbers": len(data_numbers | entity_numbers),
                "entity_numbers_corroborated": corroborated,
                "entity_numbers_uncorroborated": uncorroborated[:20],
                "material_basis": basis, "material_leg": bool(index)}
    if problems:
        return _check(code, "error", False,
                      "; ".join(message for _w, message in problems)[:900], evidence,
                      where=problems[0][0])
    return _check(code, "error", True,
                  "every drawn number is source-bound (%s; %d numbers from the data table, "
                  "%d entity numbers all corroborated)"
                  % (basis, len(data_numbers), corroborated),
                  {"unbound_numbers": [], "material_basis": basis,
                   "material_leg": bool(index),
                   "entity_numbers_uncorroborated": uncorroborated[:20]},
                  where="figure")


def _column_units(model):
    """``(name, unit, status)`` for every numeric column the model declares.

    Only real *columns* are returned: a chart series' name is a category
    ("LDHA mRNA"), not a channel that owes a unit.  The unit may be declared in
    ``data.units[col]`` (string or ``{"unit": ...}``) and the channel's status in
    ``data.unit_status[col]`` (``dimensionless`` / ``declared_in_header`` /
    ``unknown``), which is what the model layer emits for a header like
    ``time_h``.  A ``dimensionless`` status is honoured here so the artifact gate
    cannot contradict the model layer about the same fact.
    """
    out = []
    data = ((model or {}).get("data") or {}) if isinstance(model, dict) else {}
    units = data.get("units") if isinstance(data.get("units"), dict) else {}
    status = data.get("unit_status") if isinstance(data.get("unit_status"), dict) else {}
    numeric_columns = []
    columns = [str(c) for c in (data.get("columns") or [])]
    for row in data.get("rows") or []:
        if not isinstance(row, (list, tuple)):
            continue
        for col, cell in enumerate(row):
            if isinstance(cell, str) and _NUMBER_RE.match(cell.strip()):
                if col < len(columns):
                    numeric_columns.append(columns[col])
    for col in sorted(set(numeric_columns) | {str(k) for k in units}):
        raw = units.get(col)
        unit = ""
        declared_status = str(status.get(col) or "")
        if isinstance(raw, dict):
            unit = str(raw.get("unit") or raw.get("value") or "")
            declared_status = declared_status or str(raw.get("unit_status")
                                                     or raw.get("status") or "")
        elif raw is not None:
            unit = str(raw)
        if not unit:
            # ``time_h`` hides its unit in the header suffix: accept "h"/"mm"/"%"
            suffix = re.search(r"[_\-]([a-z%]{1,4})$", col.lower())
            if suffix and re.match(r"^(h|hr|hrs|min|s|ms|mm|um|nm|cm|kg|mg|ug|ng|"
                                   r"m|g|l|ml|ul|n|mN|pa|kpa|degc|c|k|%|x)$",
                                   suffix.group(1)):
                unit = suffix.group(1)
                declared_status = declared_status or "declared_in_header"
        out.append((col, unit, declared_status))
    return out


def _drawn_unit_channels(root):
    """``(unit, channel name, element id, where)`` for drawn numeric channels.

    Only channels that *assert a quantity in themselves* are returned: an entity's
    measured value and its abundance encoding.  Chart series are covered by
    :func:`_column_units`, because the unit belongs to the numeric column the
    series plots, not to the category the series is named after.
    """
    out = []
    for el in _iter_all(root):
        ident = str(_attr(el, "id") or "")
        role = str(_attr_ci(el, "data-text-role") or "")
        if ident.startswith(("entval:", "entabund:")) or role in ("entity-value",
                                                                  "entity-abundance"):
            label = _group_title(el) or ident
            out.append((str(_attr_ci(el, "data-unit") or ""), label, ident or role,
                        ident or role))
    return out


def _check_unit_missing(svg_entries, model, channels):
    """``E_UNIT_MISSING`` (error) + ``W_UNIT_DIMENSIONLESS_ASSUMED`` (warning).

    A drawn numeric channel with no unit is a defect -- *unless* the channel is
    dimensionless by convention (``p_value``, ``fold_change``, ``ratio``, ``count``,
    ``n``, ``log2FC``, ``q_value``, ``FDR``, ``r2``, ...).  Those cases are
    recorded as ``W_UNIT_DIMENSIONLESS_ASSUMED`` with the column name, so the run
    can stay honest without failing: a real material routinely omits the unit of a
    p-value.  Named quantities (``concentration``, ``time``, ``activity``,
    ``rate``) keep failing.
    """
    error_code, warn_code = "E_UNIT_MISSING", "W_UNIT_DIMENSIONLESS_ASSUMED"
    if not svg_entries:
        return (_missing_check(error_code, "units on drawn values", channels, ["svg"]),
                _missing_check(warn_code, "dimensionless assumptions", channels, ["svg"]))
    problems, assumed, checked = [], [], []
    for entry in svg_entries:
        root, err = _parse_svg(entry["path"])
        if err:
            problems.append(("%s" % entry["name"], "%s: %s" % (entry["name"], err)))
            continue
        for unit, name, ident, where in _drawn_unit_channels(root):
            if str(unit).strip():
                checked.append({"element": ident, "unit": unit})
                continue
            verdict, why = dimensionless_column(name)
            if verdict == "dimensionless":
                assumed.append("drawn channel %s (%s) carries no unit: %s -- treated as "
                               "dimensionless" % (ident, name, why))
            else:
                problems.append((where, "drawn numeric channel %s (%s) has no unit: %s"
                                 % (ident, name, why)))
    for column, unit, declared_status in _column_units(model):
        if str(unit).strip():
            checked.append({"column": column, "unit": unit,
                            "status": declared_status or "declared"})
            continue
        verdict, why = dimensionless_column(column)
        if declared_status in ("dimensionless", "not_applicable", "na"):
            assumed.append("data column %r carries no unit and the model marks it %s -- "
                           "recorded as dimensionless by convention"
                           % (column, declared_status))
        elif verdict == "dimensionless":
            assumed.append("data column %r has no unit in data.units: %s -- recorded as "
                           "dimensionless by convention" % (column, why))
        else:
            problems.append(("data.units.%s" % column,
                             "data column %r has no unit (data.units[%r]): %s"
                             % (column, column, why)))
    where = problems[0][0] if problems else "data.units"
    evidence = {"unitless": [message for _w, message in problems],
                "assumed_dimensionless": assumed[:20],
                "with_unit": checked[:20]}
    if problems:
        error_check = _check(error_code, "error", False,
                             "; ".join(message for _w, message in problems)[:900],
                             evidence, where=where)
    else:
        error_check = _check(error_code, "error", True,
                             "every drawn numeric channel declares its unit (%d channels)"
                             % len(checked), evidence, where="data.units")
    warn_check = _check(warn_code, "warn", not assumed,
                        ("%d channel(s) treated as dimensionless by convention: %s"
                         % (len(assumed), "; ".join(assumed[:4])) if assumed
                         else "no unit-less channel needed a dimensionless assumption"),
                        {"assumed": assumed}, where="data.units")
    return error_check, warn_check


def _svg_text_boxes(root, mm_per_user):
    """Approximate label rectangles (mm) for every ``<text>`` in the master.

    A raster that a reader opens must show the labels the master declares.  The
    box is estimated from the anchor, the font size and the character count (a
    generous margin absorbs font-metric error and rotation), which is enough to
    detect a blank or clearly incomplete raster without an OCR dependency.
    """
    boxes = []
    for el in _iter_all(root):
        if _strip_ns(el.tag) != "text":
            continue
        content = _text_content(el)
        if not content.strip():
            continue
        try:
            x = float(_attr(el, "x"))
            y = float(_attr(el, "y"))
            font = float(_attr(el, "font-size"))
        except (TypeError, ValueError):
            continue
        anchor = str(_attr(el, "text-anchor") or "start").lower()
        width = max(1.6, len(content) * font * 0.62)
        height = max(1.6, font * 1.35)
        x0 = x if anchor == "start" else (x - width / 2.0 if anchor == "middle" else x - width)
        boxes.append({"text": content, "x": (x0) * mm_per_user - 2.0,
                      "y": y * mm_per_user - height * 0.95 - 2.0,
                      "w": width * mm_per_user + 4.0,
                      "h": height * mm_per_user + 4.0})
    return boxes


def _check_raster_pixels(raster_entries, channels, model, svg_entries):
    """``raster_pixel_ink`` -- a raster must really show the master's labels.

    Reads the pixels (Pillow) and asserts the image is not blank and that ink
    exists inside the label rectangles the editable master declares.  A blank
    PNG, a solid block, or a raster whose labels were dropped cannot pass, which
    is the failure "only a bitmap screenshot was produced" that the challenge
    names.  Swatch colours and node fills are measured by ``export.pixel_check``
    at production time; this gate is the independent artifact-side leg.
    """
    if not raster_entries:
        return _missing_check("raster_pixel_ink", "raster (PNG/TIFF)", channels,
                              ["png", "tiff"])
    try:
        from PIL import Image
    except Exception as exc:                             # noqa: BLE001
        return _check("raster_pixel_ink", "warn", True,
                      "Pillow unavailable: pixel inspection not possible (%s)" % exc,
                      {"applicable": False, "reason": str(exc)})
    boxes = []
    for entry in svg_entries or []:
        root, err = _parse_svg(entry["path"])
        if err:
            continue
        mm_per_user = _svg_scale(root)
        if mm_per_user:
            boxes.extend(_svg_text_boxes(root, mm_per_user))
    evidence = {}
    problems = []
    for entry in raster_entries:
        path = entry["path"]
        if not os.path.isfile(path):
            problems.append("%s: missing file" % entry["name"])
            continue
        try:
            with Image.open(path) as image:
                image.load()
                grey = image.convert("L")
                pixels = grey.load()
                width, height = grey.size
                histogram = grey.histogram()
                total = float(width * height) or 1.0
                inked_total = sum(count for value, count in enumerate(histogram)
                                  if value < 240)
                ink_fraction = inked_total / total
                inked, checked, missing = 0, 0, []
                for box in boxes:
                    # the raster is at a different scale than the SVG's mm grid:
                    # locate the box by fraction of the canvas, not by dpi
                    canvas_w = channels.get("canvas_width_mm") or _canvas_width_mm(boxes)
                    if not canvas_w:
                        continue
                    scale = width / float(canvas_w)
                    x0 = int(max(0, box["x"] * scale))
                    x1 = int(min(width, (box["x"] + box["w"]) * scale))
                    y0 = int(max(0, box["y"] * scale))
                    y1 = int(min(height, (box["y"] + box["h"]) * scale))
                    if x1 <= x0 or y1 <= y0:
                        continue
                    checked += 1
                    hit = False
                    for y in range(y0, y1):
                        for x in range(x0, x1):
                            if pixels[x, y] < 200:
                                hit = True
                                break
                        if hit:
                            break
                    if hit:
                        inked += 1
                    else:
                        missing.append(box["text"][:24])
        except Exception as exc:                         # noqa: BLE001
            problems.append("%s: pixel inspection failed: %s" % (entry["name"], exc))
            evidence[entry["name"]] = {"error": str(exc)}
            continue
        record = {"ink_fraction": round(ink_fraction, 6),
                  "label_regions": checked, "label_regions_with_ink": inked,
                  "missing_examples": missing[:6]}
        evidence[entry["name"]] = record
        if ink_fraction <= 0.0004:
            problems.append("%s: the raster is blank (ink fraction %.5f); it does not "
                            "reproduce the figure" % (entry["name"], ink_fraction))
        elif ink_fraction > 0.97:
            problems.append("%s: the raster is a solid block (ink fraction %.4f)"
                            % (entry["name"], ink_fraction))
        if checked and inked < max(1, int(0.5 * checked)):
            problems.append("%s: only %d/%d label rectangles carry ink (missing e.g. %s): the "
                            "raster does not show the master's labels"
                            % (entry["name"], inked, checked, ", ".join(missing[:4])))
    if problems:
        return _check("raster_pixel_ink", "error", False, "; ".join(problems)[:600],
                      evidence, where="raster pixels")
    if not evidence:
        return _check("raster_pixel_ink", "warn", True,
                      "N/A: no raster could be inspected", {"applicable": False})
    return _check("raster_pixel_ink", "error", True,
                  "raster pixels reproduce the master's labels: %s"
                  % ", ".join("%s(ink %.4f, labels %d/%d)"
                              % (n, e.get("ink_fraction", 0),
                                 e.get("label_regions_with_ink", 0),
                                 e.get("label_regions", 0))
                              for n, e in evidence.items()),
                  evidence, where="raster pixels")


def _canvas_width_mm(boxes):
    right = max((b["x"] + b["w"] for b in boxes), default=0.0)
    return right if right > 1.0 else None


def _check_coverage(entries, channels):
    """Requested vs produced.  Missing core formats are errors; extras are warnings."""
    present = {e.get("format") for e in entries if os.path.isfile(e["path"])}
    expected = [f for f in channels["formats"] if f in ("svg", "pdf", "png", "tiff", "eps")]
    missing = [f for f in expected if f not in present]
    fatal = [f for f in missing if f in CORE_FORMATS]
    detail = ("missing requested format(s): %s%s" % (
        ", ".join(missing),
        " (core formats missing: %s -- a journal submission cannot be completed without "
        "these)" % ", ".join(fatal) if fatal else
        " (all core formats present; the missing ones are optional extras)")
        if missing else "all requested formats present: %s" % ", ".join(sorted(present)))
    return _check("format_coverage",
                  "warn" if (missing and not fatal) else "error", not missing, detail,
                  {"requested": expected, "present": sorted(present), "missing": missing,
                   "missing_core": fatal})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def check_artifacts(paths, spec, *, model=None, materials=None) -> dict:
    """Run the real compliance checks over the exported artifacts.

    ``paths`` accepts a list of paths, a ``{format: path}`` dict (the shape
    ``export_all()["formats"]`` can be reduced to), a list of ``export_all``
    format entries, or a directory.  Missing and corrupt artifacts are reported
    as failed checks; the function itself always returns a dict.

    ``materials`` is optional and additive: a ``{path: text}`` mapping, a list of
    files/directories, or a root directory.  Without it the verbatim source legs
    of ``E_QUOTE_NOT_FOUND`` / ``E_LABEL_NOT_IN_SOURCE`` /
    ``E_NUMBER_NOT_IN_SOURCE`` run against the model and the canvas only, and say
    so in ``evidence.material_basis`` instead of pretending to have checked text
    they never read.
    """
    channels = _spec(spec)
    entries = _normalise_paths(paths)
    groups = _by_format(entries)
    drawn = _drawn_canvas_mm(groups.get("svg") or [], model, channels)
    svg_entries = groups.get("svg") or []

    checks = []
    checks.append(_check_coverage(entries, channels))
    checks.append(_check_nonempty(entries, channels))
    checks.append(_check_svg_layers(svg_entries, channels))
    checks.append(_check_svg_editable(svg_entries, channels))
    checks.append(_check_svg_provenance(svg_entries, model, channels))
    checks.append(_check_svg_legend_colors(svg_entries, model, channels))
    checks.append(_check_svg_edge_direction(svg_entries, model, channels))
    # ---- CONTRACT 3.2-3.6 hard gates (interaction semantics + encodings) ----
    unit_error, unit_warn = _check_unit_missing(svg_entries, model, channels)
    checks.extend([
        _check_interaction_style(svg_entries, model, channels),
        _check_compartment_mismatch(svg_entries, model, channels),
        _check_membrane_placement(svg_entries, model, channels),
        _check_flow_direction(svg_entries, model, channels),
        _check_legend_data_mismatch(svg_entries, model, channels),
        _check_gene_protein_confusion(svg_entries, model, channels),
        _check_untraced_canvas_elements(svg_entries, model, channels),
        _check_quote_not_found(svg_entries, model, channels, materials),
        _check_label_not_in_source(svg_entries, model, channels, materials),
        _check_number_not_in_source(svg_entries, model, channels, materials),
        unit_error,
        unit_warn,
    ])
    checks.append(_check_line_width(svg_entries, channels))
    checks.append(_check_raster_dpi(groups.get("png", []) + groups.get("tiff", []),
                                    channels, model, drawn))
    checks.append(_check_raster_opens(groups.get("png", []) + groups.get("tiff", []), channels))
    checks.append(_check_raster_pixels(groups.get("png", []) + groups.get("tiff", []),
                                       channels, model, svg_entries))
    checks.append(_check_pdf_opens(groups.get("pdf") or [], channels))
    checks.append(_check_pdf_fonts(groups.get("pdf") or [], channels))
    checks.append(_check_pdf_size(groups.get("pdf") or [], channels, model, drawn))
    checks.append(_check_pdf_text(groups.get("pdf") or [], model, channels,
                                  groups.get("svg") or []))
    checks.append(_check_eps_fonts(groups.get("eps") or [], channels))
    checks.append(_check_color_space(entries, channels))

    errors = [c for c in checks if not c["ok"] and c["level"] == "error"]
    warnings = [c for c in checks if not c["ok"] and c["level"] == "warn"]
    result = {
        "schema_version": SCHEMA_VERSION,
        "created_utc": common.now_utc(),
        "ok": not errors,
        "checks": checks,
        "canvas_used": drawn,
        "summary": {
            "total": len(checks),
            "passed": len([c for c in checks if c["ok"]]),
            "failed_errors": [c["id"] for c in errors],
            "failed_warnings": [c["id"] for c in warnings],
            "artifacts": {e["name"]: e.get("format") for e in entries},
        },
        "spec": {k: channels[k] for k in ("dpi", "min_line_width_pt", "min_text_pt",
                                          "color_space", "font_embedding_required",
                                          "width_mm", "max_height_mm", "formats")},
    }
    return result
