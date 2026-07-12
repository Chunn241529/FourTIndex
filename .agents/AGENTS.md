# FourTIndex Codebase Search and Retrieval Rules

This codebase uses **FourTIndex** for local semantic search and targeted code retrieval. These rules apply to the primary agent and every delegated/sub-agent independently.

## Mandatory bootstrap for every agent

Before any code search or code read, each agent MUST:

1. Read `.agents/skills/FourTIndex/SKILL.md` completely. Do not assume a parent agent's skill state was inherited.
2. Determine its own current working directory and the absolute project root. Prefer the nearest ancestor containing `.git`; otherwise use the nearest ancestor containing `.agents/AGENTS.md` or a standard project marker.
3. Call `resolve_project(workspace_path=<cwd>, output_json=true)`. Record the returned `PROJECT_ROOT`, `PROJECT_NAME`, and `PROJECT_ID` as immutable task context.
4. If resolution returns `project_not_found`, call `index_project(project_path=PROJECT_ROOT, project_name=<unique stable name>)`, then resolve again. For `ambiguous_project` or `project_path_mismatch`, stop and correct the registry instead of guessing.
5. Pass `project_name=PROJECT_NAME` explicitly to every project-scoped FourTIndex call.

If project identity is ambiguous, stop code retrieval and report the candidate roots/projects instead of guessing.

## Delegation contract

When delegating code work, the parent agent MUST call `get_agent_context(PROJECT_ROOT)` and include its delegation block. The sub-agent MUST verify it using `resolve_project` from its own working directory before searching.

## Retrieval and completion workflow
1. **Do not dump directories:** Instead of listing files or reading entire folders, always use `search_codebase` to search semantically. Use the `file_ext` filter (e.g. `".py"`) to exclude noise like READMEs or config files if you only need code.
2. **Read structurally first:** Call `get_file_outline` to read class/function signatures of a file before fetching its implementation.
3. **Read narrow scopes:** Use `get_symbol_definition` or `read_code_lines` to read specific code blocks. Do not read the entire file if you only need a single function.
   - *Note on get_symbol_definition: It returns the full implementation body for Functions, but only the outline for Classes. To read a specific class method, query ClassName.method_name.*
4. **Summarize large files:** If a file is too large (>200 lines), you MUST use the `summarize_file` tool to generate a concise summary using the local LLM instead of pulling the whole file into context.
5. **Update DB after edits:** After creating, modifying, or deleting code or project instruction files, call `index_project(project_path=PROJECT_ROOT, project_name=PROJECT_NAME)`. `PROJECT_ROOT` MUST be absolute; never pass `.`.
6. **Free memory when done:** Call `clean_mem()` tool (or run CLI `fourtindex clean-mem`) when you are done with heavy vector searches or indexing, to release VRAM and RAM immediately and save system resources.
7. **Save design history & Hibernate:** Call `save_session_summary(..., project_name=PROJECT_NAME)` before concluding. If context is too large, use `hibernate_session(..., project_name=PROJECT_NAME)` and include both project identity values in the handoff.
8. **DO NOT SKIP STEPS / CRITICAL INSTRUCTIONS:** You are strictly prohibited from skipping steps under any circumstances. You must perform each stage of the development process (Research -> Design -> Implementation -> Deep Scan & Verification -> Re-index -> Memory Cleanup -> Session Summary) fully and sequentially. Always run the mandatory Deep Scan checks before declaring a task complete.



> [!IMPORTANT]
> **🚨 CRITICAL HANDOFF RULE: AUTO-RESUME MEMORY**
> When starting a completely new chat session, the VERY FIRST THING you MUST DO is read the contents of the `.fourtindex_handoff.md` file located at the root of the project. This file contains your hibernated memory (current task, uncommitted changes, next steps). Absolutely do not make any code changes or suggest solutions until you have fully loaded this handoff context.
