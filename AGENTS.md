# Project workflow

Before the first artwork job, check `run.py setup --show` or MCP
`workspace_settings`. If local configuration is missing, use the
`leotard-setup` skill in `.agents/skills/leotard-setup/SKILL.md` first.
Use that skill again whenever the user requests changes to output location,
file naming, SVG properties, or export defaults. Defaults are stored locally;
new jobs capture them, while existing revisions remain unchanged.

Use `leotard-panels` for reconstruction and vectorization. Record actual client
approval of both artwork and the proposed color selection before production
conversion; use candidate mode for draft tests. Present the palette-matched
preview and color list returned by preparation before requesting approval.
Preserve original references unless the user requests their removal. Development
reports and generated sample outputs are not part of the product. Do not include
client artwork or machine-local configuration in Git.

New jobs snapshot the Pantonic catalog. Use `update_pantonic` or
`run.py update-palette` to rebuild it from the chart's printed RGB labels.
Resolve uncertain RGB readings before replacing the active catalog. Do not
manually edit checksummed catalogs or existing jobs' palette snapshots.
