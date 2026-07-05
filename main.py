import os
import sys

# Add the project root directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import argparse
from rich.console import Console
from rich.table import Table
from rich.markdown import Markdown
from rich.progress import Progress

from src.config import Config
from src.embedder import Embedder
from src.database import Database
from src.indexer import Indexer
from src.llm import LLMClient

console = Console()

def cmd_index(args):
    config = Config()
    indexer = Indexer(config)
    db = Database(config)
    embedder = Embedder(config)
    
    path = os.path.abspath(args.path)
    if not os.path.exists(path):
        console.print(f"[bold red]Error:[/bold red] Path '{args.path}' does not exist.")
        sys.exit(1)
        
    console.print(f"[bold blue]Scanning files in:[/bold blue] {path}")
    files = indexer.scan_files(path)
    console.print(f"Found [green]{len(files)}[/green] files matching extension criteria.")
    
    indexed_count = 0
    skipped_count = 0
    
    with Progress() as progress:
        task = progress.add_task("[cyan]Processing files...", total=len(files))
        
        for file in files:
            rel_path = os.path.relpath(file, path).replace("\\", "/")
            current_hash = indexer.compute_file_hash(file)
            cached_hash = indexer.file_hashes.get(rel_path)
            
            if cached_hash == current_hash:
                skipped_count += 1
                progress.advance(task)
                continue
                
            progress.console.print(f"Indexing: [yellow]{rel_path}[/yellow]")
            chunks = indexer.parse_file(file, rel_path)
            
            db.delete_file_entries(rel_path, config.project_name)
            
            if chunks:
                ids = []
                documents = []
                metadatas = []
                
                chunk_texts = [c["content"] for c in chunks]
                try:
                    embeddings = embedder.get_embeddings_batch(chunk_texts)
                except Exception as e:
                    progress.console.print(f"[bold red]Failed to generate batch embeddings for {rel_path}: {e}[/bold red]")
                    embeddings = []
                
                if len(embeddings) == len(chunks):
                    for idx, c in enumerate(chunks):
                        chunk_id = f"{rel_path}#chunk_{idx}"
                        ids.append(chunk_id)
                        documents.append(c["content"])
                        
                        meta = {
                            "project_name": config.project_name,
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
                    db.upsert_code_chunks(ids, embeddings, documents, metadatas)
                else:
                    progress.console.print(f"[bold red]Failed to index {rel_path} due to embedding size mismatch.[/bold red]")
                
                # Update Outline
                outline_summary = indexer.generate_file_outline_summary(chunks, rel_path)
                try:
                    outline_embedding = embedder.get_embedding(outline_summary)
                    outline_id = f"{rel_path}#outline"
                    outline_meta = {
                        "project_name": config.project_name,
                        "file_path": rel_path,
                        "file_name": os.path.basename(file),
                        "file_ext": os.path.splitext(file)[1].lower(),
                        "hash": current_hash
                    }
                    db.upsert_file_outline(outline_id, outline_embedding, outline_summary, outline_meta)
                except Exception as e:
                    progress.console.print(f"[bold red]Failed to embed outline for {rel_path}: {e}[/bold red]")
                    
            indexer.file_hashes[rel_path] = current_hash
            indexed_count += 1
            progress.advance(task)
            
    # Save project path mapping to registry for resolving relative paths later
    db.save_project_path(config.project_name, path)
    
    if indexed_count > 0:
        indexer.save_file_hashes()
        
    console.print(f"\n[bold green]Success![/bold green] Indexed {indexed_count} files, skipped {skipped_count} unchanged files.")

def cmd_search(args):
    config = Config()
    db = Database(config)
    embedder = Embedder(config)
    
    ext_str = f" with extension '{args.file_ext}'" if args.file_ext else ""
    console.print(f"[bold blue]Searching codebase for{ext_str}:[/bold blue] '{args.query}'\n")
    
    try:
        formatted_ext = None
        if args.file_ext:
            formatted_ext = args.file_ext if args.file_ext.startswith(".") else f".{args.file_ext}"
            formatted_ext = formatted_ext.lower()
            
        query_vector = embedder.get_embedding(args.query)
        results = db.search_code_chunks(query_vector, config.project_name, limit=args.limit, file_ext=formatted_ext)
        
        if not results:
            console.print("[yellow]No matching code chunks found.[/yellow]")
            return
            
        table = Table(title="Semantic Search Results")
        table.add_column("Score", justify="right", style="green", width=8)
        table.add_column("File & Line Range", style="cyan")
        table.add_column("Symbol / Context", style="magenta")
        
        for r in results:
            meta = r["metadata"]
            symbol = meta.get("symbol_name") or f"Chunk ({meta.get('chunk_type')})"
            file_line = f"{meta.get('file_path')}:{meta.get('start_line')}-{meta.get('end_line')}"
            table.add_row(f"{r['score']:.4f}", file_line, symbol)
            
        console.print(table)
        
        # Display the highest matching chunk content
        best = results[0]
        console.print(f"\n[bold green]>>> Highest Match ({best['metadata'].get('file_path')}):[/bold green]")
        console.print(best["content"])
        
    except Exception as e:
        console.print(f"[bold red]Search Error:[/bold red] {e}")

def cmd_query(args):
    config = Config()
    db = Database(config)
    embedder = Embedder(config)
    llm = LLMClient(config)
    
    console.print(f"[bold blue]User Query:[/bold blue] {args.question}")
    console.print("[cyan]1. Retrieving context from Vector DB...[/cyan]")
    
    try:
        query_vector = embedder.get_embedding(args.question)
        results = db.search_code_chunks(query_vector, config.project_name, limit=args.limit)
        
        if not results:
            console.print("[yellow]No relevant codebase context found.[/yellow]")
            return
            
        context_parts = []
        for r in results:
            meta = r["metadata"]
            context_parts.append(
                f"File: {meta.get('file_path')} (Lines {meta.get('start_line')}-{meta.get('end_line')})\n"
                f"```\n{r['content']}\n```"
            )
        context = "\n\n".join(context_parts)
        
        console.print(f"[cyan]2. Querying local LLM '{config.ollama_llm_model}'...[/cyan]")
        answer = llm.generate_answer(args.question, context)
        
        console.print("\n[bold green]Response:[/bold green]")
        console.print(Markdown(answer))
        
    except Exception as e:
        console.print(f"[bold red]Query Error:[/bold red] {e}")

def cmd_index_skill(args):
    config = Config()
    embedder = Embedder(config)
    db = Database(config)
    indexer = Indexer(config)
    
    path = os.path.abspath(args.path)
    if os.path.isdir(path):
        file_path = os.path.join(path, "SKILL.md")
    else:
        file_path = path
        
    if not os.path.exists(file_path):
        console.print(f"[bold red]Error:[/bold red] Skill file not found at '{file_path}'")
        sys.exit(1)
        
    rel_path = os.path.relpath(file_path, os.path.dirname(os.path.dirname(file_path))).replace("\\", "/")
    console.print(f"[bold blue]Parsing skill file:[/bold blue] {rel_path}")
    
    metadata, chunks = indexer.parse_skill_file(file_path, rel_path)
    if not chunks:
        console.print(f"[bold red]Error:[/bold red] Failed to parse skill file or no chunks found.")
        sys.exit(1)
        
    skill_name = metadata.get("name", os.path.basename(os.path.dirname(file_path)))
    db.delete_skill_entries(skill_name, config.project_name)
    
    ids = []
    documents = []
    metadatas = []
    
    chunk_texts = [c["content"] for c in chunks]
    with Progress() as progress:
        task = progress.add_task("[cyan]Embedding skill sections...", total=len(chunks))
        embeddings = embedder.get_embeddings_batch(chunk_texts)
        progress.advance(task, len(chunks))
        
    for idx, c in enumerate(chunks):
        chunk_id = f"skill_{skill_name}#chunk_{idx}"
        ids.append(chunk_id)
        documents.append(c["content"])
        meta = {
            "project_name": config.project_name,
            "skill_name": skill_name,
            "file_path": rel_path,
            "heading": c["heading"],
            "start_line": c["start_line"],
            "end_line": c["end_line"]
        }
        metadatas.append(meta)
        
    db.upsert_skill_chunks(ids, embeddings, documents, metadatas)
    console.print(f"[bold green]Success![/bold green] Indexed skill '[cyan]{skill_name}[/cyan]' with {len(ids)} sections.")

def cmd_search_skills(args):
    config = Config()
    db = Database(config)
    embedder = Embedder(config)
    
    console.print(f"[bold blue]Searching indexed skills for:[/bold blue] '{args.query}'\n")
    try:
        query_vector = embedder.get_embedding(args.query)
        results = db.search_skills(query_vector, config.project_name, limit=args.limit)
        
        if not results:
            console.print("[yellow]No matching skill sections found.[/yellow]")
            return
            
        table = Table(title="Semantic Skill Search Results")
        table.add_column("Score", justify="right", style="green", width=8)
        table.add_column("Skill & Section", style="cyan")
        table.add_column("Line Range", style="magenta")
        
        for r in results:
            meta = r["metadata"]
            skill_section = f"{meta.get('skill_name')} > {meta.get('heading')}"
            file_line = f"Lines {meta.get('start_line')}-{meta.get('end_line')}"
            table.add_row(f"{r['score']:.4f}", skill_section, file_line)
            
        console.print(table)
        
        # Display best section content
        best = results[0]
        console.print(f"\n[bold green]>>> Highest Match ({best['metadata'].get('skill_name')} > {best['metadata'].get('heading')}):[/bold green]")
        console.print(best["content"])
    except Exception as e:
        console.print(f"[bold red]Search Error:[/bold red] {e}")

def cmd_setup_ollama(args):
    from src.setup_ollama import run_setup
    run_setup()

def cmd_clean_mem(args):
    from src.setup_ollama import unload_models
    unload_models()

def cmd_mcp(args):
    # Import inside function to avoid starting it during argparse setup
    from src.mcp_server import mcp
    mcp.run()

def main():
    parser = argparse.ArgumentParser(description="fourTindex - Local Code Indexer & MCP Assistant")
    subparsers = parser.add_subparsers(dest="command", required=True, help="Sub-command to execute")
    
    # index command
    p_index = subparsers.add_parser("index", help="Index project directory")
    p_index.add_argument("path", nargs="?", default=".", help="Path to project directory (default: current)")
    p_index.set_defaults(func=cmd_index)
    
    # search command
    p_search = subparsers.add_parser("search", help="Semantic codebase search")
    p_search.add_argument("query", help="Search query string")
    p_search.add_argument("--limit", type=int, default=5, help="Max results to display")
    p_search.add_argument("--file-ext", help="File extension to filter by (e.g. '.py' or 'js')")
    p_search.set_defaults(func=cmd_search)
    
    # query command
    p_query = subparsers.add_parser("query", help="Ask local LLM about codebase")
    p_query.add_argument("question", help="Question about codebase")
    p_query.add_argument("--limit", type=int, default=3, help="Max context chunks to include")
    p_query.set_defaults(func=cmd_query)
    
    # index-skill command
    p_index_skill = subparsers.add_parser("index-skill", help="Index a customization skill (SKILL.md)")
    p_index_skill.add_argument("path", help="Path to skill directory or SKILL.md")
    p_index_skill.set_defaults(func=cmd_index_skill)
    
    # search-skills command
    p_search_skills = subparsers.add_parser("search-skills", help="Semantic search on indexed skills")
    p_search_skills.add_argument("query", help="Search query string")
    p_search_skills.add_argument("--limit", type=int, default=3, help="Max results to display")
    p_search_skills.set_defaults(func=cmd_search_skills)
    
    # setup-ollama command
    p_setup_ollama = subparsers.add_parser("setup-ollama", help="Verify Ollama installation and pull required models")
    p_setup_ollama.set_defaults(func=cmd_setup_ollama)
    
    # clean-mem command
    p_clean_mem = subparsers.add_parser("clean-mem", help="Unload Ollama models to free VRAM and RAM memory")
    p_clean_mem.set_defaults(func=cmd_clean_mem)

    # mcp command
    p_mcp = subparsers.add_parser("mcp", help="Start MCP stdio server")
    p_mcp.set_defaults(func=cmd_mcp)
    
    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
