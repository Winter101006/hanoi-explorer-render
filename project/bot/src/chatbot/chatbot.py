"""WS3 orchestration against the WS1/WS2 contracts."""
import logging
import re
from contextlib import nullcontext
from dataclasses import replace

from .gemini_client import GeminiError
from .memory import ConversationMemory
from .menu import OTHER_FOOD, requested_foods
from .prompts import build_generation_prompt
from .query_processor import (
    ACTIVITY_TERMS, OTHER_PLACES_PATTERN, TOURISM_PATTERN, extract_category, extract_district,
    extract_preferences,
)
from .recommender import matches_weather_and_setting
from .schemas import ChatRequest, ChatbotResponse, ConversationState, ConversationTurn

logger = logging.getLogger(__name__)


def conversation_route(text, state):
    social = text.strip().rstrip(' .!?ạ').strip()
    if re.fullmatch(r'(?:mình |tôi )?(?:cảm ơn|cám ơn|thanks)(?: bạn)?(?: nhé| nha)?', social):
        return 'thanks'
    if social in ('xin chào', 'chào', 'chào bạn', 'hello', 'hi'):
        return 'greeting'
    if re.search(r'bạn (?:là ai|tên (?:là )?gì|làm được gì)|giới thiệu (?:bản thân|về bạn)', text):
        return 'general_chat'
    if re.search(r'thời tiết|dự báo|(?:hôm nay|ngày mai).*mưa', text) and not re.search(r'đi đâu|đi chơi|đi dạo|tìm |gợi ý', text):
        return 'weather_query'
    if re.search(r'nhà nghỉ|khách sạn|homestay|chỗ lưu trú', text) and not re.search(r'(?:gần|cạnh) (?:nhà nghỉ|khách sạn)', text):
        return 'lodging'
    if state.pending_message and re.search(r'nguyễn trãi|lê thánh tông|cơ sở [12]', text):
        return 'clarification_answer'
    if (extract_category(text) or extract_district(text) or extract_preferences(text) or requested_foods(text)
            or re.search(TOURISM_PATTERN, text)
            or re.search(r'hus|khtn|đại học|đi |ở đâu|địa điểm|địa chỉ|chỗ |quán|gợi ý|tìm |bắt đầu lại|reset|xóa hết|làm mới|chủ đề mới|mở cửa|đóng cửa|giá |ngân sách|dưới |trên |giới hạn|trong nhà|ngoài trời|tạnh mưa|hết mưa|xin chào|^chào|^hi$|hello|cảm ơn', text)
            or state.constraints.query and re.search(r'khác|hơn|rẻ|bao nhiêu|thứ |đầu tiên|thì sao|\d+\s*(?:k|tr|triệu|nghìn|ngàn|đ|vnđ)', text)):
        return 'location_search'
    return 'out_of_scope'


def social_reply(route, state):
    if route == 'thanks':
        return 'Không có gì nhé!'
    intro = ('Mình là Hanoi Explorer AI, trợ lý giúp bạn khám phá Hà Nội.'
             if route == 'general_chat' else 'Chào bạn!')
    if state.pending_clarification:
        return f'{intro} {state.pending_clarification}'
    if state.previous_place_ids:
        return f'{intro} Nếu bạn đang phân vân giữa mấy chỗ vừa xem, bạn muốn mình so sánh điểm nào?'
    if state.constraints.location:
        return f'{intro} Bạn muốn tìm thêm chỗ nào ở {state.constraints.location}?'
    if route == 'greeting':
        return f'{intro} Hôm nay bạn muốn đi đâu ở Hà Nội?'
    return (f'{intro} Bạn cứ nói điều bạn đang muốn làm, kiểu như “mình muốn ngồi đọc sách '
            'ở đâu đó yên tĩnh”. Mình sẽ gợi ý vài chỗ và giải thích vì sao từng chỗ hợp với bạn.')


class Chatbot:
    def __init__(self, query_processor, retriever, recommender, gemini_client,
                 memory=None, recommendation_k=5, places=None):
        if not 1 <= recommendation_k <= 20:
            raise ValueError('recommendation_k must be between 1 and 20')
        self.query_processor = query_processor
        self.retriever = retriever
        self.recommender = recommender
        self.gemini = gemini_client
        self.memory = memory if memory is not None else ConversationMemory()
        self.recommendation_k = recommendation_k
        self.places = {place.source.id: place for place in places or []}

    def respond(self, request: ChatRequest) -> ChatbotResponse:
        if not isinstance(request.message, str) or not request.message.strip() or len(request.message) > 500:
            raise ValueError('Message must contain 1–500 characters')
        guard = self.memory.turn(request.session_id) if request.session_id is not None else nullcontext()
        with guard:
            state = (self.memory.get(request.session_id) if request.session_id is not None
                     else self._legacy_state(request.history))
            text = request.message.strip().casefold()
            route = conversation_route(text, state)
            direct = {
                'weather_query': 'Mình chưa có dữ liệu thời tiết trực tiếp để trả lời về dự báo ở Hà Nội.',
                'lodging': 'Mình chưa có danh mục cơ sở lưu trú để tư vấn nhà nghỉ hoặc khách sạn.',
                'out_of_scope': 'Mình chuyên tư vấn địa điểm ở Hà Nội. Bạn muốn tìm chỗ nào hoặc tham gia hoạt động gì?',
            }
            if route in direct or route in ('general_chat', 'greeting', 'thanks'):
                logger.info('chat source=template intent=%s', route)
                answer = direct[route] if route in direct else social_reply(route, state)
                response = ChatbotResponse(answer, session_id=request.session_id)
                self._save(request, state, response)
                return response
            lookup = self._lookup(request, state)
            if lookup:
                logger.info('chat source=lookup')
                self._save(request, state, lookup)
                return lookup
            if request.explicit_filters.get('budget') in ('low', 'medium', 'high'):
                logger.info('chat source=template kind=budget')
                question = 'Bạn cho mình ngân sách tối đa bằng số tiền nhé?'
                response = ChatbotResponse(question, follow_up=question, session_id=request.session_id)
                self._save(request, state, response)
                return response
            message = request.message
            if route == 'clarification_answer':
                message = state.pending_message + ' ' + message
            understanding = self._understand(message, state, request.explicit_filters)
            ui_category = request.explicit_filters.get('category')
            if (ui_category and ui_category != 'all' and understanding.request.category
                    and ui_category != understanding.request.category):
                understanding = replace(understanding, request=state.constraints,
                    clarification='Bộ lọc loại hình khác với yêu cầu. Bạn muốn dùng loại hình nào?')
            if understanding.clarification:
                logger.info('chat source=template kind=clarification')
                constraints = understanding.request
                # WS2 asks campus before extracting other slots. Preserve the first
                # request by reprocessing it with the explicit campus answer next turn.
                if state.pending_clarification and not understanding.update.reset:
                    constraints = state.constraints
                updated = replace(state, constraints=constraints,
                                  pending_clarification=understanding.clarification, pending_message=message)
                if understanding.update.reset:
                    updated = ConversationState(pending_clarification=understanding.clarification)
                response = ChatbotResponse(understanding.clarification, follow_up=understanding.clarification,
                                           session_id=request.session_id)
            else:
                search = understanding.request
                if re.search(OTHER_PLACES_PATTERN, text) or re.search(OTHER_FOOD, text):
                    shown = dict.fromkeys((*state.previous_place_ids, *(
                        pid for turn in state.history if turn.role == 'assistant' for pid in turn.place_ids
                    )))
                    search = replace(search, exclude_ids=tuple(shown))
                # Supply inherited context to the WS1 embedder on short follow-ups.
                terms = [c.partition(':')[2] for c in search.hard_constraints if c.startswith(('dish:', 'area:'))]
                if search.setting == 'outdoor':
                    terms.append('ngoài trời')
                elif search.weather or search.setting == 'indoor':
                    terms.append('trong nhà')
                if 'tourism:alternative' in search.hard_constraints:
                    terms.append('địa điểm vui chơi và hoạt động giải trí')
                elif 'tourism:site' in search.hard_constraints:
                    terms.append('khu du lịch')
                query = ' '.join(filter(None, [search.query, search.category, search.location, *search.preferences, *terms]))
                search = replace(search, query=query)
                response = self._recommend(request, state, search)
                updated = replace(state, constraints=replace(search, exclude_ids=()),
                                  pending_clarification=None, pending_message='',
                                  previous_place_ids=tuple(r.place_id for r in response.recommendations))
            self._save(request, updated, response)
            return response

    def _understand(self, message, state, filters):
        dating = re.search(r'đi chơi với (?:bạn gái|gái|người yêu)|hẹn hò', message, re.I)
        if dating:
            old = state.constraints
            if 'học tập' in old.preferences and not re.search(r'học|làm việc', message, re.I):
                state = replace(state, constraints=replace(old, category=None, preferences=()))
        result = self.query_processor.process(message, state, filters)
        if dating and result.request.category == 'giai-tri' and 'đi chơi' in message.casefold() and filters.get('category') != 'giai-tri':
            if not re.search(r'rạp|phim|karaoke|bowling|giải trí', message, re.I):
                result = replace(result, request=replace(result.request, category=None))
        if result.clarification and 'HUS' in result.clarification:
            activity = next((term for term in extract_preferences(message) if term in ACTIVITY_TERMS), None)
            purpose = f'chỗ chơi {activity} ' if activity else ''
            result = replace(result, clarification=f'Bạn muốn tìm {purpose}quanh cơ sở HUS nào, Nguyễn Trãi hay Lê Thánh Tông?')

        return result

    def _legacy_state(self, history):
        state = self.memory.bounded(ConversationState(history=history))
        replay = ConversationState()
        for turn in state.history:
            if turn.role == 'user':
                route = conversation_route(turn.content.casefold(), replay)
                if route not in ('location_search', 'clarification_answer'):
                    continue
                message = (replay.pending_message + ' ' if route == 'clarification_answer' else '') + turn.content
                result = self._understand(message, replay, {})
                replay = replace(replay, constraints=result.request, pending_message=message if result.clarification else '', pending_clarification=result.clarification)
        ids = next((turn.place_ids for turn in reversed(state.history) if turn.place_ids), ())
        return replace(state, constraints=replay.constraints, pending_message=replay.pending_message, pending_clarification=replay.pending_clarification,
                       previous_place_ids=ids)

    def _save(self, request, state, response):
        history = state.history + (ConversationTurn('user', request.message),
                                    ConversationTurn('assistant', response.answer,
                                                     tuple(r.place_id for r in response.recommendations)))
        if request.session_id is not None:
            self.memory.save(request.session_id, replace(state, history=history))

    def _lookup(self, request, state):
        text = request.message.casefold()
        fields = {'địa chỉ': 'address', 'mở cửa': 'opening_hours', 'đóng cửa': 'opening_hours',
                  'giá bao nhiêu': 'price_range', 'giá vé': 'price_range'}
        field = next((field for term, field in fields.items() if term in text), None)
        if field is None:
            return None
        matches = [place for place in self.places.values() if place.source.name.casefold() in text]
        if not matches and state.previous_place_ids:
            number = re.search(r'(?:thứ|số)\s*(\d+)', text)
            index = int(number.group(1)) - 1 if number else 0
            if 0 <= index < len(state.previous_place_ids):
                place = self.places.get(state.previous_place_ids[index])
                if place:
                    matches = [place]
        if len(matches) != 1:
            return ChatbotResponse('Bạn muốn hỏi thông tin địa điểm nào?', session_id=request.session_id)
        place = matches[0]
        answer = f'{place.source.name}: {getattr(place.source, field) or "Chưa có thông tin trong dữ liệu."}'
        if field == 'address' and place.quality.address_precision in ('unknown', 'district_only', 'area'):
            answer += ' Nguồn chỉ xác định khu vực, chưa đủ địa chỉ chính xác.'
        return ChatbotResponse(answer, session_id=request.session_id)

    @staticmethod
    def _eligible(hit, search):
        """Enforce requested area/budget at integration boundary before ranking.

        WS1 may relax area and WS2 scores starting prices; these are not evidence
        that a required district or entire price range satisfies the request.
        """
        place = hit.place
        tourism = set(search.hard_constraints) & {'tourism:site', 'tourism:visit', 'tourism:alternative'}
        if tourism:
            if place.normalized_category_code not in ('di-tich', 'tam-linh', 'ngoai-troi', 'giai-tri'):
                return False
            identity = f'{place.source.name} {place.source.category}'
            is_tourism_site = bool(re.search(r'\b(?:khu du lịch|khu sinh thái|điểm du lịch)\b', identity, re.I))
            if 'tourism:site' in tourism and not is_tourism_site:
                return False
            if 'tourism:alternative' in tourism and is_tourism_site:
                return False
        corpus = ' '.join((place.source.name, place.source.category, place.source.description)).casefold()
        requirements = {'diet:chay': r'\b(?:ăn|món|ẩm thực|quán|cơm|buffet|nhà hàng|thực đơn) chay\b',
                        'amenity:wifi': r'\bwi[- ]?fi\b', 'amenity:cover': r'\bmái che\b'}
        for key, pattern in requirements.items():
            if key in search.hard_constraints and (not re.search(pattern, corpus) or
                    re.search(r'không (?:có |phục vụ )?(?:' + pattern + ')', corpus)):
                return False
        if 'exclude:ca-phe' in search.hard_constraints and place.normalized_category_code == 'ca-phe':
            return False
        if 'exclude:dating' in search.hard_constraints and re.search(r'hẹn hò|ghép đôi', corpus):
            return False
        for constraint in search.hard_constraints:
            if constraint.startswith('activity:'):
                activity = constraint.split(':', 1)[1]
                if activity == 'xem phim':
                    if not re.search(r'rạp|cinema|cineplex', f'{place.source.name} {place.source.category}', re.I):
                        return False
                    if search.budget_max is not None and re.search(r'tham quan|vào cổng', place.source.price_range, re.I):
                        return False
                    continue
                if activity == 'bida' and place.normalized_category_code not in ('the-thao', 'giai-tri'):
                    return False
                pattern = r'\b(?:bida|bi[- ]a|billiards?)\b' if activity == 'bida' else re.escape(activity)
                if not re.search(pattern, corpus):
                    return False
        if search.category and place.normalized_category_code != search.category:
            return False
        if search.location and place.source.district.casefold() != search.location.casefold().removeprefix('quận '):
            return False
        if place.source.id in search.exclude_ids:
            return False
        if search.budget_max is not None:
            if search.budget_exclusive and place.price.maximum == search.budget_max:
                return False
            if place.price.status != 'parsed' or place.price.maximum is None or place.price.maximum > search.budget_max:
                return False
        if search.budget_min is not None:
            if place.price.status != 'parsed' or place.price.maximum is None or place.price.maximum < search.budget_min:
                return False
        return matches_weather_and_setting(place, search)

    def _recommend(self, request, state, search):
        candidates = [hit for hit in self.retriever.retrieve(search) if self._eligible(hit, search)]
        selected = tuple(self.recommender.rank(search, candidates, self.recommendation_k))[:self.recommendation_k]
        places = {hit.place.source.id: hit.place for hit in candidates}
        response = ChatbotResponse('', selected, session_id=request.session_id)
        response.validate_ids(set(places))
        if not selected:
            logger.info('chat source=template kind=no_results')
            dishes = [c[5:] for c in search.hard_constraints if c.startswith('dish:')]
            if dishes:
                area = f' ở {search.location}' if search.location else ''
                return replace(response, answer=f'Mình chưa tìm được quán có thông tin phục vụ {" hoặc ".join(dishes)}{area} phù hợp với yêu cầu của bạn.')
            if any(c.startswith('tourism:') for c in search.hard_constraints):
                area = f' ở {search.location}' if search.location else ''
                kind = 'điểm tham quan'
                if 'tourism:site' in search.hard_constraints:
                    kind = 'khu du lịch'
                elif 'tourism:alternative' in search.hard_constraints:
                    kind = 'chỗ vui chơi khác'
                return replace(response, answer=f'Mình chưa tìm được {kind}{area} phù hợp trong dữ liệu hiện có.',
                               follow_up='Bạn muốn mình tìm thêm ở khu vực lân cận không?' if area else None)
            activity = next((c[9:] for c in search.hard_constraints if c.startswith('activity:')), None)
            if activity:
                area = f' ở {search.location}' if search.location else ''
                return replace(response, answer=f'Mình chưa tìm thấy chỗ chơi {activity}{area} đáp ứng yêu cầu của bạn.',
                               follow_up='Bạn muốn mình tìm ở khu vực khác không?')
            return replace(response, answer='Mình chưa tìm thấy địa điểm đáp ứng yêu cầu trong dữ liệu hiện có.',
                           follow_up='Bạn muốn điều chỉnh khu vực hay ngân sách?')
        try:
            shortlist = selected[:3]
            payload = self.gemini.generate_answer(build_generation_prompt(request.message, state, search, shortlist, places))
            self._validate_generation(payload, shortlist)
            prose = payload['answer'] + ' ' + (payload.get('follow_up') or '')
            # Prices and ratings are especially easy to invent even with valid card IDs.
            sources = [places[pid].source for pid in payload['recommendation_ids']]
            evidence = ' '.join(f'{p.price_range} {p.description}' for p in sources)
            def monetary_values(text):
                matches = re.findall(r'(?<![\d.,])(\d+(?:[.,]\d{3})*)\s*(nghìn|ngàn|k\b|đồng|vnđ|vnd|đ\b)', text, re.I)
                return {int(re.sub(r'[.,]', '', n)) * (1000 if unit.lower() in ('nghìn', 'ngàn', 'k') else 1)
                        for n, unit in matches}
            if monetary_values(payload['answer']) - monetary_values(evidence):
                raise GenerationValidationError('unsupported_price')
            for rating in re.findall(r'\b\d(?:[.,]\d+)?\s*(?:/\s*5|sao\b)', prose, re.I):
                if rating.casefold() not in evidence.casefold():
                    raise GenerationValidationError('unsupported_rating')
            if search.party_size is None and re.search(r'\b(?:các bạn|nhóm của bạn)\b', prose, re.I):
                raise GenerationValidationError('unsupported_group')
            if search.party_size != 2 and re.search(r'\b(hai bạn|hai người|cả hai bạn)\b', prose, re.I):
                raise GenerationValidationError('unsupported_party')
            if 'hẹn hò' not in search.preferences and re.search(r'buổi hẹn|hẹn hò|người yêu|bạn gái|bạn trai', prose, re.I):
                raise GenerationValidationError('unsupported_relationship')
            def visible(text):
                if not text:
                    return text
                for pid in sorted(places, key=len, reverse=True):
                    place = places[pid]
                    text = text.replace('(' + pid + ')', '').replace(pid, place.source.name)
                return re.sub(r'\s+([,.!?])', r'\1', re.sub(r'\bhn_loc_\d+\b', '', text)).strip()
            by_id = {item.place_id: item for item in shortlist}
            cards = tuple(by_id[pid] for pid in payload['recommendation_ids'])
            logger.info('chat source=gemini cards=%d', len(cards))
            return replace(response, answer=visible(payload['answer']), recommendations=cards,
                           follow_up=None if '?' in payload['answer'] else visible(payload.get('follow_up')))
        except (GeminiError, ValueError, KeyError, TypeError) as error:
            cause = error.args[0] if isinstance(error, GenerationValidationError) else type(error).__name__
            logger.warning('chat source=fallback cause=%s cards=%d', cause, len(selected))
            date = 'hẹn hò' in search.preferences
            lines = []
            for index, item in enumerate(selected[:2]):
                source = places[item.place_id].source
                intro = ('Cho buổi hẹn, mình nghiêng về ' if date else 'Mình gợi ý ') if index == 0 else 'Một lựa chọn khác là '
                sentences = re.split(r'(?<=[.!?])\s+', source.description.strip())
                cues = list(search.preferences)
                if search.category == 'an-uong':
                    cues.extend(('nước dùng', 'món đặc trưng', 'vị thanh', 'phở tái'))
                if date:
                    cues.extend(('đi dạo', 'ven hồ', 'lối đi bộ', 'trò chuyện'))
                neutral = [s for s in sentences if not re.search(
                    r'ngon nhất|tuyệt vời|bậc nhất|nổi tiếng|đỉnh cao|không thể chê|được đánh giá', s, re.I)]
                detail = max(neutral, default='', key=lambda s: sum(term.casefold() in s.casefold() for term in cues))
                detail = re.sub(r'^(?:Món ăn nổi bật|Không gian quán)\s+(?=[A-ZÀ-Ỹ])', '', detail)
                line = f'{intro}**{source.name}**.'
                if detail:
                    line += ' ' + detail.rstrip('.!?') + '.'
                elif source.price_range and search.budget_max is None:
                    line += f' Mức giá tham khảo là {source.price_range}.'
                if date and re.search(r'đi dạo|đường dạo|đường đi bộ|lối đi bộ', detail, re.I):
                    line += ' Bạn có thể vừa đi dạo vừa trò chuyện.'
                if search.budget_max is not None:
                    line += f' Giá tham khảo: {source.price_range}.'
                lines.append(line)
            if 'hus' in (request.message + ' ' + search.query).casefold():
                lines.append('Mình chọn theo khu vực của cơ sở HUS. Khoảng cách từ cổng trường đến từng chỗ chưa được xác minh.')
            if 'area:phố cổ' in search.hard_constraints:
                lines.append('Mình tìm trong quận Hoàn Kiếm. Chỉ từ tên quận thì chưa thể chắc từng quán nằm trong khu phố cổ.')
            return replace(response, answer='\n\n'.join(lines))

    @staticmethod
    def _validate_generation(payload, selected):
        if not isinstance(payload, dict) or set(payload) - {'answer', 'recommendation_ids', 'follow_up'}:
            raise GenerationValidationError('unexpected_fields')
        answer = payload.get('answer')
        if not isinstance(answer, str) or not answer.strip() or len(answer) > 12000:
            raise GenerationValidationError('invalid_answer')
        ids = payload.get('recommendation_ids')
        allowed = {item.place_id for item in selected}
        if not isinstance(ids, list) or not ids or not all(isinstance(i, str) and i in allowed for i in ids):
            raise GenerationValidationError('invalid_ids')
        if len(ids) != len(set(ids)):
            raise GenerationValidationError('duplicate_ids')
        follow_up = payload.get('follow_up')
        jargon = r'\b(?:an-uong|ca-phe|tam-linh|di-tich|ngoai-troi|giai-tri|the-thao|semantic score|ranking score|metadata match|khớp danh mục|đáp ứng sở thích)\b'
        if re.search(jargon, answer + ' ' + str(follow_up or ''), re.I):
            raise GenerationValidationError('internal_labels')
        if follow_up is not None and (not isinstance(follow_up, str) or len(follow_up) > 1000):
            raise GenerationValidationError('invalid_follow_up')


class GenerationValidationError(ValueError):
    """Only static diagnostic codes may be logged."""
