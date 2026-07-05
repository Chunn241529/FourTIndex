---
name: FourTIndex
description: Guidelines on using the local codebase indexer and MCP server FourTIndex to retrieve code context, perform semantic search, and manage project indices to save API quota.
---

# Skill: using FourTIndex Local Context Retrieval

This workspace is indexed locally using **FourTIndex**, a high-fidelity local codebase indexer and Model Context Protocol (MCP) server. 

You should use the tools provided by FourTIndex to gather codebase context and perform code searches instead of dumping or reading entire folders/files. This preserves your context window and saves API token quota.

## MCP Tools API & Type Signatures

If you are running in an MCP-enabled environment, the following tools are registered under the name `FourTIndex`. Note the parameter types:

1. `search_codebase(query: str, project_name: str = "FourTIndex", limit: int = 5, file_ext: str = None) -> str`
   - Performs semantic vector search on code chunks. Filter by file extension (e.g. `".py"`, `"ts"`) to exclude noise.
2. `get_file_outline(file_path: str, project_name: str = "FourTIndex") -> str`
   - Retrieves class outlines, function names, and import structures without full implementation code. Use this to understand file structure first.
3. `get_symbol_definition(symbol_name: str, project_name: str = "FourTIndex") -> str`
   - Retrieves the exact class or function implementation.
   - **Crucial Behavior**: If `symbol_name` is a **Function**, it returns the full body. If it is a **Class**, it returns the outline (method signatures only). To read specific methods, query `ClassName.method_name`.
4. `read_code_lines(file_path: str, start_line: int, end_line: int, project_name: str = "FourTIndex") -> str`
   - Reads exact physical lines (1-indexed, inclusive). It automatically resolves relative paths by looking up the absolute path of the project in the registry.
5. `save_session_summary(session_id: str, summary_text: str, project_name: str = "FourTIndex") -> str`
   - Stores design decisions or change logs into the session memories index for future query references.
6. `index_project(project_path: str = ".", project_name: str = "FourTIndex") -> str`
   - Forces a re-index of the codebase. It uses **16x Batch Embedding Optimization** for extremely fast index creation and only indexes modified files (Incremental Sync takes < 1 second).
   - Unnecessary files and directories (like `.git`, `node_modules`, `.fourtindex`, `*.egg-info`, `.venv`) are automatically excluded.
7. `index_skill(skill_path: str, project_name: str = "FourTIndex") -> str`
   - Indexes a specific skill's `SKILL.md` file using heading-based splitting and YAML frontmatter parsing.
8. `search_skills(query: str, project_name: str = "FourTIndex", limit: int = 3) -> str`
   - Performs semantic vector search on indexed skill sections.
9. `get_skill_outline(skill_name: str, project_name: str = "FourTIndex") -> str`
   - Retrieves the list of headings (sections) available for a specific skill.
10. `read_skill_section(skill_name: str, heading: str, project_name: str = "FourTIndex") -> str`
    - Retrieves the exact markdown section content under a specific heading for a registered skill.
11. `clean_mem() -> str`
    - Unloads all configured models from local VRAM and system memory immediately. Use this to free up GPU and system resources between tasks.

## Codebase Metadata Schema

The Vector Database contains two primary collections: `code_chunks` (fine-grained code chunks) and `file_outlines` (high-level structure). The metadata for each document contains the following fields:

* **`project_name`** (*str*): The name of the project (e.g., `"FourTIndex"`).
* **`file_path`** (*str*): The relative path of the file from the project root.
* **`file_name`** (*str*): The name of the file with extension.
* **`file_ext`** (*str*): The lowercase file extension (e.g., `".py"`, `".yaml"`, `".md"`).
* **`chunk_type`** (*str*): The classification of the chunk. Values are:
  - `"class_outline"`: High-level class definition, docstring, and list of method signatures.
  - `"function"`: A class method or a top-level global function.
  - `"global_scope"`: General module headers (imports, global constants).
  - `"generic"`: Standard sliding-window line chunk (used as fallback or for non-code files).
* **`symbol_name`** (*str*): The name of the class or function (empty for generic/global chunks).
* **`start_line`** (*int*): The 1-indexed start line of this chunk in the original file.
* **`end_line`** (*int*): The 1-indexed end line of this chunk in the original file.
* **`hash`** (*str*): The SHA256 hash of the file content when indexed.

## Command Line Fallback (Cross-Platform)

If MCP tools are not active, you can invoke FourTIndex via CLI using the local Python environment.

### Windows:
* Indexing Codebase: `fourtindex index .`
* Semantic Code Search: `fourtindex search "your search query"`
* Local LLM Q&A: `fourtindex query "your question about codebase"`
* Indexing Customization Skill: `fourtindex index-skill <path_to_skill>`
* Semantic Skill Search: `fourtindex search-skills "your search query"`

### macOS / Linux:
* Indexing Codebase: `python main.py index .`
* Semantic Code Search: `python main.py search "your search query"`
* Local LLM Q&A: `python main.py query "your question about codebase"`
* Indexing Customization Skill: `python main.py index-skill <path_to_skill>`
* Semantic Skill Search: `python main.py search-skills "your search query"`

---

## Agent Guidelines & Loop Best Practices

When answering questions or modifying code in this workspace, follow these optimization stages:

### 1. Context Gathering Stage
- **Never** read the entire codebase or list all directory trees recursively.
- Call `search_codebase` using semantic keywords first to locate where features are implemented.
- Call `get_file_outline` on target files to inspect their structure (classes/methods) before reading them.

### 2. Deep Dive Stage
- When you find a target class or function, avoid reading the whole file.
- Call `get_symbol_definition` or `read_code_lines` to inspect only the required functions/classes. This keeps your context window small and responsive.

### 3. Verification & Code Modification Stage
- Make your code edits cleanly.
- After modifying files, call `index_project` (or run `main.py index .` CLI) so that the local vector database is updated with your modifications. 
- *Note: Because of **16x Batch Embedding** and **Incremental Sync**, updating the index for modified files is extremely fast (< 1s) and safe to run frequently.*

### 4. Session Wrap-up (Session End)
- When the task is complete, summarize your modifications and design decisions.
- Call `save_session_summary` with a unique session ID (e.g., `session_<date>_<time>`) to save the session summary. This helps future sessions answer questions like "What did we do in the last session?" or "Why did we change the config?" using semantic history search.
