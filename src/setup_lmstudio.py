import sys
import os
import json
import subprocess
import urllib.request
import urllib.error
import time
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

from src.config import Config
from src.lmstudio_client import LMStudioClient

console = Console()

# Mapping from local model name -> Hugging Face repo ID for auto-pull
HF_MODEL_REGISTRY = {
    "monas": "trungvn2401s/monas",
}

def pull_from_huggingface(model_name: str) -> bool:
    """Attempts to pull a model into LM Studio using its HF deep link or lms CLI."""
    hf_repo = HF_MODEL_REGISTRY.get(model_name)
    if hf_repo:
        deep_link = f"lmstudio://open_from_hf?model={hf_repo}"
        console.print(f"Opening LM Studio deep link: [cyan]{deep_link}[/cyan]")
        try:
            os.startfile(deep_link)
            console.print("[yellow]LM Studio should open and start downloading. Please wait for it to finish.[/yellow]")
            console.print("Press Enter when the download is complete...")
            input()
            return True
        except Exception as e:
            console.print(f"[yellow]Warning: Deep link failed ({e}). Falling back to lms CLI...[/yellow]")
    
    # Fallback: use lms get
    try:
        target = hf_repo if hf_repo else model_name
        console.print(f"Running 'lms get {target}'...")
        subprocess.run(["lms", "get", target], check=False)
        return True
    except Exception as e:
        console.print(f"[yellow]Warning: Could not execute 'lms get': {e}[/yellow]")
        return False

def check_lmstudio(client: LMStudioClient) -> bool:
    """Checks if LM Studio is running and reachable."""
    console.print(f"Connecting to LM Studio at [cyan]{client.host}[/cyan]...")
    try:
        # Check by listing models (simplest endpoint)
        res = client.list_models()
        if "error" in res:
            console.print(f"[bold red]✗ Connection failed:[/bold red] {res['error']}")
            return False
        console.print("[bold green]✓ LM Studio is running and reachable![/bold green]")
        return True
    except Exception as e:
        console.print(f"[bold red]✗ Cannot connect to LM Studio at {client.host}.[/bold red]")
        console.print("Please verify that:")
        console.print("  1. The LM Studio developer server is started (or run 'lms server start').")
        console.print("  2. The port number matches your configuration.")
        console.print(f"  Error details: {e}")
        return False

def verify_and_load_model(client: LMStudioClient, model_name: str, model_type: str) -> bool:
    """Checks if model is available, downloads if missing, and loads if not in memory."""
    console.print(f"\nVerifying {model_type} model: [cyan]{model_name}[/cyan]...")
    
    # 1. Get models list
    models_res = client.list_models()
    if "error" in models_res:
        console.print(f"[bold red]✗ Failed to retrieve models list:[/bold red] {models_res['error']}")
        return False
        
    # Standard LM Studio v1 response contains "data" array of models
    models_data = models_res.get("data", [])
    
    # Check if the model is already loaded (it would be in the list of active models)
    is_available = False
    for m in models_data:
        if m.get("id") == model_name:
            is_available = True
            break
            
    if is_available:
        console.print(f"[bold green]✓ Model '{model_name}' is available and loaded in LM Studio![/bold green]")
        return True
        
    # If not loaded, attempt to pull from HF and then load
    console.print(f"Model '{model_name}' is not currently active. Attempting to pull and load it...")
    pull_from_huggingface(model_name)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True
    ) as progress:
        task = progress.add_task(description=f"Loading '{model_name}'...", total=None)
        res = client.load_model(model_name)
        
    if "error" in res:
        console.print(f"[bold red]✗ Failed to load model '{model_name}':[/bold red] {res['error']}")
        console.print("Please ensure the model is downloaded correctly.")
        return False
        
    console.print(f"[bold green]✓ Model '{model_name}' loaded successfully![/bold green]")
    return True

def run_setup() -> bool:
    """Main setup workflow for LM Studio."""
    config = Config()
    client = LMStudioClient(config)
    
    console.print("[bold blue]=== LM Studio Environment Setup ===[/bold blue]\n")
    
    if not check_lmstudio(client):
        return False
        
    llm_model = config.lmstudio_llm_model
    emb_model = config.lmstudio_embedding_model
    rerank_model = config.data.get("rerank", {}).get("model", "qwen3-reranker-0.6b")
    
    success_llm = verify_and_load_model(client, llm_model, "LLM")
    success_emb = verify_and_load_model(client, emb_model, "Embedding")
    
    success_rerank = True
    if config.data.get("rerank", {}).get("enabled", True):
        success_rerank = verify_and_load_model(client, rerank_model, "Reranker")
    
    if success_llm and success_emb and success_rerank:
        # Update config to switch provider to lmstudio
        try:
            import yaml
            with open(config.config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            
            data["provider"] = "lmstudio"
            
            with open(config.config_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, allow_unicode=True)
                
            console.print("\n[bold green]✓ Environment provider switched to 'lmstudio' in config![/bold green]")
        except Exception as e:
            console.print(f"\n[yellow]! Failed to automatically update config provider: {e}[/yellow]")
            
        console.print("\n[bold green]✓ LM Studio setup completed successfully! Ready to run fourTindex.[/bold green]")
        return True
    else:
        console.print("\n[bold red]✗ LM Studio setup completed with errors. Please resolve model loading issues.[/bold red]")
        return False
