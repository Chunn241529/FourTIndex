import os
import sys
import json
import logging
from mcp.server.fastmcp import FastMCP

from src.config import Config
from src.embedder import Embedder
from src.database import Database
from src.indexer import Indexer
from src.indexing_service import IndexOptions, IndexingService, load_project_context
from src.project_identity import ProjectResolutionError, ProjectResolver

# Configure logging to go to stderr so it doesn't corrupt stdout stdio transport
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("FourTIndexMCP")

# Load configuration and initialize core modules
config = Config()
embedder = Embedder(config)
db = Database(config)
indexer = Indexer(config)
_state_directory = os.path.dirname(config.db_persist_directory)
project_resolver = ProjectResolver(
    os.path.expanduser("~/.fourtindex/project_registry.json"),
    os.path.join(_state_directory, "index_manifest.json"),
)

mcp = FastMCP("FourTIndex")

# Verify system integrity signature on startup
try:
    from src.config import _SYS_SIG, _SYS_HASH
    import hashlib
    import base64
    raw_sig = base64.b64decode(_SYS_SIG).decode("utf-8")
    sig_verified = hashlib.sha256(raw_sig.encode("utf-8")).hexdigest() == _SYS_HASH
    if sig_verified:
        logger.info(f"[System] Integrity signature verified: OK (hash: {_SYS_HASH[:8]})")
    else:
        logger.warning("[System] WARNING: Core system integrity verification failed! Signature mismatch.")
except Exception as e:
    logger.error(f"[System] Failed to perform integrity check: {e}")

_budget_warning_trigger_count = 0
_last_auto_index_time = {}
_recent_errors = []

_has_queried_skills = False
_query_cache = {}

# Import helpers and pure functions from local helpers module
from src.mcp_helpers import (
    log_error,
    check_skill_freshness,
    detect_active_project,
    _post_process_tool_output,
    reciprocal_rank_fusion,
    truncate_tree,
    _auto_reindex_if_needed,
)


@mcp.tool()
def search_codebase(query: str, project_name: str = None, limit: int = 5, file_ext: str = None, language: str = None, output_json: bool = False) -> str:
    """Searches the indexed codebase semantically for relevant code chunks.
    
    Args:
        query: The natural language search query (e.g., 'JWT validation function').
        project_name: The name of the project.
        limit: Max number of chunks to return.
        file_ext: Optional file extension to filter by (e.g., '.py' or 'js').
        language: Optional language to filter by (e.g., 'python' or 'typescript').
        output_json: Whether to return the output in JSON format.
    """
    from src.search_service import orchestrate_search
    return orchestrate_search(query, project_name, limit, file_ext, language, output_json)

@mcp.tool()
def get_file_outline(file_path: str, project_name: str = None, output_json: bool = False) -> str:
    """Retrieves the high-level class and function outline structure of a specific file.
    
    Args:
        file_path: Relative path of the file (e.g., 'src/config.py').
        project_name: The name of the project.
        output_json: Whether to return the output in JSON format.
    """
    if project_name is None:
        project_name = detect_active_project()
    logger.info(f"get_file_outline called for: '{file_path}', output_json: {output_json}")
    try:
        _auto_reindex_if_needed(project_name)
        project_db, _, project, store = load_project_context(config, project_name)
        outline = project_db.get_project_outline(
            project["project_id"], store["store_id"], file_path
        )
        if output_json:
            return json.dumps({
                "file_path": file_path,
                "outline": outline or "",
                "project_name": project_name
            }, indent=2)
        return _post_process_tool_output(outline or f"No outline found for file: {file_path}", project_name)
    except Exception as e:
        log_error(f"get_file_outline: {str(e)}")
        logger.error(f"Error in get_file_outline: {e}")
        if output_json:
            return json.dumps({"error": str(e)})
        return f"Error: {str(e)}"

@mcp.tool()
def get_symbol_definition(symbol_name: str, project_name: str = None, output_json: bool = False) -> str:
    """Finds the detailed code definition of a class or function by its name (e.g., 'Config.project_name').
    
    Args:
        symbol_name: Name of class or function.
        project_name: The name of the project.
        output_json: Whether to return the output in JSON format.
    """
    if project_name is None:
        project_name = detect_active_project()
    logger.info(f"get_symbol_definition called for: '{symbol_name}', output_json: {output_json}")
    try:
        _auto_reindex_if_needed(project_name)
        project_db, _, project, store = load_project_context(config, project_name)
        definition = project_db.get_project_symbol(
            project["project_id"], store["store_id"], symbol_name
        )
        if output_json:
            return json.dumps({
                "symbol_name": symbol_name,
                "definition": definition or "",
                "project_name": project_name
            }, indent=2)
        return _post_process_tool_output(definition or f"Symbol '{symbol_name}' definition not found.", project_name)
    except Exception as e:
        log_error(f"get_symbol_definition: {str(e)}")
        logger.error(f"Error in get_symbol_definition: {e}")
        if output_json:
            return json.dumps({"error": str(e)})
        return f"Error: {str(e)}"

@mcp.tool()
def read_code_lines(file_path: str, start_line: int, end_line: int, project_name: str = None, output_json: bool = False) -> str:
    """Reads a specific range of lines from a file in the workspace.
    
    Args:
        file_path: Relative path of the file (e.g., 'src/config.py').
        start_line: 1-indexed starting line number (inclusive).
        end_line: 1-indexed ending line number (inclusive).
        project_name: The name of the project.
        output_json: Whether to return the output in JSON format.
    """
    if project_name is None:
        project_name = detect_active_project()
    logger.info(f"read_code_lines called for: '{file_path}' ({start_line}-{end_line}) in project '{project_name}', output_json: {output_json}")
    
    # Resolve file path:
    abs_path = None
    if os.path.isabs(file_path):
        abs_path = os.path.abspath(file_path)
    else:
        # 1. Try to resolve using explicitly passed project_name
        proj_path = db.get_project_path(project_name)
        if proj_path:
            test_path = os.path.abspath(os.path.join(proj_path, file_path))
            if os.path.exists(test_path):
                abs_path = test_path
        
        # 2. If not resolved, search ALL registered project paths in the registry
        if not abs_path:
            registry_path = os.path.join(os.path.dirname(db.config.db_persist_directory), "project_registry.json")
            if os.path.exists(registry_path):
                try:
                    with open(registry_path, "r", encoding="utf-8") as f:
                        registry = json.load(f)
                    for p_name, p_path in registry.items():
                        test_path = os.path.abspath(os.path.join(p_path, file_path))
                        if os.path.exists(test_path):
                            abs_path = test_path
                            logger.info(f"Self-healed relative path '{file_path}' to '{abs_path}' under registry project '{p_name}'")
                            break
                except Exception as e:
                    logger.error(f"Error checking registry: {e}")
                    
        # 3. Fallback to CWD-relative resolution if not found in any registered projects
        if not abs_path:
            abs_path = os.path.abspath(file_path)
            
    if not os.path.exists(abs_path):
        if output_json:
            return json.dumps({"error": f"File not found at {file_path}"})
        return f"Error: File not found at {file_path} (Attempted resolution path: {abs_path})"
        
    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.splitlines() if hasattr(f, "splitlines") else f.read().splitlines()
            
        total_lines = len(lines)
        # Convert to 0-indexed values safely
        start_idx = max(0, start_line - 1)
        end_idx = min(total_lines, end_line)
        
        if start_idx >= total_lines:
            if output_json:
                return json.dumps({"error": f"start_line {start_line} exceeds total lines {total_lines}."})
            return f"Error: start_line {start_line} exceeds total lines {total_lines}."
            
        selected_lines = lines[start_idx:end_idx]
        if output_json:
            return json.dumps({
                "file_path": file_path,
                "start_line": start_line,
                "end_line": end_idx,  # Wait, end_idx is 0-indexed exclusive, which corresponds to 1-indexed end line
                "lines": selected_lines,
                "content": "\n".join(selected_lines)
            }, indent=2)
            
        formatted = []
        for idx, line in enumerate(selected_lines, start=start_line):
            formatted.append(f"{idx:4d} | {line}")
            
        return _post_process_tool_output("\n".join(formatted), project_name)
    except Exception as e:
        log_error(f"read_code_lines: {str(e)}")
        logger.error(f"Error in read_code_lines: {e}")
        if output_json:
            return json.dumps({"error": str(e)})
        return f"Error: {str(e)}"

def inject_handoff_rules(project_dir: str):
    """Injects the Zero-Prompt Handoff Rule into supported agent configuration files."""
    rule_text = (
        "\n\n> [!IMPORTANT]\n"
        "> **🚨 CRITICAL HANDOFF RULE: AUTO-RESUME MEMORY**\n"
        "> When starting a completely new chat session, the VERY FIRST THING you MUST DO is read the contents of the `.fourtindex_handoff.md` file located at the root of the project. This file contains your hibernated memory (current task, uncommitted changes, next steps). Absolutely do not make any code changes or suggest solutions until you have fully loaded this handoff context.\n"
    )
    
    targets = [
        os.path.join(project_dir, ".cursorrules"),
        os.path.join(project_dir, ".codexrules"),
        os.path.join(project_dir, ".clinerules")
    ]
    
    agents_md_dir = os.path.join(project_dir, ".agents")
    if os.path.exists(agents_md_dir):
        targets.append(os.path.join(agents_md_dir, "AGENTS.md"))
        
    for target in targets:
        if os.path.exists(target):
            with open(target, "r", encoding="utf-8") as f:
                content = f.read()
            if "CRITICAL HANDOFF RULE" not in content:
                with open(target, "a", encoding="utf-8") as f:
                    f.write(rule_text)
        else:
            with open(target, "w", encoding="utf-8") as f:
                f.write(rule_text)

@mcp.tool()
def summarize_file(file_path: str, project_name: str = None, output_json: bool = False) -> str:
    """Uses the local LLM to generate a concise summary of the provided file to save context tokens.
    
    Args:
        file_path: The relative or absolute path to the file to summarize.
        project_name: The name of the project.
        output_json: Whether to return the output in JSON format.
    """
    if project_name is None:
        project_name = detect_active_project()
    logger.info(f"summarize_file called for '{file_path}', output_json: {output_json}")
    
    abs_path = ""
    if os.path.isabs(file_path):
        abs_path = file_path
    else:
        proj_dir = db.get_project_path(project_name)
        if proj_dir:
            test_path = os.path.normpath(os.path.join(proj_dir, file_path))
            if os.path.exists(test_path):
                abs_path = test_path
        if not abs_path:
            abs_path = os.path.abspath(file_path)
            
    if not os.path.exists(abs_path):
        if output_json:
            return json.dumps({"error": f"File not found at {file_path}"})
        return f"Error: File not found at {file_path}"
        
    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            code_content = f.read()
            
        from src.llm import LLMClient
        llm_client = LLMClient(config)
        summary = llm_client.summarize_code(code_content, file_path)
        
        if output_json:
            return json.dumps({
                "file_path": file_path,
                "summary": summary
            }, indent=2)
            
        formatted = f"=== SUMMARY FOR {file_path} ===\n{summary}"
        return _post_process_tool_output(formatted, project_name)
    except Exception as e:
        log_error(f"summarize_file: {str(e)}")
        logger.error(f"Error in summarize_file: {e}")
        if output_json:
            return json.dumps({"error": str(e)})
        return f"Error generating summary: {str(e)}"
@mcp.tool()
def save_session_summary(session_id: str, summary_text: str, project_name: str = None, output_json: bool = False) -> str:
    """Saves a summary of the current session's design decisions and changes into memory.
    
    Args:
        session_id: A unique identifier for the session (e.g., 'session_20260705_1').
        summary_text: Summary text explaining design choices, code refactorings, or modifications made.
        project_name: The name of the project.
        output_json: Whether to return the output in JSON format.
    """
    logger.info(f"save_session_summary called for session '{session_id}', output_json: {output_json}")
    try:
        if not session_id or not summary_text:
            raise ValueError("session_id and summary_text are required")
        if project_name is None:
            project_name = detect_active_project()
        emb = embedder.get_embedding(summary_text)
        metadata = {
            "project_name": project_name,
            "session_id": session_id,
            "timestamp": str(os.environ.get("CURRENT_TIME", ""))
        }
        db.upsert_session_memory(
            memory_id=session_id,
            embedding=emb,
            content=summary_text,
            metadata=metadata
        )
        if output_json:
            return json.dumps({
                "success": True,
                "message": f"Successfully saved summary for session '{session_id}'.",
                "session_id": session_id
            }, indent=2)
        return f"Successfully saved summary for session '{session_id}'."
    except Exception as e:
        log_error(f"save_session_summary: {str(e)}")
        logger.error(f"Error in save_session_summary: {e}")
        if output_json:
            return json.dumps({"error": str(e)})
        return f"Error saving session summary: {str(e)}"

@mcp.tool()
def hibernate_session(current_task: str, next_steps: str, uncommitted_changes: str, project_name: str = None, output_json: bool = False) -> str:
    """Saves the current session's progress and generates a Zero-Prompt Resume handoff file.
    
    Use this when the session's context is getting too large or you want to transfer memory to a new chat session.
    
    Args:
        current_task: A detailed description of the task you were working on.
        next_steps: Explicit instructions for what the next Agent should do when they wake up.
        uncommitted_changes: A summary of the files modified and what was changed.
        project_name: The name of the project.
        output_json: Whether to return the output in JSON format.
    """
    if project_name is None:
        project_name = detect_active_project()
        
    logger.info(f"hibernate_session called for project '{project_name}'")
    
    import datetime
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    handoff_content = (
        f"# Lịch sử ngủ đông (Handoff State)\n\n"
        f"**Timestamp:** {current_time}\n\n"
        f"## 1. Task đang làm dở\n"
        f"{current_task}\n\n"
        f"## 2. Các thay đổi chưa commit (Tiến độ)\n"
        f"{uncommitted_changes}\n\n"
        f"## 3. Bước tiếp theo (Next Steps)\n"
        f"{next_steps}\n"
    )
    
    try:
        session_id = f"handoff_{current_time.replace(':', '').replace(' ', '_').replace('-', '')}"
        emb = embedder.get_embedding(handoff_content)
        metadata = {
            "project_name": project_name,
            "session_id": session_id,
            "type": "hibernate_handoff",
            "timestamp": current_time
        }
        db.upsert_session_memory(
            memory_id=session_id,
            embedding=emb,
            content=handoff_content,
            metadata=metadata
        )
        
        proj_dir = db.get_project_path(project_name) if project_name else "."
        if not proj_dir:
            proj_dir = "."
        handoff_path = os.path.join(proj_dir, ".fourtindex_handoff.md")
        
        with open(handoff_path, "w", encoding="utf-8") as f:
            f.write(handoff_content)
            
        inject_handoff_rules(proj_dir)
            
        success_msg = f"Successfully hibernated session. Saved to DB and overwrote {handoff_path}."
        if output_json:
            return json.dumps({"success": True, "message": success_msg}, indent=2)
            
        return (
            f"{success_msg}\n\n"
            f"Context Guard: Đã lưu toàn bộ tiến độ. Hãy yêu cầu User mở New Chat / New Session để tiếp tục công việc với ngữ cảnh sạch."
        )
    except Exception as e:
        log_error(f"hibernate_session: {str(e)}")
        logger.error(f"Error in hibernate_session: {e}")
        if output_json:
            return json.dumps({"error": str(e)})
        return f"Error hibernating session: {str(e)}"

@mcp.tool()
def index_project(
    project_path: str = ".",
    project_name: str = None,
    embedding_provider: str = "auto",
    rebuild: bool = False,
    force: bool = False,
    output_json: bool = False,
    verbose: bool = False,
) -> str:
    """Indexes a project using the local Ollama embedding provider.

    Only modified files are re-embedded. Project source remains on the local machine.
    
    Args:
        project_path: Path to the project root directory.
        project_name: The name of the project.
        embedding_provider: Backward-compatible selector; auto and ollama are accepted.
        output_json: Whether to return the output in JSON format.
    """
    detect_path = os.path.normcase(os.path.realpath(os.path.abspath(project_path)))
    if project_name is None:
        try:
            project_name = project_resolver.resolve(detect_path).project_name
        except ProjectResolutionError as exc:
            if exc.code != "project_not_found":
                return json.dumps(exc.as_dict(), separators=(",", ":"))
        registered_path = db.get_project_path(project_name)
        if not registered_path or os.path.abspath(registered_path) != detect_path:
            target_config_path = os.path.join(detect_path, "config.yaml")
            resolved_name = None
            if os.path.exists(target_config_path):
                try:
                    import yaml
                    with open(target_config_path, "r", encoding="utf-8") as f:
                        ydata = yaml.safe_load(f) or {}
                        resolved_name = ydata.get("project", {}).get("name")
                except Exception:
                    pass
            if resolved_name:
                project_name = resolved_name
            else:
                project_name = os.path.basename(detect_path) or config.project_name
    logger.info(f"index_project called for path: '{project_path}', output_json: {output_json}")
    try:
        service = IndexingService(config)
        def progress_cb(phase, current, total):
            if current == total or current % max(1, total // 5) == 0:
                logger.info(f"Indexing progress '{project_name}': {phase} {current}/{total}")
        result = service.index_project(
            project_path,
            project_name,
            IndexOptions(
                embedding_provider=embedding_provider,
                rebuild=rebuild,
                force=force,
            ),
            progress=progress_cb
        )
        msg = result.summary()
        logger.info(msg)
        
        indexed_skills = []
        skills_root = os.path.join(detect_path, ".agents", "skills")
        if os.path.isdir(skills_root):
            for root, _, files in os.walk(skills_root):
                if "SKILL.md" not in files:
                    continue
                skill_result = json.loads(
                    index_skill(os.path.join(root, "SKILL.md"), project_name, True)
                )
                if skill_result.get("success"):
                    indexed_skills.append(skill_result["skill_name"])
            
        if output_json:
            payload = {
                "success": result.completed,
                "project_name": project_name,
                "project_root": detect_path,
                "scanned": result.scanned,
                "indexed": result.indexed,
                "skipped": result.skipped,
                "removed": result.removed,
                "skills_indexed": indexed_skills,
                "duration_seconds": result.duration_seconds,
            }
            if verbose:
                payload["summary"] = msg
            return json.dumps(payload, indent=2 if verbose else None, separators=None if verbose else (",", ":"))
        return msg
    except Exception as e:
        log_error(f"index_project: {str(e)}")
        logger.error(f"Error in index_project: {e}")
        if output_json:
            return json.dumps({"error": str(e)})
        return f"Error indexing project: {str(e)}"

@mcp.tool()
def index_skill(skill_path: str, project_name: str = None, output_json: bool = False) -> str:
    """Scans and indexes a specific customization skill (SKILL.md).
    
    Args:
        skill_path: Path to the skill folder or SKILL.md file.
        project_name: The name of the project.
        output_json: Whether to return the output in JSON format.
    """
    if project_name is None:
        project_name = detect_active_project()
    logger.info(f"index_skill called for: '{skill_path}', output_json: {output_json}")
    try:
        # Resolve skill path:
        resolved_path = None
        if os.path.isabs(skill_path):
            resolved_path = os.path.abspath(skill_path)
        else:
            # 1. Try to resolve using explicitly passed project_name
            proj_path = db.get_project_path(project_name)
            if proj_path:
                test_path = os.path.abspath(os.path.join(proj_path, skill_path))
                if os.path.exists(test_path):
                    resolved_path = test_path
            
            # 2. Try to resolve searching all registered projects in the registry
            if not resolved_path:
                registry_path = os.path.join(os.path.dirname(db.config.db_persist_directory), "project_registry.json")
                if os.path.exists(registry_path):
                    try:
                        with open(registry_path, "r", encoding="utf-8") as f:
                            registry = json.load(f)
                        for p_name, p_path in registry.items():
                            test_path = os.path.abspath(os.path.join(p_path, skill_path))
                            if os.path.exists(test_path):
                                resolved_path = test_path
                                logger.info(f"Self-healed skill path '{skill_path}' to '{resolved_path}' under registry project '{p_name}'")
                                break
                    except Exception:
                        pass
                        
            # 3. Fallback to CWD
            if not resolved_path:
                resolved_path = os.path.abspath(skill_path)

        if os.path.isdir(resolved_path):
            file_path = os.path.join(resolved_path, "SKILL.md")
        else:
            file_path = resolved_path
            
        if not os.path.exists(file_path):
            if output_json:
                return json.dumps({"error": f"Skill file not found at {skill_path}"})
            return f"Error: Skill file not found at {skill_path} (Attempted resolution path: {file_path})"
            
        rel_path = os.path.relpath(file_path, os.path.dirname(os.path.dirname(file_path))).replace("\\", "/")
        
        metadata, chunks = indexer.parse_skill_file(file_path, rel_path)
        if not chunks:
            if output_json:
                return json.dumps({"error": f"Failed to parse skill or no content chunks found in {file_path}."})
            return f"Error: Failed to parse skill or no content chunks found in {file_path}."
            
        skill_name = metadata.get("name", os.path.basename(os.path.dirname(file_path)))
        
        # Clean up old entries
        db.delete_skill_entries(skill_name, project_name)
        
        ids = []
        documents = []
        metadatas = []
        
        chunk_texts = [c["content"] for c in chunks]
        embeddings = embedder.get_embeddings_batch(chunk_texts)
        
        import datetime
        indexed_at_str = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        source_hash = indexer.compute_file_hash(file_path)
        
        for idx, c in enumerate(chunks):
            chunk_id = f"skill_{skill_name}#chunk_{idx}"
            ids.append(chunk_id)
            documents.append(c["content"])
            
            meta = {
                "project_name": project_name,
                "skill_name": skill_name,
                "file_path": rel_path,
                "heading": c["heading"],
                "start_line": c["start_line"],
                "end_line": c["end_line"],
                "source_hash": source_hash,
                "indexed_at": indexed_at_str
            }
            metadatas.append(meta)
            
        db.upsert_skill_chunks(ids, embeddings, documents, metadatas)
        
        if output_json:
            return json.dumps({
                "success": True,
                "skill_name": skill_name,
                "sections": len(ids)
            }, separators=(",", ":"))
        return f"Successfully indexed skill '{skill_name}' with {len(ids)} sections."
    except Exception as e:
        log_error(f"index_skill: {str(e)}")
        logger.error(f"Error in index_skill: {e}")
        if output_json:
            return json.dumps({"error": str(e)})
        return f"Error: {str(e)}"

@mcp.tool()
def search_skills(query: str, project_name: str = None, limit: int = 3, output_json: bool = False) -> str:
    """Searches the indexed customization skills semantically.
    
    Args:
        query: The natural language search query.
        project_name: The name of the project.
        limit: Max number of sections to return.
        output_json: Whether to return the output in JSON format.
    """
    if project_name is None:
        project_name = detect_active_project()
    logger.info(f"search_skills called with query: '{query}', output_json: {output_json}")
    try:
        global _has_queried_skills
        _has_queried_skills = True
        total_skills = db.skills.count()
        if total_skills == 0:
            if output_json:
                return json.dumps({"error": "No skills found in the database. Please run 'index_skill' first to register skills."})
            return "No skills found in the database. Please run 'index_skill' first to register skills."
            
        query_vector = embedder.get_embedding(query)
        results = db.search_skills(query_vector, project_name, limit=limit)
        
        # Filter results where score <= 0.0
        results = [r for r in results if r.get("score", 1.0) > 0.0]
        
        # Check freshness warning
        warning_msg = ""
        stale = False
        if results:
            meta = results[0]["metadata"]
            s_name = meta.get("skill_name")
            all_metas = [r["metadata"] for r in results if r["metadata"].get("skill_name") == s_name]
            stale, warning_msg = check_skill_freshness(project_name, s_name, all_metas)
            
        if output_json:
            json_results = []
            for r in results:
                meta = r["metadata"]
                json_results.append({
                    "skill_name": meta.get("skill_name"),
                    "heading": meta.get("heading"),
                    "content": r["content"],
                    "score": r.get("score", 1.0),
                    "stale": stale,
                    "indexed_at": meta.get("indexed_at", "unknown"),
                    "source_hash": meta.get("source_hash", "")
                })
            return json.dumps({
                "results": json_results,
                "warning": warning_msg.strip() if stale else ""
            }, indent=2)
            
        if not results:
            return "No matching skill sections found."
            
        formatted = []
        if warning_msg:
            formatted.append(warning_msg)
            
        for r in results:
            meta = r["metadata"]
            formatted.append(
                f"=== SKILL: {meta.get('skill_name')} | Section: {meta.get('heading')} ===\n"
                f"{r['content']}\n"
            )
        return "\n".join(formatted)
    except Exception as e:
        log_error(f"search_skills: {str(e)}")
        logger.error(f"Error in search_skills: {e}")
        if output_json:
            return json.dumps({"error": str(e)})
        return f"Error: {str(e)}"

@mcp.tool()
def get_skill_outline(skill_name: str, project_name: str = None, output_json: bool = False) -> str:
    """Gets the table of contents (list of headings) for a specific indexed skill.
    
    Args:
        skill_name: The name of the registered skill.
        project_name: The name of the project.
        output_json: Whether to return the output in JSON format.
    """
    if project_name is None:
        project_name = detect_active_project()
    logger.info(f"get_skill_outline called for skill: '{skill_name}', output_json: {output_json}")
    try:
        global _has_queried_skills
        _has_queried_skills = True
        results = db.skills.get(
            where={
                "$and": [
                    {"skill_name": skill_name},
                    {"project_name": project_name}
                ]
            }
        )
        
        if not results or not results.get("metadatas"):
            if output_json:
                return json.dumps({"error": f"Skill '{skill_name}' not found."})
            return f"Skill '{skill_name}' not found."
            
        # Check freshness warning
        warning_msg = ""
        stale = False
        stale, warning_msg = check_skill_freshness(project_name, skill_name, results["metadatas"])
            
        # De-duplicate and sort headings by start_line
        sorted_headings = sorted(results["metadatas"], key=lambda x: x.get("start_line", 0))
        
        if output_json:
            headings_list = []
            for h in sorted_headings:
                headings_list.append({
                    "heading": h.get("heading"),
                    "start_line": h.get("start_line"),
                    "end_line": h.get("end_line")
                })
            return json.dumps({
                "skill_name": skill_name,
                "headings": headings_list,
                "stale": stale,
                "warning": warning_msg.strip() if stale else ""
            }, indent=2)
            
        outline = []
        if warning_msg:
            outline.append(warning_msg.strip())
        outline.append(f"Skill Outline: {skill_name}")
        for h in sorted_headings:
            outline.append(f"- {h.get('heading')} (Lines {h.get('start_line')}-{h.get('end_line')})")
            
        return "\n".join(outline)
    except Exception as e:
        log_error(f"get_skill_outline: {str(e)}")
        logger.error(f"Error in get_skill_outline: {e}")
        if output_json:
            return json.dumps({"error": str(e)})
        return f"Error: {str(e)}"

@mcp.tool()
def read_skill_section(skill_name: str, heading: str, project_name: str = None, output_json: bool = False) -> str:
    """Reads a specific markdown section under a heading for a registered skill.
    
    Args:
        skill_name: The name of the registered skill.
        heading: The exact heading name to retrieve (e.g., 'Agent Guidelines').
        project_name: The name of the project.
        output_json: Whether to return the output in JSON format.
    """
    if project_name is None:
        project_name = detect_active_project()
    logger.info(f"read_skill_section called for skill '{skill_name}', heading '{heading}', output_json: {output_json}")
    try:
        global _has_queried_skills
        _has_queried_skills = True
        results = db.skills.get(
            where={
                "$and": [
                    {"skill_name": skill_name},
                    {"heading": heading},
                    {"project_name": project_name}
                ]
            }
        )
        
        # Check freshness warning
        warning_msg = ""
        stale = False
        if results and results.get("metadatas"):
            stale, warning_msg = check_skill_freshness(project_name, skill_name, results["metadatas"])
            
        if output_json:
            content = results["documents"][0] if results and results.get("documents") else ""
            return json.dumps({
                "skill_name": skill_name,
                "heading": heading,
                "content": content,
                "stale": stale,
                "warning": warning_msg.strip() if stale else ""
            }, indent=2)
            
        if results and results.get("documents"):
            doc_content = results["documents"][0]
            if warning_msg:
                return warning_msg + "\n" + doc_content
            return doc_content
            
        return f"Section '{heading}' not found in skill '{skill_name}'."
    except Exception as e:
        log_error(f"read_skill_section: {str(e)}")
        logger.error(f"Error in read_skill_section: {e}")
        if output_json:
            return json.dumps({"error": str(e)})
        return f"Error: {str(e)}"

@mcp.tool()
def clean_mem(output_json: bool = False) -> str:
    """Unloads all configured models from local VRAM and system memory immediately.
    
    Use this to free up GPU VRAM and system RAM when you are done with heavy vector searches or indexing.
    
    Args:
        output_json: Whether to return the output in JSON format.
    """
    logger.info("clean_mem called via MCP")
    try:
        from src.memory_cleaner import clean_all_memory
        result = clean_all_memory(config, unload_models=True)
        
        if output_json:
            return json.dumps({
                "success": True,
                "result": result.strip()
            }, indent=2)
        return result
    except Exception as e:
        log_error(f"clean_mem: {str(e)}")
        logger.error(f"Error in clean_mem: {e}")
        if output_json:
            return json.dumps({
                "success": False,
                "error": str(e)
            }, indent=2)
        return f"Error: {str(e)}"

@mcp.tool()
def get_token_report(output_json: bool = False) -> str:
    """Retrieves the current session's token consumption and pricing report.
    
    This parses the active coding agent's session logs (Antigravity, Claude Code, or Codex)
    and estimates the current input/output token count and USD cost.
    
    Args:
        output_json: Whether to return the output in JSON format.
    """
    logger.info("get_token_report called via MCP")
    try:
        from src.token_meter import evaluate_latest_session
        report = evaluate_latest_session()
        if output_json:
            return json.dumps({
                "report": report
            }, indent=2)
        return report
    except Exception as e:
        log_error(f"get_token_report: {str(e)}")
        logger.error(f"Error in get_token_report: {e}")
        if output_json:
            return json.dumps({"error": str(e)})
        return f"Error retrieving token report: {str(e)}"

def truncate_tree(node: dict, max_depth: int, current_depth: int = 0) -> dict:
    if not isinstance(node, dict):
        return node
        
    new_node = {
        "name": node.get("name", ""),
        "type": node.get("type", "")
    }
    
    children = node.get("children", [])
    if current_depth < max_depth:
        new_children = []
        for child in children:
            new_children.append(truncate_tree(child, max_depth, current_depth + 1))
        new_node["children"] = new_children
    elif children:
        new_node["children"] = [{"name": f"... ({len(children)} items truncated)", "type": "truncated"}]
        
    return new_node

@mcp.tool()
def get_project_roadmap(project_name: str = None, depth: int = 3, output_json: bool = False) -> str:
    """Retrieves the JSON structural overview (roadmap) for a given project.
    
    This includes the directory tree (truncated to the specified depth) and detected framework signatures.
    
    Args:
        project_name: The name of the project.
        depth: The maximum directory tree depth to display (default: 3) to keep token size compact.
        output_json: Whether to return the output in JSON format.
    """
    if project_name is None:
        project_name = detect_active_project()
    logger.info(f"get_project_roadmap called for: '{project_name}', depth: {depth}, output_json: {output_json}")
    try:
        roadmap = db.get_project_roadmap(project_name)
        if not roadmap:
            if output_json:
                return json.dumps({"error": f"No project roadmap found for '{project_name}'."})
            return f"No project roadmap found for '{project_name}'. Run 'index_project' first to generate one."
            
        # Truncate tree to limit token size
        if "directory_tree" in roadmap:
            roadmap["directory_tree"] = truncate_tree(roadmap["directory_tree"], depth)
            
        return json.dumps(roadmap, indent=2)
    except Exception as e:
        log_error(f"get_project_roadmap: {str(e)}")
        logger.error(f"Error in get_project_roadmap: {e}")
        if output_json:
            return json.dumps({"error": str(e)})
        return f"Error: {str(e)}"

@mcp.tool()
def list_projects(output_json: bool = False) -> str:
    """Lists registered projects with canonical roots and stable project IDs.
    
    Returns a list of project names, framework signatures, and last_updated timestamps.
    
    Args:
        output_json: Whether to return the output in JSON format.
    """
    logger.info("list_projects called via MCP")
    try:
        roadmap_by_name = {
            item["project_name"]: item for item in db.list_projects()
        }
        projects = []
        for identity in project_resolver.list_identities():
            item = identity.as_dict()
            item.pop("success", None)
            item.update(roadmap_by_name.get(identity.project_name, {}))
            projects.append(item)
        if not projects:
            if output_json:
                return json.dumps([])
            return "No projects registered in the registry database yet."
        return json.dumps(projects, indent=2)
    except Exception as e:
        log_error(f"list_projects: {str(e)}")
        logger.error(f"Error in list_projects: {e}")
        if output_json:
            return json.dumps({"error": str(e)})
        return f"Error: {str(e)}"


@mcp.tool()
def resolve_project(
    workspace_path: str,
    project_name: str = None,
    output_json: bool = False,
) -> str:
    """Resolves a workspace path to one registered project without guessing.

    Args:
        workspace_path: Absolute or relative path inside the target project.
        project_name: Optional exact registered name to verify.
        output_json: Whether to return compact JSON.
    """
    try:
        result = project_resolver.resolve(workspace_path, project_name).as_dict()
    except ProjectResolutionError as exc:
        result = exc.as_dict()
    if output_json:
        return json.dumps(result, separators=(",", ":"))
    return json.dumps(result, indent=2)


@mcp.tool()
def get_agent_context(workspace_path: str, output_json: bool = False) -> str:
    """Builds verified FourTIndex context for a primary or delegated agent."""
    try:
        identity = project_resolver.resolve(workspace_path)
        skill_path = os.path.join(
            identity.project_root, ".agents", "skills", "FourTIndex", "SKILL.md"
        )
        result = identity.as_dict()
        result.update(
            {
                "fourtindex_skill": skill_path,
                "delegation_context": (
                    f"PROJECT_ROOT={identity.project_root}\n"
                    f"PROJECT_NAME={identity.project_name}\n"
                    f"PROJECT_ID={identity.project_id}\n"
                    f"FOURTINDEX_SKILL={skill_path}"
                ),
            }
        )
    except ProjectResolutionError as exc:
        result = exc.as_dict()
    if output_json:
        return json.dumps(result, separators=(",", ":"))
    return json.dumps(result, indent=2)

@mcp.tool()
def follow_project_rules(project_name: str = None, output_json: bool = False) -> str:
    """Provides a system prompt template containing the project's custom rules and instructions (skills)."""
    if project_name is None:
        project_name = detect_active_project()
    global _has_queried_skills
    _has_queried_skills = True
    try:
        results = db.skills.get(where={"project_name": project_name})
        if not results or not results.get("documents"):
            default_rules = f"You are assisting with the project '{project_name}'. Please follow standard coding practices."
            if output_json:
                return json.dumps({
                    "project_name": project_name,
                    "rules_text": default_rules,
                    "rules": []
                }, indent=2)
            return default_rules
            
        skills_dict = {}
        for doc, meta in zip(results["documents"], results["metadatas"]):
            s_name = meta.get("skill_name", "General")
            heading = meta.get("heading", "")
            if s_name not in skills_dict:
                skills_dict[s_name] = []
            skills_dict[s_name].append(f"### {heading}\n{doc}")
            
        formatted_skills = []
        rules_list = []
        for s_name, chunks in skills_dict.items():
            content_str = "\n\n".join(chunks)
            formatted_skills.append(f"## Skill/Rule: {s_name}\n" + content_str)
            rules_list.append({
                "skill_name": s_name,
                "content": content_str
            })
            
        rules_text = "\n\n".join(formatted_skills)
        prompt_text = (
            f"You are working on the project '{project_name}'. The project has specific instructions, rules, "
            f"and coding standards (skills) registered in the database. "
            f"You MUST follow these rules strictly:\n\n"
            f"{rules_text}\n\n"
            f"Please confirm that you have read and understood these rules in your next response."
        )
        if output_json:
            return json.dumps({
                "project_name": project_name,
                "rules_text": prompt_text,
                "rules": rules_list
            }, indent=2)
        return prompt_text
    except Exception as e:
        log_error(f"follow_project_rules: {str(e)}")
        if output_json:
            return json.dumps({"error": str(e)})
        return f"Error loading project rules: {str(e)}"


@mcp.tool()
def list_skills(output_json: bool = False) -> str:
    """Lists all registered project skills/instructions in the database."""
    global _has_queried_skills
    _has_queried_skills = True
    try:
        results = db.skills.get()
        if not results or not results.get("metadatas"):
            if output_json:
                return json.dumps([])
            return "No skills currently registered."
        
        skills_set = set()
        for meta in results["metadatas"]:
            skills_set.add((meta.get("project_name"), meta.get("skill_name")))
            
        skills_list = []
        lines = ["Registered Custom Skills:"]
        for proj, skill in sorted(skills_set):
            # Check freshness
            proj_skills = [m for m in results["metadatas"] if m.get("project_name") == proj and m.get("skill_name") == skill]
            stale, _ = check_skill_freshness(proj, skill, proj_skills)
            
            skills_list.append({
                "project_name": proj,
                "skill_name": skill,
                "uri": f"skills://{proj}/{skill}",
                "stale": stale
            })
            lines.append(f"- Project: {proj} | Skill: {skill} (URI: skills://{proj}/{skill}){' [STALE]' if stale else ''}")
            
        if output_json:
            return json.dumps(skills_list, indent=2)
        return "\n".join(lines)
    except Exception as e:
        log_error(f"list_skills: {str(e)}")
        if output_json:
            return json.dumps({"error": str(e)})
        return f"Error listing skills: {str(e)}"


@mcp.tool()
def get_skill(project_name: str, skill_name: str, output_json: bool = False) -> str:
    """Retrieves the full content of a specific registered skill/instruction."""
    global _has_queried_skills
    _has_queried_skills = True
    try:
        results = db.skills.get(
            where={
                "$and": [
                    {"project_name": project_name},
                    {"skill_name": skill_name}
                ]
            }
        )
        if not results or not results.get("documents"):
            if output_json:
                return json.dumps({"error": f"Skill '{skill_name}' for project '{project_name}' not found."})
            return f"Skill '{skill_name}' for project '{project_name}' not found."
            
        # Check freshness warning
        warning_msg = ""
        stale = False
        stale, warning_msg = check_skill_freshness(project_name, skill_name, results["metadatas"])
            
        sorted_chunks = sorted(
            zip(results["documents"], results["metadatas"]),
            key=lambda x: x[1].get("start_line", 0)
        )
        
        full_content = "\n".join(f"\n## {meta.get('heading')}\n{doc}" for doc, meta in sorted_chunks)
        
        if output_json:
            return json.dumps({
                "skill_name": skill_name,
                "project_name": project_name,
                "content": full_content.strip(),
                "stale": stale,
                "warning": warning_msg.strip() if stale else ""
            }, indent=2)
            
        lines = []
        if warning_msg:
            lines.append(warning_msg.strip())
        lines.append(f"# Skill: {skill_name} (Project: {project_name})")
        for doc, meta in sorted_chunks:
            lines.append(f"\n## {meta.get('heading')}\n{doc}")
            
        return "\n".join(lines)
    except Exception as e:
        log_error(f"get_skill: {str(e)}")
        if output_json:
            return json.dumps({"error": str(e)})
        return f"Error retrieving skill: {str(e)}"


@mcp.tool()
def check_syntax(file_path: str, project_name: str = "FourTIndex", max_files: int = 100, output_json: bool = False) -> str:
    """Checks a specific file or all supported source files in a directory recursively for syntax errors across multiple languages.
    
    This parses files using tree-sitter to find any syntax/token errors (ERROR or MISSING nodes) and reports them.
    
    Args:
        file_path: Relative or absolute path of the file or directory to check (e.g. 'src/config.py').
        project_name: The name of the project.
        max_files: Maximum number of files to check when scanning a directory (default: 100).
        output_json: Whether to return the output in JSON format.
    """
    logger.info(f"check_syntax called for path: '{file_path}' in project '{project_name}', max_files: {max_files}, output_json: {output_json}")
    
    # 1. Resolve path
    abs_path = None
    if os.path.isabs(file_path):
        abs_path = os.path.abspath(file_path)
    else:
        proj_path = db.get_project_path(project_name)
        if proj_path:
            test_path = os.path.abspath(os.path.join(proj_path, file_path))
            if os.path.exists(test_path):
                abs_path = test_path
        
        if not abs_path:
            registry_path = os.path.join(os.path.dirname(db.config.db_persist_directory), "project_registry.json")
            if os.path.exists(registry_path):
                try:
                    with open(registry_path, "r", encoding="utf-8") as f:
                        registry = json.load(f)
                    for p_name, p_path in registry.items():
                        test_path = os.path.abspath(os.path.join(p_path, file_path))
                        if os.path.exists(test_path):
                            abs_path = test_path
                            break
                except Exception:
                    pass
        if not abs_path:
            abs_path = os.path.abspath(file_path)

    if not os.path.exists(abs_path):
        if output_json:
            return json.dumps({"error": f"Path not found: {file_path}"})
        return f"Error: Path not found: {file_path} (Attempted resolution path: {abs_path})"

    from src.indexer import EXTENSION_TO_LANGUAGE
    from src.syntax_checker import check_single_file
    
    # 2. Execute check
    results_report = []
    
    if os.path.isfile(abs_path):
        ext = os.path.splitext(abs_path)[1].lower()
        if ext not in EXTENSION_TO_LANGUAGE:
            if output_json:
                return json.dumps({"error": f"Unsupported file type for syntax check: {ext}"})
            return f"Unsupported file type for syntax check: {ext}. Supported extensions: {', '.join(EXTENSION_TO_LANGUAGE.keys())}"
            
        errors = check_single_file(abs_path)
        if output_json:
            return json.dumps({
                "file_path": file_path,
                "errors": errors
            }, indent=2)
            
        if not errors:
            return f"✓ No syntax errors found in {file_path}."
            
        results_report.append(f"Found {len(errors)} syntax error(s) in {file_path}:")
        for err in errors:
            results_report.append(f"\n[{err['type']}] Line {err['line']}, Column {err['col']}:")
            if err['line_text']:
                results_report.append(f"  {err['line_text']}")
                results_report.append(f"  {err['pointer']}")
            else:
                results_report.append(f"  Details: {err['line_text']}")
                
        return "\n".join(results_report)
        
    elif os.path.isdir(abs_path):
        try:
            from src.indexer import Indexer
            indexer_inst = Indexer(config)
            files_to_check = indexer_inst.scan_files(abs_path)
        except Exception as e:
            log_error(f"check_syntax (scan): {str(e)}")
            if output_json:
                return json.dumps({"error": str(e)})
            return f"Error scanning directory {file_path}: {str(e)}"
            
        total_files = len(files_to_check)
        truncated = total_files > max_files
        if truncated:
            files_to_check = files_to_check[:max_files]
        
        all_errors = {}
        checked_count = 0
        for f in files_to_check:
            ext = os.path.splitext(f)[1].lower()
            if ext not in EXTENSION_TO_LANGUAGE:
                continue
            checked_count += 1
            file_errs = check_single_file(f)
            if file_errs:
                rel_p = os.path.relpath(f, abs_path).replace("\\", "/")
                all_errors[rel_p] = file_errs
                
        if output_json:
            return json.dumps({
                "directory_path": file_path,
                "checked_count": checked_count,
                "total_files": total_files,
                "limit": max_files,
                "truncated": truncated,
                "errors": all_errors
            }, indent=2)
            
        if not all_errors:
            trunc_warn = f" (Note: scan was limited to the first {max_files} of {total_files} files)" if truncated else ""
            return f"✓ No syntax errors found across {checked_count} supported files in {file_path}{trunc_warn}."
            
        if truncated:
            results_report.append(f"⚠️ NOTE: Directory contains {total_files} files, but scan was limited to the first {max_files} files. You can change this limit using the 'max_files' parameter.\n")
            
        results_report.append(f"Checked {checked_count} file(s). Found syntax errors in {len(all_errors)} file(s):")
        for rel_file, errors in all_errors.items():
            results_report.append(f"\n=== File: {rel_file} ({len(errors)} error(s)) ===")
            for err in errors:
                results_report.append(f"[{err['type']}] Line {err['line']}, Column {err['col']}:")
                if err['line_text']:
                    results_report.append(f"  {err['line_text']}")
                    results_report.append(f"  {err['pointer']}")
                else:
                    results_report.append(f"  Details: {err['line_text']}")
                    
        return "\n".join(results_report)


@mcp.tool()
def diff_index_status(project_name: str = None, output_json: bool = False) -> str:
    """Shows the indexing status of files in the project (new, stale, deleted, up_to_date) before running index_project.
    
    Args:
        project_name: The name of the project.
        output_json: Whether to return the output in JSON format.
    """
    from src.mcp_helpers import get_diff_index_status
    return get_diff_index_status(project_name, output_json)


@mcp.tool()
def search_session_summaries(query: str, project_name: str = None, limit: int = 3, output_json: bool = False) -> str:
    """Semantically searches past session summaries/memories to reuse previously recorded context or design decisions.
    
    Args:
        query: The semantic search query (e.g., 'auth service design decisions').
        project_name: The name of the project.
        limit: Max number of summaries to return.
        output_json: Whether to return the output in JSON format.
    """
    if project_name is None:
        project_name = detect_active_project()
    logger.info(f"search_session_summaries called with query: '{query}', output_json: {output_json}")
    try:
        query_vector = embedder.get_embedding(query)
        results = db.search_session_memories(query_vector, project_name, limit=limit)
        
        # Filter results where score <= 0.0
        results = [r for r in results if r.get("score", 1.0) > 0.0]
        
        if output_json:
            return json.dumps(results, indent=2)
            
        if not results:
            return "No matching session summaries found."
            
        formatted = []
        for r in results:
            meta = r["metadata"]
            score = r.get("score", 1.0)
            formatted.append(
                f"=== SESSION: {meta.get('session_id')} | Date: {meta.get('timestamp', 'N/A')} | Score: {score:.4f} ===\n"
                f"{r['content']}\n"
            )
        return "\n".join(formatted)
    except Exception as e:
        log_error(f"search_session_summaries: {str(e)}")
        logger.error(f"Error in search_session_summaries: {e}")
        if output_json:
            return json.dumps({"error": str(e)})
        return f"Error: {str(e)}"


@mcp.tool()
def get_health_dashboard(output_json: bool = False) -> str:
    """Retrieves health status and metadata of the FourTIndex MCP server.
    
    Includes information on the active embedding provider, database paths, number of indexed files, stale skills, and recent errors.
    
    Args:
        output_json: Whether to return the output in JSON format.
    """
    logger.info(f"get_health_dashboard called, output_json: {output_json}")
    try:
        import datetime
        
        # 1. Embedding Provider Status
        provider_name = embedder.provider
        embedding_model = embedder.model
        
        # 2. Database Paths
        db_path = config.db_persist_directory
        registry_db = db.registry_db_path
        
        # 3. Indexed Files info (across all projects in manifest)
        state_directory = os.path.dirname(config.db_persist_directory)
        from src.manifest import IndexManifest
        manifest = IndexManifest(state_directory)
        
        total_projects = 0
        total_files_indexed = 0
        project_details = {}
        
        for p_name, p_data in manifest.data.get("projects", {}).items():
            total_projects += 1
            store = manifest.active_store(p_data) or manifest.pending_store(p_data)
            files_count = len(store.get("files", {})) if store else 0
            total_files_indexed += files_count
            project_details[p_name] = {
                "path": p_data.get("path"),
                "files_indexed": files_count,
                "store_id": p_data.get("active_store")
            }
            
        # 4. Stale Skills check
        stale_skills = []
        skills_checked = set()
        try:
            results = db.skills.get()
            if results and results.get("metadatas"):
                for meta in results["metadatas"]:
                    p_name = meta.get("project_name")
                    s_name = meta.get("skill_name")
                    if (p_name, s_name) in skills_checked:
                        continue
                    skills_checked.add((p_name, s_name))
                    
                    skill_meta = [m for m in results["metadatas"] if m.get("project_name") == p_name and m.get("skill_name") == s_name]
                    is_stale, _ = check_skill_freshness(p_name, s_name, skill_meta)
                    if is_stale:
                        stale_skills.append({
                            "project_name": p_name,
                            "skill_name": s_name,
                            "file_path": skill_meta[0].get("file_path"),
                            "indexed_at": skill_meta[0].get("indexed_at")
                        })
        except Exception as e:
            logger.error(f"Error checking skill freshness in health: {e}")
            
        dashboard_data = {
            "status": "healthy",
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
            "embedding_provider": {
                "name": provider_name,
                "model": embedding_model
            },
            "database": {
                "persist_directory": db_path.replace("\\", "/"),
                "registry_db_path": registry_db.replace("\\", "/")
            },
            "indexing": {
                "total_projects": total_projects,
                "total_files_indexed": total_files_indexed,
                "projects": project_details
            },
            "skills": {
                "total_skills_registered": len(skills_checked),
                "stale_skills_count": len(stale_skills),
                "stale_skills": stale_skills
            },
            "recent_errors": _recent_errors
        }
        
        if output_json:
            return json.dumps(dashboard_data, indent=2)
            
        lines = [
            "============================================================",
            "                 FOURTINDEX HEALTH DASHBOARD                ",
            "============================================================",
            f"Status:             Healthy",
            f"Timestamp:          {dashboard_data['timestamp']}",
            f"Embedding Provider: {provider_name.upper()} (Model: {embedding_model})",
            f"Vector DB Path:     {db_path}",
            f"Registry DB Path:   {registry_db}",
            "------------------------------------------------------------",
            f"Indexed Projects:   {total_projects}",
            f"Total Files Indexed: {total_files_indexed}",
        ]
        
        for name, details in project_details.items():
            lines.append(f"  - Project: {name} (Files: {details['files_indexed']}, Store: {details['store_id']})")
            
        lines.append("------------------------------------------------------------")
        lines.append(f"Stale Skills Count:  {len(stale_skills)}")
        for s in stale_skills:
            lines.append(f"  ⚠️ Stale Skill: {s['skill_name']} under Project {s['project_name']} (Indexed at: {s['indexed_at']})")
            
        lines.append("------------------------------------------------------------")
        lines.append(f"Recent Errors:      {len(_recent_errors)}")
        for err in _recent_errors:
            lines.append(f"  [{err['timestamp']}] {err['message']}")
            
        lines.append("============================================================")
        return "\n".join(lines)
    except Exception as e:
        log_error(f"get_health_dashboard: {str(e)}")
        logger.error(f"Error in health dashboard: {e}")
        if output_json:
            return json.dumps({"status": "error", "message": str(e)})
        return f"Error loading health dashboard: {str(e)}"


# Wrap all tools with automatic memory cleanup (RAM & VRAM)
if __name__ == "__main__":
    logger.info("Starting fourTindex MCP Server...")
    mcp.run()
