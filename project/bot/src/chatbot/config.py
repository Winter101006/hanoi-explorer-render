"""Environment configuration, loaded explicitly without network or model IO."""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

BOT_DIR = Path(__file__).resolve().parents[2]
EMBEDDING_MODEL = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'


@dataclass(frozen=True)
class Settings:
    data_path: Path
    chroma_path: Path
    collection: str
    embedding_model: str = EMBEDDING_MODEL
    device: str = 'cpu'
    batch_size: int = 32
    retrieval_k: int = 20
    recommendation_k: int = 5
    gemini_model: str = ''
    gemini_api_key: str = field(default='', repr=False)
    timeout_seconds: int = 30
    max_retries: int = 2
    session_ttl_seconds: int = 3600
    max_sessions: int = 1000
    history_turns: int = 12
    ranking_weights: tuple[float, ...] = (0.40, 0.25, 0.20, 0.15)
    document_version: str = 'v1'


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    if env is None:
        try:
            from dotenv import load_dotenv
            load_dotenv(BOT_DIR / '.env')
            load_dotenv()
        except ImportError:
            pass
        env = os.environ

    def path(name: str, default: str) -> Path:
        value = Path(env.get(name, default))
        return (value if value.is_absolute() else BOT_DIR / value).resolve()

    def integer(name: str, default: int, minimum: int = 1) -> int:
        value = int(env.get(name, str(default)))
        if value < minimum:
            raise ValueError(f'{name} must be >= {minimum}')
        return value

    weights = tuple(float(env.get(name, str(default))) for name, default in (
        ('WEIGHT_SEMANTIC', .40), ('WEIGHT_PREFERENCE', .25),
        ('WEIGHT_LOCATION', .20), ('WEIGHT_BUDGET', .15)))
    if not all(0 <= value <= 1 for value in weights) or abs(sum(weights) - 1) > 1e-8:
        raise ValueError('Ranking weights must be nonnegative and sum to 1')
    settings = Settings(
        data_path=path('DATA_PATH', 'data/hanoi_places_cleaned.json'),
        chroma_path=path('CHROMA_PATH', 'chroma_db'),
        collection=env.get('CHROMA_COLLECTION', 'hanoi_cleaned_minilm_v1'),
        device=env.get('EMBEDDING_DEVICE', 'cpu'),
        batch_size=integer('EMBEDDING_BATCH_SIZE', 32),
        retrieval_k=integer('RETRIEVAL_K', 20),
        recommendation_k=integer('RECOMMENDATION_K', 5),
        gemini_model=env.get('GEMINI_MODEL', ''),
        gemini_api_key=env.get('GEMINI_API_KEY', ''),
        timeout_seconds=integer('GEMINI_TIMEOUT_SECONDS', 30),
        max_retries=integer('GEMINI_MAX_RETRIES', 2, 0),
        session_ttl_seconds=integer('SESSION_TTL_SECONDS', 3600),
        max_sessions=integer('MAX_SESSIONS', 1000),
        history_turns=integer('HISTORY_TURNS', 12),
        ranking_weights=weights,
    )
    if settings.recommendation_k > settings.retrieval_k:
        raise ValueError('RECOMMENDATION_K exceeds RETRIEVAL_K')
    return settings
