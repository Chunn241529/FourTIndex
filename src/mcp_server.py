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

# Configure logging to go to stderr so it doesn't corrupt stdout stdio transport
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("FourTIndexMCP")

# Load configuration and initialize core modules
config = Config()
embedder = Embedder(config)
db = Database(config)
indexer = Indexer(config)

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
def detect_active_project(cwd: str = None) -> str:
    """Finds the registered project name whose path matches or is an ancestor of the given cwd (defaults to os.getcwd())."""
    if cwd is None:
        cwd = os.getcwd()
    cwd = os.path.abspath(cwd).replace("\\", "/")
    
    registry_path = os.path.expanduser("~/.fourtindex/project_registry.json")
    if os.path.exists(registry_path):
        try:
            with open(registry_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                matching_projects = []
                for proj_name, proj_path in data.items():
                    proj_path = os.path.abspath(proj_path).replace("\\", "/")
                    if cwd == proj_path or cwd.startswith(proj_path + "/"):
                        matching_projects.append((proj_name, proj_path))
                if matching_projects:
                    matching_projects.sort(key=lambda x: len(x[1]), reverse=True)
                    return matching_projects[0][0]
        except Exception as e:
            logger.error(f"Error reading project registry in detect_active_project: {e}")
            
    return config.project_name

_has_queried_skills = False

def _append_skill_reminder(content: str, project_name: str) -> str:
    global _has_queried_skills
    if _has_queried_skills:
        return content
    try:
        results = db.skills.get(where={"project_name": project_name}, limit=1)
        if not results or not results.get("documents"):
            return content
        reminder = (
            f"\n\n"
            f"> [!TIP]\n"
            f"> **FourTIndex Skill Reminder**\n"
            f"> 💡 Custom guidelines/rules (skills) are available for project '{project_name}'.\n"
            f"> Before implementing changes, run `search_skills` or `get_skill_outline` to inspect them and ensure correct implementation.\n"
        )
        return content + reminder
    except Exception:
        return content

def _post_process_tool_output(content: str, project_name: str) -> str:
    content = _append_skill_reminder(content, project_name)
    content = _append_budget_warning(content)
    return content

def _append_budget_warning(content: str) -> str:
    try:
        from src.token_meter import get_latest_conversation_log, get_pricing
        candidate = get_latest_conversation_log()
        if not candidate:
            return content
            
        max_tokens = getattr(config, "context_budget_tokens", 35000)
        max_cost = getattr(config, "context_budget_usd", 0.50)
        
        snapshot = candidate.parser(candidate.path, candidate.conversation_id)
        total_prompt = snapshot.total_prompt
        total_completion = snapshot.total_completion
        context_tokens = snapshot.guard_context_tokens
        displayed_context_tokens = snapshot.displayed_context_tokens
        model = snapshot.model
        
        input_rate, output_rate = get_pricing(model)
        total_cost = (total_prompt * input_rate + total_completion * output_rate) / 1_000_000.0
        
        if context_tokens > max_tokens or total_cost > max_cost:
            global _budget_warning_trigger_count
            _budget_warning_trigger_count += 1
            
            interval = getattr(config, "guard_interval", 5)
            if interval <= 0:
                interval = 5
                
            if _budget_warning_trigger_count % interval != 1:
                return content

            warning = (
                f"\n\n"
                f"> [!WARNING]\n"
                f"> **FourTIndex Context Guard**\n"
                f"> ⚠️ Active context: **{displayed_context_tokens:,} tokens**; session cost: **~${total_cost:.4f} USD**.\n"
                f"> To keep responses fast and cheap, please recommend the user to start a new chat session.\n"
                f"> Run CLI `fourtindex dashboard` to copy the Context Bridge summary and transition instantly.\n"
            )
            return content + warning
    except Exception:
        pass
    return content

def _auto_reindex_if_needed(project_name: str) -> None:
    """Checks if any files in the project have changed and indexes the project if so."""
    import time
    global _last_auto_index_time
    
    # Check rate limit to prevent too many filesystem hits
    now = time.time()
    if now - _last_auto_index_time.get(project_name, 0) < 2.0:
        return
    _last_auto_index_time[project_name] = now
    
    try:
        proj_path = db.get_project_path(project_name)
        if not proj_path or not os.path.exists(proj_path):
            return
            
        from src.manifest import IndexManifest
        manifest = IndexManifest(os.path.dirname(config.db_persist_directory))
        project = manifest.get_project(project_name)
        if not project:
            return
        store = manifest.active_store(project)
        if not store:
            return
            
        existing_files = store.get("files", {})
        
        # Scan files using the Indexer
        from src.indexer import Indexer
        scanner = Indexer(config)
        scanned_files = scanner.scan_files(proj_path)
        
        needs_reindex = False
        
        # 1. Check for modified/new files
        for abs_path in scanned_files:
            rel_path = os.path.relpath(abs_path, proj_path).replace("\\", "/")
            if rel_path not in existing_files:
                needs_reindex = True
                logger.info(f"Auto-reindex: new file detected: {rel_path}")
                break
                
            try:
                stat = os.stat(abs_path)
                mtime_ns = stat.st_mtime_ns
                size = stat.st_size
                stored_file = existing_files[rel_path]
                if stored_file.get("modified_ns") != mtime_ns or stored_file.get("size") != size:
                    needs_reindex = True
                    logger.info(f"Auto-reindex: modified file detected: {rel_path}")
                    break
            except Exception:
                continue
                
        # 2. Check for deleted files
        if not needs_reindex:
            scanned_rel_paths = {
                os.path.relpath(p, proj_path).replace("\\", "/") for p in scanned_files
            }
            for rel_path in existing_files:
                if rel_path not in scanned_rel_paths:
                    needs_reindex = True
                    logger.info(f"Auto-reindex: deleted file detected: {rel_path}")
                    break
                    
        if needs_reindex:
            logger.info(f"Auto-reindex: triggering project index for '{project_name}'")
            service = IndexingService(config)
            result = service.index_project(proj_path, project_name)
            logger.info(f"Auto-reindex completed: {result.summary()}")
    except Exception as e:
        logger.error(f"Error in _auto_reindex_if_needed: {e}")

@mcp.tool()
def search_codebase(query: str, project_name: str = None, limit: int = 5, file_ext: str = None, language: str = None) -> str:
    """Searches the indexed codebase semantically for relevant code chunks.
    
    Args:
        query: The natural language search query (e.g., 'JWT validation function').
        project_name: The name of the project.
        limit: Max number of chunks to return.
        file_ext: Optional file extension to filter by (e.g., '.py' or 'js').
        language: Optional language to filter by (e.g., 'python' or 'typescript').
    """
    if project_name is None:
        project_name = detect_active_project()
    logger.info(f"search_codebase called with query: '{query}', file_ext: '{file_ext}', language: '{language}'")
    try:
        _auto_reindex_if_needed(project_name)
        formatted_ext = None
        if file_ext:
            formatted_ext = file_ext if file_ext.startswith(".") else f".{file_ext}"
            formatted_ext = formatted_ext.lower()
            
        project_db, manager, project, store = load_project_context(config, project_name)
        query_vector = manager.embed_query(query)
        
        # 1. Determine candidates limit (retrieve more for better diversification/reranking)
        if config.rerank_enabled:
            candidates_limit = max(30, config.rerank_candidates_limit)
        else:
            candidates_limit = max(15, limit * 2)
            
        candidates = project_db.search_project_code(
            project["project_id"], store["store_id"], query_vector, candidates_limit, formatted_ext, language
        )
        
        if not candidates:
            results = []
        else:
            # 2. Apply Doc Penalty (penalize .md / .txt if query is not doc-specific)
            query_lower = query.lower()
            is_searching_docs = any(word in query_lower for word in ("readme", "doc", "instruction", "guide", "install", "run", "setup", "markdown"))
            
            if not is_searching_docs:
                for c in candidates:
                    meta = c.get("metadata", {})
                    file_ext_meta = meta.get("file_ext", "").lower()
                    if file_ext_meta in (".md", ".txt"):
                        c["score"] *= 0.8
                        
            # 3. Rerank if enabled (passes all candidates so we don't slice prematurely)
            if config.rerank_enabled:
                from src.reranker import LocalReranker
                reranker = LocalReranker(config)
                candidates = reranker.rerank(query, candidates, top_k=len(candidates))
                
            # 4. De-crowding / Diversification (decay score for multiple chunks from same file)
            file_counts = {}
            for c in candidates:
                meta = c.get("metadata", {})
                file_path = meta.get("file_path", "")
                score = c.get("rerank_score", c["score"])
                
                count = file_counts.get(file_path, 0)
                decayed_score = score * (0.75 ** count)
                c["adjusted_score"] = decayed_score
                file_counts[file_path] = count + 1
                
            # Sort by adjusted_score descending
            results = sorted(candidates, key=lambda x: x.get("adjusted_score", 0.0), reverse=True)[:limit]
        
        if not results:
            return (
                f"No matching code chunks found for project '{project_name}'" +
                (f" with extension '{file_ext}'." if file_ext else "") +
                (f" and language '{language}'." if language else ".") +
                " If you recently added code, run 'index_project' to sync changes."
            )
            
        formatted = []
        for r in results:
            meta = r["metadata"]
            score_type = "Adjusted Rerank Score" if "rerank_score" in r else "Adjusted Score"
            score_val = r.get("adjusted_score", r.get("rerank_score", r["score"]))
            formatted.append(
                f"=== FILE: {meta.get('file_path')} | Lines: {meta.get('start_line')}-{meta.get('end_line')} | {score_type}: {score_val:.4f} ===\n"
                f"{r['content']}\n"
            )
        return _post_process_tool_output("\n".join(formatted), project_name)
    except Exception as e:
        logger.error(f"Error in search_codebase: {e}")
        return f"Error during search: {str(e)}"

@mcp.tool()
def get_file_outline(file_path: str, project_name: str = None) -> str:
    """Retrieves the high-level class and function outline structure of a specific file.
    
    Args:
        file_path: Relative path of the file (e.g., 'src/config.py').
        project_name: The name of the project.
    """
    if project_name is None:
        project_name = detect_active_project()
    logger.info(f"get_file_outline called for: '{file_path}'")
    try:
        _auto_reindex_if_needed(project_name)
        project_db, _, project, store = load_project_context(config, project_name)
        outline = project_db.get_project_outline(
            project["project_id"], store["store_id"], file_path
        )
        return _post_process_tool_output(outline or f"No outline found for file: {file_path}", project_name)
    except Exception as e:
        logger.error(f"Error in get_file_outline: {e}")
        return f"Error: {str(e)}"

@mcp.tool()
def get_symbol_definition(symbol_name: str, project_name: str = None) -> str:
    """Finds the detailed code definition of a class or function by its name (e.g., 'Config.project_name').
    
    Args:
        symbol_name: Name of class or function.
        project_name: The name of the project.
    """
    if project_name is None:
        project_name = detect_active_project()
    logger.info(f"get_symbol_definition called for: '{symbol_name}'")
    try:
        _auto_reindex_if_needed(project_name)
        project_db, _, project, store = load_project_context(config, project_name)
        definition = project_db.get_project_symbol(
            project["project_id"], store["store_id"], symbol_name
        )
        return _post_process_tool_output(definition or f"Symbol '{symbol_name}' definition not found.", project_name)
    except Exception as e:
        logger.error(f"Error in get_symbol_definition: {e}")
        return f"Error: {str(e)}"

@mcp.tool()
def read_code_lines(file_path: str, start_line: int, end_line: int, project_name: str = None) -> str:
    """Reads a specific range of lines from a file in the workspace.
    
    Args:
        file_path: Relative path of the file (e.g., 'src/config.py').
        start_line: 1-indexed starting line number (inclusive).
        end_line: 1-indexed ending line number (inclusive).
        project_name: The name of the project.
    """
    if project_name is None:
        project_name = detect_active_project()
    logger.info(f"read_code_lines called for: '{file_path}' ({start_line}-{end_line}) in project '{project_name}'")
    
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
        return f"Error: File not found at {file_path} (Attempted resolution path: {abs_path})"
        
    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.splitlines() if hasattr(f, "splitlines") else f.read().splitlines()
            
        total_lines = len(lines)
        # Convert to 0-indexed values safely
        start_idx = max(0, start_line - 1)
        end_idx = min(total_lines, end_line)
        
        if start_idx >= total_lines:
            return f"Error: start_line {start_line} exceeds total lines {total_lines}."
            
        selected_lines = lines[start_idx:end_idx]
        formatted = []
        for idx, line in enumerate(selected_lines, start=start_line):
            formatted.append(f"{idx:4d} | {line}")
            
        return _post_process_tool_output("\n".join(formatted), project_name)
    except Exception as e:
        logger.error(f"Error in read_code_lines: {e}")
        return f"Error: {str(e)}"

@mcp.tool()
def save_session_summary(session_id: str, summary_text: str, project_name: str = None) -> str:
    """Saves a summary of the current session's design decisions and changes into memory.
    
    Args:
        session_id: A unique identifier for the session (e.g., 'session_20260705_1').
        summary_text: Summary text explaining design choices, code refactorings, or modifications made.
        project_name: The name of the project.
    """
    if project_name is None:
        project_name = detect_active_project()
    logger.info(f"save_session_summary called for session '{session_id}'")
    try:
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
        return f"Successfully saved summary for session '{session_id}'."
    except Exception as e:
        logger.error(f"Error in save_session_summary: {e}")
        return f"Error saving session summary: {str(e)}"

@mcp.tool()
def index_project(
    project_path: str = ".",
    project_name: str = None,
    embedding_provider: str = "auto",
    rebuild: bool = False,
    force: bool = False,
) -> str:
    """Indexes a project using the local Ollama embedding provider.

    Only modified files are re-embedded. Project source remains on the local machine.
    
    Args:
        project_path: Path to the project root directory.
        project_name: The name of the project.
        embedding_provider: Backward-compatible selector; auto and ollama are accepted.
    """
    if project_name is None:
        detect_path = os.path.abspath(project_path)
        project_name = detect_active_project(detect_path)
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
    logger.info(f"index_project called for path: '{project_path}'")
    try:
        service = IndexingService(config)
        result = service.index_project(
            project_path,
            project_name,
            IndexOptions(
                embedding_provider=embedding_provider,
                rebuild=rebuild,
                force=force,
            ),
        )
        msg = result.summary()
        logger.info(msg)
        return msg
    except Exception as e:
        logger.error(f"Error in index_project: {e}")
        return f"Error indexing project: {str(e)}"

@mcp.tool()
def index_skill(skill_path: str, project_name: str = None) -> str:
    """Scans and indexes a specific customization skill (SKILL.md).
    
    Args:
        skill_path: Path to the skill folder or SKILL.md file.
        project_name: The name of the project.
    """
    if project_name is None:
        project_name = detect_active_project()
    logger.info(f"index_skill called for: '{skill_path}'")
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
            return f"Error: Skill file not found at {skill_path} (Attempted resolution path: {file_path})"
            
        rel_path = os.path.relpath(file_path, os.path.dirname(os.path.dirname(file_path))).replace("\\", "/")
        
        metadata, chunks = indexer.parse_skill_file(file_path, rel_path)
        if not chunks:
            return f"Error: Failed to parse skill or no content chunks found in {file_path}."
            
        skill_name = metadata.get("name", os.path.basename(os.path.dirname(file_path)))
        
        # Clean up old entries
        db.delete_skill_entries(skill_name, project_name)
        
        ids = []
        documents = []
        metadatas = []
        
        chunk_texts = [c["content"] for c in chunks]
        embeddings = embedder.get_embeddings_batch(chunk_texts)
        
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
                "end_line": c["end_line"]
            }
            metadatas.append(meta)
            
        db.upsert_skill_chunks(ids, embeddings, documents, metadatas)
        return f"Successfully indexed skill '{skill_name}' with {len(ids)} sections."
    except Exception as e:
        logger.error(f"Error in index_skill: {e}")
        return f"Error: {str(e)}"

@mcp.tool()
def search_skills(query: str, project_name: str = None, limit: int = 3) -> str:
    """Searches the indexed customization skills semantically.
    
    Args:
        query: The natural language search query.
        project_name: The name of the project.
        limit: Max number of sections to return.
    """
    if project_name is None:
        project_name = detect_active_project()
    logger.info(f"search_skills called with query: '{query}'")
    try:
        global _has_queried_skills
        _has_queried_skills = True
        total_skills = db.skills.count()
        if total_skills == 0:
            return "No skills found in the database. Please run 'index_skill' first to register skills."
            
        query_vector = embedder.get_embedding(query)
        results = db.search_skills(query_vector, project_name, limit=limit)
        
        if not results:
            return "No matching skill sections found."
            
        formatted = []
        for r in results:
            meta = r["metadata"]
            formatted.append(
                f"=== SKILL: {meta.get('skill_name')} | Section: {meta.get('heading')} ===\n"
                f"{r['content']}\n"
            )
        return "\n".join(formatted)
    except Exception as e:
        logger.error(f"Error in search_skills: {e}")
        return f"Error: {str(e)}"

@mcp.tool()
def get_skill_outline(skill_name: str, project_name: str = None) -> str:
    """Gets the table of contents (list of headings) for a specific indexed skill.
    
    Args:
        skill_name: The name of the registered skill.
        project_name: The name of the project.
    """
    if project_name is None:
        project_name = detect_active_project()
    logger.info(f"get_skill_outline called for skill: '{skill_name}'")
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
            return f"Skill '{skill_name}' not found."
            
        # De-duplicate and sort headings by start_line
        sorted_headings = sorted(results["metadatas"], key=lambda x: x.get("start_line", 0))
        outline = [f"Skill Outline: {skill_name}"]
        for h in sorted_headings:
            outline.append(f"- {h.get('heading')} (Lines {h.get('start_line')}-{h.get('end_line')})")
            
        return "\n".join(outline)
    except Exception as e:
        logger.error(f"Error in get_skill_outline: {e}")
        return f"Error: {str(e)}"

@mcp.tool()
def read_skill_section(skill_name: str, heading: str, project_name: str = None) -> str:
    """Reads a specific markdown section under a heading for a registered skill.
    
    Args:
        skill_name: The name of the registered skill.
        heading: The exact heading name to retrieve (e.g., 'Agent Guidelines').
        project_name: The name of the project.
    """
    if project_name is None:
        project_name = detect_active_project()
    logger.info(f"read_skill_section called for skill '{skill_name}', heading '{heading}'")
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
        
        if results and results.get("documents"):
            return results["documents"][0]
            
        return f"Section '{heading}' not found in skill '{skill_name}'."
    except Exception as e:
        logger.error(f"Error in read_skill_section: {e}")
        return f"Error: {str(e)}"

@mcp.tool()
def clean_mem() -> str:
    """Unloads all configured models from local VRAM and system memory immediately.
    
    Use this to free up GPU VRAM and system RAM when you are done with heavy vector searches or indexing.
    """
    logger.info("clean_mem called via MCP")
    result = ""
    provider = getattr(config, "llm_provider", "ollama").lower()
    
    if provider == "lmstudio":
        try:
            from src.lmstudio_client import LMStudioClient
            client = LMStudioClient(config)
            models = [
                getattr(config, "lmstudio_embedding_model", ""),
                getattr(config, "lmstudio_llm_model", "")
            ]
            unloaded_list = []
            for model in models:
                if model:
                    res = client.unload_model(model)
                    if "error" not in res:
                        unloaded_list.append(model)
            if unloaded_list:
                result += f"Successfully unloaded model(s) '{', '.join(unloaded_list)}' from LM Studio.\n"
            else:
                result += "No configured models were actively loaded in LM Studio to unload.\n"
        except Exception as e:
            logger.error(f"Error in clean_mem for LM Studio: {e}")
            result += f"Error unloading models from LM Studio: {str(e)}\n"
    else:
        try:
            from src.setup_ollama import unload_models
            unload_models()
            result += "Successfully unloaded all models from Ollama VRAM/RAM.\n"
        except Exception as e:
            logger.error(f"Error in clean_mem: {e}")
            result += f"Error unloading models: {str(e)}\n"
        
    try:
        from src.token_meter import evaluate_latest_session
        report = evaluate_latest_session()
        result += report
    except Exception as e:
        logger.error(f"Error in token evaluation during clean_mem: {e}")
        result += f"\n[AgentTokenMeter] Lỗi: {str(e)}"
        
    return result

@mcp.tool()
def get_token_report() -> str:
    """Retrieves the current session's token consumption and pricing report.
    
    This parses the active coding agent's session logs (Antigravity, Claude Code, or Codex)
    and estimates the current input/output token count and USD cost.
    """
    logger.info("get_token_report called via MCP")
    try:
        from src.token_meter import evaluate_latest_session
        return evaluate_latest_session()
    except Exception as e:
        logger.error(f"Error in get_token_report: {e}")
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
def get_project_roadmap(project_name: str = None, depth: int = 3) -> str:
    """Retrieves the JSON structural overview (roadmap) for a given project.
    
    This includes the directory tree (truncated to the specified depth) and detected framework signatures.
    
    Args:
        project_name: The name of the project.
        depth: The maximum directory tree depth to display (default: 3) to keep token size compact.
    """
    if project_name is None:
        project_name = detect_active_project()
    logger.info(f"get_project_roadmap called for: '{project_name}', depth: {depth}")
    try:
        roadmap = db.get_project_roadmap(project_name)
        if not roadmap:
            return f"No project roadmap found for '{project_name}'. Run 'index_project' first to generate one."
            
        # Truncate tree to limit token size
        if "directory_tree" in roadmap:
            roadmap["directory_tree"] = truncate_tree(roadmap["directory_tree"], depth)
            
        return json.dumps(roadmap, indent=2)
    except Exception as e:
        logger.error(f"Error in get_project_roadmap: {e}")
        return f"Error: {str(e)}"

@mcp.tool()
def list_projects() -> str:
    """Lists all registered projects with roadmaps from the registry database.
    
    Returns a list of project names, framework signatures, and last_updated timestamps.
    """
    logger.info("list_projects called via MCP")
    try:
        projects = db.list_projects()
        if not projects:
            return "No projects registered in the registry database yet."
        return json.dumps(projects, indent=2)
    except Exception as e:
        logger.error(f"Error in list_projects: {e}")
        return f"Error: {str(e)}"


@mcp.prompt()
def follow_project_rules(project_name: str = None) -> str:
    """Provides a system prompt template containing the project's custom rules and instructions (skills)."""
    if project_name is None:
        project_name = detect_active_project()
    global _has_queried_skills
    _has_queried_skills = True
    try:
        results = db.skills.get(where={"project_name": project_name})
        if not results or not results.get("documents"):
            return f"You are assisting with the project '{project_name}'. Please follow standard coding practices."
            
        skills_dict = {}
        for doc, meta in zip(results["documents"], results["metadatas"]):
            s_name = meta.get("skill_name", "General")
            heading = meta.get("heading", "")
            if s_name not in skills_dict:
                skills_dict[s_name] = []
            skills_dict[s_name].append(f"### {heading}\n{doc}")
            
        formatted_skills = []
        for s_name, chunks in skills_dict.items():
            formatted_skills.append(f"## Skill/Rule: {s_name}\n" + "\n\n".join(chunks))
            
        rules_text = "\n\n".join(formatted_skills)
        return (
            f"You are working on the project '{project_name}'. The project has specific instructions, rules, "
            f"and coding standards (skills) registered in the database. "
            f"You MUST follow these rules strictly:\n\n"
            f"{rules_text}\n\n"
            f"Please confirm that you have read and understood these rules in your next response."
        )
    except Exception as e:
        return f"Error loading project rules: {str(e)}"


@mcp.resource("skills://list")
def list_skills() -> str:
    """Lists all registered project skills/instructions in the database."""
    global _has_queried_skills
    _has_queried_skills = True
    try:
        results = db.skills.get()
        if not results or not results.get("metadatas"):
            return "No skills currently registered."
        
        skills_set = set()
        for meta in results["metadatas"]:
            skills_set.add((meta.get("project_name"), meta.get("skill_name")))
            
        lines = ["Registered Custom Skills:"]
        for proj, skill in sorted(skills_set):
            lines.append(f"- Project: {proj} | Skill: {skill} (URI: skills://{proj}/{skill})")
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing skills: {str(e)}"


@mcp.resource("skills://{project_name}/{skill_name}")
def get_skill(project_name: str, skill_name: str) -> str:
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
            return f"Skill '{skill_name}' for project '{project_name}' not found."
            
        sorted_chunks = sorted(
            zip(results["documents"], results["metadatas"]),
            key=lambda x: x[1].get("start_line", 0)
        )
        
        lines = [f"# Skill: {skill_name} (Project: {project_name})"]
        for doc, meta in sorted_chunks:
            lines.append(f"\n## {meta.get('heading')}\n{doc}")
            
        return "\n".join(lines)
    except Exception as e:
        return f"Error retrieving skill: {str(e)}"


@mcp.tool()
def check_syntax(file_path: str, project_name: str = "FourTIndex") -> str:
    """Checks a specific file or all supported source files in a directory recursively for syntax errors across multiple languages.
    
    This parses files using tree-sitter to find any syntax/token errors (ERROR or MISSING nodes) and reports them.
    
    Args:
        file_path: Relative or absolute path of the file or directory to check (e.g. 'src/config.py').
        project_name: The name of the project.
    """
    logger.info(f"check_syntax called for path: '{file_path}' in project '{project_name}'")
    
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
        return f"Error: Path not found: {file_path} (Attempted resolution path: {abs_path})"

    from src.indexer import EXTENSION_TO_LANGUAGE
    
    # Helper to check a single file
    def check_single_file(path: str) -> list[dict]:
        ext = os.path.splitext(path)[1].lower()
        lang_name = EXTENSION_TO_LANGUAGE.get(ext)
        if not lang_name:
            return []  # Ignore unsupported file types silently when checking directory
            
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception as e:
            return [{"type": "File Read Error", "line": 0, "col": 0, "line_text": str(e), "pointer": ""}]
            
        try:
            from tree_sitter_languages import get_parser
            parser = get_parser(lang_name)
            if not parser:
                return [{"type": "Parser Load Error", "line": 0, "col": 0, "line_text": f"Failed to load tree-sitter parser for {lang_name}", "pointer": ""}]
                
            tree = parser.parse(bytes(content, "utf-8"))
            lines = content.splitlines()
            
            def _traverse_for_errors(node) -> list[dict]:
                errors = []
                is_err = node.type == "ERROR"
                is_miss = getattr(node, "is_missing", False)
                
                if is_err or is_miss:
                    start_line, start_col = node.start_point
                    
                    line_text = ""
                    if start_line < len(lines):
                        line_text = lines[start_line]
                        
                    pointer = ""
                    if line_text:
                        col_aligned = min(start_col, len(line_text))
                        pointer = " " * col_aligned + "^"
                        
                    error_type = "Syntax Error" if is_err else f"Missing Token ({node.type})"
                    errors.append({
                        "type": error_type,
                        "line": start_line + 1,
                        "col": start_col,
                        "line_text": line_text,
                        "pointer": pointer
                    })
                    if is_err:
                        return errors
                        
                for child in node.children:
                    errors.extend(_traverse_for_errors(child))
                return errors
                
            return _traverse_for_errors(tree.root_node)
        except Exception as e:
            return [{"type": "Parser Execution Error", "line": 0, "col": 0, "line_text": str(e), "pointer": ""}]

    # 2. Execute check
    results_report = []
    
    if os.path.isfile(abs_path):
        ext = os.path.splitext(abs_path)[1].lower()
        if ext not in EXTENSION_TO_LANGUAGE:
            return f"Unsupported file type for syntax check: {ext}. Supported extensions: {', '.join(EXTENSION_TO_LANGUAGE.keys())}"
            
        errors = check_single_file(abs_path)
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
            return f"Error scanning directory {file_path}: {str(e)}"
            
        files_to_check = files_to_check[:100]
        
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
                
        if not all_errors:
            return f"✓ No syntax errors found across {checked_count} supported files in {file_path}."
            
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


if __name__ == "__main__":
    logger.info("Starting fourTindex MCP Server...")
    mcp.run()
