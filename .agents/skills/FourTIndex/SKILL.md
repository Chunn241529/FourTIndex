---
name: FourTIndex
description: Use FourTIndex for project-safe semantic code retrieval, targeted reads, indexing, and agent handoffs.
---

# FourTIndex Local Context Retrieval

Use FourTIndex instead of dumping directories or whole source files. Every primary, delegated, background, and worktree agent must establish project identity independently.

## Project Bootstrap

Before the first code search or code read:

1. Determine the agent's actual working directory.
2. Call `resolve_project(workspace_path=<cwd>, output_json=true)`.
3. Record the returned `project_root`, `project_name`, and `project_id` for the task.
4. Pass `project_name` explicitly to every project-scoped tool.
5. If resolution returns `project_not_found`, index the absolute project root with a unique name, then resolve again.
6. If resolution returns `ambiguous_project` or `project_path_mismatch`, stop and correct the registry. Never guess.

Use `get_agent_context(workspace_path)` when delegating. The parent includes its returned delegation block; the sub-agent verifies it by calling `resolve_project` from its own working directory.

## Core Tools

1. `resolve_project(workspace_path, project_name=None, output_json=False)` resolves identity without guessing.
2. `get_agent_context(workspace_path, output_json=False)` returns verified sub-agent context.
3. `list_projects(output_json=False)` returns names, canonical roots, IDs, index status, and roadmap metadata.
4. `search_codebase(query, project_name, limit=5, file_ext=None)` performs semantic search.
5. `get_file_outline(file_path, project_name)` retrieves structure before implementation reads.
6. `get_symbol_definition(symbol_name, project_name)` retrieves a focused definition.
7. `read_code_lines(file_path, start_line, end_line, project_name)` reads a narrow physical range.
8. `summarize_file(file_path, project_name)` summarizes a large file locally.
9. `index_project(project_path, project_name, output_json=False, verbose=False)` incrementally indexes code and agent instructions. `project_path` must be absolute.
10. `index_skill(skill_path, project_name)` explicitly indexes one skill when needed.
11. `save_session_summary(session_id, summary_text, project_name)` records durable design history.
12. `hibernate_session(current_task, next_steps, uncommitted_changes, project_name)` creates a handoff.
13. `get_token_report()` reports usage only when requested.
14. `clean_mem()` explicitly unloads local models after heavy work.

JSON output is compact by default. Use `verbose=true` where supported for diagnostic details. Memory cleanup and token reports are explicit operations and are not appended to ordinary tool results.

## Retrieval Workflow

1. Search semantically with explicit `project_name`.
2. Inspect the target file outline.
3. Read only the required symbol or a range no larger than 100 lines.
4. Avoid duplicate reads and unrelated files.

## Workflow by Task Risk

### Read-only

Bootstrap, search, inspect, and answer. Do not index, save memory, or clean models unless the task actually needs it.

### Small edit

Bootstrap, retrieve, edit, run targeted validation, and call `index_project` with the absolute root.

### Production change

Add broader tests and scan symbols, imports, type/async flow, null handling, edge cases, side effects, and logical correctness. Re-index and save durable design decisions.

### Handoff

Read `.fourtindex_handoff.md` only when it exists and is relevant to the current task. Hibernate only when transferring unfinished work; include project root, name, ID, next steps, and uncommitted changes.

## Instruction Indexing

`index_project` includes root `AGENTS.md`, `.agents/AGENTS.md`, and `.agents/**/SKILL.md` even when hidden directories are ignored. It also refreshes discovered skills. The result reports `skills_indexed`; `verbose=true` adds the full summary.

## CLI Fallback

Run CLI commands from the project root. Prefer an absolute path for scripted/background execution:

- Windows: `fourtindex index D:\absolute\project\root`
- macOS/Linux: `fourtindex index /absolute/project/root`
- Search: `fourtindex search "query"`
- Skill index: `fourtindex index-skill <absolute-skill-path>`
- Cleanup: `fourtindex clean-mem`
