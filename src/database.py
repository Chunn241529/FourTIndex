import os
import json
import tempfile
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
        self.code_chunks = self._safe_get_collection(
            name="code_chunks",
            metadata={"hnsw:space": "cosine"}  # Use cosine similarity for embeddings
        )
        self.file_outlines = self._safe_get_collection(
            name="file_outlines",
            metadata={"hnsw:space": "cosine"}
        )
        self.session_memories = self._safe_get_collection(
            name="session_memories",
            metadata={"hnsw:space": "cosine"}
        )
        self.skills = self._safe_get_collection(
            name="skills",
            metadata={"hnsw:space": "cosine"}
        )

        # Initialize SQLite Registry DB for roadmaps
        self.registry_db_path = self.config.registry_db_path
        self._init_registry_db()

    @staticmethod
    def _project_collection_names(project_id: str, store_id: str) -> tuple[str, str]:
        suffix = f"{project_id}_{store_id}".replace("-", "_")
        return f"code_{suffix}", f"outline_{suffix}"

    def _safe_get_collection(self, name: str, metadata: dict = None):
        try:
            return self.client.get_collection(name=name)
        except Exception:
            return self.client.get_or_create_collection(name=name, metadata=metadata)

    def _connect_db(self):
        import sqlite3
        conn = sqlite3.connect(self.registry_db_path)
        try:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("PRAGMA cache_size = -64000;")
        except Exception:
            pass
        return conn

    def get_project_collections(self, project_id: str, store_id: str):
        code_name, outline_name = self._project_collection_names(project_id, store_id)
        code = self._safe_get_collection(
            name=code_name, metadata={"hnsw:space": "cosine"}
        )
        outlines = self._safe_get_collection(
            name=outline_name, metadata={"hnsw:space": "cosine"}
        )
        return code, outlines

    def delete_project_store(self, project_id: str, store_id: str) -> None:
        for name in self._project_collection_names(project_id, store_id):
            try:
                self.client.delete_collection(name)
            except Exception:
                pass
        # Sync with FTS5
        try:
            with self._connect_db() as conn:
                conn.execute("DELETE FROM code_chunks_fts WHERE project_id = ? AND store_id = ?", (project_id, store_id))
                conn.commit()
        except Exception:
            pass

    def delete_legacy_project(self, project_name: str) -> None:
        where = {"project_name": project_name}
        self.code_chunks.delete(where=where)
        self.file_outlines.delete(where=where)
        # Sync with FTS5
        try:
            with self._connect_db() as conn:
                conn.execute("DELETE FROM code_chunks_fts WHERE project_name = ?", (project_name,))
                conn.commit()
        except Exception:
            pass

    def upsert_project_records(
        self,
        project_id: str,
        store_id: str,
        code_records: list[dict],
        outline_records: list[dict],
    ) -> None:
        code, outlines = self.get_project_collections(project_id, store_id)
        self._upsert_records(code, code_records)
        self._upsert_records(outlines, outline_records)
        
        # Sync with FTS5
        if code_records:
            try:
                with self._connect_db() as conn:
                    data_to_insert = []
                    for item in code_records:
                        proj_name = item["metadata"].get("project_name", "")
                        file_path = item["metadata"].get("file_path", "")
                        data_to_insert.append((
                            item["id"],
                            item["document"],
                            proj_name,
                            file_path,
                            project_id,
                            store_id
                        ))
                    
                    conn.executemany("""
                        INSERT OR REPLACE INTO code_chunks_fts (id, content, project_name, file_path, project_id, store_id)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, data_to_insert)
                    conn.commit()
            except Exception as e:
                import sys
                sys.stderr.write(f"Warning: Failed to index in FTS5: {e}\n")

    def _upsert_records(self, collection, records: list[dict]) -> None:
        if not records:
            return
        get_limit = getattr(self.client, "get_max_batch_size", None)
        batch_limit = get_limit() if callable(get_limit) else 5000
        for start in range(0, len(records), batch_limit):
            batch = records[start : start + batch_limit]
            collection.upsert(
                ids=[item["id"] for item in batch],
                embeddings=[item["embedding"] for item in batch],
                documents=[item["document"] for item in batch],
                metadatas=[item["metadata"] for item in batch],
            )

    def delete_project_ids(
        self,
        project_id: str,
        store_id: str,
        code_ids: list[str] | None = None,
        outline_ids: list[str] | None = None,
    ) -> None:
        code, outlines = self.get_project_collections(project_id, store_id)
        if code_ids:
            code.delete(ids=code_ids)
            # Sync with FTS5
            try:
                with self._connect_db() as conn:
                    for i in range(0, len(code_ids), 999):
                        batch = code_ids[i:i+999]
                        placeholders = ",".join("?" for _ in batch)
                        conn.execute(f"DELETE FROM code_chunks_fts WHERE id IN ({placeholders})", batch)
                    conn.commit()
            except Exception:
                pass
        if outline_ids:
            outlines.delete(ids=outline_ids)

    def search_project_code(
        self,
        project_id: str,
        store_id: str,
        query_embedding: list[float],
        limit: int = 5,
        file_ext: str | None = None,
        language: str | None = None,
    ) -> list[dict]:
        code, _ = self.get_project_collections(project_id, store_id)
        if code.count() == 0:
            return []
            
        where_clauses = []
        if file_ext:
            where_clauses.append({"file_ext": file_ext})
        if language:
            where_clauses.append({"language": language.lower()})
            
        if len(where_clauses) == 1:
            where = where_clauses[0]
        elif len(where_clauses) > 1:
            where = {"$and": where_clauses}
        else:
            where = None
            
        results = code.query(
            query_embeddings=[query_embedding],
            n_results=min(limit, code.count()),
            where=where,
        )
        return self._format_query_results(results)

    @staticmethod
    def _format_query_results(results: dict) -> list[dict]:
        if not results.get("documents") or not results["documents"][0]:
            return []
        documents = results["documents"][0]
        metadatas = results["metadatas"][0]
        identifiers = results["ids"][0]
        distances = results.get("distances", [[0.0] * len(documents)])[0]
        return [
            {
                "id": identifiers[index],
                "content": document,
                "metadata": metadatas[index],
                "score": 1.0 - distances[index],
            }
            for index, document in enumerate(documents)
        ]

    def search_project_code_fts(
        self,
        project_id: str,
        store_id: str,
        query: str,
        limit: int = 30,
    ) -> list[dict]:
        """Searches project code chunks using SQLite FTS5 BM25 search."""
        import sqlite3
        import re
        
        words = [w for w in re.findall(r'\w+', query) if w]
        if not words:
            return []
        
        # Broad match using OR for ranking
        match_expr = " OR ".join(words)
        results = []
        
        try:
            with self._connect_db() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id FROM code_chunks_fts 
                    WHERE project_id = ? AND store_id = ? AND content MATCH ?
                    LIMIT ?
                """, (project_id, store_id, match_expr, limit))
                ids = [row[0] for row in cursor.fetchall()]
                
                if ids:
                    # Fetch documents from ChromaDB
                    code, _ = self.get_project_collections(project_id, store_id)
                    retrieved = code.get(ids=ids, include=["documents", "metadatas"])
                    if retrieved and "documents" in retrieved and retrieved["documents"]:
                        docs = retrieved["documents"]
                        metas = retrieved["metadatas"]
                        retrieved_ids = retrieved["ids"]
                        
                        id_map = {retrieved_ids[i]: (docs[i], metas[i]) for i in range(len(retrieved_ids))}
                        for rank, item_id in enumerate(ids):
                            if item_id in id_map:
                                doc, meta = id_map[item_id]
                                results.append({
                                    "id": item_id,
                                    "content": doc,
                                    "metadata": meta,
                                    "fts_rank": rank
                                })
        except Exception as e:
            import sys
            sys.stderr.write(f"Warning: FTS5 search error: {e}\n")
            
        return results

    def get_project_outline(self, project_id: str, store_id: str, file_path: str) -> str | None:
        _, outlines = self.get_project_collections(project_id, store_id)
        result = outlines.get(where={"file_path": file_path}, include=["documents"])
        documents = result.get("documents") or []
        return documents[0] if documents else None

    def get_project_symbol(self, project_id: str, store_id: str, symbol_name: str) -> str | None:
        code, _ = self.get_project_collections(project_id, store_id)
        result = code.get(where={"symbol_name": symbol_name}, include=["documents"])
        documents = result.get("documents") or []
        return documents[0] if documents else None

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
        except Exception:
            pass
            
        # Sync with FTS5
        try:
            with self._connect_db() as conn:
                conn.execute("DELETE FROM code_chunks_fts WHERE project_name = ? AND file_path = ?", (project_name, relative_path))
                conn.commit()
        except Exception:
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
        try:
            self.session_memories.upsert(
                ids=[memory_id],
                embeddings=[embedding],
                documents=[content],
                metadatas=[metadata]
            )
        except Exception as e:
            if "expecting embedding with dimension of" in str(e):
                import sys
                sys.stderr.write("Warning: Session memory collection dimension mismatch. Recreating...\n")
                try:
                    self.client.delete_collection("session_memories")
                    self.session_memories = self.client.get_or_create_collection(
                        name="session_memories",
                        metadata={"hnsw:space": "cosine"}
                    )
                    self.session_memories.upsert(
                        ids=[memory_id],
                        embeddings=[embedding],
                        documents=[content],
                        metadatas=[metadata]
                    )
                except Exception as ex:
                    raise RuntimeError(f"Failed to reset session memories collection: {ex}") from ex
            else:
                raise

    def search_session_memories(self, query_embedding: list[float], project_name: str, limit: int = 3) -> list[dict]:
        """Searches past session memories."""
        where_clause = {"project_name": project_name}
        try:
            results = self.session_memories.query(
                query_embeddings=[query_embedding],
                n_results=limit,
                where=where_clause
            )
        except Exception as e:
            if "expecting embedding with dimension of" in str(e):
                return []
            raise
        
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
        registry_path = os.path.expanduser("~/.fourtindex/project_registry.json")
        registry_directory = os.path.dirname(registry_path)
        os.makedirs(registry_directory, exist_ok=True)
        data = {}
        if os.path.exists(registry_path):
            try:
                with open(registry_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    raise ValueError("Project registry must contain a JSON object")
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"Unable to read project registry: {exc}") from exc
        data[project_name] = os.path.abspath(project_path).replace("\\", "/")
        descriptor, temporary_path = tempfile.mkstemp(
            prefix="project_registry_", suffix=".json", dir=registry_directory
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary_path, registry_path)
        except OSError as exc:
            raise RuntimeError(f"Unable to write project registry: {exc}") from exc
        finally:
            if os.path.exists(temporary_path):
                os.unlink(temporary_path)

    def get_project_path(self, project_name: str) -> str | None:
        """Retrieves the absolute path for a given project_name."""
        registry_path = os.path.expanduser("~/.fourtindex/project_registry.json")
        if os.path.exists(registry_path):
            try:
                with open(registry_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if not isinstance(data, dict):
                        raise ValueError("Project registry must contain a JSON object")
                    return data.get(project_name)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"Unable to read project registry: {exc}") from exc
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
        try:
            self.skills.upsert(
                ids=ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas
            )
        except Exception as e:
            if "expecting embedding with dimension of" in str(e):
                import sys
                sys.stderr.write("Warning: Skills collection dimension mismatch. Recreating...\n")
                try:
                    self.client.delete_collection("skills")
                    self.skills = self.client.get_or_create_collection(
                        name="skills",
                        metadata={"hnsw:space": "cosine"}
                    )
                    self.skills.upsert(
                        ids=ids,
                        embeddings=embeddings,
                        documents=documents,
                        metadatas=metadatas
                    )
                except Exception as ex:
                    raise RuntimeError(f"Failed to reset skills collection: {ex}") from ex
            else:
                raise

    def search_skills(self, query_embedding: list[float], project_name: str, limit: int = 3) -> list[dict]:
        """Searches for relevant skill sections using vector similarity."""
        where_clause = {"project_name": project_name}
        try:
            results = self.skills.query(
                query_embeddings=[query_embedding],
                n_results=limit,
                where=where_clause
            )
        except Exception as e:
            if "expecting embedding with dimension of" in str(e):
                return []
            raise
        
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

    def _init_registry_db(self):
        os.makedirs(os.path.dirname(self.registry_db_path), exist_ok=True)
        with self._connect_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS project_roadmaps (
                    project_name TEXT PRIMARY KEY,
                    directory_tree_json TEXT,
                    framework_signatures_json TEXT,
                    last_updated TEXT
                )
            """)
            try:
                # virtual table code_chunks_fts for hybrid search BM25
                conn.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS code_chunks_fts USING fts5(
                        id UNINDEXED, 
                        content, 
                        project_name UNINDEXED,
                        file_path UNINDEXED,
                        project_id UNINDEXED,
                        store_id UNINDEXED
                    )
                """)
            except Exception as e:
                import sys
                sys.stderr.write(f"Warning: FTS5 not supported in sqlite3: {e}\n")
            conn.commit()

    def save_project_roadmap(self, project_name: str, directory_tree: dict, framework_signatures: list[str]):
        """Saves the project roadmap to the SQLite registry database."""
        import datetime
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        with self._connect_db() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO project_roadmaps (project_name, directory_tree_json, framework_signatures_json, last_updated)
                VALUES (?, ?, ?, ?)
            """, (
                project_name,
                json.dumps(directory_tree),
                json.dumps(framework_signatures),
                now_str
            ))
            conn.commit()

    def get_project_roadmap(self, project_name: str) -> dict | None:
        """Retrieves the project roadmap from the SQLite registry database."""
        with self._connect_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT directory_tree_json, framework_signatures_json, last_updated
                FROM project_roadmaps
                WHERE project_name = ?
            """, (project_name,))
            row = cursor.fetchone()
            if row:
                return {
                    "project_name": project_name,
                    "directory_tree": json.loads(row[0]),
                    "framework_signatures": json.loads(row[1]),
                    "last_updated": row[2]
                }
        return None

    def list_projects(self) -> list[dict]:
        """Lists all registered projects with roadmaps from the SQLite registry database."""
        projects = []
        with self._connect_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT project_name, framework_signatures_json, last_updated
                FROM project_roadmaps
            """)
            for row in cursor.fetchall():
                projects.append({
                    "project_name": row[0],
                    "framework_signatures": json.loads(row[1]),
                    "last_updated": row[2]
                })
        return projects

    def build_project_roadmap(self, project_root: str) -> tuple[dict, list[str]]:
        """Crawls the project directory recursively to build a structural JSON tree and detect framework signatures, respecting ignore files."""
        import pathspec
        project_root = os.path.abspath(project_root)
        ignore_lines = list(self.config.exclude_globs)
        default_ignores = [
            "package-lock.json",
            "yarn.lock",
            "pnpm-lock.yaml",
            "bun.lockb",
            "*.min.js",
            "*.min.css",
            "*.map"
        ]
        for item in default_ignores:
            if item not in ignore_lines:
                ignore_lines.append(item)
        if self.config.respect_gitignore:
            for ignore_name in (".gitignore", ".fourtindexignore"):
                ignore_path = os.path.join(project_root, ignore_name)
                if os.path.exists(ignore_path):
                    try:
                        with open(ignore_path, "r", encoding="utf-8", errors="replace") as file:
                            ignore_lines.extend(file.read().splitlines())
                    except OSError:
                        pass
        ignore_spec = pathspec.GitIgnoreSpec.from_lines(ignore_lines)
        exclude_dirs = [os.path.normpath(os.path.join(project_root, d)) for d in self.config.exclude_dirs]
        exclude_names = set(self.config.exclude_dirs)

        detected_signatures = set()

        def crawl(current_dir: str) -> dict | None:
            rel_path = os.path.relpath(current_dir, project_root).replace("\\", "/")
            if rel_path == ".":
                rel_path = ""
            
            if rel_path and ignore_spec.match_file(rel_path + "/"):
                return None

            node_name = os.path.basename(current_dir) or project_root
            node = {
                "name": node_name,
                "type": "directory",
                "children": []
            }

            try:
                entries = os.listdir(current_dir)
            except OSError:
                return None

            for entry in entries:
                full_path = os.path.normpath(os.path.join(current_dir, entry))
                entry_rel = os.path.relpath(full_path, project_root).replace("\\", "/")

                if os.path.isdir(full_path):
                    if entry in exclude_names or full_path in exclude_dirs:
                        continue
                    child_node = crawl(full_path)
                    if child_node:
                        node["children"].append(child_node)
                else:
                    if ignore_spec.match_file(entry_rel):
                        continue
                    
                    ext = os.path.splitext(entry)[1].lower()
                    if ext == ".csproj":
                        detected_signatures.add("Unity (C#)" if "Unity" in entry or "Assembly" in entry else "C# Project")
                    elif ext == ".uproject":
                        detected_signatures.add("Unreal Engine")
                    elif entry == "project.godot":
                        detected_signatures.add("Godot Engine")
                    elif entry == "package.json":
                        try:
                            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                                pdata = json.load(f)
                                deps = pdata.get("dependencies", {})
                                dev_deps = pdata.get("devDependencies", {})
                                all_deps = {**deps, **dev_deps}
                                if any("cocos" in k.lower() for k in all_deps):
                                    detected_signatures.add("Cocos Creator")
                                else:
                                    detected_signatures.add("Node.js/JavaScript")
                        except Exception:
                            detected_signatures.add("Node.js/JavaScript")
                    elif entry in ("main.lua", "init.lua"):
                        if os.path.exists(os.path.join(current_dir, "default.project.json")):
                            detected_signatures.add("Roblox (Lua)")
                    elif entry in ("pyproject.toml", "setup.py", "requirements.txt", "Pipfile", "poetry.lock"):
                        detected_signatures.add("Python")
                        if entry == "pyproject.toml":
                            try:
                                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                                    toml_content = f.read().lower()
                                    if "fastapi" in toml_content:
                                        detected_signatures.add("FastAPI")
                                    if "django" in toml_content:
                                        detected_signatures.add("Django")
                                    if "pytest" in toml_content:
                                        detected_signatures.add("pytest")
                            except Exception:
                                pass
                        elif entry == "requirements.txt":
                            try:
                                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                                    req_content = f.read().lower()
                                    if "fastapi" in req_content:
                                        detected_signatures.add("FastAPI")
                                    if "django" in req_content:
                                        detected_signatures.add("Django")
                                    if "pytest" in req_content:
                                        detected_signatures.add("pytest")
                            except Exception:
                                pass
                    elif entry == "manage.py":
                        detected_signatures.add("Django")
                        detected_signatures.add("Python")
                    elif ext == ".py":
                        detected_signatures.add("Python")
                    
                    node["children"].append({
                        "name": entry,
                        "type": "file"
                    })
            
            node["children"].sort(key=lambda x: (0 if x["type"] == "directory" else 1, x["name"].lower()))
            return node

        tree = crawl(project_root)
        if os.path.exists(os.path.join(project_root, "default.project.json")):
            detected_signatures.add("Roblox (Lua)")

        return tree or {}, list(detected_signatures)
