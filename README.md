# GK panel artwork pipeline

Prototype for the agreed workflow: model image → client-reviewed flat front/back
artwork → vectorization skill → SVG and TIFF, with optional native CDR export.

Start with [leotard-setup](.agents/skills/leotard-setup/SKILL.md) for initial
installation and preferences. Invoke it again whenever output paths, filenames,
SVG properties or export defaults need adjustment. The artwork skill is
[leotard-panels](.agents/skills/leotard-panels/SKILL.md). It
guides the host's image generator; the Python backend handles masks, settings,
tracing, comparison and export. The MCP server does not itself generate images.

## Generated files

Development reports and sample job outputs are not shipped with the product.
The configured output folder is created when the first job is prepared; it can
be outside the application folder. Generated artwork and local settings are
excluded from Git.

Each conversion produces SVG, TIFF, PNG previews, a side-by-side comparison,
an amplified difference image and a JSON report. Inspect these in a browser or
image viewer before accepting a result. Tracing approximates small motifs,
gradients and logo edges. Artwork silhouettes are not validated sewing patterns.

## Setup and CLI

Python 3.10 is the tested runtime for the pinned dependencies. Create a local
virtual environment using the commands below. macOS commands are in the
[cross-platform setup guide](docs/mcp-setup.md).

Invoke `$leotard-setup` before the first job. It collects preferences and saves
`gk-vector.local.json`, which is excluded from Git. New job preparation requires
this file. To initialize the documented defaults directly:

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
.\.venv\Scripts\python.exe run.py setup --defaults
.\.venv\Scripts\python.exe run.py prepare path/to/flat-panels.png --design 201-107 --revision r01
.\.venv\Scripts\python.exe run.py vectorize output/201-107/r01 --candidate
```

`prepare` requires front on the left and back on the right, separated by a gap
and surrounded by a light neutral background or transparency. It produces
`mask-review.png`, transparent per-panel images and `clean.png`. If automatic
segmentation fails, supply a same-size white-on-black mask with `--mask`.
The default profile is [profiles/201-107.json](profiles/201-107.json).

After actual client approval of the artwork and masks:

```powershell
.\.venv\Scripts\python.exe run.py approve output/201-107/r01 --note "Client's approval message"
.\.venv\Scripts\python.exe run.py vectorize output/201-107/r01
.\.venv\Scripts\python.exe run.py export-cdr output/201-107/r01
```

Candidate outputs are isolated from production outputs. Input hashes are checked
before conversion. Existing jobs and exports are not overwritten; use a new
revision when changing artwork, masks or conversion settings. Failed conversions
do not publish partial output and can be retried.

By default a job goes under `output/{design}/{revision}` and deliverables are
`{design}_{revision}.svg`, `.tif`, and `.cdr` within `candidate/` or `production/`.
Use the `job_folder` returned by prepare and the `artifacts` map in `report.json`.

## Setup and later adjustments

Read current values with `run.py setup --show`. Apply a JSON patch using
`run.py setup --settings-file preferences.json`, or invoke `$leotard-setup`.
For example:

```json
{
  "output_folder": "D:/Artwork/Leotards",
  "job_template": "{design}/{revision}",
  "filename_template": "{design}-{revision}.{ext}",
  "svg": {
    "units": "mm", "version": "1.1", "precision": 3,
    "trace_mode": "spline", "background": "solid",
    "shape_rendering": "geometricPrecision"
  },
  "overrides": {"dpi": 150}
}
```

Patches preserve unmentioned settings. Changes affect new jobs only; existing
artwork is not moved or renamed. Paths can be relative to the app or absolute.
The output directory is created when preparing a job. Filename templates accept
`{design}`, `{revision}`, and `{ext}`, must end with `.{ext}`, and cannot contain
directories. Designs/revisions use letters, digits, underscores and hyphens.

SVG options: units `mm`/`px`; version `1.1`/`2.0`; path precision `0`–`6`;
tracing `spline`/`polygon`; background `solid`/`transparent`; shape rendering
`auto`/`geometricPrecision`/`crispEdges`. Transparent SVG retains the exterior
alpha; RGB TIFF is composited onto the configured export background. Physical
SVG dimensions stay exact when path precision changes. Raster export defaults
are inherited from the selected profile and optional saved overrides.

## Adjustable settings

Pass a JSON file with `prepare --overrides-file settings.json`, for example:

```json
{"dpi": 300, "canvas_mm": [600, 800], "trace_max_dimension": 2000}
```

Changing DPI alone preserves physical canvas size and recalculates pixels.
Explicit `pixels` override derives physical size at the requested DPI. Conflicting
explicit physical and pixel dimensions are rejected. Artwork is uniformly fitted
and centered, not stretched. Output is capped at 160 million pixels; large exports
need substantial RAM. Current export color mode is RGB and TIFF compression is
LZW. Other color workflows are not implemented yet. Panel-specific dimensions,
sewing allowances and bleed have not been extracted from the CDR. The original
410 × 680 mm document page is reference metadata, separate from the TIFF canvas.

Tracing controls: `color_precision` (1–8), `gradient_step`, `filter_speckle`,
`trace_max_dimension`, and `preserve_white_details`. Native CDR target version
is configured by `cdr_version`, defaulting to 16 (X6), subject to native testing.

## Native CDR limitation

Native CDR export requires Windows with registered CorelDRAW automation.
macOS can generate SVG/TIFF; this Windows COM adapter cannot export CDR on macOS.

[corel.py](src/gk_vector/corel.py) provides an adapter using a separate CorelDRAW
automation instance, SVG import and native `SaveAs`. It needs installed licensed
CorelDRAW and remains unverified against a real installation. A successful save
is reported as needing visual verification, not as proven render parity. The
TIFF is rendered by resvg; verify clipping, gradients and colors in CorelDRAW.

## MCP

Start the stdio server with:

```powershell
.\.venv\Scripts\python.exe run.py serve
```

Tools: `workspace_settings`, `configure_workspace`, `prepare_panels`,
`approve_panels`, `vectorize_panels`, `export_native_cdr`, `panel_job_status`.
Paths are restricted to `GK_VECTOR_ROOT` and the configured output folder,
where `GK_VECTOR_ROOT` defaults to the server's working directory. Configure that
environment variable when the host launches the server elsewhere.

See [Claude Desktop and ChatGPT setup](docs/mcp-setup.md) for installation,
connection and verification on Windows and macOS. The generic
[mcp.example.json](mcp.example.json) uses placeholders; ready-to-edit platform
examples are [Windows](examples/mcp.windows.json) and
[macOS](examples/mcp.macos.json). Claude uses local stdio JSON; the ChatGPT guide
uses OpenAI's Secure MCP Tunnel to the same local server. No user app settings
are changed automatically.

## Verification

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Tests exercise real tracing/rendering/TIFF metadata, source revision integrity,
approval behavior, settings overrides, failure recovery, mask preservation,
setup/adjustment persistence, safe filename templates, configured SVG properties,
workspace path restrictions, and a real stdio MCP client/server round trip.
Windows named pipes may require running outside a restricted execution sandbox.
