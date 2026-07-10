---
name: FourTIndex
description: Guidelines on using the local codebase indexer and MCP server FourTIndex to retrieve code context, perform semantic search, and manage project indices to save API quota.
---

# Skill: using FourTIndex Local Context Retrieval

This workspace is indexed locally using **FourTIndex**, a high-fidelity local codebase indexer and Model Context Protocol (MCP) server. 

You should use the tools provided by FourTIndex to gather codebase context and perform code searches instead of dumping or reading entire folders/files. This preserves your context window and saves API token quota.

## MCP Tools API & Type Signatures

If you are running in an MCP-enabled environment, the following tools are registered under the name `FourTIndex`. Note the parameter types:

1. `search_codebase(query: str, project_name: str = None, limit: int = 5, file_ext: str = None) -> str`
   - Performs semantic vector search on code chunks. `project_name` defaults to `None` and is dynamically resolved to the active project based on the caller's working directory.
2. `get_file_outline(file_path: str, project_name: str = None) -> str`
   - Retrieves class outlines, function names, and import structures. `project_name` is optional.
3. `get_symbol_definition(symbol_name: str, project_name: str = None) -> str`
   - Retrieves the exact class or function implementation. `project_name` is optional.
4. `read_code_lines(file_path: str, start_line: int, end_line: int, project_name: str = None) -> str`
   - Reads exact physical lines. `project_name` is optional.
5. `summarize_file(file_path: str, project_name: str = None) -> str`
   - Uses the local LLM to generate a concise summary of the provided file to save context tokens.
6. `save_session_summary(session_id: str, summary_text: str, project_name: str = None) -> str`
   - Stores design decisions or change logs. `project_name` is optional.
7. `hibernate_session(current_task: str, next_steps: str, uncommitted_changes: str, project_name: str = None) -> str`
   - Saves the current session's progress and generates a Zero-Prompt Resume handoff file `.fourtindex_handoff.md`.
6. `index_project(project_path: str = ".", project_name: str = None) -> str`
   - Forces a re-index of the codebase. `project_name` is optional. **CRITICAL**: Always provide the ABSOLUTE PATH to your project root (e.g. `d:\project\FourTIndex`) for `project_path`. Do NOT use `.` as it will resolve to the MCP server's internal directory instead of your project.
7. `index_skill(skill_path: str, project_name: str = None) -> str`
   - Indexes a specific skill's `SKILL.md` file. `project_name` is optional.
8. `search_skills(query: str, project_name: str = None, limit: int = 3) -> str`
   - Performs semantic vector search on indexed skill sections. `project_name` is optional.
9. `get_skill_outline(skill_name: str, project_name: str = None) -> str`
   - Retrieves the list of headings (sections) available. `project_name` is optional.
10. `read_skill_section(skill_name: str, heading: str, project_name: str = None) -> str`
    - Retrieves the exact markdown section content. `project_name` is optional.
11. `get_project_roadmap(project_name: str = None) -> str`
    - Retrieves the full JSON structural overview (roadmap) and detected framework signatures. `project_name` is optional.
12. `list_projects() -> str`
    - Lists all registered projects in the registry database.
13. `get_token_report() -> str`
    - Estimates and outputs the current session's input/output token usage.
14. `clean_mem() -> str`
    - Unloads all configured models from VRAM/RAM.

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

> [!IMPORTANT]
> **CRITICAL: NO STEP SKIPPING ALLOWED!**
> The LLM is strictly prohibited from skipping any part of the development, verification, indexing, or cleanup process. Every task must be executed through all specified stages sequentially. Shortcuts or skipping steps will lead to bug accumulation and project failure.

> [!IMPORTANT]
> **🚨 CRITICAL HANDOFF RULE: AUTO-RESUME MEMORY**
> When starting a completely new chat session, the VERY FIRST THING you MUST DO is read the contents of the `.fourtindex_handoff.md` file located at the root of the project (using standard file reading tools if available, or ask the user to provide it). This file contains your hibernated memory (current task, uncommitted changes, next steps). Absolutely do not make any code changes or suggest solutions until you have fully loaded this handoff context.

When answering questions or modifying code in this workspace, you MUST follow these optimization and verification stages:

> [!CAUTION]
> **CRITICAL CONTEXT & TOKEN BUDGET CONTROL:**
> 1. **Mandatory Token Audit**: You MUST call `get_token_report()` on your first turn to evaluate the active prompt size and API cost.
> 2. **Context Bloat Warning**: If the active prompt size exceeds **35,000 tokens**, you MUST immediately advise the user to start a new chat session and transition using the Context Bridge.
> 3. **File Size Reading Bound**: You are strictly prohibited from calling `read_code_lines` or `view_file` on ranges larger than **100 lines** without first calling `get_file_outline` and specifying a narrow, targeted line range.
> 4. **No Duplicate Reads**: Do not call `read_code_lines` on the same file multiple times in a row.

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

### 4. Deep Scan & Correctness Verification (Mandatory)
Before finishing the task, perform a thorough review of your modifications following the **Anti-Bug Coding Rules v2** (mandatory):
- **Symbol Scan**: Verify that all variables, functions, and properties exist and are correctly named.
- **Dependency & Import Scan**: Ensure all imports are correct, no unused imports remain, and path targets exist.
- **Type & Async Flow Scan**: Trace type flows, null/undefined safety guards, and await logic with proper error handling.
- **Edge Cases**: Verify behavior on null, empty values, boundary conditions, and error-throwing code blocks.
- **Semantic & Logical Correctness**: Do not use fake or placeholder logic. Ensure side effects are managed.

### 5. Session Wrap-up (Session End)
- **Memory Cleanup**: Call `clean_mem()` tool (or run `fourtindex clean-mem` CLI) to unload models from local VRAM and system memory.
- **Save Design History**: When the task is complete, summarize your modifications and design decisions. Call `save_session_summary` with a unique session ID (e.g., `session_<date>_<time>`) to save the summary. This helps future sessions locate past design context.

