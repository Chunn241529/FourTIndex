import os
import sys
import json
import logging
import time
import datetime

logger = logging.getLogger("FourTIndexMCP")


def log_error(err_msg: str):
    """Log an error message with a timestamp to recent errors list."""
    from src import mcp_server
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    mcp_server._recent_errors.append({"timestamp": now_str, "message": err_msg})
    if len(mcp_server._recent_errors) > 10:
        mcp_server._recent_errors.pop(0)


def detect_active_project(cwd: str = None) -> str:
    """Resolves the active project and fails closed when identity is unknown."""
    from src import mcp_server
    return mcp_server.project_resolver.resolve(cwd or os.getcwd()).project_name


def check_skill_freshness(project_name: str, skill_name: str, metadatas: list[dict]) -> tuple[bool, str]:
    """Checks if the skill file has changed compared to its source_hash metadata.
    
    Returns (stale, warning_message).
    """
    if not metadatas:
        return False, ""
    meta = metadatas[0]
    file_path = meta.get("file_path")
    expected_hash = meta.get("source_hash")
    indexed_at = meta.get("indexed_at", "unknown")
    
    if not file_path:
        return False, ""
        
    from src import mcp_server
    db = mcp_server.db
    indexer = mcp_server.indexer

    resolved_path = None
    proj_path = db.get_project_path(project_name)
    if proj_path:
        test_path = os.path.abspath(os.path.join(proj_path, file_path))
        if os.path.exists(test_path):
            resolved_path = test_path
            
    if not resolved_path:
        registry_path = os.path.expanduser("~/.fourtindex/project_registry.json")
        if os.path.exists(registry_path):
            try:
                with open(registry_path, "r", encoding="utf-8") as f:
                    registry = json.load(f)
                for p_name, p_path in registry.items():
                    test_path = os.path.abspath(os.path.join(p_path, file_path))
                    if os.path.exists(test_path):
                        resolved_path = test_path
                        break
            except Exception:
                pass
                
    if not resolved_path:
        if os.path.exists(file_path):
            resolved_path = os.path.abspath(file_path)
            
    if not resolved_path:
        return True, f"⚠️ WARNING: Skill '{skill_name}' source file not found. It might have been deleted. (Indexed at: {indexed_at})\n"
        
    current_hash = indexer.compute_file_hash(resolved_path)
    if not current_hash:
        return True, f"⚠️ WARNING: Failed to read skill file '{resolved_path}'. (Indexed at: {indexed_at})\n"
        
    if current_hash != expected_hash:
        return True, f"⚠️ WARNING: Skill '{skill_name}' index is stale. The source file '{resolved_path}' has changed. Please run 'index_skill' to re-index. (Indexed at: {indexed_at})\n"
        
    return False, ""


def _append_skill_reminder(content: str, project_name: str) -> str:
    from src import mcp_server
    if mcp_server._has_queried_skills:
        return content
    try:
        results = mcp_server.db.skills.get(where={"project_name": project_name}, limit=1)
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


def _append_budget_warning(content: str) -> str:
    from src import mcp_server
    try:
        from src.token_meter import get_latest_conversation_log, get_pricing
        candidate = get_latest_conversation_log()
        if not candidate:
            return content
            
        max_tokens = getattr(mcp_server.config, "context_budget_tokens", 35000)
        max_cost = getattr(mcp_server.config, "context_budget_usd", 0.50)
        
        snapshot = candidate.parser(candidate.path, candidate.conversation_id)
        total_prompt = snapshot.total_prompt
        total_completion = snapshot.total_completion
        context_tokens = snapshot.guard_context_tokens
        displayed_context_tokens = snapshot.displayed_context_tokens
        model = snapshot.model
        
        input_rate, output_rate = get_pricing(model)
        total_cost = (total_prompt * input_rate + total_completion * output_rate) / 1_000_000.0
        
        if context_tokens > max_tokens or total_cost > max_cost:
            mcp_server._budget_warning_trigger_count += 1
            
            interval = getattr(mcp_server.config, "guard_interval", 5)
            if interval <= 0:
                interval = 5
                
            if mcp_server._budget_warning_trigger_count % interval != 1:
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


def _post_process_tool_output(content: str, project_name: str) -> str:
    content = _append_skill_reminder(content, project_name)
    content = _append_budget_warning(content)
    return content


def _auto_reindex_if_needed(project_name: str) -> bool:
    """Checks if any files in the project have changed and indexes the project if so. Returns True if reindexed."""
    from src import mcp_server
    now = time.time()
    if now - mcp_server._last_auto_index_time.get(project_name, 0) < 2.0:
        return False
    mcp_server._last_auto_index_time[project_name] = now
    
    try:
        proj_path = mcp_server.db.get_project_path(project_name)
        if not proj_path or not os.path.exists(proj_path):
            return False
            
        from src.manifest import IndexManifest
        manifest = IndexManifest(os.path.dirname(mcp_server.config.db_persist_directory))
        project = manifest.get_project(project_name)
        if not project:
            return False
        store = manifest.active_store(project)
        if not store:
            return False
            
        existing_files = store.get("files", {})
        
        # Scan files using the Indexer
        from src.indexer import Indexer
        scanner = Indexer(mcp_server.config)
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
            from src.indexing_service import IndexingService
            service = IndexingService(mcp_server.config)
            def progress_cb(phase, current, total):
                if current == total or current % max(1, total // 10) == 0:
                    logger.info(f"Auto-reindex progress: {phase} {current}/{total}")
            result = service.index_project(proj_path, project_name, progress=progress_cb)
            logger.info(f"Auto-reindex completed: {result.summary()}")
            return True
            
    except Exception as e:
        logger.error(f"Error in _auto_reindex_if_needed: {e}")
        
    return False


def reciprocal_rank_fusion(vector_results: list[dict], fts_results: list[dict], k: int = 60) -> list[dict]:
    """Combines vector search and FTS5 search results using Reciprocal Rank Fusion (RRF)."""
    scores = {}
    item_map = {}
    
    # Process vector results
    for rank, item in enumerate(vector_results):
        item_id = item["id"]
        scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank + 1)
        item_map[item_id] = item
        
    # Process FTS results
    for rank, item in enumerate(fts_results):
        item_id = item["id"]
        scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank + 1)
        if item_id not in item_map:
            item_map[item_id] = item
            
    # Sort by RRF score descending
    sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
    
    merged_results = []
    for item_id in sorted_ids:
        item = item_map[item_id]
        # Store original scores but use RRF score for sorting
        item["original_score"] = item.get("score", 0.0)
        item["score"] = scores[item_id]
        merged_results.append(item)
        
    return merged_results


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


def get_diff_index_status(project_name: str = None, output_json: bool = False) -> str:
    """Shows the indexing status of files in the project (new, stale, deleted, up_to_date) before running index_project."""
    from src import mcp_server
    from src.mcp_helpers import detect_active_project, log_error
    db = mcp_server.db
    indexer = mcp_server.indexer
    config = mcp_server.config

    if project_name is None:
        project_name = detect_active_project()
    logger.info(f"diff_index_status called for: '{project_name}', output_json: {output_json}")
    try:
        proj_path = db.get_project_path(project_name)
        if not proj_path:
            registry_path = os.path.expanduser("~/.fourtindex/project_registry.json")
            if os.path.exists(registry_path):
                with open(registry_path, "r", encoding="utf-8") as f:
                    registry = json.load(f)
                proj_path = registry.get(project_name)
        if not proj_path or not os.path.exists(proj_path):
            proj_path = os.getcwd()
            
        proj_path = os.path.abspath(proj_path)
        files_on_disk = indexer.scan_files(proj_path)
        
        state_directory = os.path.dirname(config.db_persist_directory)
        from src.manifest import IndexManifest
        manifest = IndexManifest(state_directory)
        project = manifest.get_project(project_name)
        
        existing = {}
        if project:
            store = manifest.active_store(project) or manifest.pending_store(project)
            if store:
                existing = store.get("files", {})
                
        new_files = []
        stale_files = []
        deleted_files = []
        up_to_date = []
        
        files_on_disk_rel = [os.path.relpath(f, proj_path).replace("\\", "/") for f in files_on_disk]
        
        for rel_path in files_on_disk_rel:
            abs_path = os.path.join(proj_path, rel_path)
            if rel_path not in existing:
                new_files.append(rel_path)
            else:
                curr_hash = indexer.compute_file_hash(abs_path)
                expected_hash = existing[rel_path].get("hash")
                if curr_hash != expected_hash:
                    stale_files.append(rel_path)
                else:
                    up_to_date.append(rel_path)
                    
        for rel_path in existing:
            if rel_path not in files_on_disk_rel:
                deleted_files.append(rel_path)
                
        summary = {
            "project_name": project_name,
            "project_path": proj_path.replace("\\", "/"),
            "new_count": len(new_files),
            "stale_count": len(stale_files),
            "deleted_count": len(deleted_files),
            "up_to_date_count": len(up_to_date),
            "new_files": new_files,
            "stale_files": stale_files,
            "deleted_files": deleted_files
        }
        
        if output_json:
            return json.dumps(summary, indent=2)
            
        lines = [
            f"=== Diff Index Status for Project '{project_name}' ===",
            f"Path: {proj_path}",
            f"Status Summary:",
            f"  - New files:      {len(new_files)}",
            f"  - Stale files:    {len(stale_files)}",
            f"  - Deleted files:  {len(deleted_files)}",
            f"  - Up-to-date:     {len(up_to_date)}"
        ]
        
        if new_files:
            lines.append("\n[NEW] Files to be indexed:")
            for f in new_files[:20]:
                lines.append(f"  + {f}")
            if len(new_files) > 20:
                lines.append(f"  ... and {len(new_files) - 20} more")
                
        if stale_files:
            lines.append("\n[STALE] Files modified since last index:")
            for f in stale_files[:20]:
                lines.append(f"  * {f}")
            if len(stale_files) > 20:
                lines.append(f"  ... and {len(stale_files) - 20} more")
                
        if deleted_files:
            lines.append("\n[DELETED] Files removed from disk:")
            for f in deleted_files[:20]:
                lines.append(f"  - {f}")
            if len(deleted_files) > 20:
                lines.append(f"  ... and {len(deleted_files) - 20} more")
                
        if not new_files and not stale_files and not deleted_files:
            lines.append("\n✓ Index is completely up-to-date. No changes detected.")
            
        return "\n".join(lines)
    except Exception as e:
        log_error(f"diff_index_status: {str(e)}")
        logger.error(f"Error in diff_index_status: {e}")
        if output_json:
            return json.dumps({"error": str(e)})
        return f"Error: {str(e)}"

