import os
import sys
import json
import platform
import urllib.request
import urllib.error
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, DownloadColumn, TransferSpeedColumn
from src.config import Config

console = Console(stderr=True)

def get_installed_models() -> list[str]:
    """Fetches list of installed models from local Ollama service."""
    url = "http://localhost:11434/api/tags"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=3) as response:
            data = json.loads(response.read().decode("utf-8"))
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []

def check_ollama() -> bool:
    """Checks if Ollama service is running. If not, displays OS-specific install guide."""
    url = "http://localhost:11434/api/tags"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=3) as _:
            console.print("[bold green]✓ Ollama is running and accessible at http://localhost:11434[/bold green]")
            return True
    except Exception:
        system = platform.system()
        console.print("[bold red]✗ Ollama is not running or not installed.[/bold red]\n", style="bold")
        console.print("[bold yellow]Installation Guide for your OS:[/bold yellow]")
        
        if system == "Windows":
            console.print("1. Download the Windows installer from: [cyan]https://ollama.com/download/OllamaSetup.exe[/cyan]")
            console.print("2. Run the installer and complete the setup wizard.")
            console.print("3. Launch the Ollama application from the Start Menu or Tray.")
        elif system == "Darwin": # macOS
            console.print("Option A (Download installer):")
            console.print("  - Download the macOS zip from: [cyan]https://ollama.com/download/Ollama-darwin.zip[/cyan]")
            console.print("  - Unzip and drag Ollama to your Applications folder.")
            console.print("Option B (Homebrew):")
            console.print("  - Run: [cyan]brew install ollama[/cyan]")
            console.print("  - Start service: [cyan]brew services start ollama[/cyan]")
        else: # Linux
            console.print("Install using the official curl script:")
            console.print("  - Run: [cyan]curl -fsSL https://ollama.com/install.sh | sh[/cyan]")
            console.print("  - Start service: [cyan]sudo systemctl start ollama[/cyan]")
            
        console.print("\n[yellow]After installing, start Ollama and run this command again to pull models.[/yellow]")
        return False

def pull_model_with_progress(model_name: str) -> bool:
    """Pulls a model from Ollama library displaying a real-time rich progress bar."""
    installed = get_installed_models()
    
    # Try direct name matching and matching without tags (e.g. 'qwen2.5-coder:7b' vs 'qwen2.5-coder:latest')
    if model_name in installed or f"{model_name}:latest" in installed:
        console.print(f"[bold green]✓ Model '{model_name}' is already installed.[/bold green]")
        return True

    console.print(f"[yellow]Pulling model '{model_name}'...[/yellow]")
    url = "http://localhost:11434/api/pull"
    post_data = json.dumps({"name": model_name}).encode("utf-8")
    req = urllib.request.Request(url, data=post_data, headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req) as response:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                DownloadColumn(),
                TransferSpeedColumn(),
            ) as progress:
                task_id = progress.add_task(f"[cyan]Downloading {model_name}...", total=100)
                layers = {}
                
                # Read JSON stream response line by line
                for line in response:
                    if not line:
                        continue
                    try:
                        status_data = json.loads(line.decode("utf-8"))
                        status = status_data.get("status", "")
                        digest = status_data.get("digest")
                        total = status_data.get("total", 0)
                        completed = status_data.get("completed", 0)
                        
                        if digest and total > 0:
                            layers[digest] = (completed, total)
                            sum_completed = sum(c for c, t in layers.values())
                            sum_total = sum(t for c, t in layers.values())
                            progress.update(task_id, completed=sum_completed, total=sum_total, description=f"[cyan]Pulling {model_name}: {status}")
                        else:
                            progress.update(task_id, description=f"[cyan]{model_name}: {status}")
                    except Exception:
                        pass
            console.print(f"[bold green]✓ Successfully pulled model '{model_name}'![/bold green]")
            return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            console.print(f"[bold red]Error: Model '{model_name}' not found in the Ollama library.[/bold red]")
            console.print("[yellow]Please check the model name or configure a fallback like 'nomic-embed-text' in config.yaml.[/yellow]")
        else:
            console.print(f"[bold red]Failed to pull model '{model_name}': HTTP Error {e.code}[/bold red]")
        return False
    except Exception as e:
        console.print(f"[bold red]Network error pulling model '{model_name}': {e}[/bold red]")
        return False

def unload_models() -> bool:
    """Unloads all configured and currently loaded models from local Ollama VRAM/RAM."""
    config = Config()
    host = config.ollama_host.rstrip('/')
    
    # Start with configured models as fallbacks
    models_to_unload = set([
        config.ollama_embedding_model,
        config.ollama_llm_model
    ])
    
    # Try to query currently loaded models via /api/ps
    ps_url = f"{host}/api/ps"
    try:
        req = urllib.request.Request(ps_url)
        with urllib.request.urlopen(req, timeout=3) as response:
            ps_data = json.loads(response.read().decode("utf-8"))
            for m in ps_data.get("models", []):
                model_name = m.get("name") or m.get("model")
                if model_name:
                    models_to_unload.add(model_name)
    except Exception:
        # If Ollama is not running or /api/ps is not supported, ignore and use the fallbacks
        pass
        
    url = f"{host}/api/generate"
    success = True
    
    console.print("[bold blue]Unloading models from Ollama VRAM/RAM...[/bold blue]\n")
    
    # If no models found/configured to unload, return early
    models_list = [m for m in models_to_unload if m]
    if not models_list:
        console.print("No models found to unload.\n")
        return True
        
    for model in models_list:
        try:
            # Passing keep_alive: 0 unloads the model from VRAM/RAM instantly
            post_data = json.dumps({"model": model, "keep_alive": 0}).encode("utf-8")
            req = urllib.request.Request(url, data=post_data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=3) as _:
                console.print(f"  - Unloaded model '[cyan]{model}[/cyan]' from VRAM/RAM. [bold green]✓[/bold green]")
        except Exception as e:
            # Some model names might not be actively loaded or server could be down
            sys.stderr.write(f"  - Failed to unload model '{model}': {e}\n")
            success = False
            
    if success:
        console.print("\n[bold green]✓ All running models unloaded successfully. VRAM & RAM freed![/bold green]")
    return success


def run_setup() -> bool:
    """Main setup workflow to verify Ollama status and pull necessary models."""
    config = Config()
    console.print("[bold blue]=== Ollama Environment Setup ===[/bold blue]\n")
    
    if not check_ollama():
        sys.exit(1)
        
    embedding_model = config.ollama_embedding_model
    llm_model = config.ollama_llm_model
    
    console.print("\n[bold blue]Checking required models:[/bold blue]")
    console.print(f"  - Embedding Model: [cyan]{embedding_model}[/cyan]")
    console.print(f"  - LLM Model:       [cyan]{llm_model}[/cyan]\n")
    
    success_emb = pull_model_with_progress(embedding_model)
    success_llm = pull_model_with_progress(llm_model)
    
    if success_emb and success_llm:
        console.print("\n[bold green]✓ Environment setup completed successfully! Ready to run fourTindex.[/bold green]")
        return True
    else:
        console.print("\n[bold red]✗ Environment setup completed with errors. Some models failed to pull.[/bold red]")
        return False
