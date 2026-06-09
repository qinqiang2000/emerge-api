# emerge plugin

Connect Claude to your team's **emerge** workspace — a document-processing
colleague. Point it at documents and an API emerges: field extraction today,
with classification and matching as it grows.

In **Claude Code**, one install gives you:

- the **emerge remote connector** (its tools appear as `mcp__emerge__*`),
- an auto-loaded **`emerge` skill** that orients Claude to the workspace, and
- `/emerge:*` slash commands for the common workflows.

## Install

**Claude Code (CLI)** — install the plugin (gets the connector + skill + `/emerge:*` commands):

```
/plugin marketplace add qinqiang2000/emerge-api
/plugin install emerge@emerge
```

(The marketplace lives in this repo. If it's private, you need git access to it.)

**Claude Desktop / Cowork / web** — these use *connectors*, not the plugin
marketplace. Add the connector directly: "Add custom connector", URL
`https://fpydoc.duckdns.org/mcp/`, OAuth = Auto-register (dynamic client
registration).

Either way, on first use the connector runs an OAuth login — your browser opens
an emerge consent page. **Sign in with your emerge account** (the one with an
active team); approve, and Claude is connected to that team's workspace. No
tokens to paste.

## Use

- `/emerge:run <doc>` — run extraction on a document and show the result.
- `/emerge:compare <model>` — compare two models on a doc and see which is more accurate.
- `/emerge:tune` — refine a project's accuracy against reviewed ground truth.
- `/emerge:publish` — freeze the project as a versioned API and issue a key.

Or just talk to it: "find the 北方工业 project, add gemini-2.5-flash, run it on
1.jpg." Claude discovers the workspace through the connector and does the rest.

## How it works

The plugin is a thin entry point. All capability lives on the emerge server — the
plugin only declares the remote connector and a small skill that teaches Claude to
**discover before acting** (read workspace files with `ws_list` / `ws_read` rather
than assuming a shared filesystem) and to use the typed tools for anything with an
invariant (registering a model, editing a schema, publishing). For the full
playbook, the connector exposes the `emerge-extractor` MCP prompt.
