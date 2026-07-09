from typing import Any, Dict, List, Optional
import re
from src.config import Config

class LocalReranker:
    def __init__(self, config: Config):
        self.config = config
        self.model_name = self.config.rerank_model
        self.model = None
        self.use_lmstudio = False
        self.lm_client = None

        # Check if the rerank model is currently active in LM Studio
        try:
            from src.lmstudio_client import LMStudioClient
            client = LMStudioClient(config)
            res = client.list_models()
            models_list = res.get("models", res.get("data", []))
            for m in models_list:
                if m.get("key") == self.model_name or m.get("id") == self.model_name:
                    self.use_lmstudio = True
                    self.lm_client = client
                    break
                loaded = m.get("loaded_instances", [])
                for inst in loaded:
                    if inst.get("id") == self.model_name:
                        self.use_lmstudio = True
                        self.lm_client = client
                        break
                if self.use_lmstudio:
                    break
        except Exception:
            pass

    def _lazy_init(self) -> None:
        """Lazy loads sentence-transformers and initializes CrossEncoder model if not using LM Studio."""
        if self.use_lmstudio:
            return
            
        if self.model is None:
            # Import sentence_transformers inside initialization to keep startup times fast
            from sentence_transformers import CrossEncoder
            self.model = CrossEncoder(self.model_name)

    def rerank(self, query: str, chunks: List[Dict[str, Any]], top_k: int = 5) -> List[Dict[str, Any]]:
        """Reranks retrieved codebase chunks based on relevance to query using CrossEncoder or LM Studio API."""
        if not chunks:
            return []
            
        if self.use_lmstudio:
            return self._rerank_via_lmstudio(query, chunks, top_k)
            
        self._lazy_init()
        
        # Prepare inputs: list of [query, document]
        pairs = [[query, chunk.get("content", "")] for chunk in chunks]
        
        try:
            scores = self.model.predict(pairs)
            
            # Map scores to chunks
            for chunk, score in zip(chunks, scores):
                chunk["rerank_score"] = float(score)
                
            # Sort descending by score
            sorted_chunks = sorted(chunks, key=lambda x: x.get("rerank_score", 0.0), reverse=True)
            return sorted_chunks[:top_k]
        except Exception as e:
            # Fail gracefully by falling back to vector search order
            import sys
            sys.stderr.write(f"Warning: Reranker failed with error: {e}. Falling back to vector search order.\n")
            return chunks[:top_k]

    def _rerank_via_lmstudio(self, query: str, chunks: List[Dict[str, Any]], top_k: int = 5) -> List[Dict[str, Any]]:
        """Queries LM Studio chat completions to rank the chunks using the active model."""
        scored_chunks = []
        
        system_prompt = (
            "You are an expert code search ranking assistant.\n"
            "Your task is to evaluate the relevance of a document to a query and output a single float number between 0.0 and 1.0.\n"
            "Output ONLY the numeric float (e.g., 0.85). Do not include any thoughts, conversational filler, or explanation."
        )
        
        for chunk in chunks:
            content = chunk.get("content", "")
            
            try:
                res = self.lm_client.chat_completions(
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": "Query: split array into batches\nDocument: def _pack_batches(items, max_items): ..."},
                        {"role": "assistant", "content": "1.0"},
                        {"role": "user", "content": f"Query: {query}\nDocument: {content}"}
                    ],
                    temperature=0.0,
                    max_tokens=10
                )
                
                output_text = res.get("choices", [{}])[0].get("message", {}).get("content", "0.0").strip()
                file_info = chunk.get("metadata", {}).get("file_path") or chunk.get("metadata", {}).get("file", "unknown")
                import sys
                sys.stderr.write(f"DEBUG - Model output for chunk '{file_info}': '{output_text}'\n")
                
                # Parse numeric score from output
                match = re.search(r"[-+]?\d*\.\d+|\d+", output_text)
                if match:
                    try:
                        score = float(match.group(0))
                        score = max(0.0, min(1.0, score))
                    except ValueError:
                        score = 0.0
                else:
                    score = 0.0
                            
                chunk["rerank_score"] = score
                scored_chunks.append(chunk)
            except Exception as e:
                import sys
                sys.stderr.write(f"LM Studio Reranker error for chunk: {e}\n")
                chunk["rerank_score"] = 0.0
                scored_chunks.append(chunk)
                
        sorted_chunks = sorted(scored_chunks, key=lambda x: x.get("rerank_score", 0.0), reverse=True)
        return sorted_chunks[:top_k]

