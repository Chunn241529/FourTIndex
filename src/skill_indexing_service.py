import datetime
import os

from src.config import Config
from src.database import Database
from src.embedding.manager import EmbeddingManager
from src.indexer import Indexer


def index_skill_file(
    config: Config, file_path: str, project_name: str
) -> dict:
    absolute_path = os.path.abspath(file_path)
    if not os.path.isfile(absolute_path):
        raise FileNotFoundError(f"Skill file not found: {absolute_path}")

    indexer = Indexer(config)
    database = Database(config)
    embedding = EmbeddingManager(config)
    embedding.select_for_new_index()
    relative_path = os.path.relpath(
        absolute_path, config.project_root
    ).replace("\\", "/")
    metadata, chunks = indexer.parse_skill_file(absolute_path, relative_path)
    if not chunks:
        raise ValueError(f"Skill has no indexable sections: {absolute_path}")

    skill_name = metadata.get("name", os.path.basename(os.path.dirname(absolute_path)))
    documents = [chunk["content"] for chunk in chunks]
    embeddings = embedding.embed_documents(documents)
    indexed_at = datetime.datetime.now(datetime.timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )
    source_hash = indexer.compute_file_hash(absolute_path)
    ids = [f"skill_{skill_name}#chunk_{index}" for index in range(len(chunks))]
    metadatas = [
        {
            "project_name": project_name,
            "skill_name": skill_name,
            "file_path": relative_path,
            "heading": chunk["heading"],
            "start_line": chunk["start_line"],
            "end_line": chunk["end_line"],
            "source_hash": source_hash,
            "indexed_at": indexed_at,
        }
        for chunk in chunks
    ]

    database.delete_skill_entries(skill_name, project_name)
    database.upsert_skill_chunks(ids, embeddings, documents, metadatas)
    return {"skill_name": skill_name, "sections": len(ids)}


def index_discovered_skills(config: Config, project_name: str) -> list[dict]:
    skills_root = os.path.join(config.project_root, ".agents", "skills")
    if not os.path.isdir(skills_root):
        return []
    results = []
    for root, _, files in os.walk(skills_root):
        if "SKILL.md" in files:
            results.append(
                index_skill_file(config, os.path.join(root, "SKILL.md"), project_name)
            )
    return results
