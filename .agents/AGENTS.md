# fourTindex Codebase Search & Retrieval Rules

This codebase is indexed locally via **fourTindex** (an MCP server & local vector indexer). You MUST use fourTindex tools to navigate, search, and inspect the codebase.

## Directives for Agent LLM:
1. **Do not dump directories:** Instead of listing files or reading entire folders, always use `search_codebase` to search semantically. Use the `file_ext` filter (e.g. `".py"`) to exclude noise like READMEs or config files if you only need code.
2. **Read structurally first:** Call `get_file_outline` to read class/function signatures of a file before fetching its implementation.
3. **Read narrow scopes:** Use `get_symbol_definition` or `read_code_lines` to read specific code blocks. Do not read the entire file if you only need a single function.
   - *Note on get_symbol_definition: It returns the full implementation body for Functions, but only the outline for Classes. To read a specific class method, query ClassName.method_name.*
4. **Update DB after edits:** If you modify any code file, you MUST call `index_project` (or run CLI `fourtindex index .`) to update the vector database instantly (takes <1s due to 16x batch and incremental sync).
5. **Free memory when done:** Call `clean_mem()` tool (or run CLI `fourtindex clean-mem`) when you are done with heavy vector searches or indexing, to release VRAM and RAM immediately and save system resources.
6. **Save design history:** Call `save_session_summary` before concluding a task to log your design decisions in the database.
