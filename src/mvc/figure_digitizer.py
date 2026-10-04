"""OPTION — read data points off a published kinetics figure (vision model).

This is the "Track 2 touch" kept on-topic: papers often report kinetics only as
a figure, so the evidence base cannot hold the numbers. A vision-language model
can propose (day, value) pairs from the plot image.

Honesty rules baked in:
  * every extracted series is tagged `source="digitized_from_figure"`, which the
    comparability engine automatically flags as `conditional`;
  * the model must also return the axis ranges it believes it read; if those are
    missing or implausible the extraction is rejected;
  * extracted points are never written into the verified evidence base — they
    land in a separate file and must be checked against the paper by a human.

Needs: `MVC_VLM_MODEL` pulled in Ollama (e.g. qwen2.5vl:3b), and PyMuPDF only if
you extract the images from a PDF yourself.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from . import llm

FIGURE_SCHEMA = {
    "type": "object",
    "properties": {
        "x_axis": {"type": "object", "properties": {
            "label": {"type": "string"}, "min": {"type": "number"}, "max": {"type": "number"},
            "unit": {"type": "string", "enum": ["days", "weeks", "months", "unknown"]},
            "log_scale": {"type": "boolean"}},
            "required": ["label", "min", "max", "unit", "log_scale"]},
        "y_axis": {"type": "object", "properties": {
            "label": {"type": "string"}, "min": {"type": "number"}, "max": {"type": "number"},
            "log_scale": {"type": "boolean"}},
            "required": ["label", "min", "max", "log_scale"]},
        "series": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"},
            "compartment_guess": {"type": "string", "enum": ["nasal", "oral", "serum", "blood_cells", "unknown"]},
            "points": {"type": "array", "items": {"type": "object", "properties": {
                "x": {"type": "number"}, "y": {"type": "number"}},
                "required": ["x", "y"]}}},
            "required": ["name", "compartment_guess", "points"]}},
        "readable": {"type": "boolean"},
        "caveats": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["x_axis", "y_axis", "series", "readable", "caveats"],
}

SYSTEM = """You read data points off a scientific line/scatter plot of antibody kinetics.
Rules:
- Report the axis ranges exactly as printed on the axes; if an axis is unreadable set readable=false.
- Give one entry per visible series, using its legend name.
- Read the x value in the unit printed on the x axis (do not convert).
- Only report points you can actually see a marker for. Do not interpolate, do not invent.
- If the y axis is logarithmic, report the value, not its logarithm.
- List every reason the reading may be wrong in caveats (overlapping markers, error bars, broken axis...)."""


@dataclass
class Digitization:
    source_image: str
    data: dict
    rows: pd.DataFrame
    rejected: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.rejected


def _validate(d: dict) -> list[str]:
    bad = []
    if not d.get("readable", False):
        bad.append("model reported the figure as unreadable")
    for ax in ("x_axis", "y_axis"):
        a = d.get(ax, {})
        if a.get("min") is None or a.get("max") is None or a["min"] >= a["max"]:
            bad.append(f"{ax}: implausible range {a.get('min')}..{a.get('max')}")
    if d.get("x_axis", {}).get("unit") == "unknown":
        bad.append("x-axis unit unknown: timepoints cannot be placed on a day scale")
    if not d.get("series"):
        bad.append("no series extracted")
    for s in d.get("series", []):
        pts = s.get("points", [])
        if len(pts) < 3:
            bad.append(f"series '{s.get('name')}': only {len(pts)} points, not usable for kinetics")
        xs = [p["x"] for p in pts]
        a = d["x_axis"]
        if any(x < a["min"] - 1e-6 or x > a["max"] + 1e-6 for x in xs):
            bad.append(f"series '{s.get('name')}': points outside the x-axis range")
    return bad


TO_DAYS = {"days": 1.0, "weeks": 7.0, "months": 30.0}


def digitize(image_path: str | Path, model: str | None = None, hint: str = "") -> Digitization:
    path = Path(image_path)
    img = path.read_bytes()
    prompt = "Extract the data points from this figure." + (f"\nContext: {hint}" if hint else "")
    raw = llm.chat(prompt, system=SYSTEM, model=model or llm.VLM_MODEL,
                   json_schema=FIGURE_SCHEMA, images=[img])
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return Digitization(str(path), {}, pd.DataFrame(), ["model did not return valid JSON"])
    rejected = _validate(data)
    rows = []
    if not rejected:
        factor = TO_DAYS.get(data["x_axis"]["unit"], 1.0)
        for s in data["series"]:
            for i, p in enumerate(s["points"]):
                rows.append({
                    "subject_id": f"figure_{s['name']}", "arm_id": s["name"],
                    "day": float(p["x"]) * factor, "value": float(p["y"]),
                    "compartment": s["compartment_guess"],
                    "method": "nasal_wash" if s["compartment_guess"] == "nasal" else "serum",
                    "isotype": "IgA" if "iga" in s["name"].lower() else "IgG",
                    "assay": "elisa_binding", "unit": "au_ml", "normalization": "none",
                    "antigen": "unspecified", "lab": f"figure:{path.stem}",
                    "source": "digitized_from_figure", "lloq": None, "below_lloq": False,
                    "point_index": i, "y_axis_label": data["y_axis"]["label"],
                })
    return Digitization(str(path), data, pd.DataFrame(rows), rejected)


def extract_figures_from_pdf(pdf_path: str | Path, out_dir: str | Path, min_px: int = 300) -> list[Path]:
    """Pull raster images out of a PDF so they can be digitised (needs PyMuPDF)."""
    import fitz

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    with fitz.open(pdf_path) as doc:
        for pno, page in enumerate(doc, start=1):
            for i, info in enumerate(page.get_images(full=True)):
                pix = fitz.Pixmap(doc, info[0])
                if pix.width < min_px or pix.height < min_px:
                    continue
                if pix.n > 4:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                p = out_dir / f"{Path(pdf_path).stem}_p{pno}_i{i}.png"
                pix.save(p)
                saved.append(p)
    return saved


def report(d: Digitization) -> str:
    lines = [f"# Figure digitisation — {Path(d.source_image).name}", ""]
    if d.rejected:
        lines += ["**REJECTED** — not usable:", ""] + [f"- {r}" for r in d.rejected]
        return "\n".join(lines) + "\n"
    x, y = d.data["x_axis"], d.data["y_axis"]
    lines += [f"- x axis: {x['label']} [{x['min']}, {x['max']}] {x['unit']}, log={x['log_scale']}",
              f"- y axis: {y['label']} [{y['min']}, {y['max']}], log={y['log_scale']}",
              f"- series: {len(d.data['series'])}, points: {len(d.rows)}", ""]
    if d.data.get("caveats"):
        lines += ["**Model-reported caveats**", ""] + [f"- {c}" for c in d.data["caveats"]] + [""]
    lines += ["All rows are tagged `digitized_from_figure`; the comparability engine marks them "
              "`conditional`. A human must check them against the paper before any use.", ""]
    return "\n".join(lines)
