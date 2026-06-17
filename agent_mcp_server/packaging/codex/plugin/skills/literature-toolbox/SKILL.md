---
name: literature-toolbox
description: "Use when working with the local Literature Assistant through MCP: search projects, read materials/chunks, export annotations, inspect safe source, or compose local literature workflows."
---

# Literature Toolbox

Use this skill when a task needs the local Literature Assistant database, source-readable toolbox code, or a repeatable literature workflow.

## Preferred Tools

Use the `literature_assistant` MCP server first when available:

- `literature.config_status` before runtime work, especially when the backend may not be running.
- `literature.list_projects` to discover project ids.
- `literature.list_materials` and `literature.read_material` to inspect project contents.
- `literature.get_material_chunks` for grounded reading and citation context.
- `literature.search_literature` for existing indexed chunks.
- `literature.ingest_then_search` when pending files may need to be indexed before search.
- `literature.export_annotations_markdown` when the user asks for annotation export.
- `source.list_tree`, `source.search`, `source.read_file`, and `source.read_symbols` to inspect safe Literature Assistant source.
- `source.inspect_routes`, `source.find_references`, and `source.explain_entrypoints` for static route/reference/entrypoint analysis.
- `workflow.create_plan`, `workflow.write_json_workflow`, and `workflow.run_json_workflow` for bounded multi-step workflows.
- `artifact.write_markdown`, `artifact.read_artifact`, and `artifact.list_artifacts` for workflow outputs under the agent artifact workspace.

## Safety Boundary

Do not ask the MCP server to read credentials, `.env` files, runtime state, backups, logs, browser profiles, rollback snapshots, or host agent configuration. If you need provider configuration, use Literature Assistant backend status/tools and ask the user to configure keys in the application UI.

## Workflow

1. Check `literature.config_status`.
2. Discover the project and material ids only when they are not already known.
3. Prefer search and chunk-reading tools before broad source inspection.
4. Use source tools when a workflow requires implementation details or when a tool error suggests a local code issue.
5. Use JSON workflow tools for repeatable multi-step work; do not request arbitrary shell or Python execution through MCP.
6. Keep outputs grounded in returned chunks or explicitly label source-code inferences.
