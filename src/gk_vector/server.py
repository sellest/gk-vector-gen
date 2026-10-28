"""Stdio MCP server restricted to a configured project root."""
import json
import os
from contextlib import contextmanager
import threading
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from . import pipeline
from . import config
from .corel import export_cdr
from .palette import update_palette, load_palette
from .update import update_tool

ROOT = Path(os.environ.get("GK_VECTOR_ROOT", Path.cwd())).resolve()
mcp = FastMCP("GK Panel Artwork")
OPERATION_LOCK=threading.Lock()
RESTART_REQUIRED=False


@contextmanager
def active_operation():
    with OPERATION_LOCK:
        if RESTART_REQUIRED:
            raise ValueError('Restart the app or MCP connection to load the installed update before continuing.')
        yield


@mcp.tool()
def update_gk_vector() -> dict:
    """Update the local gk-vector tool when the user asks to update it.

    Pulls main from the fixed project repository. Startup installs dependencies
    after the client restarts. Preserves local settings/artwork. Refuses tracked
    code changes or non-fast-forward histories. Tell the client to restart the
    app or MCP connection after installation. This is not a palette refresh.
    """
    global RESTART_REQUIRED
    with OPERATION_LOCK:
        result=update_tool()
        RESTART_REQUIRED=RESTART_REQUIRED or result['restart_required']
        return result


def local(path: str) -> Path:
    resolved = (ROOT / path).resolve()
    allowed = [ROOT]
    if (ROOT / config.CONFIG_NAME).exists():
        allowed.append((ROOT / config.read_config(ROOT)["output_folder"]).resolve())
    if not any(resolved.is_relative_to(base) for base in allowed):
        raise ValueError("Paths must stay within GK_VECTOR_ROOT")
    return resolved


@mcp.tool()
def update_pantonic(source: str = "docs/pantonic.tif", destination: str = "palettes/pantonic.json",
                    corrections: dict | None = None, force: bool = False) -> dict:
    """Rebuild the reusable palette from the chart's printed RGB labels, not patch pixels.

    On uncertain RGB readings, returns review/candidate paths and preserves the
    active palette. Corrections require matching source_sha256 and entries keyed
    by grid IDs. Does not modify the source TIFF or existing job snapshots.
    """
    with active_operation():
        return update_palette(local(source), local(destination), corrections, force)


@mcp.tool()
def pantonic_status(palette: str = "palettes/pantonic.json") -> dict:
    """Read the active palette version, chart checksum and OCR name-review count."""
    data = load_palette(local(palette))
    return {key:data[key] for key in ("name","version","source_sha256","grid","name_review_count")} | {"colors":len(data["entries"])}


@mcp.tool()
def workspace_settings() -> dict:
    """Read setup state. Invoke leotard-setup first if configured=False."""
    if not (ROOT / config.CONFIG_NAME).exists():
        return {"configured":False, "defaults":config.DEFAULTS, "next_step":"Invoke leotard-setup to choose output folder, naming and SVG properties."}
    return {"configured":True, **config.describe(ROOT, config.read_config(ROOT))}


@mcp.tool()
def configure_workspace(settings: dict) -> dict:
    """Save initial setup or adjust defaults for NEW jobs. Existing revisions are unchanged.

    Use user-selected output_folder, filename_template, job_template and svg
    properties. A configured external output folder is also permitted for jobs.
    """
    with active_operation():
        return config.configure(ROOT, settings)


@mcp.tool()
def prepare_panels(image: str, job: str | None = None, overrides: dict | None = None,
                   profile: str | None = None, mask: str | None = None,
                   design: str = "leotard", revision: str = "r01") -> dict:
    """Create a draft from a flat reconstruction, with front left and back right.

    This tool does not call an image generator. Generate artwork with the host's
    image tool, save it under the project root, then pass it here. Inspect
    mask-review.png and colors-review.html. Returns color_review.colors with
    chart IDs, names, RGB, HEX, panel shares, and palette-matched preview paths.
    Client approval must cover BOTH the design and the proposed colors before
    production vectorization; no tracing is performed by this preparation tool.
    """
    preferences = config.read_config(ROOT)
    profile_data = json.loads(local(profile or preferences["profile"]).read_text(encoding="utf-8"))
    overrides = dict(overrides or {})
    svg = config.merge(preferences["svg"], overrides.pop("svg", {}))
    resolved = {**preferences["overrides"], **overrides, "svg":svg}
    folder = local(job) if job else config.job_path(ROOT, preferences, design, revision)
    identity = {"design":design, "revision":revision,
                "export_names":config.export_names(preferences, design, revision), "configuration":preferences}
    with active_operation():
        result = pipeline.prepare(local(image), folder, profile_data, resolved, local(mask) if mask else None, identity,
                                  local(preferences["palette_file"]))
    return {"job_folder":str(folder), **result}


@mcp.tool()
def approve_panels(job: str, client_approval: str, colors_approved: bool = False) -> dict:
    """Record approval of artwork, masks AND the color selection returned by prepare_panels.

    Set colors_approved=True only after the client has seen the palette-matched
    preview and color list and approved both. Never infer approval from a test.
    """
    with active_operation():
        return pipeline.approve(local(job), client_approval, colors_approved)


@mcp.tool()
def vectorize_panels(job: str, candidate: bool = False) -> dict:
    """Trace a saved reconstruction to genuine SVG paths and matching TIFF.

    Production requires recorded approval. candidate=True permits draft tests
    without approval. Both return a visual comparison and measured error.
    """
    with active_operation():
        return pipeline.vectorize(local(job), candidate)


@mcp.tool()
def export_native_cdr(job: str, candidate: bool = False) -> dict:
    """Try native CDR saving via installed CorelDRAW. Reports failure explicitly."""
    with active_operation():
        return export_cdr(local(job), candidate)


@mcp.tool()
def panel_job_status(job: str) -> dict:
    """Read a revision and its conversion reports."""
    folder, data = pipeline.load_job(local(job))
    return {"job": data, "reports": {name: json.loads((folder/name/"report.json").read_text(encoding="utf-8"))
            for name in ("candidate", "production") if (folder/name/"report.json").exists()}}


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
