import json
import logging
import math
from typing import Any, Dict, List

from src.config import Config

logger = logging.getLogger("fourTindex.reranker")

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
            import os
            # Import sentence_transformers inside initialization to keep startup times fast
            from sentence_transformers import CrossEncoder
            model_path = self.model_name
            if model_path == "monas-reranker":
                if not os.path.isdir(model_path):
                    model_path = "trungvn2401s/monas-reranker"
            try:
                self.model = CrossEncoder(model_path, local_files_only=True)
            except Exception:
                try:
                    self.model = CrossEncoder(model_path, local_files_only=False)
                except TypeError:
                    self.model = CrossEncoder(model_path)

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
        """Reranks all candidates in one validated LM Studio request."""
        system_prompt = (
            "Rank every document for relevance to the query. Return only a JSON array "
            "with one object per document: {\"index\": integer, \"score\": number}. "
            "Scores must be between 0 and 1. Include every index exactly once."
        )
        request_body = {
            "query": query,
            "documents": [
                {"index": index, "content": chunk.get("content", "")}
                for index, chunk in enumerate(chunks)
            ],
        }
        try:
            response = self.lm_client._chat_completions(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(request_body)},
                ],
                stream=False,
                temperature=0.0,
                max_tokens=max(64, len(chunks) * 24),
                timeout=10,
            )
            if "error" in response:
                raise RuntimeError(str(response["error"]))
            output = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            logger.debug("LM Studio reranker output: %.500s", output)
            parsed = json.loads(output)
            if not isinstance(parsed, list) or len(parsed) != len(chunks):
                raise ValueError("reranker output must contain one score per candidate")

            scores = {}
            for item in parsed:
                if not isinstance(item, dict) or isinstance(item.get("index"), bool):
                    raise ValueError("reranker item must contain an integer index")
                index = item.get("index")
                score = item.get("score")
                if not isinstance(index, int) or index < 0 or index >= len(chunks):
                    raise ValueError("reranker index is out of range")
                if index in scores:
                    raise ValueError("reranker index is duplicated")
                if isinstance(score, bool) or not isinstance(score, (int, float)):
                    raise ValueError("reranker score must be numeric")
                score = float(score)
                if not math.isfinite(score) or not 0.0 <= score <= 1.0:
                    raise ValueError("reranker score is outside [0, 1]")
                scores[index] = score

            for index, chunk in enumerate(chunks):
                chunk["rerank_score"] = scores[index]
            return sorted(
                chunks, key=lambda item: item["rerank_score"], reverse=True
            )[:top_k]
        except Exception as exc:
            logger.warning("LM Studio reranking failed; using retrieval order: %s", exc)
            return chunks[:top_k]
