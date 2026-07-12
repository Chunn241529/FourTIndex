# FourTIndex Codebase Search and Retrieval Rules

This codebase uses **FourTIndex** for local semantic search and targeted code retrieval. These rules apply to the primary agent and every delegated/sub-agent independently.

## Mandatory bootstrap for every agent

Before any code search or code read, each agent MUST:

1. Read `.agents/skills/FourTIndex/SKILL.md` completely. Do not assume a parent agent's skill state was inherited.
2. Determine its own current working directory and the absolute project root. Prefer the nearest ancestor containing `.git`; otherwise use the nearest ancestor containing `.agents/AGENTS.md` or a standard project marker.
3. Call `list_projects()` and match the absolute project root to a registered FourTIndex project. Record `PROJECT_ROOT=<absolute path>` and `PROJECT_NAME=<registered project name>` as immutable task context.
4. If no matching project is registered, call `index_project(project_path=PROJECT_ROOT, project_name=<stable project name>)`, then call `list_projects()` again. Never silently search a different/default project.
5. Pass `project_name=PROJECT_NAME` explicitly to every project-scoped FourTIndex call. Do not rely on automatic working-directory resolution, especially in sub-agents, worktrees, or background tasks.

If project identity is ambiguous, stop code retrieval and report the candidate roots/projects instead of guessing.

## Delegation contract

When delegating code work, the parent agent MUST include `PROJECT_ROOT`, `PROJECT_NAME`, and the skill path in the sub-agent prompt. The sub-agent MUST still verify those values against its own working directory and `list_projects()` before searching.

## Directives for Agent LLM:
1. **Do not dump directories:** Instead of listing files or reading entire folders, always use `search_codebase` to search semantically. Use the `file_ext` filter (e.g. `".py"`) to exclude noise like READMEs or config files if you only need code.
2. **Read structurally first:** Call `get_file_outline` to read class/function signatures of a file before fetching its implementation.
3. **Read narrow scopes:** Use `get_symbol_definition` or `read_code_lines` to read specific code blocks. Do not read the entire file if you only need a single function.
   - *Note on get_symbol_definition: It returns the full implementation body for Functions, but only the outline for Classes. To read a specific class method, query ClassName.method_name.*
4. **Summarize large files:** If a file is too large (>200 lines), you MUST use the `summarize_file` tool to generate a concise summary using the local LLM instead of pulling the whole file into context.
5. **Update DB after edits:** If you modify any code file, you MUST call `index_project` to update the vector database instantly. **CRITICAL**: When using the `index_project` MCP tool, you MUST provide the absolute path to the project root (e.g., `d:\project\FourTIndex`) as the `project_path` argument, DO NOT use `.` as it may resolve to the MCP server's system directory instead of your workspace.
6. **Free memory when done:** Call `clean_mem()` tool (or run CLI `fourtindex clean-mem`) when you are done with heavy vector searches or indexing, to release VRAM and RAM immediately and save system resources.
7. **Save design history & Hibernate:** Call `save_session_summary` before concluding a task to log your design decisions in the database. If context is getting too large (>30k tokens), you MUST use `hibernate_session` to save a handoff state and request the user to start a new chat.
8. **DO NOT SKIP STEPS / CRITICAL INSTRUCTIONS:** You are strictly prohibited from skipping steps under any circumstances. You must perform each stage of the development process (Research -> Design -> Implementation -> Deep Scan & Verification -> Re-index -> Memory Cleanup -> Session Summary) fully and sequentially. Always run the mandatory Deep Scan checks before declaring a task complete.



> [!IMPORTANT]
> **🚨 CRITICAL HANDOFF RULE: AUTO-RESUME MEMORY**
> When starting a completely new chat session, the VERY FIRST THING you MUST DO is read the contents of the `.fourtindex_handoff.md` file located at the root of the project. This file contains your hibernated memory (current task, uncommitted changes, next steps). Absolutely do not make any code changes or suggest solutions until you have fully loaded this handoff context.
