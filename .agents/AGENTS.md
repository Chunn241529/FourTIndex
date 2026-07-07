# fourTindex Codebase Search & Retrieval Rules

This codebase is indexed locally via **fourTindex** (an MCP server & local vector indexer). You MUST use fourTindex tools to navigate, search, and inspect the codebase.

## 🚨 CRITICAL: MANDATORY FIRST STEP FOR ALL TASKS
On the very first turn of any task, you MUST inspect the `.agents/skills/` directory to locate the project's skill directory (for this codebase, it is `.agents/skills/FourTIndex/SKILL.md`), and call `view_file` on its `SKILL.md` (or use `read_skill_section` / `get_skill_outline`) to load the optimal query and context management guidelines. This step is STRICTLY MANDATORY and cannot be skipped under any circumstances. You must explicitly state in your first response that you have read and loaded the skill instructions.

## Directives for Agent LLM:
1. **Do not dump directories:** Instead of listing files or reading entire folders, always use `search_codebase` to search semantically. Use the `file_ext` filter (e.g. `".py"`) to exclude noise like READMEs or config files if you only need code.
2. **Read structurally first:** Call `get_file_outline` to read class/function signatures of a file before fetching its implementation.
3. **Read narrow scopes:** Use `get_symbol_definition` or `read_code_lines` to read specific code blocks. Do not read the entire file if you only need a single function.
   - *Note on get_symbol_definition: It returns the full implementation body for Functions, but only the outline for Classes. To read a specific class method, query ClassName.method_name.*
4. **Update DB after edits:** If you modify any code file, you MUST call `index_project` (or run CLI `fourtindex index .`) to update the vector database instantly (takes <1s due to 16x batch and incremental sync).
5. **Free memory when done:** Call `clean_mem()` tool (or run CLI `fourtindex clean-mem`) when you are done with heavy vector searches or indexing, to release VRAM and RAM immediately and save system resources.
6. **Save design history:** Call `save_session_summary` before concluding a task to log your design decisions in the database.
7. **DO NOT SKIP STEPS / CRITICAL INSTRUCTIONS:** You are strictly prohibited from skipping steps under any circumstances. You must perform each stage of the development process (Research -> Design -> Implementation -> Deep Scan & Verification -> Re-index -> Memory Cleanup -> Session Summary) fully and sequentially. Always run the mandatory Deep Scan checks before declaring a task complete.

