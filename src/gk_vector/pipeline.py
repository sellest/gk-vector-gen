from __future__ import annotations

import hashlib
import io
import json
import math
import tempfile
from pathlib import Path
import xml.etree.ElementTree as ET

import cv2
import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageOps, ImageStat, ImageCms
import resvg_py
import vtracer

from .config import validate_svg
from .palette import DEFAULT_PALETTE, load_palette, Matcher, write_color_report, build_color_review

SVG = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def resolve_settings(profile: dict, overrides: dict | None = None) -> dict:
    settings = dict(profile)
    overrides = overrides or {}
    allowed = {"canvas_mm", "dpi", "pixels", "background", "trace_max_dimension",
               "color_precision", "gradient_step", "filter_speckle", "cdr_version", "preserve_white_details", "svg"}
    unknown = overrides.keys() - allowed
    if unknown:
        raise ValueError(f"Unknown settings: {sorted(unknown)}")
    settings.update(overrides)
    settings["svg"] = validate_svg(overrides.get("svg", settings.get("svg", {})))
    dpi = float(settings["dpi"])
    if not math.isfinite(dpi) or not 1 <= dpi <= 2400:
        raise ValueError("DPI must be finite and between 1 and 2400")
    mm = settings["canvas_mm"]
    if len(mm) != 2 or any(not math.isfinite(float(v)) or v <= 0 for v in mm):
        raise ValueError("canvas_mm requires two positive finite dimensions")
    pixels = [round(v / 25.4 * dpi) for v in mm]
    if "pixels" in overrides:
        requested = overrides["pixels"]
        if len(requested) != 2 or any(type(v) is not int or v < 1 for v in requested):
            raise ValueError("pixels requires two positive integers")
        if "canvas_mm" in overrides and requested != pixels:
            raise ValueError("Conflicting canvas_mm, pixels and DPI")
        pixels = requested
        settings["canvas_mm"] = [v / dpi * 25.4 for v in pixels]
    if min(pixels) < 1 or pixels[0] * pixels[1] > 160_000_000:
        raise ValueError("Output must contain 1 to 160 million pixels")
    if not 128 <= settings["trace_max_dimension"] <= 5000:
        raise ValueError("trace_max_dimension must be between 128 and 5000")
    if type(settings.get("preserve_white_details", True)) is not bool:
        raise ValueError("preserve_white_details must be true or false")
    if not 1 <= settings["color_precision"] <= 8 or not 0 <= settings["gradient_step"] <= 255 or settings["filter_speckle"] < 0:
        raise ValueError("Invalid tracing precision, gradient step or speckle filter")
    settings["pixels"] = pixels
    # Check colors here, before creating a job or allocating output buffers.
    Image.new("RGB", (1, 1), settings["background"])
    return settings


def load_job(folder: str | Path) -> tuple[Path, dict]:
    folder = Path(folder).resolve()
    return folder, json.loads((folder / "job.json").read_text(encoding="utf-8"))


def verify_sources(folder: Path, job: dict) -> None:
    if job.get('settings_sha256') and hashlib.sha256(json.dumps(job['settings'],sort_keys=True).encode()).hexdigest()!=job['settings_sha256']:
        raise ValueError('Settings changed. Prepare a new reconstruction revision.')
    for filename, expected in job["source_hashes"].items():
        if digest(folder / filename) != expected:
            raise ValueError(f"Source changed: {filename}. Prepare a new reconstruction revision.")
    if job.get('color_review') and json.loads((folder/'color-selection.json').read_text(encoding='utf-8'))!=job['color_review']:
        raise ValueError('Color selection changed. Prepare a new reconstruction revision.')


def prepare(image: str | Path, folder: str | Path, profile: dict,
            overrides: dict | None = None, masks: str | Path | None = None,
            identity: dict | None = None, palette_file: str | Path = DEFAULT_PALETTE) -> dict:
    """Save an immutable draft input and two explicit panel masks.

    Automatic segmentation assumes two disconnected panels on a light neutral
    background. A supplied grayscale mask bypasses segmentation. White=artwork.
    """
    settings = resolve_settings(profile, overrides)
    palette = load_palette(palette_file)
    opened = ImageOps.exif_transpose(Image.open(image))
    alpha = opened.convert("RGBA").getchannel("A")
    managed = opened.convert("RGB")
    if opened.info.get("icc_profile"):
        managed = ImageCms.profileToProfile(managed, ImageCms.ImageCmsProfile(io.BytesIO(opened.info["icc_profile"])),
                                           ImageCms.createProfile("sRGB"), outputMode="RGB")
    source = managed.convert("RGBA")
    source.putalpha(alpha)
    rgb = Image.new("RGB", source.size, settings["background"])
    rgb.paste(source, mask=source.getchannel("A"))
    array = np.array(rgb)
    if masks is not None:
        mask_image = Image.open(masks).convert("L")
        if mask_image.size != rgb.size:
            raise ValueError("Mask dimensions must match the source image")
        candidate = (np.array(mask_image) > 127).astype(np.uint8) * 255
    elif source.getchannel("A").getextrema()[0] < 255:
        candidate = (np.array(source.getchannel("A")) > 127).astype(np.uint8) * 255
    else:
        # Colorful/dark artwork plus thin dark outlines separate the neutral
        # exterior from white trim. Fill contours so white logos remain opaque.
        spread = np.max(array, axis=2).astype(int) - np.min(array, axis=2).astype(int)
        candidate = ((spread > 35) | (np.min(array, axis=2) < 200)).astype(np.uint8) * 255
        # Close antialiasing-sized breaks in fine outer outlines before finding
        # enclosed silhouettes, otherwise light trim leaks into the exterior.
        candidate = cv2.morphologyEx(candidate, cv2.MORPH_CLOSE, np.ones((3,3), np.uint8))
    contours, _ = cv2.findContours(candidate, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = [c for c in contours if cv2.contourArea(c) > rgb.width * rgb.height * .03]
    contours.sort(key=lambda c: cv2.boundingRect(c)[0])
    if len(contours) != 2:
        raise ValueError(f"Expected 2 separate panels; found {len(contours)}. Supply an explicit combined mask.")
    if any(cv2.boundingRect(c)[0] == 0 or cv2.boundingRect(c)[1] == 0 or
           cv2.boundingRect(c)[0] + cv2.boundingRect(c)[2] >= rgb.width or
           cv2.boundingRect(c)[1] + cv2.boundingRect(c)[3] >= rgb.height for c in contours):
        raise ValueError("Panel touches canvas edge; add margins or provide a complete reconstruction")
    folder = Path(folder).resolve()
    if folder.exists():
        raise ValueError("Job directory already exists; use a new revision directory")
    folder.mkdir(parents=True)
    rgb.save(folder / "source.png")
    union = np.zeros(array.shape[:2], dtype=np.uint8)
    outline = rgb.copy()
    draw = ImageDraw.Draw(outline)
    panels = []
    for name, contour in zip(("front", "back"), contours):
        binary = np.zeros_like(union)
        cv2.drawContours(binary, [contour], -1, 255, cv2.FILLED)
        union |= binary
        mask = Image.fromarray(binary)
        mask.save(folder / f"{name}-mask.png")
        rgba = rgb.convert("RGBA")
        rgba.putalpha(mask)
        rgba.save(folder / f"{name}.png")
        box = list(cv2.boundingRect(contour))
        panels.append({"name": name, "bounds_px": box})
        points = [tuple(map(int, p[0])) for p in contour]
        draw.line(points + [points[0]], fill="#ff00ff", width=2)
    mask = Image.fromarray(union)
    clean = Image.new("RGB", rgb.size, settings["background"])
    clean.paste(rgb, mask=mask)
    clean.save(folder / "clean.png")
    outline.save(folder / "mask-review.png")
    write_json(folder / "palette.json", palette)
    color_review = build_color_review(folder, clean,
        {name:Image.open(folder / f'{name}-mask.png').convert('L') for name in ('front','back')},settings,palette)
    inputs = ["source.png", "clean.png", "front-mask.png", "back-mask.png", "mask-review.png", "palette.json"]
    inputs.extend(color_review['files'].values())
    job = {"schema_version": 1, "status": "draft", "settings": settings,
           "settings_sha256":hashlib.sha256(json.dumps(settings,sort_keys=True).encode()).hexdigest(),
           "source_size": list(rgb.size), "panels": panels,
           "source_hashes": {name: digest(folder / name) for name in inputs},
           "palette": {"version":palette["version"], "source_sha256":palette["source_sha256"], "snapshot":"palette.json"},
           "color_review":color_review,
           "approval": None,
           "notes": "Left panel=front, right=back. Masks are artwork silhouettes, not validated sewing patterns."}
    if identity:
        job["identity"] = identity
    write_json(folder / "job.json", job)
    return job


def approve(folder: str | Path, note: str, colors_approved: bool = False) -> dict:
    if not note.strip():
        raise ValueError("Record the client's approval message")
    folder, job = load_job(folder)
    verify_sources(folder, job)
    if not job.get('color_review'):
        raise ValueError('Job predates color selection review. Prepare a new revision.')
    if not colors_approved:
        raise ValueError('Approval must include the proposed color selection. Review colors-review.html, then explicitly approve colors.')
    job["status"] = "approved"
    job["approval"] = {"note": note, "source_hashes": job["source_hashes"],
                       "scope":['artwork','panel_masks','color_selection'],
                       "color_selection_sha256":digest(folder/'color-selection.json')}
    write_json(folder / "job.json", job)
    return job


def vectorize(folder: str | Path, candidate: bool = False) -> dict:
    folder, job = load_job(folder)
    verify_sources(folder, job)
    if not job.get('color_review'):
        raise ValueError('Job predates color selection review. Prepare a new revision.')
    if not candidate and not job["approval"]:
        raise ValueError("Client approval is required. Use candidate=True only for draft conversion tests.")
    if not candidate and 'color_selection' not in job['approval'].get('scope',[]):
        raise ValueError('Color selection approval is required before production conversion.')
    destination = folder / ("candidate" if candidate else "production")
    if destination.exists():
        raise ValueError("Conversion output already exists; use a new job revision")
    # Publish only complete exports. Failed attempts remain retryable.
    with tempfile.TemporaryDirectory(prefix=".conversion-", dir=folder) as temporary:
        staged = Path(temporary) / "result"
        staged.mkdir()
        result = _convert(folder, job, staged, candidate)
        staged.rename(destination)
    return result


def _convert(folder: Path, job: dict, destination: Path, candidate: bool) -> dict:
    settings = job["settings"]
    if not job.get("palette"):
        raise ValueError("Job predates palette support. Prepare a new revision to snapshot its palette.")
    catalog = load_palette(folder / "palette.json")
    selection=json.loads((folder/'color-selection.json').read_text(encoding='utf-8'))
    if selection['palette_version']!=catalog['version']:
        raise ValueError('Color selection and palette versions do not match')
    selected_ids={color['id'] for color in selection['colors']}
    selected_entries=[entry for entry in catalog['entries'] if entry['id'] in selected_ids]
    if not selected_ids or len(selected_entries)!=len(selected_ids):
        raise ValueError('Invalid color selection')
    matcher = Matcher({**catalog,'entries':selected_entries})
    svg_options = validate_svg(settings.get("svg", {}))
    precision = svg_options["precision"]
    names = dict(job.get("identity", {}).get("export_names", {"svg":"panels.svg", "tif":"panels.tif", "cdr":"panels.cdr"}))
    names.setdefault("colors", Path(names["svg"]).stem + "_colors.txt")
    clean = Image.open(folder / "clean.png").convert("RGB")
    trace = Image.open(folder/'palette-matched.png').convert('RGB')
    trace.save(destination / "trace-input.png")
    vtracer.convert_image_to_svg_py(
        str(destination / "trace-input.png"), str(destination / "trace.svg"),
        colormode="color", hierarchical="stacked", mode=svg_options["trace_mode"],
        filter_speckle=settings["filter_speckle"], color_precision=settings["color_precision"],
        layer_difference=settings["gradient_step"], path_precision=precision)
    traced = ET.parse(destination / "trace.svg").getroot()
    (destination / "trace.svg").unlink()
    (destination / "trace-input.png").unlink()
    w, h = settings["pixels"]
    mmw, mmh = settings["canvas_mm"]
    dimensions = {"width": f"{mmw}mm", "height": f"{mmh}mm"} if svg_options["units"] == "mm" else {"width":str(w), "height":str(h)}
    root = ET.Element(f"{{{SVG}}}svg", {**dimensions, "viewBox": f"0 0 {w} {h}",
                      "version":svg_options["version"], "preserveAspectRatio":"xMidYMid meet",
                      "shape-rendering":svg_options["shape_rendering"]})
    if svg_options["background"] == "solid":
        ET.SubElement(root, f"{{{SVG}}}rect", {"width": str(w), "height": str(h), "fill": settings["background"]})
    # Uniform scale and centered letterboxing avoid stretching artwork when the
    # requested export canvas differs from the reconstructed image aspect ratio.
    scale = min(w / trace.width, h / trace.height)
    x, y = (w - trace.width * scale) / 2, (h - trace.height * scale) / 2
    defs = ET.SubElement(root, f"{{{SVG}}}defs")
    clip = ET.SubElement(defs, f"{{{SVG}}}clipPath", {"id": "panels", "clipPathUnits": "userSpaceOnUse"})
    union = np.maximum(np.array(Image.open(folder / "front-mask.png")),
                       np.array(Image.open(folder / "back-mask.png")))
    contours, _ = cv2.findContours(union, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contour_scale = trace.width / clean.width, trace.height / clean.height
    for c in contours:
        c = cv2.approxPolyDP(c, .4, True)
        points = [f"{p[0][0]*contour_scale[0]:.{precision}f},{p[0][1]*contour_scale[1]:.{precision}f}" for p in c]
        ET.SubElement(clip, f"{{{SVG}}}path", {"d": "M" + " L".join(points) + " Z"})
    placed = ET.SubElement(root, f"{{{SVG}}}g", {"transform": f"translate({x} {y}) scale({scale})"})
    clipped = ET.SubElement(placed, f"{{{SVG}}}g", {"clip-path": "url(#panels)"})
    for child in traced:
        clipped.append(child)
    # Color clustering can merge thin white trim into the neutral backdrop.
    # Preserve actual near-white source regions as a separate vector layer,
    # including holes in letters and white outline shapes.
    white_contour_count = 0
    if settings.get("preserve_white_details", True):
        rgb_array = np.array(clean).astype(np.int16)
        whites = ((rgb_array.min(axis=2) >= 210) &
                  (rgb_array.max(axis=2)-rgb_array.min(axis=2) <= 30) & (union > 0)).astype(np.uint8)*255
        white_contours, _ = cv2.findContours(whites, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        commands = []
        for contour in white_contours:
            if cv2.contourArea(contour) < 1:
                continue
            contour = cv2.approxPolyDP(contour, .25, True)
            points = [f"{p[0][0]*contour_scale[0]:.{precision}f},{p[0][1]*contour_scale[1]:.{precision}f}" for p in contour]
            commands.append("M" + " L".join(points) + " Z")
        white_contour_count = len(commands)
        if commands:
            ET.SubElement(clipped, f"{{{SVG}}}path", {"id":"preserved-white-details", "d":" ".join(commands),
                                                      "fill":"#ffffff", "fill-rule":"evenodd"})
    used_colors = matcher.constrain_svg(root)
    write_color_report(destination / names["colors"], catalog, used_colors, names["svg"])
    svg_path = destination / names["svg"]
    ET.ElementTree(root).write(svg_path, encoding="utf-8", xml_declaration=True)
    # Rasterize the vectors themselves, rather than upscaling the input raster.
    svg_text = svg_path.read_text(encoding="utf-8")
    rgba = Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=svg_text, width=w, height=h,
                                                      dpi=settings["dpi"]))).convert("RGBA")
    palette_background, _ = matcher.color(settings["background"])
    rendered = Image.new("RGB", rgba.size, palette_background)
    rendered.paste(rgba, mask=rgba.getchannel("A"))
    rendered.save(destination / names["tif"], compression="tiff_lzw", dpi=(settings["dpi"], settings["dpi"]),
                  icc_profile=ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes())
    preview = rendered.copy()
    preview.thumbnail((1500, 1500))
    preview.save(destination / "vector-preview.png")
    expected = ImageOps.contain(clean, (w, h), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (w, h), settings["background"])
    canvas.paste(expected, ((w - expected.width)//2, (h - expected.height)//2))
    # Report similarity at review resolution to avoid implying a semantic score.
    baseline = canvas.resize(preview.size, Image.Resampling.LANCZOS)
    difference = ImageChops.difference(baseline, preview)
    mae = sum(ImageStat.Stat(difference).mean) / 3
    amplified = difference.point(lambda value: min(255, value * 5))
    amplified.save(destination / "difference-x5.png")
    sheet = Image.new("RGB", (preview.width*2, preview.height+32), "white")
    sheet.paste(baseline, (0,32)); sheet.paste(preview, (preview.width,32))
    draw = ImageDraw.Draw(sheet)
    draw.text((10,8), "RECONSTRUCTED RASTER", fill="black")
    draw.text((preview.width+10,8), "VECTORIZED RENDER - REVIEW REQUIRED", fill="black")
    sheet.save(destination / "comparison.jpg", quality=92)
    result = {"status": "candidate" if candidate else "exported", "settings": settings,
              "source_hashes": job["source_hashes"], "path_count": len(root.findall(f".//{{{SVG}}}path")),
              "embedded_rasters": len(root.findall(f".//{{{SVG}}}image")),
              "review_mae_rgb_0_255": round(mae, 4), "review_required": True,
              "preserved_white_contours": white_contour_count,
              "palette": {"version":catalog["version"],"source_sha256":catalog["source_sha256"],
                          "colors_used":len(used_colors),"matching":"CIELAB Delta E 76",
                          "selected_colors":len(selected_entries),"selection_sha256":digest(folder/'color-selection.json'),
                          "name_review_count":catalog.get("name_review_count",0)},
              "cdr": {"status": "not_exported", "reason": "Run export-cdr on a Windows machine with CorelDRAW installed."},
              "artifacts": names,
              "files": [names["svg"], names["tif"], names["colors"], "vector-preview.png", "comparison.jpg", "difference-x5.png"]}
    write_json(destination / "report.json", result)
    return result
