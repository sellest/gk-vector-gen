# Pantonic palette

New jobs use [palettes/pantonic.json](../palettes/pantonic.json), derived from the
**printed RGB labels** in `docs/pantonic.tif` and interpreted as sRGB. The chart's
Adobe RGB profile and sampled patches are recorded as source information; patch
pixels do not determine the vector paint values. Color names follow the chart,
including any original spelling; they are not normalized against an external
Pantone database.

## Refresh the reusable catalog

Replace `docs/pantonic.tif` with the updated chart, then run:

```powershell
.\.venv\Scripts\python.exe run.py update-palette
```

macOS:

```sh
./.venv/bin/python run.py update-palette
```

Or call MCP **`update_pantonic`**. Its defaults are `source="docs/pantonic.tif"`
and `destination="palettes/pantonic.json"`. Optional arguments are `corrections`
(the JSON object below) and `force` (rerun OCR even when inputs are unchanged).
Paths must stay inside the project or configured output folder. Read the active
version with MCP `pantonic_status`.

The importer supports the supplied rectangular two-label swatch grid. It detects
rows/columns, handles gaps between chart sections, and recognizes RGB and name
lines separately. Ambiguous, invalid or low-confidence RGB readings prevent an
update. The active catalog is replaced atomically only after validation; the
source TIFF and existing job snapshots are never rewritten. A source change
during import is rejected. A redesigned chart layout may need another importer.

## OCR installation and cache

Normal vector export uses only the JSON catalog. Rebuilding additionally needs
the optional OCR dependencies:

```sh
python -m pip install -e ".[palette-update]"
```

They are also included in `requirements-lock.txt`. The first rebuild downloads
an English OCR model into `palettes/.ocr/`, verifies its pinned SHA256, and then
processes the chart locally. The model cache is excluded from Git. Later updates
can run offline while the model remains cached. Export never downloads a model.

Model provenance: RapidAI's `en_PP-OCRv4_rec_mobile`, revision `v3.9.2`, listed in
the [official model manifest](https://github.com/RapidAI/RapidOCR/blob/main/python/rapidocr/default_models.yaml).
SHA256: `e8770c967605983d1570cdf5352041dfb68fa0c21664f49f47b155abd3e0e318`.

## Review and corrections

`pantonic.review.json` records uncertain labels by grid ID: `r01c06` means row 1,
column 6. Unresolved RGB readings or missing names produce a local
`pantonic.candidate.json` and leave the active catalog unchanged. Low-confidence
names are flagged separately. OCR confidence does not prove correctness; compare
uncertain labels with the chart. These diagnostic files are excluded from Git.

Corrections use the exact source checksum from the review file:

```json
{
  "source_sha256": "<SHA256_OF_THE_CURRENT_CHART>",
  "entries": {
    "r20c05": {"name": "Seedpearl"},
    "r13c10": {"name": "Deep Dive", "rgb": [41, 73, 92]}
  }
}
```

The updater automatically reuses `pantonic.corrections.json` beside the catalog
when its checksum matches the chart. After a chart change, old corrections are
not applied. An explicitly supplied correction object with a mismatched checksum
is rejected. Retain all desired corrections in the object; each rebuild uses the
chart plus that complete correction set. The shipped correction file records
labels visually checked against this chart.

To specify another correction file:

```powershell
.\.venv\Scripts\python.exe run.py update-palette --corrections-file palettes/pantonic.corrections.json
```

MCP accepts the same object as `update_pantonic(corrections=...)`. The active
catalog and curated corrections are reusable product assets. Do not edit the
catalog by hand: its version checksum is validated when loaded.

## Palette-constrained vector and TXT

Before vectorization, `prepare_panels` calculates the proposed color selection
and returns it as `color_review.colors`: chart IDs, names, RGB, HEX, panel roles
and approximate shares measured inside the panels at analysis resolution. It
also writes `palette-matched.png`, `color-comparison.jpg`, `colors-review.html`,
`color-selection.json` and `color-selection.txt`. Background-only entries are
identified separately. This preparation does not run the vectorizer.

Present these results with the reconstructed panels. Production approval must
include artwork, masks AND the selected colors: pass `colors_approved=true` to
MCP `approve_panels`, or `--colors-approved` to the CLI `approve` command, only
after the client gives that combined approval. These files and settings are
checked for changes. New design or color choices require a new revision.

Preparing artwork snapshots the catalog into the job's `palette.json`, hashes
it with the artwork, and records its version. Later catalog updates cannot change
that revision. Modified snapshots fail verification. Jobs created before palette
support or color-selection review must be prepared again as new revisions.

Tagged source artwork is converted to sRGB. Colors are matched during preparation;
vectorization reuses that saved image and constrains final paints to the selected
subset. It may omit selected colors but cannot add other catalog entries.
Matching uses nearest CIELAB color, Delta E 76. Duplicate RGB entries
choose the first grid entry deterministically. White details and backgrounds
are also palette-matched. Transitions use opaque colored regions rather than
unrestricted gradients. The rendered TIFF is tagged sRGB; antialiasing naturally
creates intermediate raster edge pixels.

Every conversion writes `<svg-stem>_colors.txt` using the configured filename
stem. It lists unique paint colors defined in the SVG: grid ID, name, RGB, HEX,
palette version and chart checksum. It does not estimate coverage or count
antialiasing colors. Names retain their OCR/correction provenance. The JSON
conversion report exposes the filename as `artifacts.colors`.

Native CDR imports this constrained SVG. CorelDRAW color-management behavior still
needs native verification. This feature uses named RGB colors, not spot inks.
