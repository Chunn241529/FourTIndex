import os
import sys
import time
import urllib.request
import urllib.error
import json
import sqlite3
from typing import Tuple, List
from rich.console import Console
from rich.table import Table
from src.config import Config
from src.embedding.providers import create_provider

console = Console()


def is_lmstudio_embedding_model_available(
    configured_model: str, available_models: List[str]
) -> bool:
    """Return whether LM Studio exposes the configured embedding model or its API alias."""
    if not configured_model:
        return False

    candidates = {configured_model}
    if not configured_model.startswith("text-embedding-"):
        candidates.add(f"text-embedding-{configured_model}")
    return not candidates.isdisjoint(available_models)


def check_http_endpoint(url: str, api_token: str = None, timeout: float = 3.0) -> Tuple[bool, str, List[str]]:
    """Checks if HTTP endpoint is active and returns list of available model names."""
    try:
        req = urllib.request.Request(url)
        if api_token:
            req.add_header("Authorization", f"Bearer {api_token}")
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
            
            # Ollama /api/tags response parsing
            if "/api/tags" in url:
                models = [m["name"] for m in data.get("models", [])]
                return True, "Online", models
                
            # LM Studio /v1/models response parsing
            elif "/v1/models" in url:
                models = [m["id"] for m in data.get("data", [])]
                return True, "Online", models
                
            return True, "Online", []
    except urllib.error.URLError as e:
        return False, f"Offline ({e.reason})", []
    except Exception as e:
        return False, f"Error ({e})", []

def run_diagnostics(config: Config) -> bool:
    console.print("\n[bold blue]🏥 FourTIndex Doctor - System Health Diagnostic[/bold blue]\n")
    all_ok = True
    
    # 1. Check Configuration Provider
    provider = config.llm_provider
    console.print(f"[bold]Active LLM Provider:[/bold] {provider.upper()}")
    
    # 2. Check Providers (Ollama / LM Studio)
    # Check Ollama
    ollama_host = config.ollama_host
    ollama_url = f"{ollama_host.rstrip('/')}/api/tags"
    ollama_ok, ollama_status, ollama_models = check_http_endpoint(ollama_url)
    
    # Check LM Studio
    lmstudio_host = config.lmstudio_host
    lmstudio_url = f"{lmstudio_host.rstrip('/')}/v1/models"
    lmstudio_ok, lmstudio_status, lmstudio_models = check_http_endpoint(
        lmstudio_url, api_token=config.lmstudio_api_token
    )
    
    # Render Providers Table
    table = Table(title="Provider Health Status")
    table.add_column("Provider", style="cyan")
    table.add_column("Endpoint", style="magenta")
    table.add_column("Status")
    table.add_column("Available Models", style="dim")
    
    ollama_status_colored = f"[bold green]{ollama_status}[/bold green]" if ollama_ok else f"[bold red]{ollama_status}[/bold red]"
    lmstudio_status_colored = f"[bold green]{lmstudio_status}[/bold green]" if lmstudio_ok else f"[bold red]{lmstudio_status}[/bold red]"
    
    table.add_row("Ollama", ollama_host, ollama_status_colored, f"{len(ollama_models)} models")
    table.add_row("LM Studio", lmstudio_host, lmstudio_status_colored, f"{len(lmstudio_models)} models")
    console.print(table)
    
    # 3. Model Checks based on Provider
    console.print("\n[bold]🔍 Checking configured models:[/bold]")
    if provider == "ollama":
        llm_model = config.ollama_llm_model
        embed_model = config.ollama_embedding_model
        
        # LLM check
        if ollama_ok:
            if llm_model in ollama_models or f"{llm_model}:latest" in ollama_models:
                console.print(f"  [green]✓[/green] LLM Model '{llm_model}' is available in Ollama.")
            else:
                console.print(f"  [red]✗[/red] LLM Model '{llm_model}' not found in Ollama (use 'ollama pull {llm_model}').")
                all_ok = False
            # Embedding check
            if embed_model in ollama_models or f"{embed_model}:latest" in ollama_models:
                console.print(f"  [green]✓[/green] Embedding Model '{embed_model}' is available in Ollama.")
            else:
                console.print(f"  [red]✗[/red] Embedding Model '{embed_model}' not found in Ollama (use 'ollama pull {embed_model}').")
                all_ok = False
        else:
            console.print(f"  [yellow]![/yellow] Cannot verify models because Ollama service is offline.")
            all_ok = False
            
    elif provider == "lmstudio":
        llm_model = config.lmstudio_llm_model
        embed_model = config.lmstudio_embedding_model
        
        if lmstudio_ok:
            if llm_model in lmstudio_models:
                console.print(f"  [green]✓[/green] LLM Model '{llm_model}' is loaded in LM Studio.")
            else:
                console.print(f"  [red]✗[/red] LLM Model '{llm_model}' is not loaded/available in LM Studio.")
                all_ok = False
            if is_lmstudio_embedding_model_available(embed_model, lmstudio_models):
                console.print(f"  [green]✓[/green] Embedding Model '{embed_model}' is loaded in LM Studio.")
            else:
                console.print(f"  [red]✗[/red] Embedding Model '{embed_model}' is not loaded/available in LM Studio.")
                all_ok = False
        else:
            console.print(f"  [yellow]![/yellow] Cannot verify models because LM Studio service is offline.")
            all_ok = False

    # 4. Check SQLite Registry
    console.print("\n[bold]💾 Checking database files:[/bold]")
    registry_path = config.registry_db_path
    if os.path.exists(registry_path):
        try:
            conn = sqlite3.connect(registry_path)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            conn.close()
            console.print(f"  [green]✓[/green] Registry DB is active: {registry_path} ({len(tables)} tables found)")
        except Exception as e:
            console.print(f"  [red]✗[/red] Registry DB is corrupted or locked: {e}")
            all_ok = False
    else:
        console.print(f"  [yellow]![/yellow] Registry DB does not exist yet (will be created automatically on index).")

    # Check ChromaDB
    chroma_dir = config.db_persist_directory
    if os.path.exists(chroma_dir):
        console.print(f"  [green]✓[/green] Local ChromaDB folder exists at: {chroma_dir}")
    else:
        console.print(f"  [yellow]![/yellow] ChromaDB folder does not exist yet (will be created on first indexing).")

    # 5. Measure Embedding Latency (If Provider is Online)
    active_ok = ollama_ok if provider == "ollama" else lmstudio_ok
    if active_ok:
        console.print("\n[bold]⚡ Running Embedding Latency check...[/bold]")
        try:
            t0 = time.time()
            emb_provider = create_provider(provider, config)
            # Embed a single test sentence
            vector = emb_provider.embed_query("fourtindex health check sentence")
            latency = (time.time() - t0) * 1000.0
            console.print(f"  [green]✓[/green] Generated embedding successfully (dim={len(vector)}) in [bold green]{latency:.2f}ms[/bold green]")
        except Exception as e:
            console.print(f"  [red]✗[/red] Embedding generation failed: {e}")
            all_ok = False

    # 6. Summary Result
    console.print("\n--------------------------------------------------")
    if all_ok:
        console.print("[bold green]✓ FourTIndex is HEALTHY and ready to index/query![/bold green]\n")
    else:
        console.print("[bold red]✗ Some checks failed. Please inspect the logs above to troubleshoot.[/bold red]\n")
        
    return all_ok
