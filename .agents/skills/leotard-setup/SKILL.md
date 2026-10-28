---
name: leotard-setup
description: Set up or update the local gk-vector tool, adjust output folders, filenames, SVG and export defaults, or refresh its Pantonic palette. Use for requests such as "please update gk-vector tool" and before the first artwork job when configuration is missing.
---

# Leotard app setup and adjustments

Use this skill before the first artwork job and whenever the user requests changes
to app preferences. Setup does not generate artwork or alter existing revisions.
Work from the project root containing `run.py` and `pyproject.toml`.
On Windows use `.venv/Scripts/python.exe`; on macOS use `.venv/bin/python`.
The shell examples below are for Windows. For macOS installation and both hosts'
MCP connections, read [the cross-platform setup guide](../../../docs/mcp-setup.md).

## Update the tool

When the user says "please update gk-vector tool", call MCP `update_gk_vector`.
The equivalent CLI is `run.py update`, using the local environment's Python.
This pulls `origin/main` with `--ff-only` and returns restart instructions.
On restart, startup installs the lock file and project into the current environment
and checks dependencies before importing native image libraries.
It does not choose releases, stage installations, reset files, or restart itself.

After success, tell the client to restart the app or reconnect its MCP server.
For a Secure MCP Tunnel, stop and start the tunnel client so it relaunches the
server; for Claude Desktop, fully quit and reopen the app. Do not continue artwork
operations in the old server process. Refuse to report an installed update as
active before that restart. The first reconnect can take longer while dependencies install.

If blocked by local tracked changes, a different branch/remote, or a diverged
history, report the reason. Do not stash, discard changes, or force reset. Local
settings and artwork stay in place. If startup installation fails, it remains
pending and is retried at the next startup. Read host/tunnel logs to resolve the
cause, then restart. Do not claim rollback or success. Tool updates are separate from
`update_pantonic`, which refreshes only the color catalog.

## Check installation and saved preferences

Check that the project virtual environment exists. Python 3.10 is the tested
runtime for the pinned dependencies. If needed,
create `.venv` and install the application with its pinned dependencies:

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
```

The lock includes setuptools and wheel for local installation. Use the actual
available Python launcher/version; do not recreate an existing working environment.
Use native shell quoting for paths and JSON files for configuration patches.

Read preferences with `run.py setup --show`, or MCP `workspace_settings`.
Missing local configuration means initial setup is required. Existing configuration
means adjustment mode: read current values and change only what the user requests.
Use the existing app workflow for unrelated work rather than rerunning setup.

## Choose settings

Use preferences already supplied by the user. For unspecified initial choices,
present these defaults and collect the user's preferences in a concise question:

- Output folder: `output` relative to the app, or a user-selected absolute folder.
- Job directory template: `{design}/{revision}`.
- Export filename template: `{design}_{revision}.{ext}`; for example
  `201-107_r01.svg`, `.tif`, and `.cdr` in the same job's export directory.
- SVG: millimeter units, version 1.1, 3 decimal places for paths, spline tracing,
  solid background, geometricPrecision rendering.
- Export defaults: the example-derived profile, including 150 DPI. Keep settings
  the user has not asked to change. Measurements apply to the export canvas.
- Palette: `palettes/pantonic.json`. New jobs capture their own catalog snapshot;
  match the printed RGB labels as sRGB, not sampled Adobe RGB patch pixels.

Ask only about choices that remain unresolved. Continue installation/read-only
checks while waiting. If the user requests default setup, apply defaults directly.
If they delegate the choices, state the chosen defaults and proceed. A task to
create this skill alone is not a request to choose a personal output directory.

Filename templates accept `{design}`, `{revision}`, and `{ext}` only, must end
with `.{ext}`, and cannot include directories. Put directories in `job_template`.
Design/revision identifiers use letters, digits, underscores, and hyphens.
Templates do not overwrite existing jobs. New revisions use a different identifier.

Supported SVG properties are `units` (`mm`/`px`), `version` (`1.1`/`2.0`),
`precision` (0–6), `trace_mode` (`spline`/`polygon`), `background`
(`solid`/`transparent`), and `shape_rendering` (`auto`, `geometricPrecision`,
`crispEdges`). Transparent SVG keeps its exterior transparent; RGB TIFF is still
composited onto the configured export background. SVG physical dimensions are
not rounded when path precision changes. Text/logos are traced paths, not fonts.

## Save and verify

Write only the requested patch to a temporary JSON file in the workspace:

```json
{
  "output_folder": "output",
  "filename_template": "{design}_{revision}.{ext}",
  "svg": {"units": "mm", "precision": 3},
  "overrides": {"dpi": 150}
}
```

Apply it with `run.py setup --settings-file <patch.json>` or MCP
`configure_workspace(settings=...)`. Remove the temporary patch afterward.
`run.py setup --defaults` explicitly initializes defaults without resetting an
existing configuration. Patches merge into existing preferences. Do not hand-edit
jobs to retrofit changed defaults.

Read back `setup --show`. Report the resolved output folder and an example job
and filename. Configuration is saved as `gk-vector.local.json`, excluded from Git.
Each new job captures its settings and filename map. Adjustments affect new jobs;
old revisions retain their original settings, paths and artifact names.

External output folders need local filesystem access. Report an actual permission
failure and use the platform's normal approval mechanism when needed. Do not move
or delete existing artwork when changing output folders. The backend creates job
directories when preparing artwork, not when merely saving preferences.

If dependencies changed, run the test suite. For preference-only adjustments,
validation and read-back are sufficient unless a custom SVG mode needs a trial.
Native CDR still requires CorelDRAW; setup must not report it ready just because
Python dependencies are installed.

## Palette refresh

Normal export uses the shipped catalog and does not require OCR. When the user
updates the chart, invoke MCP `update_pantonic` or `run.py update-palette`.
Install `.[palette-update]` if the optional OCR engine is missing. The first
refresh downloads a checksum-pinned English model into the ignored local cache;
later refreshes can run offline. See [palette updates and corrections](../../../docs/palette.md).

Read `pantonic_status` after updating. If OCR leaves unresolved RGB readings,
the active catalog remains unchanged: inspect the review file and supply
source-checksum-bound corrections. Do not invent values or edit the active
catalog manually. `palette_file` can be changed with a setup patch; it must point
to a validated catalog, not the source TIFF. Existing revisions retain their
snapshot when this preference or the active palette changes.
