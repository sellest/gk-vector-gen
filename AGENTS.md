# Project workflow

Before the first artwork job, check `run.py setup --show` or MCP
`workspace_settings`. If local configuration is missing, use the
`leotard-setup` skill in `.agents/skills/leotard-setup/SKILL.md` first.
Use that skill again whenever the user requests changes to output location,
file naming, SVG properties, or export defaults. Defaults are stored locally;
new jobs capture them, while existing revisions remain unchanged.

Use `leotard-panels` for reconstruction and vectorization. Record actual client
approval before production conversion; use candidate mode for draft tests.
Preserve original references unless the user requests their removal. Development
reports and generated sample outputs are not part of the product. Do not include
client artwork or machine-local configuration in Git.
