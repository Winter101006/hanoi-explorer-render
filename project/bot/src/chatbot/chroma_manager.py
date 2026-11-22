"""ChromaDB Manager for vector storage, metadata filtering, and semantic similarity search.

Maintains collection metadata (model, dimension, version, dataset fingerprint)
to guarantee index compatibility without unneeded startup rebuilding.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

from project.bot.src.chatbot.config import Settings
from project.bot.src.chatbot.embedding import EmbeddingManager, build_document_text
from project.bot.src.chatbot.schemas import Place

logger = logging.getLogger(__name__)


def compute_dataset_fingerprint(places: List[Place]) -> str:
    """Fingerprint the source and derived fields used by search."""
    from dataclasses import asdict
    import json
    content = json.dumps([asdict(p) for p in sorted(places, key=lambda p: p.source.id)],
                         ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]


class ChromaManager:
    """Manages persistent ChromaDB vector store and semantic search operations."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.chroma_path = Path(settings.chroma_path)
        self.chroma_path.mkdir(parents=True, exist_ok=True)

        self.client = chromadb.PersistentClient(
            path=str(self.chroma_path),
            settings=ChromaSettings(anonymized_telemetry=False, is_persistent=True),
        )
        self.collection_name = settings.collection
        self._collection = None

    @property
    def collection(self):
        """Get or initialize the Chroma collection with cosine distance space."""
        if self._collection is None:
            self._collection = self.client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

    def get_collection_metadata(self) -> Dict[str, Any]:
        """Fetch metadata associated with current collection."""
        try:
            return self.collection.metadata or {}
        except Exception:
            return {}

    def is_indexed(self, expected_count: Optional[int] = None) -> bool:
        """Check if vector collection is populated and valid."""
        try:
            count = self.client.get_collection(self.collection_name, embedding_function=None).count()
            if count == 0:
                return False
            if expected_count is not None and count != expected_count:
                return False
            return True
        except Exception as e:
            logger.warning(f"Error checking index status: {e}")
            return False

    def index_places(
        self,
        places: List[Place],
        embedding_manager: Optional[EmbeddingManager] = None,
        batch_size: int = 32,
    ) -> int:
        """Batch encode and upsert places into ChromaDB with rich metadata."""
        if not places:
            return 0

        embedder = embedding_manager or EmbeddingManager(
            model_name=self.settings.embedding_model,
            device=self.settings.device,
        )

        fingerprint = compute_dataset_fingerprint(places)
        metadata_spec = {
            "hnsw:space": "cosine",
            "model": self.settings.embedding_model,
            "dimension": 384,
            "normalized": True,
            "document_version": self.settings.document_version,
            "dataset_fingerprint": fingerprint,
            "total_items": len(places),
        }

        self._collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata=metadata_spec,
            embedding_function=None,
        )
        if any((self._collection.metadata or {}).get(key) != value for key, value in metadata_spec.items()):
            raise ValueError("Collection is incompatible. Set CHROMA_COLLECTION to a new name.")

        total = len(places)
        logger.info(f"Indexing {total} places into Chroma collection '{self.collection_name}'...")

        for i in range(0, total, batch_size):
            batch = places[i : i + batch_size]
            docs = [build_document_text(p) for p in batch]
            ids = [p.source.id for p in batch]

            metadatas: list[dict[str, Any]] = []
            for p in batch:
                meta = {
                    "id": p.source.id,
                    "name": p.source.name,
                    "category": p.source.category,
                    "category_code": p.source.category_code,
                    "normalized_category_code": p.normalized_category_code or "unknown",
                    "district": p.source.district,
                    "address_precision": p.quality.address_precision,
                    "has_conflict": p.quality.category_conflict,
                    "price_status": p.price.status,
                    "price_min": p.price.minimum if p.price.minimum is not None else -1,
                    "price_max": p.price.maximum if p.price.maximum is not None else -1,
                    "weather_fit": p.source.weather_fit or "",
                    "suitable_for": p.source.suitable_for or "",
                }
                metadatas.append(meta)

            vectors = embedder.encode(docs)
            self.collection.upsert(
                ids=ids,
                embeddings=vectors,
                documents=docs,
                metadatas=metadatas,
            )

        logger.info(f"Successfully indexed {total} places.")
        return total

    def search(
        self,
        query_embedding: List[float],
        n_results: int = 20,
        where: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Query ChromaDB by embedding vector and optional metadata filters."""
        params: dict[str, Any] = {
            "query_embeddings": [query_embedding],
            "n_results": n_results,
            "include": ["metadatas", "documents", "distances"],
        }
        if where:
            params["where"] = where

        try:
            res = self.collection.query(**params)
        except Exception as e:
            logger.warning(f"Filtered search failed ({e}), retrying without where clause")
            params.pop("where", None)
            res = self.collection.query(**params)

        results = []
        if res and res["ids"] and len(res["ids"][0]) > 0:
            ids = res["ids"][0]
            distances = res["distances"][0] if "distances" in res and res["distances"] else [0.0] * len(ids)
            metadatas = res["metadatas"][0] if "metadatas" in res and res["metadatas"] else [{}] * len(ids)
            documents = res["documents"][0] if "documents" in res and res["documents"] else [""] * len(ids)

            for item_id, dist, meta, doc in zip(ids, distances, metadatas, documents):
                # Cosine distance in Chroma: dist in [0, 2]
                # Clamp semantic score: 1 - dist in [0, 1]
                semantic_score = max(0.0, min(1.0, 1.0 - float(dist)))
                results.append({
                    "id": item_id,
                    "distance": float(dist),
                    "semantic_score": semantic_score,
                    "metadata": meta,
                    "document": doc,
                })

        return results
