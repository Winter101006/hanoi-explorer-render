"""Query understanding and constraint state management.

Extracts categories, locations, budgets, preferences, weather/setting context,
party sizes, and detects ambiguous prompts before retrieval.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional, Tuple

from project.bot.src.chatbot.menu import OTHER_FOOD, requested_foods
from project.bot.src.chatbot.schemas import (
    CATEGORY_CODES,
    CategoryCode,
    ConversationState,
    QueryUnderstanding,
    QueryUpdate,
    SearchRequest,
)

# Recognized areas may include places outside the current dataset.
DISTRICT_PATTERNS: dict[str, list[str]] = {
    'Gia Lâm': [r'\bgia lâm\b'],
    'Ba Đình': [r'\bba đình\b', r'\bgiảng võ\b', r'\bliễu giai\b', r'\bđội cấn\b', r'\bkim mã\b', r'\bphan đình phùng\b'],
    'Hoàn Kiếm': [
        r'\bhoàn kiếm\b', r'\bhồ gươm\b', r'\bbờ hồ\b', r'\bphố cổ\b',
        r'\btạ hiện\b', r'\bhàng bạc\b', r'\bhàng bồ\b', r'\blê thánh tông\b', r'\bđinh tiên hoàng\b',
    ],
    'Tây Hồ': [r'\btây hồ\b', r'\bhồ tây\b', r'\bquảng an\b', r'\bxuân diệu\b', r'\btrúc bạch\b', r'\bnghi tàm\b'],
    'Long Biên': [r'\blong biên\b', r'\bngọc lâm\b', r'\bnguyễn sơn\b', r'\bbo thề\b', r'\baeon long biên\b'],
    'Cầu Giấy': [
        r'\bcầu giấy\b', r'\btô hiệu\b', r'\bnghĩa tân\b', r'\bdịch vọng\b',
        r'\btrần thái tông\b', r'\bduy tân\b', r'\bxuân thủy\b', r'\bhồ tùng mậu\b',
    ],
    'Đống Đa': [
        r'\bđống đa\b', r'\bchùa láng\b', r'\bô chợ dừa\b', r'\bxã đàn\b',
        r'\bthái hà\b', r'\bhoàng cầu\b', r'\bnguyên hồng\b',
    ],
    'Hai Bà Trưng': [
        r'\bhai bà trưng\b', r'\btạ quang bửu\b', r'\bbách khoa\b', r'\btrần đại nghĩa\b',
        r'\blê thanh nghị\b', r'\btimes city\b', r'\bphố minh khai\b', r'\bminh khai\b',
    ],
    'Hoàng Mai': [r'\bhoàng mai\b', r'\blinh đàm\b', r'\bđịnh công\b', r'\bkim giang\b'],
    'Thanh Xuân': [
        r'\bthanh xuân\b', r'\bnguyễn trãi\b', r'\bngụy như kon tum\b',
        r'\bkhương trung\b', r'\broyal city\b',
    ],
    'Nam Từ Liêm': [
        r'\bnam từ liêm\b', r'\bmễ trì\b', r'\bđình thôn\b',
        r'\bphùng khoang\b', r'\btrung văn\b', r'\bmỹ đình\b',
    ],
    'Bắc Từ Liêm': [r'\bbắc từ liêm\b', r'\bcổ nhuế\b', r'\bxuân đỉnh\b', r'\bphường minh khai\b'],
    'Hà Đông': [r'\bhà đông\b', r'\bvăn quán\b', r'\bmỗ lao\b', r'\bquang trung hà đông\b', r'\bvạn phúc\b'],
}

CATEGORY_LABELS: dict[CategoryCode, str] = {
    'an-uong': 'Ăn uống',
    'ca-phe': 'Cà phê / Đồ uống',
    'tam-linh': 'Tâm linh / Văn hóa',
    'di-tich': 'Di tích / Lịch sử',
    'ngoai-troi': 'Ngoài trời / Sinh thái',
    'giai-tri': 'Giải trí',
    'the-thao': 'Thể thao',
}

# Specific keywords are checked before vague fallback terms so phrases like
# "đi bơi ở hồ bơi" -> the-thao and "đi chơi ăn uống" -> an-uong.
CATEGORY_KEYWORDS: dict[CategoryCode, list[str]] = {
    'the-thao': ['hồ bơi', 'bể bơi', 'thể thao', 'gym', 'bóng đá', 'cầu lông', 'pickleball', 'bơi', 'tennis', 'yoga', 'chạy bộ'],
    'ca-phe': ['cà phê muối', 'cà phê', 'cafe', 'coffee', 'quán nước', 'trà sữa', 'matcha', 'trà chanh'],
    'an-uong': [
        'quán ăn', 'nhà hàng', 'ăn uống', 'bún bò', 'bún chả', 'bún đậu', 'bún riêu', 'bún ốc', 'bún',
        'phở bò', 'phở gà', 'phở cuốn', 'phở', 'cháo sườn', 'cháo gà', 'cháo lòng', 'cháo',
        'cơm', 'lẩu', 'nướng', 'nhậu', 'bánh mì', 'bánh cuốn', 'chả cá', 'xôi', 'ăn vặt', 'chè', 'ẩm thực',
    ],
    'tam-linh': ['văn miếu', 'quốc tử giám', 'chùa', 'đền', 'phủ', 'miếu', 'nhà thờ', 'tâm linh', 'dâng hương', 'cầu an'],
    'di-tich': ['di tích', 'bảo tàng', 'lăng bác', 'lăng', 'hoàng thành', 'nhà tù', 'hỏa lò', 'cột cờ', 'lịch sử'],
    'giai-tri': [
        'bida', 'billiards', 'bowling', 'xem phim', 'rạp chiếu phim', 'rạp chiếu',
        'cinema', 'karaoke', 'board game', 'game', 'giải trí', 'vui chơi',
    ],
    'ngoai-troi': ['công viên', 'cắm trại', 'dã ngoại', 'đi dạo', 'vườn hoa', 'picnic', 'view hồ', 'sinh thái'],
}

GENERIC_CATEGORY_KEYWORDS: list[Tuple[CategoryCode, list[str]]] = [
    ('an-uong', ['ăn']),
    ('giai-tri', ['nơi chơi', 'đi chơi']),
    ('ngoai-troi', ['ngoài trời', 'hồ']),
]

PREFERENCE_KEYWORDS: dict[str, list[str]] = {
    'yên tĩnh': ['yên tĩnh', 'quiet', 'không ồn', 'trầm lắng'],
    'học tập': ['học bài', 'học tập', 'làm việc', 'study', 'work', 'chạy deadline', 'deadline'],
    'view đẹp': ['view đẹp', 'sống ảo', 'checkin', 'check-in', 'chụp ảnh', 'view hồ'],
    'hẹn hò': ['hẹn hò', 'date', 'couple', 'người yêu'],
    'tụ tập': ['tụ tập', 'nhóm bạn', 'họp nhóm', 'đông người', 'bạn bè'],
    'gia đình': ['gia đình', 'trẻ em', 'cho bé', 'cho trẻ', 'cả nhà'],
    '24/7': ['24/7', 'mở khuya', 'mở muộn', 'đến muộn', 'xuyên đêm', 'qua đêm'],
    'ngoài trời': ['ngoài trời', 'sân vườn', 'vỉa hè', 'hóng gió', 'ban công', 'rooftop'],
    'trong nhà': ['trong nhà', 'điều hòa', 'máy lạnh'],
}

ACTIVITY_TERMS = ('cầu lông', 'bida', 'bowling', 'gym', 'bơi')

LOCATION_NAMES_WITH_CATEGORY_WORDS = (
    r'\bchùa láng\b', r'\bchùa bộc\b', r'\bchùa hà\b', r'\bphủ doãn\b', r'\bphủ lỗ\b',
    r'\btây hồ\b', r'\bhồ tây\b', r'\bhồ gươm\b', r'\bhồ hoàn kiếm\b', r'\bbờ hồ\b',
    r'\bhồ tùng mậu\b', r'\bhồ đắc di\b',
    r'\bhàng cháo\b', r'\bhàng bún\b', r'\bhàng đậu\b', r'\bhàng gà\b',
    r'\bhàng cá\b', r'\bhàng muối\b', r'\bhàng đường\b', r'\bhàng than\b',
)

TOURISM_PATTERN = r'\b(?:khu du lịch|điểm du lịch|địa điểm du lịch|tham quan|du lịch sinh thái|đi du lịch)\b'
OTHER_PLACES_PATTERN = (
    r'\b(?:(?:chỗ|địa điểm|quán|khu du lịch)(?: [\w-]+){0,3}? khác'
    r'|(?:còn|có) gì (?:chơi )?khác|(?:đi|chơi) (?:đâu|gì) khác'
    r'|đổi (?:chỗ|địa điểm|quán|hoạt động)|thêm (?:chỗ|địa điểm|quán))\b'
)

_CLEAR_BUDGET_PHRASES = (
    'không giới hạn giá', 'bỏ giới hạn giá', 'giá nào cũng được',
    'không cần giới hạn', 'bỏ ngân sách', 'không giới hạn ngân sách',
)

_NON_MONEY_AFTER_RE = re.compile(
    r'^\s*(?:giờ|h\b|tiếng|phút|p\b|giây|người\s+bạn|người|bạn|đứa|thành\s+viên'
    r'|km|m\b|mét|lần|lượt|tháng|ngày|năm|tuổi|cơ\s*sở|cs\b|chỗ|quán|món|tầng)\b',
    re.I,
)
_NON_MONEY_BEFORE_RE = re.compile(
    r'(?:cơ\s*sở|cs|thứ|số|lần|lượt|nhóm|team|đi\s+với|đi\s+cùng|tòa|ngõ|ngách|tầng)\s*$',
    re.I,
)
_MONEY_TRIGGER_BEFORE_RE = re.compile(
    r'(?:ngân\s*sách|giá(?:\s*(?:dưới|tầm|khoảng|tối\s*đa|trên|từ|tối\s*thiểu))?'
    r'|tối\s*đa|tối\s*thiểu|dưới|trên|từ|<=|<|>=|>|tầm|khoảng|chừng)\s*$',
    re.I,
)
_MIN_CUE_BEFORE_RE = re.compile(r'(?:trên|từ|tối\s*thiểu|ít\s*nhất|hơn|>=|>)\s*$', re.I)
_STRICT_MAX_CUE_BEFORE_RE = re.compile(r'(?:\bdưới(?:\s+tầm)?|<)\s*$', re.I)
_MAX_CUE_BEFORE_RE = re.compile(r'(?:dưới(?:\s+tầm)?|tối\s*đa|<=|<|đến|tới)\s*$', re.I)

_MONEY_MILLION_SPLIT_RE = re.compile(r'(?<!\w)(\d+)\s*tr\s*(\d{1,2})(?!\w)', re.I)
_MONEY_UNIT_RE = re.compile(
    r'(?<!\w)(\d+(?:[.,]\d+)?)\s*(triệu|tr|k|nghìn|ngàn)\b'
    r'|(?<!\w)(\d{1,3}(?:[.,]\d{3})+|\d{4,9})\s*(đồng|vnd|vnđ|đ)?(?![\w\d])',
    re.I,
)
_BARE_SMALL_MONEY_RE = re.compile(r'(?<!\w)(\d{2,3})(?!\w)', re.I)

_VIET_NUMBERS: dict[str, int] = {
    'một': 1, 'hai': 2, 'ba': 3, 'bốn': 4, 'tư': 4,
    'năm': 5, 'sáu': 6, 'bảy': 7, 'tám': 8, 'chín': 9, 'mười': 10,
}
_NUM_WORD_ALT = r'\d+|' + '|'.join(_VIET_NUMBERS)
_NEG_PREFIX_RE = re.compile(
    r'(?:không\s+(?:cần|muốn|thích|đi|phải)|không|đừng|tránh|bỏ|bớt)\s*(?:chỗ|quán|khu)?\s*$',
    re.I,
)
_SETTING_INDOOR_KW = ('trong nhà', 'điều hòa', 'máy lạnh', 'phòng kín')
_SETTING_OUTDOOR_KW = ('ngoài trời', 'sân vườn', 'ban công', 'rooftop', 'vỉa hè')


def _word_regex(keyword: str) -> re.Pattern[str]:
    return re.compile(r'(?<!\w)' + re.escape(keyword) + r'(?!\w)', re.I)


def _strip_category_false_positives(text: str) -> str:
    sanitized = text.lower()
    for pattern in LOCATION_NAMES_WITH_CATEGORY_WORDS:
        sanitized = re.sub(pattern, ' ', sanitized)
    return sanitized


def _parse_money_tokens(lower: str) -> List[Tuple[int, int, int]]:
    """Find (start, end, amount_vnd) spans while rejecting time/people/count numbers."""
    spans: List[Tuple[int, int, int]] = []
    occupied: List[Tuple[int, int]] = []

    def is_free(start: int, end: int) -> bool:
        return not any(not (end <= s or start >= e) for s, e in occupied)

    for m in _MONEY_MILLION_SPLIT_RE.finditer(lower):
        if _NON_MONEY_AFTER_RE.match(lower[m.end():]):
            continue
        major = int(m.group(1))
        frac = m.group(2)
        val = major * 1_000_000 + int(frac) * (10 ** (6 - len(frac)))
        spans.append((m.start(), m.end(), val))
        occupied.append((m.start(), m.end()))

    for m in _MONEY_UNIT_RE.finditer(lower):
        if not is_free(m.start(), m.end()):
            continue
        if _NON_MONEY_AFTER_RE.match(lower[m.end():]):
            continue
        if m.group(1) and m.group(2):
            num_raw = m.group(1).replace(',', '.')
            unit = m.group(2).lower()
            mult = 1_000_000 if unit in ('triệu', 'tr') else 1_000
            val = int(round(float(num_raw) * mult))
        else:
            digits = re.sub(r'[.,]', '', m.group(3))
            val = int(digits)
            has_currency = bool(m.group(4))
            has_separator = '.' in m.group(3) or ',' in m.group(3)
            before = lower[:m.start()]
            if _NON_MONEY_BEFORE_RE.search(before):
                continue
            if not has_currency and not has_separator and not _MONEY_TRIGGER_BEFORE_RE.search(before):
                continue
        spans.append((m.start(), m.end(), val))
        occupied.append((m.start(), m.end()))

    for m in _BARE_SMALL_MONEY_RE.finditer(lower):
        if not is_free(m.start(), m.end()):
            continue
        if _NON_MONEY_AFTER_RE.match(lower[m.end():]):
            continue
        before = lower[:m.start()]
        if _NON_MONEY_BEFORE_RE.search(before):
            continue
        if not _MONEY_TRIGGER_BEFORE_RE.search(before):
            continue
        num = int(m.group(1))
        if num < 10:
            continue
        spans.append((m.start(), m.end(), num * 1000))
        occupied.append((m.start(), m.end()))

    spans.sort(key=lambda item: item[0])
    return spans


def _extract_budget(text: str) -> Tuple[Optional[int], Optional[int], bool, bool]:
    """Return the price bounds, whether to clear them, and whether the upper bound is strict."""
    lower = text.lower()
    if any(k in lower for k in _CLEAR_BUDGET_PHRASES):
        return None, None, True, False

    spans = _parse_money_tokens(lower)
    if not spans:
        return None, None, False, False

    if len(spans) >= 2:
        between = lower[spans[0][1]:spans[1][0]].strip()
        if between in ('-', '–', 'đến', 'tới'):
            low, high = spans[0][2], spans[1][2]
            return min(low, high), max(low, high), False, False

    bmin: Optional[int] = None
    bmax: Optional[int] = None
    exclusive = False
    for start, _end, val in spans:
        before = lower[max(0, start - 24):start]
        if _MIN_CUE_BEFORE_RE.search(before):
            bmin = val
        elif _MAX_CUE_BEFORE_RE.search(before) or bmax is None:
            bmax = val
            exclusive = bool(_STRICT_MAX_CUE_BEFORE_RE.search(before))

    if bmin is not None and bmax is not None and bmin > bmax:
        bmin, bmax = bmax, bmin
        exclusive = False
    return bmin, bmax, False, exclusive


def extract_budget_bounds(text: str) -> Tuple[Optional[int], Optional[int], bool]:
    minimum, maximum, clear, _ = _extract_budget(text)
    return minimum, maximum, clear


def extract_budget(text: str) -> Tuple[Optional[int], bool]:
    """Extract max budget from text, or check if user asks to remove budget limits."""
    _, budget_max, clear_budget = extract_budget_bounds(text)
    return budget_max, clear_budget


def extract_district(text: str) -> Optional[str]:
    """Identify target district or landmark, handling multi-district transitions and HUS campuses."""
    lower = text.lower()
    elsewhere = re.search(r'\b(?:ở|tại|quanh)\s+(?:thành phố |tp\.? )?(đà nẵng|hồ chí minh|sài gòn|huế|hải phòng|đà lạt|nha trang|cần thơ|hội an)\b', lower)
    if elsewhere:
        return elsewhere[1].title()
    raw_matches: List[Tuple[int, int, str]] = []
    for district, patterns in DISTRICT_PATTERNS.items():
        for pat in patterns:
            for m in re.finditer(pat, lower):
                raw_matches.append((m.start(), m.end(), district))

    if re.search(r'\b(?:hus|khtn|khoa\s+học\s+tự\s+nhiên)\b', lower):
        for pat, district in ((r'\b(?:cơ\s*sở\s*1|cs1)\b', 'Hoàn Kiếm'), (r'\b(?:cơ\s*sở\s*2|cs2)\b', 'Thanh Xuân')):
            for m in re.finditer(pat, lower):
                raw_matches.append((m.start(), m.end(), district))

    if not raw_matches:
        return None

    # Resolve overlapping spans by longest match first (e.g. "phường minh khai" vs "minh khai").
    raw_matches.sort(key=lambda item: (-(item[1] - item[0]), item[0]))
    accepted: List[Tuple[int, int, str]] = []
    for s, e, d in raw_matches:
        if any(not (e <= as_ or s >= ae) for as_, ae, _ in accepted):
            continue
        accepted.append((s, e, d))
    accepted.sort(key=lambda item: item[0])

    origin_or_neg = re.compile(r'(?:^|\s)(?:từ|rời|bỏ|trừ|ngoài|thay\s+vì|không\s+(?:ở|tại|phải))\s*$', re.I)
    target_cue = re.compile(r'(?:^|\s)(?:sang|qua|chuyển\s+sang|đổi\s+sang|về|tới|đến|ở|tại|quanh|gần)\s*(?:quận|khu)?\s*$', re.I)

    non_negated: List[Tuple[int, bool, str]] = []
    for s, _e, d in accepted:
        prefix = lower[max(0, s - 22):s]
        if origin_or_neg.search(prefix):
            continue
        has_target = bool(target_cue.search(prefix))
        non_negated.append((s, has_target, d))

    if non_negated:
        targeted = [item for item in non_negated if item[1]]
        return targeted[-1][2] if targeted else non_negated[-1][2]
    return accepted[-1][2]


def extract_category(text: str) -> Optional[CategoryCode]:
    """Classify user intent into one of 7 category codes without street/substring false positives."""
    sanitized = _strip_category_false_positives(text)

    # Pass 1: match specific category phrases first, picking earliest occurrence (longest on ties).
    specific_hits: List[Tuple[int, int, CategoryCode]] = []
    for cat_code, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            m = _word_regex(kw).search(sanitized)
            if m:
                specific_hits.append((m.start(), -(m.end() - m.start()), cat_code))
    if specific_hits:
        specific_hits.sort()
        return specific_hits[0][2]

    # Pass 2: generic fallback keywords (strip swimming pool compounds so 'hồ bơi' stays sport).
    generic_text = re.sub(r'\b(?:hồ bơi|bể bơi)\b', ' ', sanitized)
    for cat_code, keywords in GENERIC_CATEGORY_KEYWORDS:
        for kw in keywords:
            if _word_regex(kw).search(generic_text):
                return cat_code
    return None


def extract_preferences_delta(text: str) -> Tuple[List[str], List[str]]:
    """Return (added_preferences, removed_preferences) respecting word boundaries and negation."""
    lower = text.lower()
    # Mask affirmative "không (quá) ồn" so negation detection doesn't treat it as negative.
    quiet_masked = re.sub(r'(?<!\w)không\s+(?:quá\s+)?ồn(?!\w)', ' yên tĩnh ', lower)

    added: List[str] = []
    removed: List[str] = []

    for pref, keywords in PREFERENCE_KEYWORDS.items():
        for kw in keywords:
            for m in _word_regex(kw).finditer(quiet_masked):
                before = quiet_masked[max(0, m.start() - 24):m.start()]
                if _NEG_PREFIX_RE.search(before):
                    if pref not in removed:
                        removed.append(pref)
                else:
                    if pref not in added:
                        added.append(pref)

    # "không cần yên tĩnh" shouldn't re-add if a later phrase wasn't affirmative.
    added = [p for p in added if p not in removed]

    for term in ACTIVITY_TERMS:
        m = _word_regex(term).search(quiet_masked)
        if m:
            before = quiet_masked[max(0, m.start() - 24):m.start()]
            if _NEG_PREFIX_RE.search(before):
                if term not in removed:
                    removed.append(term)
            elif term not in added:
                added.append(term)
    return added, removed


def extract_preferences(text: str) -> List[str]:
    """Extract matching lifestyle and contextual preferences using word boundaries."""
    added, _ = extract_preferences_delta(text)
    return added


def extract_weather(text: str) -> Tuple[Optional[str], Optional[str], bool]:
    """Extract explicit weather condition or clear flag: (weather, weather_source, clear_weather)."""
    lower = text.lower()
    if re.search(r'(?<!\w)(?:tạnh\s*mưa|hết\s*mưa|trời\s*tạnh|không\s*mưa\s*nữa|hết\s*nắng|hết\s*nóng|hết\s*lạnh)(?!\w)', lower):
        return None, None, True
    if re.search(r'(?<!\w)(?:trời\s+(?:đang\s+)?mưa|đang\s+mưa|mưa\s+(?:phùn|to|lớn|rào)|(?<!tạnh\s)(?<!hết\s)(?<!không\s)mưa)(?!\w)', lower):
        return 'mưa', 'user', False
    if re.search(r'(?<!\w)(?:nắng\s+nóng|trời\s+nắng|nắng\s+gắt|nóng\s+bức|nóng\s+nực|oi\s+bức|trời\s+nóng)(?!\w)', lower):
        return 'nắng nóng', 'user', False
    # Guard against matching "máy lạnh" (air conditioner).
    if re.search(r'(?<!máy\s)(?<!\w)(?:trời\s+lạnh|lạnh\s+giá|gió\s+lạnh|trời\s+rét|rét|se\s+lạnh)(?!\w)', lower):
        return 'lạnh', 'user', False
    return None, None, False


def extract_setting(text: str) -> Optional[Literal['indoor', 'outdoor']]:
    """Extract indoor/outdoor venue preference, taking the latest non-negated mention."""
    lower = text.lower()
    hits: List[Tuple[int, Literal['indoor', 'outdoor']]] = []
    for kw in _SETTING_INDOOR_KW:
        for m in _word_regex(kw).finditer(lower):
            if not _NEG_PREFIX_RE.search(lower[max(0, m.start() - 24):m.start()]):
                hits.append((m.start(), 'indoor'))
    for kw in _SETTING_OUTDOOR_KW:
        for m in _word_regex(kw).finditer(lower):
            if not _NEG_PREFIX_RE.search(lower[max(0, m.start() - 24):m.start()]):
                hits.append((m.start(), 'outdoor'))
    if not hits:
        return None
    hits.sort(key=lambda item: item[0])
    return hits[-1][1]


def _parse_viet_number(token: str) -> Optional[int]:
    t = token.strip().lower()
    if t.isdigit():
        return int(t)
    return _VIET_NUMBERS.get(t)


def extract_party_size(text: str) -> Optional[int]:
    """Extract group / party size from digits or Vietnamese number words."""
    lower = text.lower()
    if re.search(r'(?<!\w)(?:một|1)\s*mình(?!\w)|\bđi\s+lẻ\b', lower):
        return 1
    comp = re.search(rf'(?<!\w)đi\s+(?:cùng|với)\s+({_NUM_WORD_ALT})\s+(?:người\s+bạn|người|bạn|đứa)(?!\w)', lower)
    if comp:
        n = _parse_viet_number(comp.group(1))
        if n is not None:
            return 1 + n
    grp = re.search(
        rf'(?<!\w)(?:(?:nhóm|team|bọn\s+mình|tụi\s+mình|chúng\s+mình|tổng|khoảng|tầm|có|gồm)\s+)?'
        rf'({_NUM_WORD_ALT})\s+(?:người|bạn|đứa|thành\s+viên)(?!\w)',
        lower,
    )
    if grp:
        n = _parse_viet_number(grp.group(1))
        if n is not None and n >= 1:
            return n
    if re.search(r'(?<!\w)(?:cặp\s+đôi|couple|2\s*đứa|hai\s*đứa)(?!\w)', lower):
        return 2
    return None


class QueryProcessor:
    """Processes conversational messages and manages query constraints."""

    def process(
        self,
        message: str,
        state: ConversationState,
        explicit_filters: Optional[Dict[str, Any]] = None,
    ) -> QueryUnderstanding:
        explicit_filters = explicit_filters or {}
        cleaned_msg = message.strip()
        lower_msg = cleaned_msg.lower()

        # 1. Reset intent detection
        if any(k in lower_msg for k in ('bắt đầu lại', 'reset', 'xóa hết', 'làm mới', 'chủ đề mới')):
            update = QueryUpdate(reset=True)
            new_request = update.apply(state.constraints)
            return QueryUnderstanding(
                request=new_request,
                update=update,
                intent='reset',
                clarification='Đã làm mới ngữ cảnh tìm kiếm. Bạn muốn tìm địa điểm nào ở Hà Nội?',
            )

        # 2. HUS Ambiguity Check: cơ sở 19 Lê Thánh Tông vs 334 Nguyễn Trãi
        if any(k in lower_msg for k in ('hus', 'khtn', 'khoa học tự nhiên', 'đại học khoa học tự nhiên')):
            has_le_thanh_tong = any(k in lower_msg for k in ('lê thánh tông', 'hoàn kiếm', 'cơ sở 1', 'cs1'))
            has_nguyen_trai = any(k in lower_msg for k in ('nguyễn trãi', 'thanh xuân', 'cơ sở 2', 'cs2'))
            if not has_le_thanh_tong and not has_nguyen_trai:
                return QueryUnderstanding(
                    request=state.constraints,
                    update=QueryUpdate(),
                    intent='clarification',
                    clarification=(
                        "Trường Đại học Khoa học Tự nhiên (HUS) có 2 cơ sở: "
                        "334 Nguyễn Trãi (Thanh Xuân) và 19 Lê Thánh Tông (Hoàn Kiếm). "
                        "Bạn đang muốn tìm địa điểm quanh cơ sở nào?"
                    ),
                )

        # 3. Extract core message entities & detect UI filter conflicts
        target = re.search(r'\b(?:tìm(?: cho (?:tôi|mình))?|gợi ý(?: cho (?:tôi|mình))?)\s+(?:một |các |những )?(quán\b.*)', lower_msg)
        subject = re.split(r'\b(?:để|trước khi|sau khi|gần rạp|gần khu du lịch)\b', target[1], maxsplit=1)[0] if target else lower_msg
        detected_district = extract_district(cleaned_msg)
        food_text = subject
        if detected_district:
            food_text = re.sub(r'\s+(?:(?:quận|huyện)\s+)?' + re.escape(detected_district) + r'\b', '', food_text, flags=re.I)
        foods = requested_foods(food_text)
        change_food = bool(re.search(OTHER_FOOD, lower_msg))
        msg_category = extract_category(subject)
        if (target and not msg_category) or change_food:
            msg_category = 'an-uong'
        if foods:
            msg_category = 'ca-phe' if all(f in ('trà sữa', 'cà phê muối') for f in foods) else 'an-uong'

        activities = [a for a in ACTIVITY_TERMS if _word_regex(a).search(subject)]
        if re.search(r'(?<!\w)(?:bi[- ]a|billiards?)(?!\w)', subject) and 'bida' not in activities:
            activities.append('bida')
        if not target and re.search(r'\b(?:xem phim|rạp phim|rạp chiếu phim|cinema)\b', subject):
            activities.append('xem phim')

        ui_district = explicit_filters.get('district')
        if ui_district and ui_district not in ('all', '', None):
            msg_district = detected_district
            if msg_district and msg_district.lower() != ui_district.lower():
                return QueryUnderstanding(
                    request=state.constraints,
                    update=QueryUpdate(),
                    intent='clarification',
                    clarification=(
                        f"Bạn đang chọn bộ lọc Quận {ui_district} nhưng trong tin nhắn muốn tìm ở Quận {msg_district}. "
                        f"Bạn muốn ưu tiên tìm ở {msg_district} hay {ui_district}?"
                    ),
                )

        ui_cat = explicit_filters.get('category')
        if ui_cat and ui_cat in CATEGORY_CODES and msg_category and msg_category != ui_cat:
            # Cross-category indoor activities ('bida', 'bowling') legitimately span 'giai-tri' & 'the-thao'.
            is_cross_activity = any(a in ('bida', 'bowling') for a in activities) and ui_cat in ('giai-tri', 'the-thao')
            if not is_cross_activity:
                return QueryUnderstanding(
                    request=state.constraints,
                    update=QueryUpdate(),
                    intent='clarification',
                    clarification=(
                        f"Bạn đang chọn bộ lọc {CATEGORY_LABELS.get(ui_cat, ui_cat)} "
                        f"nhưng trong tin nhắn muốn tìm {CATEGORY_LABELS.get(msg_category, msg_category)}. "
                        f"Bạn muốn ưu tiên tìm theo loại hình nào?"
                    ),
                )

        # 4. Extract remaining entities
        detected_category = msg_category
        tourism = bool(re.search(TOURISM_PATTERN, subject))
        detected_budget_min, detected_budget_max, clear_budget, budget_exclusive = _extract_budget(cleaned_msg)
        added_prefs, removed_prefs = extract_preferences_delta(cleaned_msg)
        detected_weather, detected_weather_source, clear_weather = extract_weather(cleaned_msg)
        detected_setting = extract_setting(cleaned_msg)
        if detected_setting is None and 'đi dạo' in subject and not re.search(r'\bkhông (?:đi )?ngoài trời', lower_msg):
            detected_setting = 'outdoor'
        if 'gia truyền' in lower_msg:
            added_prefs.append('gia truyền')

        # Apply UI filters if message omitted them
        if not detected_category and ui_cat and ui_cat in CATEGORY_CODES:
            detected_category = ui_cat  # type: ignore[assignment]

        if not detected_district and ui_district and ui_district not in ('all', '', None):
            for d in DISTRICT_PATTERNS:
                if d.lower() == ui_district.lower():
                    detected_district = d
                    break

        values: dict[str, Any] = {}
        clear_fields: list[str] = []
        constraints = list(state.constraints.hard_constraints)
        no_cafe = bool(re.search(r'không (?:phải |muốn |chọn )?(?:quán )?(?:cafe|cà phê)', lower_msg))
        if no_cafe:
            detected_category = 'an-uong' if 'quán' in lower_msg else None
            if detected_category is None and state.constraints.category:
                clear_fields.append('category')
            if 'exclude:ca-phe' not in constraints:
                constraints.append('exclude:ca-phe')
        elif detected_category == 'ca-phe':
            constraints = [c for c in constraints if c != 'exclude:ca-phe']
        for key, pattern in (('diet:chay', r'\b(?:ăn|quán|món|đồ) chay\b'),
                             ('amenity:wifi', r'\bwi[- ]?fi\b'), ('amenity:cover', r'\bmái che\b')):
            if re.search(pattern, lower_msg) and key not in constraints:
                constraints.append(key)
        if re.search(r'không (?:đi )?ngoài trời', lower_msg):
            added_prefs = [p for p in added_prefs if p != 'ngoài trời']
            if detected_setting is None:
                detected_setting = 'indoor'
            if detected_category == 'ngoai-troi':
                detected_category = None
                if state.constraints.category:
                    clear_fields.append('category')
        alternatives = bool(re.search(OTHER_PLACES_PATTERN, lower_msg))
        generic_alternative = alternatives and not re.search(r'\bquán(?: nào)? khác\b', lower_msg)
        other_activities = alternatives and bool(re.search(r'\b(?:chơi|hoạt động)\b', lower_msg))
        if tourism or detected_category or foods:
            constraints = [c for c in constraints if not c.startswith('tourism:')]
        if tourism and not foods:
            constraints = [c for c in constraints if not c.startswith(('dish:', 'activity:'))]
            constraints.append('tourism:site' if re.search(r'\bkhu du lịch\b', lower_msg) else 'tourism:visit')
            if detected_category is None and state.constraints.category:
                clear_fields.append('category')
        elif (detected_category is None and not foods
              and (other_activities or generic_alternative and 'tourism:site' in constraints)):
            constraints = [c for c in constraints if not c.startswith(('tourism:', 'dish:', 'activity:'))]
            constraints.append('tourism:alternative')
            if state.constraints.category:
                clear_fields.append('category')

        party_size = extract_party_size(cleaned_msg)
        if party_size is not None:
            values['party_size'] = party_size

        if activities or detected_category:
            constraints = [c for c in constraints if not c.startswith('activity:')]
            constraints.extend('activity:' + a for a in activities)
        if activities == ['xem phim']:
            detected_category = 'giai-tri'
        elif activities:
            detected_category = None  # Activities can span sport and entertainment categories.
            if state.constraints.category and ui_cat not in CATEGORY_CODES and 'category' not in clear_fields:
                clear_fields.append('category')
            elif ui_cat in CATEGORY_CODES:
                detected_category = ui_cat
        if foods or change_food or (detected_category and detected_category != state.constraints.category):
            constraints = [c for c in constraints if not c.startswith('dish:')]
            constraints.extend('dish:' + f for f in foods)
        if detected_district:
            constraints = [c for c in constraints if c != 'area:phố cổ']
            if 'phố cổ' in lower_msg:
                constraints.append('area:phố cổ')
        values['hard_constraints'] = tuple(constraints)

        if detected_category:
            values['category'] = detected_category
        elif detected_setting == 'indoor' and state.constraints.category == 'ngoai-troi':
            if 'category' not in clear_fields:
                clear_fields.append('category')

        if detected_district:
            values['location'] = detected_district

        if clear_budget:
            clear_fields.extend(['budget_min', 'budget_max', 'budget_unit', 'budget_exclusive'])
        else:
            if detected_budget_min is not None:
                values['budget_min'] = detected_budget_min
                values['budget_unit'] = 'VND'
                if detected_budget_max is None and state.constraints.budget_max is not None:
                    # Replacing an older max-only budget when asking e.g. "trên 100k".
                    if (state.constraints.budget_max < detected_budget_min or
                            state.constraints.budget_exclusive and state.constraints.budget_max == detected_budget_min):
                        clear_fields.extend(['budget_max', 'budget_exclusive'])
            if detected_budget_max is not None:
                values['budget_max'] = detected_budget_max
                values['budget_unit'] = 'VND'
                values['budget_exclusive'] = budget_exclusive
                if detected_budget_min is None and state.constraints.budget_min is not None:
                    if (state.constraints.budget_min > detected_budget_max or
                            budget_exclusive and state.constraints.budget_min == detected_budget_max):
                        clear_fields.append('budget_min')

        if clear_weather:
            clear_fields.extend(['weather', 'weather_source'])
        elif detected_weather is not None:
            values['weather'] = detected_weather
            values['weather_source'] = detected_weather_source

        if detected_setting is not None:
            values['setting'] = detected_setting

        # Resolve preference additions, removals, and mutually exclusive settings
        if added_prefs or removed_prefs or detected_setting is not None:
            existing_prefs = [p for p in state.constraints.preferences if p not in removed_prefs]
            if detected_setting == 'indoor' or 'trong nhà' in added_prefs:
                existing_prefs = [p for p in existing_prefs if p != 'ngoài trời']
            elif detected_setting == 'outdoor' or 'ngoài trời' in added_prefs:
                existing_prefs = [p for p in existing_prefs if p != 'trong nhà']
            for p in added_prefs:
                if p not in existing_prefs:
                    existing_prefs.append(p)
            values['preferences'] = tuple(existing_prefs)
        if re.search(r'không (?:muốn )?hẹn hò', lower_msg):
            values['preferences'] = tuple(p for p in values.get('preferences', state.constraints.preferences)
                                          if p != 'hẹn hò')
            if 'exclude:dating' not in constraints:
                values['hard_constraints'] = (*values['hard_constraints'], 'exclude:dating')
        elif 'hẹn hò' in added_prefs:
            values['hard_constraints'] = tuple(c for c in values['hard_constraints'] if c != 'exclude:dating')

        values['query'] = cleaned_msg

        # Dedup clear_fields and guard against setting & clearing the same key
        dedup_clear = tuple(k for k in dict.fromkeys(clear_fields) if k not in values)
        update = QueryUpdate(values=values, clear_fields=dedup_clear)
        updated_request = update.apply(state.constraints)

        return QueryUnderstanding(
            request=updated_request,
            update=update,
            intent='location_recommendation',
            clarification=None,
        )


def process(
    message: str,
    state: ConversationState,
    explicit_filters: Optional[Dict[str, Any]] = None,
) -> QueryUnderstanding:
    """Functional interface matching CONTRACTS.md."""
    processor = QueryProcessor()
    return processor.process(message, state, explicit_filters)
