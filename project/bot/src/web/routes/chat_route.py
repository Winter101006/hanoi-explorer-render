"""Compatible Flask endpoints for existing and session-aware clients."""
import logging
from uuid import uuid4
from flask import Blueprint, current_app, request, jsonify
from project.bot.src.chatbot.schemas import CATEGORY_CODES
from project.bot.src.web.services.chat_service import IndexUnavailable

chat_bp = Blueprint('chat_bp', __name__)
logger = logging.getLogger(__name__)


def service():
    return current_app.extensions['chat_service']


def error(message, status):
    return jsonify(status='error', reply=message, places=[]), status


@chat_bp.post('/api/chat')
def chat():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error('Payload phải là JSON object.', 400)
    if not isinstance(data.get('message', ''), str) or len(data.get('message', '')) > 500:
        return error('Tin nhắn phải là chuỗi tối đa 500 ký tự.', 400)
    if not isinstance(data.get('history', []), list):
        return error('History phải là danh sách.', 400)
    for key in ('category', 'district', 'budget'):
        if not isinstance(data.get(key, 'all'), str):
            return error('Bộ lọc phải là chuỗi.', 400)
    if data.get('category', 'all') not in CATEGORY_CODES | {'all'}:
        return error('Danh mục không hợp lệ.', 400)
    sid = data.get('session_id')
    if sid is not None and (not isinstance(sid, str) or not sid.strip() or len(sid) > 128):
        return error('Session ID không hợp lệ.', 400)
    try:
        return jsonify(service().respond(data))
    except ValueError:
        return error('Yêu cầu hoặc lịch sử không hợp lệ.', 400)
    except IndexUnavailable:
        return error('Index chưa sẵn sàng hoặc không tương thích. Hãy kiểm tra cấu hình indexing.', 503)
    except Exception as failure:
        logger.error('Chat request failed cause=%s', type(failure).__name__)
        return error('Dịch vụ tạm thời chưa sẵn sàng.', 503)


@chat_bp.get('/api/places')
def places():
    category, district = request.args.get('category', 'all'), request.args.get('district', 'all')
    rows = [service().card(place) for place in service().places
            if (category == 'all' or place.normalized_category_code == category)
            and (district == 'all' or place.source.district == district)]
    return jsonify(status='success', total=len(rows), places=rows)


@chat_bp.get('/api/districts')
def districts():
    return jsonify(status='success', districts=sorted({p.source.district for p in service().places}))


@chat_bp.get('/api/categories')
def categories():
    names = {'all':'Tất cả', 'an-uong':'Ẩm thực', 'ca-phe':'Cà phê & trà', 'tam-linh':'Tâm linh',
             'di-tich':'Di tích & bảo tàng', 'ngoai-troi':'Ngoài trời', 'giai-tri':'Giải trí', 'the-thao':'Thể thao'}
    return jsonify(status='success', categories=[{'code': k, 'name': v} for k, v in names.items()])


@chat_bp.get('/api/health')
def health():
    ready = False
    try:
        service().retriever.checked_manager()
        ready = True
    except Exception:
        pass
    settings = service().settings
    return jsonify(status='online' if ready else 'degraded', index_ready=ready,
                   model=settings.embedding_model, database='ChromaDB Persistent',
                   runtime_loaded=service().retriever._retriever is not None,
                   gemini_configured=bool(settings.gemini_api_key and settings.gemini_model),
                   places=len(service().places))


@chat_bp.get('/api/weather')
def weather():
    return jsonify(status='unavailable', city='Hà Nội', temp=None, feels_like=None,
                   condition='Chưa kết nối dữ liệu thời tiết', icon='fa-cloud', season=None,
                   advisory='Hãy kiểm tra dự báo thời tiết trước khi đi.')


@chat_bp.post('/api/sessions')
def create_session():
    return jsonify(session_id=str(uuid4())), 201


@chat_bp.delete('/api/sessions/<session_id>')
def clear_session(session_id):
    try:
        service().memory.clear(session_id)
    except ValueError:
        return error('Session ID không hợp lệ.', 400)
    return jsonify(status='success')
