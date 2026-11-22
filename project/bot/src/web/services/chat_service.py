"""WS4 composition of the supplied WS1/WS2 modules and WS3 orchestration."""
import os
from dataclasses import asdict, replace
from threading import RLock

from project.bot.src.chatbot.config import BOT_DIR, load_settings
from project.bot.src.chatbot.data_loader import load
from project.bot.src.chatbot.schemas import ChatRequest, ConversationTurn
from project.bot.src.chatbot.memory import ConversationMemory
from project.bot.src.chatbot.gemini_client import GeminiClient
from project.bot.src.chatbot.query_processor import QueryProcessor
from project.bot.src.chatbot.recommender import Recommender
from project.bot.src.chatbot.chatbot import Chatbot


class IndexUnavailable(RuntimeError):
    pass


def runtime_settings(settings):
    # HNSW native IO on Windows fails with accented absolute path ancestors.
    # Keep the data directory unchanged, using an ASCII relative path where possible.
    if os.name == 'nt':
        try:
            relative = os.path.relpath(settings.chroma_path)
            if relative.isascii():
                return replace(settings, chroma_path=relative)
        except ValueError:
            pass
    return settings


class LazyRetriever:
    def __init__(self, settings, places):
        self.settings = runtime_settings(settings)
        self.places = places
        self._retriever = None
        self._lock = RLock()

    def checked_manager(self):
        from project.bot.src.chatbot.chroma_manager import ChromaManager, compute_dataset_fingerprint
        manager = ChromaManager(self.settings)
        try:
            # Fetch only. Startup must never create or rebuild a collection.
            collection = manager.client.get_collection(self.settings.collection, embedding_function=None)
            metadata = collection.metadata or {}
            expected = {'model': self.settings.embedding_model, 'document_version': self.settings.document_version,
                        'dataset_fingerprint': compute_dataset_fingerprint(self.places), 'normalized': True,
                        'dimension': 384, 'hnsw:space': 'cosine'}
            if any(metadata.get(key) != value for key, value in expected.items()):
                raise IndexUnavailable('Index metadata is missing or incompatible')
            if collection.count() != len(self.places):
                raise IndexUnavailable('Index is empty or incomplete')
            manager._collection = collection
            return manager
        except IndexUnavailable:
            raise
        except Exception as error:
            raise IndexUnavailable('Index is unavailable; run offline indexing for the configured collection') from error

    def warm_up(self):
        with self._lock:
            if self._retriever is None:
                from project.bot.src.chatbot.embedding import EmbeddingManager
                from project.bot.src.chatbot.retriever import Retriever
                manager = self.checked_manager()
                os.environ.setdefault('SENTENCE_TRANSFORMERS_HOME', str(BOT_DIR / 'model_cache'))
                embedder = EmbeddingManager(self.settings.embedding_model, self.settings.device)
                embedder.encode_query('Hà Nội')
                self._retriever = Retriever(self.settings, manager, embedder, self.places)
            return self._retriever

    def retrieve(self, request):
        with self._lock:
            self.warm_up()
            return self._retriever.retrieve(request)


class ChatService:
    def __init__(self, settings=None, bot=None, places=None):
        self.settings = settings or load_settings()
        self.places = places if places is not None else load(self.settings.data_path)
        self.by_id = {place.source.id: place for place in self.places}
        if len(self.by_id) != len(self.places):
            raise ValueError('Dataset contains duplicate place IDs')
        self.memory = ConversationMemory(self.settings.session_ttl_seconds,
                                         self.settings.max_sessions, self.settings.history_turns)
        self.retriever = LazyRetriever(self.settings, self.places)
        self.bot = bot or Chatbot(QueryProcessor(), self.retriever, Recommender(self.settings),
                                 GeminiClient(self.settings), self.memory,
                                 self.settings.recommendation_k, self.places)

    def card(self, place):
        result = asdict(place.source)
        result['category_code'] = place.normalized_category_code or 'unknown'
        result['data_quality'] = asdict(place.quality)
        for key in ('address', 'opening_hours', 'price_range', 'suitable_for', 'weather_fit', 'description'):
            if not result[key]:
                result[key] = 'Chưa có thông tin trong dữ liệu'
        return result

    def respond(self, data):
        history = []
        for item in data.get('history', [])[-self.settings.history_turns:]:
            if not isinstance(item, dict) or item.get('role') not in ('user', 'assistant') or not isinstance(item.get('content'), str):
                raise ValueError('Invalid history item')
            supplied = item.get('places', [])
            if not isinstance(supplied, list):
                raise ValueError('Invalid history places')
            ids = tuple(place['id'] for place in supplied if isinstance(place, dict)
                        and isinstance(place.get('id'), str) and place['id'] in self.by_id)
            history.append(ConversationTurn(item['role'], item['content'][:2000], ids))
        message = data.get('message', '').strip() or 'Xin chào'
        response = self.bot.respond(ChatRequest(message, data.get('session_id'),
                                   {key: data.get(key, 'all') for key in ('category', 'district', 'budget')}, tuple(history)))
        response.validate_ids(set(self.by_id))
        cards = [self.card(self.by_id[item.place_id]) for item in response.recommendations]
        return {'status': 'success', 'reply': response.answer, 'answer': response.answer,
                'places': cards, 'recommendations': [asdict(item) for item in response.recommendations],
                'total_results': len(cards), 'itinerary': None,
                'location_info': {'has_location': bool(cards), 'districts': sorted({card['district'] for card in cards})},
                'follow_up': response.follow_up, 'session_id': response.session_id}


def load_places():
    from flask import current_app
    runtime = current_app.extensions['chat_service']
    return [runtime.card(place) for place in runtime.places]


def sanitize_place(place):
    from flask import current_app
    runtime = current_app.extensions['chat_service']
    return runtime.card(runtime.by_id[place['id']])


def process_chat_request(message, category='all', district=None, budget=None, history=None, top_k=6):
    from flask import current_app
    result = current_app.extensions['chat_service'].respond({
        'message': message, 'category': category, 'district': district or 'all',
        'budget': budget or 'all', 'history': history or []})
    result['places'] = result['places'][:top_k]
    result['recommendations'] = result['recommendations'][:top_k]
    result['total_results'] = len(result['places'])
    return result
