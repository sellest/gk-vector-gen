"""Stdio MCP server restricted to a configured project root."""
import json
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from . import pipeline
from . import config
from .corel import export_cdr

ROOT = Path(os.environ.get("GK_VECTOR_ROOT", Path.cwd())).resolve()
mcp = FastMCP("GK Panel Artwork")


def local(path: str) -> Path:
    resolved = (ROOT / path).resolve()
    allowed = [ROOT]
    if (ROOT / config.CONFIG_NAME).exists():
        allowed.append((ROOT / config.read_config(ROOT)["output_folder"]).resolve())
    if not any(resolved.is_relative_to(base) for base in allowed):
        raise ValueError("Paths must stay within GK_VECTOR_ROOT")
    return resolved


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
    return config.configure(ROOT, settings)


@mcp.tool()
def prepare_panels(image: str, job: str | None = None, overrides: dict | None = None,
                   profile: str | None = None, mask: str | None = None,
                   design: str = "leotard", revision: str = "r01") -> dict:
    """Create a draft from a flat reconstruction, with front left and back right.

    This tool does not call an image generator. Generate artwork with the host's
    image tool, save it under the project root, then pass it here. Inspect
    mask-review.png before the client approves the revision.
    """
    preferences = config.read_config(ROOT)
    profile_data = json.loads(local(profile or preferences["profile"]).read_text(encoding="utf-8"))
    overrides = dict(overrides or {})
    svg = config.merge(preferences["svg"], overrides.pop("svg", {}))
    resolved = {**preferences["overrides"], **overrides, "svg":svg}
    folder = local(job) if job else config.job_path(ROOT, preferences, design, revision)
    identity = {"design":design, "revision":revision,
                "export_names":config.export_names(preferences, design, revision), "configuration":preferences}
    result = pipeline.prepare(local(image), folder, profile_data, resolved, local(mask) if mask else None, identity)
    return {"job_folder":str(folder), **result}


@mcp.tool()
def approve_panels(job: str, client_approval: str) -> dict:
    """Record actual client approval of artwork AND masks. Never infer approval from a request to test."""
    return pipeline.approve(local(job), client_approval)


@mcp.tool()
def vectorize_panels(job: str, candidate: bool = False) -> dict:
    """Trace a saved reconstruction to genuine SVG paths and matching TIFF.

    Production requires recorded approval. candidate=True permits draft tests
    without approval. Both return a visual comparison and measured error.
    """
    return pipeline.vectorize(local(job), candidate)


@mcp.tool()
def export_native_cdr(job: str, candidate: bool = False) -> dict:
    """Try native CDR saving via installed CorelDRAW. Reports failure explicitly."""
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
