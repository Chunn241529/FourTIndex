import os
import sys
import json
import logging
import urllib.request
import urllib.error
import gc
from src.config import Config
from src.lmstudio_client import LMStudioClient

logger = logging.getLogger("fourTindex.memory_cleaner")

def clean_all_memory(config: Config, unload_models: bool = False) -> str:
    """Cleans memory by running Python garbage collection and clearing CUDA cache.
    Optionally unloads loaded model instances from both LM Studio and Ollama if unload_models is True.
    
    Returns a text report summarizing what cleanup was performed.
    """
    result = []
    
    # 1. Local Python RAM and VRAM cleanup
    gc_count = gc.collect()
    cuda_cleaned = False
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            cuda_cleaned = True
    except Exception:
        pass
        
    local_msg = f"Python garbage collection completed (collected {gc_count} objects)."
    if cuda_cleaned:
        local_msg += " Cleared PyTorch CUDA cache (VRAM)."
    result.append(local_msg)
    
    if unload_models:
        # 2. Clean LM Studio
        try:
            client = LMStudioClient(config)
            # Attempt to unload all running models via API
            unloaded_lmstudio = client.unload_all_models()
            if unloaded_lmstudio:
                result.append(f"Successfully unloaded model(s) from LM Studio: {', '.join(unloaded_lmstudio)}")
            else:
                # Check if LM Studio is reachable by listing models (will raise exception if offline)
                _ = client.list_models()
                result.append("No active models found to unload in LM Studio.")
        except Exception as e:
            logger.debug(f"LM Studio memory cleanup skipped or failed: {e}")
            pass

        # 3. Clean Ollama
        try:
            host = config.ollama_host.rstrip('/')
            ps_url = f"{host}/api/ps"
            models_to_unload = set([
                config.ollama_embedding_model,
                config.ollama_llm_model
            ])
            
            # Discover loaded Ollama models
            try:
                req = urllib.request.Request(ps_url)
                with urllib.request.urlopen(req, timeout=2) as response:
                    ps_data = json.loads(response.read().decode("utf-8"))
                    for m in ps_data.get("models", []):
                        model_name = m.get("name") or m.get("model")
                        if model_name:
                            models_to_unload.add(model_name)
            except Exception:
                pass
                
            unloaded_ollama = []
            url = f"{host}/api/generate"
            for model in models_to_unload:
                if not model:
                    continue
                try:
                    post_data = json.dumps({"model": model, "keep_alive": 0}).encode("utf-8")
                    req = urllib.request.Request(url, data=post_data, headers={"Content-Type": "application/json"})
                    with urllib.request.urlopen(req, timeout=2) as _:
                        unloaded_ollama.append(model)
                except Exception:
                    pass
                    
            if unloaded_ollama:
                result.append(f"Successfully unloaded model(s) from Ollama: {', '.join(unloaded_ollama)}")
            else:
                # Check if Ollama is reachable at all
                try:
                    tags_url = f"{host}/api/tags"
                    req = urllib.request.Request(tags_url)
                    with urllib.request.urlopen(req, timeout=1) as _:
                        result.append("No active models found to unload in Ollama.")
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"Ollama memory cleanup skipped or failed: {e}")
            pass

    # 4. Add token usage report
    try:
        from src.token_meter import evaluate_latest_session
        report = evaluate_latest_session()
        if report:
            result.append("\n" + report.strip())
    except Exception as e:
        logger.error(f"Error in token evaluation during clean_memory: {e}")

    return "\n".join(result)
