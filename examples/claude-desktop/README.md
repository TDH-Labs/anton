# Claude Desktop + Anton

Two ways to add Anton to Claude Desktop: a one-click **`.mcpb` bundle** or
a manual JSON entry.

## Option A — .mcpb bundle (double-click)

```bash
npm install -g @modelcontextprotocol/desktop-bundler-v0 2>/dev/null \
  || npx -y @modelcontextprotocol/desktop-bundler-v0 \
       --spec ./anton.mcpb.spec.json --output ./anton.mcpb
```

Then double-click `anton.mcpb` in Claude Desktop — it installs the server
and prompts for permission.

The spec (`anton.mcpb.spec.json`) points at the **stdio** command against
the local dashboard. For a remote Anton, change it to the SSE URL form.

## Option B — manual JSON

`claude_desktop_config.json` (Claude → Settings → Developer → Edit
Config):

```json
{
  "mcpServers": {
    "anton": {
      "command": "anton",
      "args": ["mcp"]
    }
  }
}
```

or, remote (SSE surface, token required):

```json
{
  "mcpServers": {
    "anton": {
      "type": "sse",
      "url": "http://<anton-host>:8877/sse",
      "headers": { "Authorization": "Bearer <token>" }
    }
  }
}
```

Restart Claude Desktop. The wrench → **anton** shows the 8 tools.

## What it needs on the host

`anton` on PATH (or the full path to the venv's `anton`), a running
dashboard at `ANTON_BASE_URL`, and `ANTON_DASHBOARD_TOKEN` in the
environment only when authz is on.

## Verification

- Claude Desktop → connection status green.
- Ask it to call `anton_status` → real payload.
- One caution to keep honest: `.mcpb` double-click *installs*; whether the
  bundle format of your Desktop version matches is checked on import. If
  it rejects, use Option B — the JSON is the same server config.