---
name: leotard-panels
description: Reconstruct flat front and back leotard panel artwork from a model reference, then vectorize an approved reconstruction and export SVG, TIFF, and optional native CDR using this project's pipeline.
---

# Leotard panels

Work from the project root containing `run.py`, `profiles/201-107.json`, and the
`gk_vector` package. Use `.venv/Scripts/python.exe` on Windows or
`.venv/bin/python` on macOS; command examples below use Windows syntax. Read
`run.py setup --show` (or MCP `workspace_settings`) before preparing a new job.
If setup is missing, invoke the sibling `$leotard-setup` skill first. It can also
be invoked at any time to adjust output location, naming, SVG properties or export
defaults. Preserve references and old revisions; use the configured output folder.

## Reconstruct artwork

Use the host's image-generation/edit tool with the client's model image as the
design reference. If supplied, use flat examples only for silhouette and layout.
Ask for orthographic front-left and back-right panels, clean margins and a gap,
flat print colors, crisp logos, no model/folds/shadows/texture/perspective, and a
uniform light neutral background or genuine transparency. Carry the design into
hidden areas and propose a coherent back. Do not claim these areas were observed.
Keep the prompt with the saved revision. If no image tool is available, provide
the prompt for use in ChatGPT and resume from the client's exported flat image;
do not substitute a mockup or claim generation happened.

Use `references/reconstruction-prompt.md` for the editable prompt template.
Inspect and iterate the reconstruction with the client. Generated silhouettes
are artwork templates, not validated sewing patterns. Default measurements and
export settings come from the profile; do not require sewing engineering inputs
for a visual artwork job.

## Handoff and vectorize

Prepare a new revision:

```powershell
.\.venv\Scripts\python.exe run.py prepare path/to/flat-panels.png --design 201-107 --revision r01
```

Inspect `mask-review.png`, `front.png`, `back.png`, and `clean.png`. Auto masks
assume two disconnected panels on a light neutral backdrop; supply `--mask`
with a same-size white-on-black combined panel mask if auto detection is wrong.
Left=front and right=back. Panel edges and white trim must survive segmentation.
Use the returned `job_folder` for subsequent commands. Examples below assume
the default configured folder and job template, producing `output/201-107/r01`.

After actual client approval of this revision, record their message and convert:

```powershell
.\.venv\Scripts\python.exe run.py approve output/201-107/r01 --note "<client approval>"
.\.venv\Scripts\python.exe run.py vectorize output/201-107/r01
```

For an explicitly requested pipeline test before design approval, use
`vectorize ... --candidate`; it leaves the job draft. Never record approval just
to get a test to run. Changed source hashes require a new revision.

Compare `comparison.jpg`, `vector-preview.png`, and `difference-x5.png`. Read
`report.json`; use its `artifacts` map for configured SVG/TIFF/CDR filenames.
Inspect logos, thin lines, colors, mask edges, and missing details.
Vector output must contain actual paths with zero embedded raster images.
RGB error is diagnostic, not proof of design fidelity. Tracing can create many
objects and approximate gradients. Show material changes for review.

## Settings and native CDR

`prepare --overrides` accepts JSON with `dpi`, `canvas_mm`, `pixels`, `background`,
`trace_max_dimension`, `color_precision`, `gradient_step`, `filter_speckle`, and
`cdr_version`, plus `preserve_white_details` to retain thin white regions as an
additional vector layer. Use a JSON file with `--overrides-file` when shell
escaping is awkward. Physical canvas size is preserved when only DPI changes;
artwork is uniformly fitted and centered. Page size in the profile is reference
metadata, not the export canvas or individual panel dimensions. Numeric panel
dimensions and bleed are not inferred from the page size.

```powershell
.\.venv\Scripts\python.exe run.py export-cdr output/201-107/r01
```

Native export requires installed licensed CorelDRAW and its Windows automation
components. Report unavailable/failed explicitly; SVG is not CDR and renaming
does not convert it. The adapter needs verification on the client's CorelDRAW
version. A saved CDR still needs visual verification in CorelDRAW. The pipeline
currently renders TIFF through resvg, so cross-renderer parity with CorelDRAW
must be checked. Sewing patterns/size grading are outside this skill's scope.

The same operations are available via `run.py serve` if the MCP server is
connected. The MCP backend does not provide an image-generation service; the
host performs reconstruction before handing off files.
