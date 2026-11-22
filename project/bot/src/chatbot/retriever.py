"""Semantic and metadata-filtered place retriever.

Retrieves candidate places using cosine similarity over dense MiniLM embeddings,
filtered by normalized category codes and district locations.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

from project.bot.src.chatbot.config import Settings
from project.bot.src.chatbot.chroma_manager import ChromaManager
from project.bot.src.chatbot.embedding import EmbeddingManager
from project.bot.src.chatbot.schemas import (
    CATEGORY_CODES,
    Place,
    RetrievalResult,
    SearchRequest,
    validate_score,
)

logger = logging.getLogger(__name__)


def _venue_name(text):
    return ' '.join(re.findall(r'\w+', text.casefold()))

HANOI_URBAN_DISTRICTS = {
    'ba đình', 'hoàn kiếm', 'tây hồ', 'long biên', 'cầu giấy',
    'đống đa', 'hai bà trưng', 'hoàng mai', 'thanh xuân',
    'nam từ liêm', 'bắc từ liêm', 'hà đông',
}


def normalize_district_name(district_input: Optional[str]) -> Optional[str]:
    """Match freeform district string to canonical district name in database."""
    if not district_input:
        return None
    d = district_input.strip().lower()
    d = d.removeprefix('quận ').removeprefix('huyện ').strip()
    district_map = {
        'ba đình': 'Ba Đình',
        'hoàn kiếm': 'Hoàn Kiếm',
        'tây hồ': 'Tây Hồ',
        'long biên': 'Long Biên',
        'cầu giấy': 'Cầu Giấy',
        'đống đa': 'Đống Đa',
        'hai bà trưng': 'Hai Bà Trưng',
        'hoàng mai': 'Hoàng Mai',
        'thanh xuân': 'Thanh Xuân',
        'nam từ liêm': 'Nam Từ Liêm',
        'bắc từ liêm': 'Bắc Từ Liêm',
        'hà đông': 'Hà Đông',
        'gia lâm': 'Gia Lâm',
    }
    return district_map.get(d)


class Retriever:
    """Coordinates vector encoding, ChromaDB search, and place hydration."""

    def __init__(
        self,
        settings: Settings,
        chroma_manager: ChromaManager,
        embedding_manager: Optional[EmbeddingManager] = None,
        places: Optional[List[Place]] = None,
    ):
        self.settings = settings
        self.chroma_manager = chroma_manager
        self.embedding_manager = embedding_manager or EmbeddingManager(
            model_name=settings.embedding_model,
            device=settings.device,
        )
        self.places_map: Dict[str, Place] = {}
        if places:
            self.set_places(places)

    def set_places(self, places: List[Place]) -> None:
        """Cache Place objects by ID for fast hydration."""
        self.places_map = {p.source.id: p for p in places}

    def _build_where_filter(self, request: SearchRequest) -> Optional[Dict]:
        """Construct Chroma metadata query conditions."""
        filters = []
        if request.budget_min is not None or request.budget_max is not None:
            filters.append({"price_status": {"$eq": "parsed"}})
            filters.append({"price_max": {"$gte": request.budget_min if request.budget_min is not None else 0}})
        if request.budget_max is not None:
            comparison = "$lt" if request.budget_exclusive else "$lte"
            filters.append({"price_max": {comparison: request.budget_max}})

        if request.category and request.category in CATEGORY_CODES:
            filters.append({"normalized_category_code": {"$eq": request.category}})

        if request.location:
            canonical_district = normalize_district_name(request.location)
            if canonical_district:
                filters.append({"district": {"$eq": canonical_district}})

        if not filters:
            return None
        if len(filters) == 1:
            return filters[0]
        return {"$and": filters}

    def retrieve(self, request: SearchRequest) -> List[RetrievalResult]:
        """Execute semantic retrieval according to search constraints."""
        # Synthesize textual query if prompt is empty
        query_text = request.query.strip()
        if not query_text:
            components = []
            if request.category:
                components.append(f"thể loại {request.category}")
            if request.location:
                components.append(f"ở {request.location}")
            if request.preferences:
                components.append(" ".join(request.preferences))
            query_text = " ".join(components) if components else "địa điểm ăn uống vui chơi Hà Nội"

        # Encode query
        query_vector = self.embedding_manager.encode_query(query_text)

        where_filter = self._build_where_filter(request)
        k = max(self.settings.retrieval_k, self.settings.recommendation_k * 2, 50)

        # Staged relaxation: never mix in results that violate the category constraint.
        stages = [self._build_where_filter(request)]
        if request.category and request.location:
            stages.append({"normalized_category_code": {"$eq": request.category}})
        raw_results: list = []
        seen_ids: set = set()
        for where in stages:
            batch = self.chroma_manager.search(query_embedding=query_vector, n_results=k, where=where)
            for item in batch:
                if item["id"] not in seen_ids:
                    raw_results.append(item)
                    seen_ids.add(item["id"])
            if len(raw_results) >= self.settings.recommendation_k:
                break
        if not raw_results and not request.category and not request.location:
            raw_results = self.chroma_manager.search(query_embedding=query_vector, n_results=k, where=None)
        exclude_set = set(request.exclude_ids)
        retrieval_results: List[RetrievalResult] = []

        for item in raw_results:
            place_id = item["id"]
            if place_id in exclude_set:
                continue

            place = self.places_map.get(place_id)
            if not place:
                continue

            semantic_score = item["semantic_score"]
            validate_score(semantic_score)

            evidence = []
            if request.category and place.normalized_category_code == request.category:
                evidence.append(f"Khớp danh mục {request.category}")
            if request.location and place.source.district.lower() == request.location.lower():
                evidence.append(f"Nằm tại {place.source.district}")
            if request.preferences:
                matched_prefs = [p for p in request.preferences if p.lower() in place.source.description.lower() or p.lower() in [t.lower() for t in place.source.tags]]
                if matched_prefs:
                    evidence.append(f"Phù hợp: {', '.join(matched_prefs)}")

            retrieval_results.append(
                RetrievalResult(
                    place=place,
                    semantic_score=semantic_score,
                    evidence=tuple(evidence),
                )
            )

        # Exact venue names are independent evidence and may fall outside the vector top-K.
        query_name = f' {_venue_name(query_text)} '
        exact = {}
        district = normalize_district_name(request.location)
        for pid, place in self.places_map.items():
            if pid in exclude_set or (request.category and request.category != place.normalized_category_code):
                continue
            if district and place.source.district != district:
                continue
            head = place.source.name.split(' (', 1)[0]
            variants = [_venue_name(part) for part in [head, *re.split(r'\s+[-–—]\s+', head)]]
            if any(len(name.split()) >= 3 and f' {name} ' in query_name for name in variants):
                exact[pid] = place
        if not exact:
            return retrieval_results
        scores = {hit.place.source.id: hit.semantic_score for hit in retrieval_results}
        named = [RetrievalResult(place, scores.get(pid, 0.0), ('Khớp tên địa điểm',))
                 for pid, place in exact.items()]
        named.sort(key=lambda hit: len(hit.place.source.name), reverse=True)
        return named + [hit for hit in retrieval_results if hit.place.source.id not in exact]


