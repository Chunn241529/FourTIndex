import os
import json
import chromadb
from src.config import Config

class Database:
    def __init__(self, config: Config):
        self.config = config
        # Ensure database persist directory exists
        os.makedirs(self.config.db_persist_directory, exist_ok=True)
        
        # Initialize persistent ChromaDB client
        self.client = chromadb.PersistentClient(path=self.config.db_persist_directory)
        
        # Initialize collections
        self.code_chunks = self.client.get_or_create_collection(
            name="code_chunks",
            metadata={"hnsw:space": "cosine"}  # Use cosine similarity for embeddings
        )
        self.file_outlines = self.client.get_or_create_collection(
            name="file_outlines",
            metadata={"hnsw:space": "cosine"}
        )
        self.session_memories = self.client.get_or_create_collection(
            name="session_memories",
            metadata={"hnsw:space": "cosine"}
        )
        self.skills = self.client.get_or_create_collection(
            name="skills",
            metadata={"hnsw:space": "cosine"}
        )

    def delete_file_entries(self, relative_path: str, project_name: str):
        """Deletes all chunks and outline belonging to a specific file in a project."""
        # Deleting old entries prevents orphaned chunks when code is modified
        where_filter = {
            "$and": [
                {"file_path": relative_path},
                {"project_name": project_name}
            ]
        }
        try:
            self.code_chunks.delete(where=where_filter)
            self.file_outlines.delete(where=where_filter)
        except Exception as e:
            # If the database is empty or filters have issues, catch safely
            pass

    def upsert_code_chunks(self, ids: list[str], embeddings: list[list[float]], documents: list[str], metadatas: list[dict]):
        """Inserts or updates detailed code chunks into the vector database."""
        if not ids:
            return
        self.code_chunks.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas
        )

    def upsert_file_outline(self, file_id: str, embedding: list[float], outline_text: str, metadata: dict):
        """Inserts or updates the high-level outline of a file."""
        self.file_outlines.upsert(
            ids=[file_id],
            embeddings=[embedding],
            documents=[outline_text],
            metadatas=[metadata]
        )

    def search_code_chunks(self, query_embedding: list[float], project_name: str, limit: int = 5, file_ext: str = None) -> list[dict]:
        """Searches for relevant code chunks using vector similarity."""
        where_conditions = [{"project_name": project_name}]
        
        if file_ext:
            where_conditions.append({"file_ext": file_ext})
            
        where_clause = where_conditions[0] if len(where_conditions) == 1 else {"$and": where_conditions}

        results = self.code_chunks.query(
            query_embeddings=[query_embedding],
            n_results=limit,
            where=where_clause
        )
        
        formatted_results = []
        if results and "documents" in results and results["documents"]:
            docs = results["documents"][0]
            metas = results["metadatas"][0]
            ids = results["ids"][0]
            distances = results["distances"][0] if "distances" in results else [0.0] * len(docs)
            
            for idx in range(len(docs)):
                formatted_results.append({
                    "id": ids[idx],
                    "content": docs[idx],
                    "metadata": metas[idx],
                    "score": 1.0 - distances[idx]  # Convert distance to similarity score
                })
        return formatted_results

    def search_file_outlines(self, query_embedding: list[float], project_name: str, limit: int = 3) -> list[dict]:
        """Searches file outlines for high-level structures."""
        where_clause = {"project_name": project_name}
        results = self.file_outlines.query(
            query_embeddings=[query_embedding],
            n_results=limit,
            where=where_clause
        )
        
        formatted_results = []
        if results and "documents" in results and results["documents"]:
            docs = results["documents"][0]
            metas = results["metadatas"][0]
            ids = results["ids"][0]
            distances = results["distances"][0] if "distances" in results else [0.0] * len(docs)
            
            for idx in range(len(docs)):
                formatted_results.append({
                    "id": ids[idx],
                    "content": docs[idx],
                    "metadata": metas[idx],
                    "score": 1.0 - distances[idx]
                })
        return formatted_results

    def upsert_session_memory(self, memory_id: str, embedding: list[float], content: str, metadata: dict):
        """Saves a session summary memory to retrieve design history later."""
        self.session_memories.upsert(
            ids=[memory_id],
            embeddings=[embedding],
            documents=[content],
            metadatas=[metadata]
        )

    def search_session_memories(self, query_embedding: list[float], project_name: str, limit: int = 3) -> list[dict]:
        """Searches past session memories."""
        where_clause = {"project_name": project_name}
        results = self.session_memories.query(
            query_embeddings=[query_embedding],
            n_results=limit,
            where=where_clause
        )
        
        formatted_results = []
        if results and "documents" in results and results["documents"]:
            docs = results["documents"][0]
            metas = results["metadatas"][0]
            ids = results["ids"][0]
            distances = results["distances"][0] if "distances" in results else [0.0] * len(docs)
            
            for idx in range(len(docs)):
                formatted_results.append({
                    "id": ids[idx],
                    "content": docs[idx],
                    "metadata": metas[idx],
                    "score": 1.0 - distances[idx]
                })
        return formatted_results

    def save_project_path(self, project_name: str, project_path: str):
        """Saves the mapping of project_name to its absolute project_path."""
        registry_path = os.path.join(os.path.dirname(self.config.db_persist_directory), "project_registry.json")
        data = {}
        if os.path.exists(registry_path):
            try:
                with open(registry_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                pass
        data[project_name] = os.path.abspath(project_path).replace("\\", "/")
        try:
            with open(registry_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def get_project_path(self, project_name: str) -> str | None:
        """Retrieves the absolute path for a given project_name."""
        registry_path = os.path.join(os.path.dirname(self.config.db_persist_directory), "project_registry.json")
        if os.path.exists(registry_path):
            try:
                with open(registry_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get(project_name)
            except Exception:
                pass
        return None

    def delete_skill_entries(self, skill_name: str, project_name: str):
        """Deletes all chunks belonging to a specific skill in a project."""
        where_filter = {
            "$and": [
                {"skill_name": skill_name},
                {"project_name": project_name}
            ]
        }
        try:
            self.skills.delete(where=where_filter)
        except Exception:
            pass

    def upsert_skill_chunks(self, ids: list[str], embeddings: list[list[float]], documents: list[str], metadatas: list[dict]):
        """Inserts or updates skill chunks in the vector database."""
        if not ids:
            return
        self.skills.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas
        )

    def search_skills(self, query_embedding: list[float], project_name: str, limit: int = 3) -> list[dict]:
        """Searches for relevant skill sections using vector similarity."""
        where_clause = {"project_name": project_name}
        results = self.skills.query(
            query_embeddings=[query_embedding],
            n_results=limit,
            where=where_clause
        )
        
        formatted_results = []
        if results and "documents" in results and results["documents"]:
            docs = results["documents"][0]
            metas = results["metadatas"][0]
            ids = results["ids"][0]
            distances = results["distances"][0] if "distances" in results else [0.0] * len(docs)
            
            for idx in range(len(docs)):
                formatted_results.append({
                    "id": ids[idx],
                    "content": docs[idx],
                    "metadata": metas[idx],
                    "score": 1.0 - distances[idx]
                })
        return formatted_results
