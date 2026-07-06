import hashlib
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable

from src.config import Config
from src.database import Database
from src.embedding import EmbeddingManager, EmbeddingProfile
from src.embedding.base import ProviderError, ProviderInputError
from src.indexer import Indexer
from src.manifest import IndexManifest


@dataclass
class IndexOptions:
    embedding_provider: str = "auto"
    rebuild: bool = False
    force: bool = False
    batch_size: int | None = None
    workers: int | None = None


@dataclass
class IndexResult:
    project_name: str
    provider: str
    model: str
    scanned: int = 0
    indexed: int = 0
    skipped: int = 0
    removed: int = 0
    failed: list[str] = field(default_factory=list)
    chunks: int = 0
    requests: int = 0
    tokens: int = 0
    duration_seconds: float = 0.0

    @property
    def completed(self) -> bool:
        return not self.failed

    def summary(self) -> str:
        return (
            f"Indexing finished with {self.provider}/{self.model}. "
            f"Indexed {self.indexed} files ({self.chunks} chunks), skipped {self.skipped}, "
            f"removed {self.removed}, failed {len(self.failed)}. "
            f"Requests: {self.requests}, tokens: {self.tokens}, "
            f"duration: {self.duration_seconds:.2f}s."
        )


@dataclass
class FileRecord:
    absolute_path: str
    relative_path: str
    content_hash: str
    size: int
    modified_ns: int
    chunks: list[dict]
    outline: str
    chunk_embeddings: list[list[float]] = field(default_factory=list)
    outline_embedding: list[float] = field(default_factory=list)


class IndexingService:
    def __init__(self, config: Config):
        self.config = config
        self.indexer = Indexer(config)
        self.database = Database(config)
        self.embedding = EmbeddingManager(config)
        state_directory = os.path.dirname(config.db_persist_directory)
        self.manifest = IndexManifest(state_directory)

    def index_project(
        self,
        project_path: str,
        project_name: str,
        options: IndexOptions | None = None,
        progress: Callable[[str, int, int], None] | None = None,
    ) -> IndexResult:
        options = options or IndexOptions()
        started_at = time.perf_counter()
        root = os.path.abspath(project_path)
        if not os.path.isdir(root):
            raise ValueError(f"Project path is not a directory: {project_path}")

        project = self.manifest.register_project(project_name, root)
        store, provider, pending = self._resolve_store(
            project, project_name, root, options
        )
        result = IndexResult(project_name, provider.name, provider.model)
        files = self.indexer.scan_files(root)
        result.scanned = len(files)
        self._notify(progress, "scan", result.scanned, result.scanned)

        existing = store.setdefault("files", {})
        file_states = self._hash_files(root, files, options.workers or self.config.parse_workers)
        changed = [
            state
            for state in file_states
            if options.force or existing.get(state[1], {}).get("hash") != state[2]
        ]
        result.skipped = len(file_states) - len(changed)

        parsed = self._parse_files(changed, options.workers or self.config.parse_workers, result)
        total_groups = max(1, (len(parsed) + self.config.commit_batch_files - 1) // self.config.commit_batch_files)
        for group_index, start in enumerate(
            range(0, len(parsed), self.config.commit_batch_files), start=1
        ):
            group = parsed[start : start + self.config.commit_batch_files]
            successful = self._embed_group(group, options, result)
            if successful:
                self._commit_group(project, store, successful, result)
            self._notify(progress, "index", group_index, total_groups)

        current_paths = {state[1] for state in file_states}
        removed_paths = sorted(set(existing) - current_paths)
        self._remove_paths(project, store, removed_paths)
        for relative_path in removed_paths:
            existing.pop(relative_path, None)
        result.removed = len(removed_paths)
        self.manifest.save()

        if pending and not result.failed and len(existing) == len(current_paths):
            previous_store = self.manifest.complete_store(project, store)
            self.database.delete_legacy_project(project_name)
            if previous_store and previous_store != store["store_id"]:
                self.database.delete_project_store(project["project_id"], previous_store)
                self.manifest.remove_store(project, previous_store)

        self.database.save_project_path(project_name, root)
        
        # Save project structure roadmap in registry.db
        try:
            tree, signatures = self.database.build_project_roadmap(root)
            self.database.save_project_roadmap(project_name, tree, signatures)
        except Exception as e:
            sys.stderr.write(f"Warning: Failed to save project roadmap: {e}\n")

        result.requests = provider.request_count
        result.tokens = provider.token_count
        result.duration_seconds = time.perf_counter() - started_at
        return result

    def _resolve_store(
        self, project: dict, project_name: str, project_path: str, options: IndexOptions
    ):
        active = self.manifest.active_store(project)
        pending = self.manifest.pending_store(project)

        if options.rebuild:
            provider = self.embedding.select_for_new_index(options.embedding_provider)
            self.embedding.provider = provider
            return self.manifest.begin_store(project, provider.profile()), provider, True

        if pending:
            profile = EmbeddingProfile.from_dict(pending["profile"])
            provider = self.embedding.load_profile(profile)
            return pending, provider, True

        if active:
            profile = EmbeddingProfile.from_dict(active["profile"])
            if options.embedding_provider not in ("auto", profile.provider):
                raise ProviderError(
                    "Changing embedding providers requires --rebuild because vector spaces are incompatible"
                )
            provider = self.embedding.load_profile(profile)
            return active, provider, False

        legacy_path = self.database.get_project_path(project_name)
        is_legacy_project = bool(
            legacy_path
            and os.path.normcase(os.path.realpath(legacy_path))
            == os.path.normcase(os.path.realpath(project_path))
        )
        requested = "ollama" if is_legacy_project else options.embedding_provider
        provider = self.embedding.select_for_new_index(requested)
        self.embedding.provider = provider
        return self.manifest.begin_store(project, provider.profile()), provider, True

    @staticmethod
    def _hash_files(root: str, files: list[str], workers: int) -> list[tuple]:
        def inspect(path: str) -> tuple:
            stat = os.stat(path)
            relative = os.path.relpath(path, root).replace("\\", "/")
            hasher = hashlib.sha256()
            with open(path, "rb") as file:
                while block := file.read(1024 * 1024):
                    hasher.update(block)
            return path, relative, hasher.hexdigest(), stat.st_size, stat.st_mtime_ns

        with ThreadPoolExecutor(max_workers=workers) as executor:
            return list(executor.map(inspect, files))

    def _parse_files(self, states: list[tuple], workers: int, result: IndexResult) -> list[FileRecord]:
        def parse(state: tuple) -> FileRecord:
            absolute, relative, content_hash, size, modified_ns = state
            chunks = self.indexer.parse_file(absolute, relative)
            outline = self.indexer.generate_file_outline_summary(chunks, relative)
            return FileRecord(
                absolute, relative, content_hash, size, modified_ns, chunks, outline
            )

        records = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [(state, executor.submit(parse, state)) for state in states]
            for state, future in futures:
                try:
                    records.append(future.result())
                except Exception:
                    result.failed.append(state[1])
        return records

    def _embed_group(
        self, records: list[FileRecord], options: IndexOptions, result: IndexResult
    ) -> list[FileRecord]:
        if not records:
            return []
        try:
            self._embed_records(records, options)
            return records
        except ProviderInputError:
            successful = []
            for record in records:
                try:
                    self._embed_records([record], options)
                    successful.append(record)
                except ProviderError:
                    result.failed.append(record.relative_path)
            return successful

    def _embed_records(self, records: list[FileRecord], options: IndexOptions) -> None:
        items = []
        for record in records:
            record.chunk_embeddings = [[] for _ in record.chunks]
            record.outline_embedding = []
            items.extend((record, "chunk", index, chunk["content"]) for index, chunk in enumerate(record.chunks))
            items.append((record, "outline", 0, record.outline))

        provider = self.embedding.provider
        batch_limit = min(
            options.batch_size or self.config.embedding_batch_size,
            provider.max_batch_items if provider else self.config.embedding_batch_size,
        )
        for batch in self._pack_batches(items, batch_limit, self.config.embedding_batch_max_chars):
            vectors = self.embedding.embed_documents([item[3] for item in batch])
            for item, vector in zip(batch, vectors):
                record, kind, index, _ = item
                if kind == "chunk":
                    record.chunk_embeddings[index] = vector
                else:
                    record.outline_embedding = vector

    @staticmethod
    def _pack_batches(items: list[tuple], max_items: int, max_chars: int):
        batch = []
        character_count = 0
        for item in items:
            item_size = len(item[3])
            if batch and (len(batch) >= max_items or character_count + item_size > max_chars):
                yield batch
                batch = []
                character_count = 0
            batch.append(item)
            character_count += item_size
        if batch:
            yield batch

    def _commit_group(
        self, project: dict, store: dict, records: list[FileRecord], result: IndexResult
    ) -> None:
        code_records = []
        outline_records = []
        stale_ids = []
        files = store["files"]
        for record in records:
            digest = hashlib.sha256(record.relative_path.encode("utf-8")).hexdigest()[:16]
            file_ext = os.path.splitext(record.relative_path)[1].lower()
            from src.indexer import EXTENSION_TO_LANGUAGE
            lang = EXTENSION_TO_LANGUAGE.get(file_ext, "generic")
            metadata_base = {
                "project_id": project["project_id"],
                "project_name": result.project_name,
                "file_path": record.relative_path,
                "file_name": os.path.basename(record.relative_path),
                "file_ext": file_ext,
                "language": lang,
                "hash": record.content_hash,
            }
            for index, (chunk, embedding) in enumerate(
                zip(record.chunks, record.chunk_embeddings)
            ):
                metadata = dict(metadata_base)
                metadata.update(
                    {
                        "chunk_type": chunk["chunk_type"],
                        "symbol_name": chunk["symbol_name"],
                        "start_line": chunk["start_line"],
                        "end_line": chunk["end_line"],
                    }
                )
                code_records.append(
                    {
                        "id": f"{digest}_chunk_{index}",
                        "embedding": embedding,
                        "document": chunk["content"],
                        "metadata": metadata,
                    }
                )
            outline_records.append(
                {
                    "id": f"{digest}_outline",
                    "embedding": record.outline_embedding,
                    "document": record.outline,
                    "metadata": metadata_base,
                }
            )
            old_count = int(files.get(record.relative_path, {}).get("chunk_count", 0))
            stale_ids.extend(
                f"{digest}_chunk_{index}" for index in range(len(record.chunks), old_count)
            )

        self.database.upsert_project_records(
            project["project_id"], store["store_id"], code_records, outline_records
        )
        if stale_ids:
            self.database.delete_project_ids(
                project["project_id"], store["store_id"], code_ids=stale_ids
            )
        for record in records:
            files[record.relative_path] = {
                "hash": record.content_hash,
                "size": record.size,
                "modified_ns": record.modified_ns,
                "chunk_count": len(record.chunks),
            }
            result.indexed += 1
            result.chunks += len(record.chunks)
        self.manifest.save()

    def _remove_paths(self, project: dict, store: dict, paths: list[str]) -> None:
        for relative_path in paths:
            digest = hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:16]
            count = int(store["files"].get(relative_path, {}).get("chunk_count", 0))
            self.database.delete_project_ids(
                project["project_id"],
                store["store_id"],
                code_ids=[f"{digest}_chunk_{index}" for index in range(count)],
                outline_ids=[f"{digest}_outline"],
            )

    @staticmethod
    def _notify(progress, phase: str, current: int, total: int) -> None:
        if progress:
            progress(phase, current, total)


def load_project_context(config: Config, project_name: str):
    database = Database(config)
    manifest = IndexManifest(os.path.dirname(config.db_persist_directory))
    project = manifest.get_project(project_name)
    if not project:
        raise ValueError(f"Project '{project_name}' has not been indexed with manifest v2")
    store = manifest.active_store(project)
    if not store:
        raise ValueError(f"Project '{project_name}' has no complete index")
    profile = EmbeddingProfile.from_dict(store["profile"])
    manager = EmbeddingManager(config)
    manager.load_profile(profile)
    return database, manager, project, store
