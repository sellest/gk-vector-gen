# MCP setup: Claude Desktop and ChatGPT

Examples use placeholder installation locations. Replace them with your actual
checkout path; no personal developer paths are required.

| Client | Windows | macOS |
| --- | --- | --- |
| Claude Desktop | [Local stdio JSON](../examples/mcp.windows.json) | [Local stdio JSON](../examples/mcp.macos.json) |
| ChatGPT | Secure MCP Tunnel to the same local server | Secure MCP Tunnel to the same local server |

The root [mcp.example.json](../mcp.example.json) is a generic stdio template.
Replace `<PROJECT_ROOT>` and `<PYTHON_EXECUTABLE>` before using it. MCP clients
do not necessarily expand shell variables or `~` inside JSON; use absolute paths.

## 1. Install the app

Python 3.10 is the tested runtime for the pinned dependencies. The macOS commands
assume `python3.10` is installed. Windows installation and MCP round trips have
been tested locally; macOS examples have not been executed on macOS.

### Windows / PowerShell

Place the checkout at your chosen location, then run:

```powershell
Set-Location 'C:/Apps/gk-vector-mcp'
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
.\.venv\Scripts\python.exe run.py setup --show
```

### macOS / Terminal

```sh
cd /Users/USERNAME/Apps/gk-vector-mcp
python3.10 -m venv .venv
./.venv/bin/python -m pip install -r requirements-lock.txt
./.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
./.venv/bin/python run.py setup --show
```

The Windows-only `pywin32` dependency is excluded by its platform marker on macOS.
SVG and TIFF conversion do not need CorelDRAW. The native CDR adapter uses Windows
COM and cannot export CDR on macOS, even if CorelDRAW for Mac is installed.

For initial preferences, follow
[leotard-setup](../.agents/skills/leotard-setup/SKILL.md), or connect the host and
ask it to call `workspace_settings` followed by `configure_workspace` with your
output folder, naming and SVG choices. For the documented defaults, run
`run.py setup --defaults` using your virtual environment's Python executable.

## 2. Connect Claude Desktop

1. Open Claude Desktop settings, then **Developer → Edit Config**. This identifies
   the active config file even if its location changes between app builds.
2. Merge the `gk-vector` entry from the appropriate OS example into the existing
   `mcpServers` object. Preserve other servers. Replace all three checkout paths.
3. Fully quit and restart Claude Desktop. Check Developer settings for server
   status and logs, then ask Claude to call `workspace_settings`.

Common config locations:

- Windows: `%APPDATA%\Claude\claude_desktop_config.json`.
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`.

Claude launches the Python process; a separately running server is unnecessary.
This is manual JSON setup, not a packaged `.mcpb` desktop extension. See the
[official local MCP connection guide](https://modelcontextprotocol.io/docs/develop/connect-local-servers).

## 3. Connect ChatGPT

ChatGPT does not import Claude's JSON. Secure MCP Tunnel can bridge this private
stdio server. Create a tunnel in Platform tunnel settings and install
`tunnel-client`. You need tunnel permissions, a runtime API key, and ChatGPT
developer-mode access. Set `CONTROL_PLANE_API_KEY` privately in your terminal;
keep credentials outside this repository. These examples assume paths without
spaces. [Official OpenAI tunnel documentation](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).

### Windows / PowerShell

```powershell
$env:GK_VECTOR_ROOT = 'C:/Apps/gk-vector-mcp'
tunnel-client init --sample sample_mcp_stdio_local --profile gk-vector --tunnel-id '<TUNNEL_ID>' --mcp-command 'C:/Apps/gk-vector-mcp/.venv/Scripts/python.exe C:/Apps/gk-vector-mcp/run.py serve'
tunnel-client doctor --profile gk-vector --explain
tunnel-client run --profile gk-vector
```

### macOS / Terminal

```sh
export GK_VECTOR_ROOT=/Users/USERNAME/Apps/gk-vector-mcp
tunnel-client init --sample sample_mcp_stdio_local --profile gk-vector --tunnel-id '<TUNNEL_ID>' --mcp-command '/Users/USERNAME/Apps/gk-vector-mcp/.venv/bin/python /Users/USERNAME/Apps/gk-vector-mcp/run.py serve'
tunnel-client doctor --profile gk-vector --explain
tunnel-client run --profile gk-vector
```

Keep the client running. In ChatGPT **Plugins**, select **+ → Add custom MCP
server**, choose **Tunnel** under Connection, and select your tunnel. Complete
authentication and the connection review. If unavailable, check workspace access
and tunnel permissions. Ask ChatGPT to call `workspace_settings`.
The tunnel supplies transport, not the app's image generation or filesystem code.

## 4. Use the workflow

Connecting MCP exposes seven backend tools; it does not automatically install the
repository's skill files into a host. Use the host's supported skill installation
mechanism, or follow the linked skill instructions and invoke the tools directly.

Start by asking:

> Check workspace_settings, then help me configure the output folder, filename
> template and SVG properties before preparing the first job.

Reconstruct the flat panels using an image generator available in your host.
If the host has no image generator, create the panels in ChatGPT and save the
result locally. This server does not provide image generation. Save panel inputs
inside `GK_VECTOR_ROOT` or the configured output folder before calling
`prepare_panels`; chat attachments are not automatically local files. Tool
responses currently return paths and reports, not downloadable file attachments.

After setup, use `prepare_panels`, inspect the mask preview, approve the actual
revision, and call `vectorize_panels`. Use candidate mode when testing a draft.
SVG/TIFF files and comparison previews are written to the configured output.
Use `export_native_cdr` only on a Windows machine with licensed CorelDRAW.

## Troubleshooting

- **Initial setup required:** call `configure_workspace`, or follow the setup skill.
- **Python missing:** check the JSON `command` path against the actual virtual environment.
- **Profile missing / wrong files:** check `GK_VECTOR_ROOT`; host working directories vary.
- **Tools absent in Claude:** check its active config, restart, and read Developer logs.
- **Tunnel unavailable:** use `tunnel-client doctor`; check the linked OpenAI permission guidance.
- **CDR unavailable:** the native adapter requires Windows CorelDRAW automation.

Connection instructions follow the official documentation linked above, checked
2026-10-21. Account access and host interfaces may differ; external Claude/ChatGPT
connections have not been tested with a signed-in account in this repository.
