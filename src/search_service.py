import os
import json
import logging

logger = logging.getLogger("FourTIndexMCP")


def orchestrate_search(
    query: str,
    project_name: str = None,
    limit: int = 5,
    file_ext: str = None,
    language: str = None,
    output_json: bool = False,
) -> str:
    from src import mcp_server
    from src.mcp_helpers import reciprocal_rank_fusion, _post_process_tool_output, log_error

    db = mcp_server.db
    config = mcp_server.config
    embedder = mcp_server.embedder
    indexer = mcp_server.indexer

    if project_name is None:
        from src.mcp_helpers import detect_active_project
        project_name = detect_active_project()

    logger.info(
        f"search_codebase called with query: '{query}', file_ext: '{file_ext}', language: '{language}', output_json: {output_json}"
    )
    try:
        from src.keyword_search import is_valid_keyword, search_exact_keyword, format_keyword_results

        # Search must remain a bounded read operation. Reindexing can involve a
        # full project scan and remote embedding calls, so callers trigger it
        # explicitly with index_project instead of blocking this request.
        if len(mcp_server._query_cache) > 1000:
            mcp_server._query_cache.clear()

        # Check cache
        cache_key = (project_name, query, limit, file_ext, language, output_json)
        if cache_key in mcp_server._query_cache:
            logger.info(f"Returning cached result for query: '{query}'")
            return mcp_server._query_cache[cache_key]

        formatted_ext = None
        if file_ext:
            formatted_ext = file_ext if file_ext.startswith(".") else f".{file_ext}"
            formatted_ext = formatted_ext.lower()

        # Fast Path: Exact Keyword Search
        if is_valid_keyword(query):
            logger.info(f"Query '{query}' qualifies for exact Keyword Search.")
            exts = [formatted_ext] if formatted_ext else config.supported_extensions

            # Fetch the actual project path from the database
            project_path = db.get_project_path(project_name)

            if project_path:
                kw_results = search_exact_keyword(project_path, query, exts)

                if kw_results:
                    logger.info(f"Fast path successful: Found exact match for '{query}'.")
                    if output_json:
                        # Format to match the semantic search schema
                        json_results = []
                        for kw in kw_results:
                            json_results.append({
                                "file_path": kw.get("file"),
                                "start_line": kw.get("line"),
                                "end_line": kw.get("line") + kw.get("content", "").count("\n"),
                                "content": kw.get("content"),
                                "score": 1.0,
                                "score_type": "exact_match",
                                "indexed_at": "now",
                                "source_hash": "exact_match",
                            })
                        res = json.dumps(json_results, indent=2)
                        mcp_server._query_cache[cache_key] = res
                        return res
                    res = format_keyword_results(query, kw_results)
                    mcp_server._query_cache[cache_key] = res
                    return res

        # Slow Path: Semantic Vector Search & FTS5 Hybrid Search
        from src.indexing_service import load_project_context
        project_db, manager, project, store = load_project_context(config, project_name)
        query_vector = manager.embed_query(query)

        # 1. Determine candidates limit
        if config.rerank_enabled:
            candidates_limit = max(30, config.rerank_candidates_limit)
        else:
            candidates_limit = max(15, limit * 2)

        # Run Vector search
        vector_candidates = project_db.search_project_code(
            project["project_id"],
            store["store_id"],
            query_vector,
            candidates_limit,
            formatted_ext,
            language,
        )

        # Run FTS5 search (BM25)
        fts_candidates = project_db.search_project_code_fts(
            project["project_id"], store["store_id"], query, candidates_limit
        )

        # Merge using Reciprocal Rank Fusion (RRF)
        candidates = reciprocal_rank_fusion(vector_candidates, fts_candidates)

        if not candidates:
            results = []
        else:
            # 2. Apply Doc Penalty (penalize .md / .txt if query is not doc-specific)
            query_lower = query.lower()
            is_searching_docs = any(
                word in query_lower
                for word in (
                    "readme",
                    "doc",
                    "instruction",
                    "guide",
                    "install",
                    "run",
                    "setup",
                    "markdown",
                )
            )

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

                # Blended Hybrid Score:
                raw_rrf_score = c.get("score", 0.0)
                scaled_rrf = min(1.0, raw_rrf_score * 30.0)

                rerank_score = c.get("rerank_score", 0.0) if "rerank_score" in c else scaled_rrf

                # Blend scores if Reranker ran
                if "rerank_score" in c:
                    blended_score = scaled_rrf * 0.2 + rerank_score * 0.8
                else:
                    blended_score = scaled_rrf

                count = file_counts.get(file_path, 0)
                decayed_score = blended_score * (0.75**count)
                c["adjusted_score"] = decayed_score
                file_counts[file_path] = count + 1

            # Sort by adjusted_score descending, and filter out scores <= 0.0
            sorted_candidates = sorted(
                candidates, key=lambda x: x.get("adjusted_score", 0.0), reverse=True
            )
            results = []
            proj_path = db.get_project_path(project_name) or os.getcwd()
            for r in sorted_candidates:
                score_val = r.get("adjusted_score", r.get("rerank_score", r["score"]))
                if score_val <= 0.0:
                    continue

                # Check staleness
                meta = r["metadata"]
                file_path = meta.get("file_path")
                expected_hash = meta.get("source_hash") or meta.get("hash")
                stale = False
                if file_path:
                    abs_p = os.path.abspath(os.path.join(proj_path, file_path))
                    if os.path.exists(abs_p):
                        curr_hash = indexer.compute_file_hash(abs_p)
                        if curr_hash != expected_hash:
                            stale = True
                    else:
                        stale = True
                r["stale"] = stale
                results.append(r)
                if len(results) >= limit:
                    break

            # Adaptive Threshold Fallback: If all candidates were filtered out due to low reranker scores (<= 0.0),
            # fallback to taking the top candidates anyway to avoid returning empty results.
            if not results and sorted_candidates:
                logger.info(
                    "Adaptive Threshold triggered: falling back to top candidates ignoring <= 0.0 filter."
                )
                for r in sorted_candidates[: min(limit, 3)]:
                    meta = r["metadata"]
                    file_path = meta.get("file_path")
                    expected_hash = meta.get("source_hash") or meta.get("hash")
                    stale = False
                    if file_path:
                        abs_p = os.path.abspath(os.path.join(proj_path, file_path))
                        if os.path.exists(abs_p):
                            curr_hash = indexer.compute_file_hash(abs_p)
                            if curr_hash != expected_hash:
                                stale = True
                        else:
                            stale = True
                    r["stale"] = stale
                    results.append(r)

        if output_json:
            json_results = []
            for r in results:
                meta = r["metadata"]
                score_val = r.get("adjusted_score", r.get("rerank_score", r["score"]))
                json_results.append({
                    "file_path": meta.get("file_path"),
                    "start_line": meta.get("start_line"),
                    "end_line": meta.get("end_line"),
                    "score": score_val,
                    "content": r["content"],
                    "stale": r.get("stale", False),
                    "indexed_at": meta.get("indexed_at", "unknown"),
                    "source_hash": meta.get("source_hash") or meta.get("hash"),
                })
            res = json.dumps(json_results, indent=2)
            mcp_server._query_cache[cache_key] = res
            return res

        if not results:
            return (
                f"No matching code chunks found for project '{project_name}'"
                + (f" with extension '{file_ext}'." if file_ext else "")
                + (f" and language '{language}'." if language else ".")
                + " If you recently added code, run 'index_project' to sync changes."
            )

        formatted = []
        for r in results:
            meta = r["metadata"]
            score_type = "Adjusted Rerank Score" if "rerank_score" in r else "Adjusted Score"
            score_val = r.get("adjusted_score", r.get("rerank_score", r["score"]))
            freshness_str = (
                f"stale: {r.get('stale', False)}, indexed_at: {meta.get('indexed_at', 'unknown')}"
            )
            formatted.append(
                f"=== FILE: {meta.get('file_path')} | Lines: {meta.get('start_line')}-{meta.get('end_line')} | {score_type}: {score_val:.4f} | Freshness: [{freshness_str}] ===\n"
                f"{r['content']}\n"
            )
        res = _post_process_tool_output("\n".join(formatted), project_name)
        mcp_server._query_cache[cache_key] = res
        return res
    except Exception as e:
        log_error(f"search_codebase: {str(e)}")
        logger.error(f"Error in search_codebase: {e}")
        if output_json:
            return json.dumps({"error": str(e)})
        return f"Error during search: {str(e)}"
