"""Persistent local preferences; snapshots are copied into each new job."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
from string import Formatter

CONFIG_NAME = "gk-vector.local.json"
DEFAULTS = {
    "schema_version": 1,
    "output_folder": "output",
    "job_template": "{design}/{revision}",
    "filename_template": "{design}_{revision}.{ext}",
    "profile": "profiles/201-107.json",
    "overrides": {},
    "svg": {"units": "mm", "version": "1.1", "precision": 3,
            "trace_mode": "spline", "background": "solid",
            "shape_rendering": "geometricPrecision"},
}


def merge(base: dict, patch: dict) -> dict:
    result = deepcopy(base)
    for key, value in patch.items():
        if key not in base:
            raise ValueError(f"Unknown configuration setting: {key}")
        if isinstance(base[key], dict):
            if not isinstance(value, dict):
                raise ValueError(f"{key} must be a JSON object")
            result[key] = {**base[key], **deepcopy(value)} if key == "overrides" else merge(base[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def validate_svg(svg: dict) -> dict:
    value = merge(DEFAULTS["svg"], svg)
    for key, choices in {"units": ("mm", "px"), "version": ("1.1", "2.0"),
                         "trace_mode": ("spline", "polygon"), "background": ("solid", "transparent"),
                         "shape_rendering": ("auto", "geometricPrecision", "crispEdges")}.items():
        if value[key] not in choices:
            raise ValueError(f"svg.{key} must be one of {choices}")
    if type(value["precision"]) is not int or not 0 <= value["precision"] <= 6:
        raise ValueError("svg.precision must be an integer between 0 and 6")
    return value


def render_template(template: str, *, design: str, revision: str, ext: str = "", filename: bool = False) -> str:
    for value in (design, revision):
        if not re.fullmatch(r"[\w-]+", value, re.UNICODE) or value.endswith((".", " ")):
            raise ValueError("Design and revision must contain only letters, digits, underscores or hyphens")
    if not isinstance(template, str) or not template:
        raise ValueError("Templates must be nonempty strings")
    fields = set()
    for _, field, spec, conversion in Formatter().parse(template):
        if field is not None:
            if field not in {"design", "revision", "ext"} or spec or conversion:
                raise ValueError("Templates support only {design}, {revision}, and {ext}")
            fields.add(field)
    if filename and "ext" not in fields:
        raise ValueError("Filename template must include {ext}")
    value = template.format(design=design, revision=revision, ext=ext)
    parts = value.replace("\\", "/").split("/")
    if any(not p or p in (".", "..") or re.search(r'[<>:"|?*\x00-\x1f]', p) or p.endswith((".", " ")) for p in parts):
        raise ValueError("Template produced an invalid or unsafe path")
    if any(p.split('.')[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1,10)), *(f"LPT{i}" for i in range(1,10))} for p in parts):
        raise ValueError("Template produced a Windows reserved name")
    if filename and len(parts) != 1:
        raise ValueError("Filename template must produce a basename, not a directory")
    if filename and not value.lower().endswith("." + ext):
        raise ValueError("Filename template must end with .{ext}")
    return value


def read_config(root: str | Path) -> dict:
    path = Path(root) / CONFIG_NAME
    if not path.exists():
        raise ValueError("Initial setup required: invoke $leotard-setup or run 'run.py setup --defaults'.")
    return validate_config(json.loads(path.read_text(encoding="utf-8")))


def validate_config(config: dict) -> dict:
    value = merge(DEFAULTS, config)
    if value["schema_version"] != 1:
        raise ValueError("Unsupported configuration schema")
    for key in ("output_folder", "profile"):
        if not isinstance(value[key], str) or not value[key].strip():
            raise ValueError(f"{key} must be a nonempty path")
    value["svg"] = validate_svg(value["svg"])
    render_template(value["job_template"], design="example", revision="r01")
    for ext in ("svg", "tif", "cdr"):
        render_template(value["filename_template"], design="example", revision="r01", ext=ext, filename=True)
    if not isinstance(value["overrides"], dict):
        raise ValueError("overrides must be a JSON object")
    return value


def configure(root: str | Path, patch: dict | None = None) -> dict:
    root = Path(root).resolve()
    path = root / CONFIG_NAME
    current = read_config(root) if path.exists() else deepcopy(DEFAULTS)
    value = validate_config(merge(current, patch or {}))
    profile = (root / value["profile"]).resolve()
    from .pipeline import resolve_settings
    resolve_settings(json.loads(profile.read_text(encoding="utf-8")), {**value["overrides"], "svg": value["svg"]})
    # Atomic replacement avoids a partially written settings file.
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    return describe(root, value)


def describe(root: str | Path, config: dict) -> dict:
    root = Path(root).resolve()
    return {"config_file": str(root / CONFIG_NAME), "settings": config,
            "resolved_output_folder": str((root / config["output_folder"]).resolve()),
            "example_job": str(job_path(root, config, "example", "r01")),
            "example_exports": export_names(config, "example", "r01")}


def export_names(config: dict, design: str, revision: str) -> dict:
    return {ext: render_template(config["filename_template"], design=design, revision=revision, ext=ext, filename=True)
            for ext in ("svg", "tif", "cdr")}


def job_path(root: str | Path, config: dict, design: str, revision: str) -> Path:
    base = (Path(root) / config["output_folder"]).resolve()
    job = (base / render_template(config["job_template"], design=design, revision=revision)).resolve()
    if not job.is_relative_to(base):
        raise ValueError("Job path escapes the configured output folder")
    return job
