"""Shared data contracts. Source values and derived values remain separate."""
from dataclasses import dataclass, field, replace
from math import isfinite
from typing import Literal

CategoryCode = Literal['an-uong', 'ca-phe', 'tam-linh', 'di-tich', 'ngoai-troi', 'giai-tri', 'the-thao']
CATEGORY_CODES = frozenset(('an-uong', 'ca-phe', 'tam-linh', 'di-tich', 'ngoai-troi', 'giai-tri', 'the-thao'))


@dataclass(frozen=True)
class RawPlace:
    id: str
    name: str
    category: str
    category_code: str
    district: str
    address: str
    opening_hours: str
    price_range: str
    suitable_for: str
    weather_fit: str
    description: str
    latitude: float | None
    longitude: float | None
    tags: tuple[str, ...]

    @classmethod
    def from_dict(cls, data: dict) -> 'RawPlace':
        """Validate source records without inventing missing factual values."""
        values = dict(data)
        for name in ('id', 'name'):
            if not isinstance(values.get(name), str) or not values[name].strip():
                raise ValueError(f'{name} must be a non-empty string')
        for name in ('category', 'category_code', 'district', 'address', 'opening_hours',
                     'price_range', 'suitable_for', 'weather_fit', 'description'):
            value = values.get(name, '')
            if not isinstance(value, str):
                raise ValueError(f'{name} must be a string')
            values[name] = value
        for name, bound in (('latitude', 90), ('longitude', 180)):
            value = values.get(name)
            if value is not None:
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or abs(value) > bound:
                    raise ValueError(f'Invalid {name}')
            values[name] = value
        tags = values.get('tags', [])
        if not isinstance(tags, (list, tuple)) or not all(isinstance(tag, str) for tag in tags):
            raise ValueError('tags must contain strings')
        values['tags'] = tuple(tags)
        return cls(**{name: values[name] for name in cls.__dataclass_fields__})


@dataclass(frozen=True)
class PriceInfo:
    minimum: int | None = None
    maximum: int | None = None
    unit: str | None = None
    conditions: tuple[str, ...] = ()
    status: Literal['unknown', 'parsed', 'ambiguous'] = 'unknown'

    def __post_init__(self):
        for value in (self.minimum, self.maximum):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError('Price must be a nonnegative integer')
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError('Price minimum exceeds maximum')
        if self.status not in ('unknown', 'parsed', 'ambiguous'):
            raise ValueError('Invalid price status')


@dataclass(frozen=True)
class DataQuality:
    category_conflict: bool = False
    address_precision: Literal['unknown', 'district_only', 'area', 'street_or_specific'] = 'unknown'
    coordinates_verified: bool = False
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class Place:
    source: RawPlace
    normalized_category_code: CategoryCode | None = None
    price: PriceInfo = field(default_factory=PriceInfo)
    quality: DataQuality = field(default_factory=DataQuality)

    def __post_init__(self):
        if self.normalized_category_code is not None and self.normalized_category_code not in CATEGORY_CODES:
            raise ValueError('Invalid normalized category')


@dataclass(frozen=True)
class SearchRequest:
    query: str = ''
    category: CategoryCode | None = None
    location: str | None = None
    budget_min: int | None = None
    budget_max: int | None = None
    budget_unit: str | None = None
    preferences: tuple[str, ...] = ()
    exclude_ids: tuple[str, ...] = ()
    hard_constraints: tuple[str, ...] = ()
    party_size: int | None = None
    weather: str | None = None
    weather_source: str | None = None
    setting: Literal['indoor', 'outdoor'] | None = None
    budget_exclusive: bool = False

    def __post_init__(self):
        if self.category is not None and self.category not in CATEGORY_CODES:
            raise ValueError('Invalid category')
        for val in (self.budget_min, self.budget_max):
            if val is not None and (type(val) is not int or val < 0):
                raise ValueError('Invalid budget')
        if self.budget_min is not None and self.budget_max is not None and self.budget_min > self.budget_max:
            raise ValueError('Invalid budget')
        if self.setting is not None and self.setting not in ('indoor', 'outdoor'):
            raise ValueError('Invalid setting')


@dataclass(frozen=True)
class QueryUpdate:
    """Absent keys retain state; clear_fields explicitly removes constraints."""
    values: dict = field(default_factory=dict)
    clear_fields: tuple[str, ...] = ()
    reset: bool = False

    def apply(self, previous: SearchRequest) -> SearchRequest:
        allowed = set(SearchRequest.__dataclass_fields__)
        if (set(self.values) | set(self.clear_fields)) - allowed:
            raise ValueError('Unknown constraint field')
        if set(self.values) & set(self.clear_fields):
            raise ValueError('Cannot set and clear the same field')
        if any(value is None for value in self.values.values()):
            raise ValueError('Use clear_fields to remove constraints')
        defaults = SearchRequest()
        changes = {name: getattr(defaults, name) for name in self.clear_fields}
        changes.update(self.values)
        return replace(defaults if self.reset else previous, **changes)


@dataclass(frozen=True)
class ConversationTurn:
    role: Literal['user', 'assistant']
    content: str
    place_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConversationState:
    constraints: SearchRequest = field(default_factory=SearchRequest)
    history: tuple[ConversationTurn, ...] = ()
    previous_place_ids: tuple[str, ...] = ()
    pending_clarification: str | None = None
    pending_message: str = ''


@dataclass(frozen=True)
class QueryUnderstanding:
    request: SearchRequest
    update: QueryUpdate
    intent: str = 'location_recommendation'
    clarification: str | None = None


@dataclass(frozen=True)
class RetrievalResult:
    place: Place
    semantic_score: float
    evidence: tuple[str, ...] = ()

    def __post_init__(self):
        validate_score(self.semantic_score)


def validate_score(value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or not 0 <= value <= 1:
        raise ValueError('Score must be finite and in [0, 1]')


@dataclass(frozen=True)
class Recommendation:
    place_id: str
    score: float
    components: dict[str, float] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self):
        validate_score(self.score)
        for value in self.components.values():
            validate_score(value)


@dataclass(frozen=True)
class ChatRequest:
    message: str
    session_id: str | None = None
    explicit_filters: dict = field(default_factory=dict)
    history: tuple[ConversationTurn, ...] = ()


@dataclass(frozen=True)
class ChatbotResponse:
    answer: str
    recommendations: tuple[Recommendation, ...] = ()
    follow_up: str | None = None
    session_id: str | None = None

    def validate_ids(self, retrieved_ids: set[str]) -> None:
        ids = [item.place_id for item in self.recommendations]
        if len(ids) != len(set(ids)) or not set(ids) <= retrieved_ids:
            raise ValueError('Recommendations must reference unique retrieved IDs')
