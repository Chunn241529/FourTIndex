import os
import sys
import logging
from mcp.server.fastmcp import FastMCP

from src.config import Config
from src.embedder import Embedder
from src.database import Database
from src.indexer import Indexer

# Configure logging to go to stderr so it doesn't corrupt stdout stdio transport
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("fourTindexMCP")

# Load configuration and initialize core modules
config = Config(config_path="config.yaml")
embedder = Embedder(config)
db = Database(config)
indexer = Indexer(config)

mcp = FastMCP("fourTindex")

@mcp.tool()
def search_codebase(query: str, project_name: str = "fourTindex", limit: int = 5, file_ext: str = None) -> str:
    """Searches the indexed codebase semantically for relevant code chunks.
    
    Args:
        query: The natural language search query (e.g., 'JWT validation function').
        project_name: The name of the project.
        limit: Max number of chunks to return.
        file_ext: Optional file extension to filter by (e.g., '.py' or 'js').
    """
    logger.info(f"search_codebase called with query: '{query}', file_ext: '{file_ext}'")
    try:
        # Check if database is empty for this project
        total_chunks = db.code_chunks.count()
        if total_chunks == 0:
            return (
                f"No code chunks found in the database. "
                f"The project '{project_name}' has not been indexed yet. "
                f"Please run the 'index_project' tool first to initialize the index."
            )
            
        formatted_ext = None
        if file_ext:
            formatted_ext = file_ext if file_ext.startswith(".") else f".{file_ext}"
            formatted_ext = formatted_ext.lower()
            
        query_vector = embedder.get_embedding(query)
        results = db.search_code_chunks(query_vector, project_name, limit=limit, file_ext=formatted_ext)
        
        if not results:
            return (
                f"No matching code chunks found for project '{project_name}'" +
                (f" with extension '{file_ext}'." if file_ext else ".") +
                " If you recently added code, run 'index_project' to sync changes."
            )
            
        formatted = []
        for r in results:
            meta = r["metadata"]
            formatted.append(
                f"=== FILE: {meta.get('file_path')} | Lines: {meta.get('start_line')}-{meta.get('end_line')} | Score: {r['score']:.4f} ===\n"
                f"{r['content']}\n"
            )
        return "\n".join(formatted)
    except Exception as e:
        logger.error(f"Error in search_codebase: {e}")
        return f"Error during search: {str(e)}"

@mcp.tool()
def get_file_outline(file_path: str, project_name: str = "fourTindex") -> str:
    """Retrieves the high-level class and function outline structure of a specific file.
    
    Args:
        file_path: Relative path of the file (e.g., 'src/config.py').
        project_name: The name of the project.
    """
    logger.info(f"get_file_outline called for: '{file_path}'")
    try:
        # ChromaDB query works with query embeddings, so we generate a quick dummy search query or exact match
        # Let's search in the outlines collection by using exact path query or simple semantic lookup
        query_vector = embedder.get_embedding(f"File: {file_path}")
        results = db.search_file_outlines(query_vector, project_name, limit=5)
        
        # Filter for exact file path if possible
        for r in results:
            if r["metadata"].get("file_path") == file_path:
                return r["content"]
                
        # Fallback to the first match if exact path wasn't found
        if results:
            return results[0]["content"]
            
        return f"No outline found for file: {file_path}"
    except Exception as e:
        logger.error(f"Error in get_file_outline: {e}")
        return f"Error: {str(e)}"

@mcp.tool()
def get_symbol_definition(symbol_name: str, project_name: str = "fourTindex") -> str:
    """Finds the detailed code definition of a class or function by its name (e.g., 'Config.project_name').
    
    Args:
        symbol_name: Name of class or function.
        project_name: The name of the project.
    """
    logger.info(f"get_symbol_definition called for: '{symbol_name}'")
    try:
        # Query database directly using ChromaDB metadata where filters
        # Note: ChromaDB doesn't allow direct metadata where query without an embedding,
        # so we pass the symbol name embedding to search, and filter results by matching metadata
        query_vector = embedder.get_embedding(symbol_name)
        results = db.code_chunks.query(
            query_embeddings=[query_vector],
            n_results=10,
            where={
                "$and": [
                    {"symbol_name": symbol_name},
                    {"project_name": project_name}
                ]
            }
        )
        
        if results and "documents" in results and results["documents"] and results["documents"][0]:
            return results["documents"][0][0]
            
        return f"Symbol '{symbol_name}' definition not found."
    except Exception as e:
        logger.error(f"Error in get_symbol_definition: {e}")
        return f"Error: {str(e)}"

@mcp.tool()
def read_code_lines(file_path: str, start_line: int, end_line: int, project_name: str = "fourTindex") -> str:
    """Reads a specific range of lines from a file in the workspace.
    
    Args:
        file_path: Relative path of the file (e.g., 'src/config.py').
        start_line: 1-indexed starting line number (inclusive).
        end_line: 1-indexed ending line number (inclusive).
        project_name: The name of the project.
    """
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
            
        return "\n".join(formatted)
    except Exception as e:
        logger.error(f"Error in read_code_lines: {e}")
        return f"Error: {str(e)}"

@mcp.tool()
def save_session_summary(session_id: str, summary_text: str, project_name: str = "fourTindex") -> str:
    """Saves a summary of the current session's design decisions and changes into memory.
    
    Args:
        session_id: A unique identifier for the session (e.g., 'session_20260705_1').
        summary_text: Summary text explaining design choices, code refactorings, or modifications made.
        project_name: The name of the project.
    """
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
def index_project(project_path: str = ".", project_name: str = "fourTindex") -> str:
    """Scans and indexes (or updates index for) the specified project path.
    Only modified files are re-embedded.
    
    Args:
        project_path: Path to the project root directory.
        project_name: The name of the project.
    """
    logger.info(f"index_project called for path: '{project_path}'")
    try:
        files = indexer.scan_files(project_path)
        logger.info(f"Found {len(files)} files to check.")
        
        indexed_count = 0
        skipped_count = 0
        
        for file in files:
            rel_path = os.path.relpath(file, project_path).replace("\\", "/")
            current_hash = indexer.compute_file_hash(file)
            cached_hash = indexer.file_hashes.get(rel_path)
            
            if cached_hash == current_hash:
                skipped_count += 1
                continue
                
            logger.info(f"Indexing modified file: {rel_path}")
            chunks = indexer.parse_file(file, rel_path)
            
            # Clean up old chunks
            db.delete_file_entries(rel_path, project_name)
            
            if chunks:
                ids = []
                documents = []
                metadatas = []
                
                # Batch generate embeddings for all chunks in the file at once
                chunk_texts = [c["content"] for c in chunks]
                embeddings = embedder.get_embeddings_batch(chunk_texts)
                
                for idx, c in enumerate(chunks):
                    chunk_id = f"{rel_path}#chunk_{idx}"
                    ids.append(chunk_id)
                    documents.append(c["content"])
                    
                    meta = {
                        "project_name": project_name,
                        "file_path": rel_path,
                        "file_name": os.path.basename(file),
                        "file_ext": os.path.splitext(file)[1].lower(),
                        "chunk_type": c["chunk_type"],
                        "symbol_name": c["symbol_name"],
                        "start_line": c["start_line"],
                        "end_line": c["end_line"],
                        "hash": current_hash
                    }
                    metadatas.append(meta)
                    
                # Guard against length mismatch just in case
                if len(embeddings) == len(ids):
                    db.upsert_code_chunks(ids, embeddings, documents, metadatas)
                else:
                    logger.error(f"Length mismatch: embeddings={len(embeddings)}, ids={len(ids)}. Falling back to sequential upsert.")
                    # Fallback
                    embeddings = [embedder.get_embedding(doc) for doc in documents]
                    db.upsert_code_chunks(ids, embeddings, documents, metadatas)
                
                # File Outline Summary
                outline_summary = indexer.generate_file_outline_summary(chunks, rel_path)
                outline_embedding = embedder.get_embedding(outline_summary)
                outline_id = f"{rel_path}#outline"
                outline_meta = {
                    "project_name": project_name,
                    "file_path": rel_path,
                    "file_name": os.path.basename(file),
                    "file_ext": os.path.splitext(file)[1].lower(),
                    "hash": current_hash
                }
                db.upsert_file_outline(outline_id, outline_embedding, outline_summary, outline_meta)
                
            # Update cache
            indexer.file_hashes[rel_path] = current_hash
            indexed_count += 1
            
        # Save project path registry
        db.save_project_path(project_name, project_path)

        if indexed_count > 0:
            indexer.save_file_hashes()
            
        msg = f"Indexing finished. Indexed {indexed_count} files, skipped {skipped_count} unchanged files."
        logger.info(msg)
        return msg
    except Exception as e:
        logger.error(f"Error in index_project: {e}")
        return f"Error indexing project: {str(e)}"

@mcp.tool()
def index_skill(skill_path: str, project_name: str = "fourTindex") -> str:
    """Scans and indexes a specific customization skill (SKILL.md).
    
    Args:
        skill_path: Path to the skill folder or SKILL.md file.
        project_name: The name of the project.
    """
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
def search_skills(query: str, project_name: str = "fourTindex", limit: int = 3) -> str:
    """Searches the indexed customization skills semantically.
    
    Args:
        query: The natural language search query.
        project_name: The name of the project.
        limit: Max number of sections to return.
    """
    logger.info(f"search_skills called with query: '{query}'")
    try:
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
def get_skill_outline(skill_name: str, project_name: str = "fourTindex") -> str:
    """Gets the table of contents (list of headings) for a specific indexed skill.
    
    Args:
        skill_name: The name of the registered skill.
        project_name: The name of the project.
    """
    logger.info(f"get_skill_outline called for skill: '{skill_name}'")
    try:
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
def read_skill_section(skill_name: str, heading: str, project_name: str = "fourTindex") -> str:
    """Reads a specific markdown section under a heading for a registered skill.
    
    Args:
        skill_name: The name of the registered skill.
        heading: The exact heading name to retrieve (e.g., 'Agent Guidelines').
        project_name: The name of the project.
    """
    logger.info(f"read_skill_section called for skill '{skill_name}', heading '{heading}'")
    try:
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
    try:
        from src.setup_ollama import unload_models
        unload_models()
        return "Successfully unloaded all models from Ollama VRAM/RAM."
    except Exception as e:
        logger.error(f"Error in clean_mem: {e}")
        return f"Error: {str(e)}"

if __name__ == "__main__":
    logger.info("Starting fourTindex MCP Server...")
    mcp.run()
