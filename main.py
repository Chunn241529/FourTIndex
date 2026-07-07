import os
import sys

# Add the project root directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Reconfigure stdout/stderr to UTF-8 to avoid UnicodeEncodeError on Windows
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


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
from src.embedding import EmbeddingManager
from src.indexing_service import IndexOptions, IndexingService, load_project_context

console = Console()

def inject_agent_skill():
    """Automatically injects the FourTIndex SKILL.md into the current working directory's .agents folder."""
    try:
        import shutil
        cwd = os.getcwd()
        if "system32" in cwd.lower() or cwd.lower().endswith("windows"):
            return
            
        target_dir = os.path.join(cwd, ".agents", "skills", "FourTIndex")
        target_file = os.path.join(target_dir, "SKILL.md")
        
        if not os.path.exists(target_file):
            package_dir = os.path.dirname(os.path.abspath(__file__))
            template_file = os.path.join(package_dir, "src", "templates", "SKILL.md")
            
            if os.path.exists(template_file):
                os.makedirs(target_dir, exist_ok=True)
                shutil.copy2(template_file, target_file)
    except Exception as e:
        sys.stderr.write(f"Warning: Failed to inject agent skill: {e}\n")

def cmd_index(args):
    inject_agent_skill()
    config = Config()
    service = IndexingService(config)
    
    project_name = args.project_name
    if not project_name:
        target_path = os.path.abspath(args.path)
        target_config_path = os.path.join(target_path, "config.yaml")
        if os.path.exists(target_config_path):
            try:
                import yaml
                with open(target_config_path, "r", encoding="utf-8") as f:
                    ydata = yaml.safe_load(f) or {}
                    project_name = ydata.get("project", {}).get("name")
            except Exception:
                pass
        if not project_name:
            project_name = os.path.basename(target_path) or config.project_name

    try:
        result = service.index_project(
            args.path,
            project_name,
            IndexOptions(
                embedding_provider=args.embedding_provider,
                rebuild=args.rebuild,
                force=args.force,
                batch_size=args.batch_size,
                workers=args.workers,
            ),
        )
        style = "bold green" if result.completed else "bold yellow"
        console.print(result.summary(), style=style)
        if result.failed:
            console.print("Failed files: " + ", ".join(result.failed), style="bold red")
    except KeyboardInterrupt:
        console.print("Indexing interrupted; completed checkpoints were preserved.", style="yellow")
        raise SystemExit(130)
    except Exception as exc:
        console.print(f"[bold red]Indexing error:[/bold red] {exc}")
        raise SystemExit(1)

def cmd_search(args):
    config = Config()
    project_name = args.project_name or config.project_name
    
    ext_str = f" with extension '{args.file_ext}'" if args.file_ext else ""
    console.print(f"[bold blue]Searching codebase for{ext_str}:[/bold blue] '{args.query}'\n")
    
    try:
        formatted_ext = None
        if args.file_ext:
            formatted_ext = args.file_ext if args.file_ext.startswith(".") else f".{args.file_ext}"
            formatted_ext = formatted_ext.lower()
            
        db, manager, project, store = load_project_context(config, project_name)
        query_vector = manager.embed_query(args.query)
        
        if config.rerank_enabled:
            candidates = db.search_project_code(
                project["project_id"], store["store_id"], query_vector, config.rerank_candidates_limit, formatted_ext
            )
            if candidates:
                from src.reranker import LocalReranker
                reranker = LocalReranker(config)
                results = reranker.rerank(args.query, candidates, top_k=args.limit)
            else:
                results = []
        else:
            results = db.search_project_code(
                project["project_id"], store["store_id"], query_vector, args.limit, formatted_ext
            )
        
        if not results:
            console.print("[yellow]No matching code chunks found.[/yellow]")
            return
            
        score_column_name = "Rerank Score" if config.rerank_enabled else "Score"
        table = Table(title="Semantic Search Results")
        table.add_column(score_column_name, justify="right", style="green", width=12)
        table.add_column("File & Line Range", style="cyan")
        table.add_column("Symbol / Context", style="magenta")
        
        for r in results:
            meta = r["metadata"]
            symbol = meta.get("symbol_name") or f"Chunk ({meta.get('chunk_type')})"
            file_line = f"{meta.get('file_path')}:{meta.get('start_line')}-{meta.get('end_line')}"
            score_val = r.get("rerank_score", r["score"])
            table.add_row(f"{score_val:.4f}", file_line, symbol)
            
        console.print(table)
        
        # Display the highest matching chunk content
        best = results[0]
        console.print(f"\n[bold green]>>> Highest Match ({best['metadata'].get('file_path')}):[/bold green]")
        console.print(best["content"])
        
    except Exception as e:
        console.print(f"[bold red]Search Error:[/bold red] {e}")

def cmd_query(args):
    config = Config()
    llm = LLMClient(config)
    project_name = args.project_name or config.project_name
    
    console.print(f"[bold blue]User Query:[/bold blue] {args.question}")
    console.print("[cyan]1. Retrieving context from Vector DB...[/cyan]")
    
    try:
        db, manager, project, store = load_project_context(config, project_name)
        query_vector = manager.embed_query(args.question)
        
        if config.rerank_enabled:
            console.print(f"[cyan]   Retrieving {config.rerank_candidates_limit} candidates for reranking...[/cyan]")
            candidates = db.search_project_code(
                project["project_id"], store["store_id"], query_vector, config.rerank_candidates_limit
            )
            if candidates:
                console.print(f"[cyan]   Reranking candidates using '{config.rerank_model}'...[/cyan]")
                from src.reranker import LocalReranker
                reranker = LocalReranker(config)
                results = reranker.rerank(args.question, candidates, top_k=args.limit)
            else:
                results = []
        else:
            results = db.search_project_code(
                project["project_id"], store["store_id"], query_vector, args.limit
            )
        
        if not results:
            console.print("[yellow]No relevant codebase context found.[/yellow]")
            return
            
        context_parts = []
        for r in results:
            meta = r["metadata"]
            score_str = f" | Rerank Score: {r['rerank_score']:.4f}" if "rerank_score" in r else ""
            context_parts.append(
                f"File: {meta.get('file_path')} (Lines {meta.get('start_line')}-{meta.get('end_line')}{score_str})\n"
                f"```\n{r['content']}\n```"
            )
        context = "\n\n".join(context_parts)
        
        active_llm_model = config.lmstudio_llm_model if config.llm_provider == "lmstudio" else config.ollama_llm_model
        console.print(f"[cyan]2. Querying local LLM '{active_llm_model}'...[/cyan]")
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

def cmd_setup_lmstudio(args):
    from src.setup_lmstudio import run_setup as run_lmstudio_setup
    run_lmstudio_setup()

def cmd_clean_mem(args):
    config = Config()
    provider = config.llm_provider.lower()
    
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
                print(f"Successfully unloaded model(s) '{', '.join(unloaded_list)}' from LM Studio.")
            else:
                print("No configured models were actively loaded in LM Studio to unload.")
        except Exception as e:
            print(f"Error unloading models from LM Studio: {e}")
    else:
        from src.setup_ollama import unload_models
        unload_models()
        print("Successfully unloaded all models from Ollama VRAM/RAM.")
        
    try:
        from src.token_meter import evaluate_latest_session
        print(evaluate_latest_session())
    except Exception as e:
        print(f"Error in token evaluation: {e}")



def cmd_providers(args):
    config = Config()
    manager = EmbeddingManager(config)
    table = Table(title="Embedding Providers")
    table.add_column("Provider", style="cyan")
    table.add_column("Model")
    table.add_column("Dimension", justify="right")
    table.add_column("Enabled")
    table.add_column("Status")
    for status in manager.provider_statuses(check=args.check):
        table.add_row(
            status["provider"],
            status["model"],
            str(status["dimension"]),
            "yes" if status["enabled"] else "no",
            status["state"],
        )
    console.print(table)

def cmd_mcp(args):
    inject_agent_skill()
    # Import inside function to avoid starting it during argparse setup
    from src.mcp_server import mcp
    mcp.run()

def cmd_dashboard(args):
    from src.dashboard_server import start_dashboard_server
    try:
        start_dashboard_server(port=args.port, open_browser=not args.no_open)
    except KeyboardInterrupt:
        print("\nDashboard server stopped.")
        sys.exit(0)

def main():
    parser = argparse.ArgumentParser(description="fourTindex - Local Code Indexer & MCP Assistant")
    subparsers = parser.add_subparsers(dest="command", required=True, help="Sub-command to execute")
    
    # index command
    p_index = subparsers.add_parser("index", help="Index project directory")
    p_index.add_argument("path", nargs="?", default=".", help="Path to project directory (default: current)")
    p_index.add_argument("--project-name", help="Stable project name")
    p_index.add_argument("--embedding-provider", default="auto", help="Provider name or auto")
    p_index.add_argument("--rebuild", action="store_true", help="Build a new provider-isolated index")
    p_index.add_argument("--force", action="store_true", help="Re-index all matching files")
    p_index.add_argument("--batch-size", type=int, help="Maximum embedding inputs per request")
    p_index.add_argument("--workers", type=int, help="Parallel file parsing workers")
    p_index.set_defaults(func=cmd_index)
    
    # search command
    p_search = subparsers.add_parser("search", help="Semantic codebase search")
    p_search.add_argument("query", help="Search query string")
    p_search.add_argument("--limit", type=int, default=5, help="Max results to display")
    p_search.add_argument("--file-ext", help="File extension to filter by (e.g. '.py' or 'js')")
    p_search.add_argument("--project-name", help="Indexed project name")
    p_search.set_defaults(func=cmd_search)
    
    # query command
    p_query = subparsers.add_parser("query", help="Ask local LLM about codebase")
    p_query.add_argument("question", help="Question about codebase")
    p_query.add_argument("--limit", type=int, default=3, help="Max context chunks to include")
    p_query.add_argument("--project-name", help="Indexed project name")
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
    
    # setup-lmstudio command
    p_setup_lmstudio = subparsers.add_parser("setup-lmstudio", help="Verify LM Studio connectivity, load models, and set as active provider")
    p_setup_lmstudio.set_defaults(func=cmd_setup_lmstudio)
    
    # clean-mem command
    p_clean_mem = subparsers.add_parser("clean-mem", help="Unload Ollama models to free VRAM and RAM memory")
    p_clean_mem.set_defaults(func=cmd_clean_mem)

    p_providers = subparsers.add_parser("providers", help="List embedding providers")
    p_providers.add_argument("--check", action="store_true", help="Call configured providers")
    p_providers.set_defaults(func=cmd_providers)

    # mcp command
    p_mcp = subparsers.add_parser("mcp", help="Start MCP stdio server")
    p_mcp.set_defaults(func=cmd_mcp)

    # dashboard command
    p_dashboard = subparsers.add_parser("dashboard", help="Start the interactive token dashboard and context auditor web server")
    p_dashboard.add_argument("--port", type=int, default=4040, help="Port to run the dashboard server on")
    p_dashboard.add_argument("--no-open", action="store_true", help="Do not automatically open the dashboard in the web browser")
    p_dashboard.set_defaults(func=cmd_dashboard)
    
    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
