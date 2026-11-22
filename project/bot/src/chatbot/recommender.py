"""Multi-factor recommender engine with adaptive weight renormalization.

Ranks retrieval candidates using:
Score = 0.40 * semantic + 0.25 * preference + 0.20 * location + 0.15 * budget
Renormalizes weights when user criteria are inactive.
"""
from __future__ import annotations

import logging
from .menu import menu_strength
from typing import Dict, List, Optional, Tuple

from project.bot.src.chatbot.config import Settings
from project.bot.src.chatbot.schemas import (
    Place,
    Recommendation,
    RetrievalResult,
    SearchRequest,
    validate_score,
)

logger = logging.getLogger(__name__)


def calculate_preference_score(place: Place, preferences: Tuple[str, ...]) -> Tuple[float, List[str]]:
    """Score how well a place fulfills specific preferences."""
    if not preferences:
        return 0.0, []

    matched = []
    text_corpus = (
        f"{place.source.name} {place.source.description} {place.source.suitable_for} "
        f"{' '.join(place.source.tags)} {place.source.weather_fit}"
    ).lower()

    for pref in preferences:
        p_clean = pref.lower().strip()
        if p_clean in text_corpus:
            matched.append(pref)

    score = len(matched) / len(preferences)
    return min(1.0, max(0.0, score)), matched


def calculate_location_score(place: Place, location: Optional[str]) -> Tuple[float, List[str]]:
    """Score place proximity to target location/district."""
    if not location:
        return 0.0, []

    target = location.strip().lower()
    district = place.source.district.strip().lower()
    address = place.source.address.strip().lower()

    if target == district or target in district:
        return 1.0, [f"Nằm đúng tại Quận {place.source.district}"]
    elif target in address:
        return 0.8, [f"Khu vực {place.source.district} (gần {location})"]

    return 0.0, []


def matches_weather_and_setting(place: Place, request: SearchRequest) -> bool:
    wf = place.source.weather_fit.strip().lower()
    if request.setting == 'indoor':
        return 'trong nhà' in wf
    if request.setting == 'outdoor':
        return 'ngoài trời' in wf
    if request.weather == 'mưa' or (request.weather == 'nắng nóng' and 'mát mẻ' in request.query.lower()):
        if wf == 'ngoài trời' and request.category != 'ngoai-troi':
            return False
    return True


def calculate_budget_score(
    place: Place,
    budget_max: Optional[int],
    budget_min: Optional[int] = None,
) -> Tuple[float, List[str], List[str]]:
    """Score price fit and report unknowns in limitations."""
    if budget_max is None and budget_min is None:
        return 0.0, [], []

    reasons = []
    limitations = []

    price = place.price
    if price.status == 'parsed':
        if budget_min is not None:
            if price.maximum is not None and price.maximum < budget_min:
                limitations.append(f"Mức giá tối đa {price.maximum:,}đ thấp hơn mức yêu cầu ({budget_min:,}đ)")
                return 0.0, reasons, limitations
            if budget_max is None:
                if price.minimum is not None and price.minimum >= budget_min:
                    reasons.append(f"Mức giá {place.source.price_range} đáp ứng mức từ {budget_min:,}đ")
                    return 1.0, reasons, limitations
                reasons.append(f"Mức giá tối đa {price.maximum:,}đ đáp ứng mức trên {budget_min:,}đ")
                return 0.75, reasons, limitations

        # Free places (when only budget_max applies)
        if price.minimum == 0 and price.maximum == 0:
            reasons.append("Miễn phí")
            return 1.0, reasons, limitations

        # Upper bound within budget
        if price.maximum is not None and budget_max is not None and price.maximum <= budget_max:
            reasons.append(f"Mức giá {place.source.price_range} phù hợp ngân sách")
            return 1.0, reasons, limitations

        # Lower bound within budget
        if price.minimum is not None and budget_max is not None and price.minimum <= budget_max:
            reasons.append(f"Giá khởi điểm từ {price.minimum:,}đ phù hợp ngân sách")
            return 0.75, reasons, limitations

        # Exceeds budget
        if price.minimum is not None and budget_max is not None and price.minimum > budget_max:
            limitations.append(f"Mức giá khởi điểm {price.minimum:,}đ vượt ngân sách yêu cầu ({budget_max:,}đ)")
            return 0.0, reasons, limitations

        return 0.5, reasons, limitations

    # Unknown price gets 0 match credit per contract
    limitations.append("Chưa có thông tin giá chính xác để đối chiếu ngân sách")
    return 0.0, reasons, limitations


class Recommender:
    """Ranks candidates using normalized multi-factor criteria."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings
        self.default_weights = (0.40, 0.25, 0.20, 0.15)
        if settings and settings.ranking_weights:
            self.default_weights = settings.ranking_weights

    def rank(
        self,
        request: SearchRequest,
        candidates: List[RetrievalResult],
        limit: int = 5,
    ) -> List[Recommendation]:
        """Rank candidates against user request and return top recommendations."""
        if not candidates:
            return []

        w_semantic, w_pref_base, w_loc_base, w_bud_base = self.default_weights

        # Determine active criteria
        foods = [c[5:] for c in request.hard_constraints if c.startswith('dish:') and c[5:]]
        pref_active = bool(request.preferences or foods)
        loc_active = bool(request.location)
        bud_active = request.budget_max is not None or request.budget_min is not None

        active_weight_sum = w_semantic
        if pref_active:
            active_weight_sum += w_pref_base
        if loc_active:
            active_weight_sum += w_loc_base
        if bud_active:
            active_weight_sum += w_bud_base

        # Renormalize weights
        w_sem_norm = w_semantic / active_weight_sum
        w_pref_norm = (w_pref_base / active_weight_sum) if pref_active else 0.0
        w_loc_norm = (w_loc_base / active_weight_sum) if loc_active else 0.0
        w_bud_norm = (w_bud_base / active_weight_sum) if bud_active else 0.0

        scored_recommendations: List[Recommendation] = []
        exclude_set = set(request.exclude_ids)

        for candidate in candidates:
            place = candidate.place
            place_id = place.source.id
            if place_id in exclude_set:
                continue
            specialty = menu_strength(place.source, foods) if foods else None
            if specialty == 0:
                continue
            # Hard constraints: category, weather/setting, and known price bounds
            if request.category and place.normalized_category_code != request.category:
                continue
            if not matches_weather_and_setting(place, request):
                continue
            if request.budget_max is not None:
                if (request.budget_exclusive and place.price.maximum is not None
                        and place.price.maximum >= request.budget_max):
                    continue
                if place.price.status == 'parsed' and place.price.minimum is not None and place.price.minimum > request.budget_max:
                    continue
            if request.budget_min is not None:
                if place.price.status == 'parsed' and place.price.maximum is not None and place.price.maximum < request.budget_min:
                    continue

            reasons: list[str] = list(candidate.evidence)
            limitations: list[str] = []

            # 1. Semantic score
            sem_score = candidate.semantic_score

            # 2. Preference score
            pref_score = 0.0
            if pref_active:
                pref_score, matched_prefs = calculate_preference_score(place, request.preferences)
                if specialty is not None:
                    pref_score = (pref_score + specialty) / 2 if request.preferences else specialty
                if matched_prefs:
                    reasons.append(f"Đáp ứng sở thích: {', '.join(matched_prefs)}")
                elif request.preferences:
                    limitations.append("Chưa có thông tin xác nhận các tiện ích yêu cầu")

            # 3. Location score
            loc_score = 0.0
            if loc_active:
                loc_score, loc_reasons = calculate_location_score(place, request.location)
                reasons.extend(loc_reasons)
                if loc_score == 0.0:
                    limitations.append(f"Không nằm tại Quận {request.location}")

            # 4. Budget score
            bud_score = 0.0
            if bud_active:
                bud_score, bud_reasons, bud_limits = calculate_budget_score(place, request.budget_max, request.budget_min)
                reasons.extend(bud_reasons)
                limitations.extend(bud_limits)

            # Composite multi-factor formula
            final_score = (
                w_sem_norm * sem_score
                + w_pref_norm * pref_score
                + w_loc_norm * loc_score
                + w_bud_norm * bud_score
            )

            # Quality penalties
            if place.quality.category_conflict:
                final_score *= 0.95
                limitations.append("Dữ liệu thể loại gốc có thể bị nhầm lẫn")
            if place.quality.address_precision == 'district_only':
                limitations.append("Địa chỉ chỉ xác định ở cấp quận")

            final_score = max(0.0, min(1.0, float(final_score)))
            validate_score(final_score)

            components = {
                'semantic': sem_score,
                'preference': pref_score,
                'location': loc_score,
                'budget': bud_score,
            }

            rec = Recommendation(
                place_id=place_id,
                score=final_score,
                components=components,
                reasons=tuple(reasons),
                limitations=tuple(limitations),
            )
            scored_recommendations.append(rec)

        # Sort descending by score
        scored_recommendations.sort(
            key=lambda x: ('Khớp tên địa điểm' in x.reasons, x.score), reverse=True)
        return scored_recommendations[:limit]


def rank(
    request: SearchRequest,
    candidates: List[RetrievalResult],
    limit: int = 5,
) -> List[Recommendation]:
    """Functional ranking interface matching CONTRACTS.md."""
    recommender = Recommender()
    return recommender.rank(request, candidates, limit)

