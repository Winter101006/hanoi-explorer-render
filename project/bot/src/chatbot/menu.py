"""Menu evidence shared by query understanding and ranking."""
import re


FOODS = {
    'phở bò': ('phở bò', 'phở tái', 'phở chín', 'phở nạm', 'phở gầu'),
    'phở gà': ('phở gà',), 'phở cuốn': ('phở cuốn',), 'phở': ('phở',),
    'cháo sườn': ('cháo sườn', 'cháo sườn sụn'),
    'cháo gà': ('cháo gà',),
    'cháo lòng': ('cháo lòng',),
    'cháo trai': ('cháo trai',),
    'cháo vịt': ('cháo vịt',),
    'cháo': ('cháo',),
    **{dish: (dish,) for dish in ('bún chả', 'bún đậu', 'bún riêu', 'bún ốc',
       'bún bò', 'bánh mì', 'bánh cuốn', 'chả cá', 'xôi', 'lẩu', 'nướng',
       'cà phê muối', 'trà sữa')},
}

_STREET_FOOD_FALSE_POSITIVES = (
    r'\bhàng cháo\b', r'\bhàng bún\b', r'\bhàng đậu\b', r'\bhàng gà\b',
    r'\bhàng cá\b', r'\bhàng muối\b', r'\bhàng đường\b', r'\bhàng hành\b',
    r'\bhàng mắm\b', r'\bhàng buồm\b',
)
_GENERIC_DISH_STOPWORDS = frozenset({
    'gì', 'nào', 'ngon', 'khác', 'này', 'kia', 'đó', 'đây',
    'ăn', 'đặc sản', 'vặt', 'chính', 'tráng miệng', 'nhậu', 'mới',
    'việt', 'hà nội', 'truyền thống', 'bình dân', 'chay', 'nóng', 'lạnh',
})
_EXPLICIT_DISH_RE = re.compile(
    r'\bmón\s+([a-zà-ỹ0-9_-]+(?:\s+[a-zà-ỹ0-9_-]+){0,2}?)'
    r'(?=\s+(?:gì|nào|ngon|khác|ở|tại|gần|quanh|khu|quận|dưới|trên|từ|tầm|khoảng|giá|cho|nhé|nhỉ|ạ|thì|không)\b|[,.!?]|$)',
    re.I,
)


def contains(text, phrase):
    return re.search(r'(?<!\w)' + re.escape(phrase) + r'(?!\w)', text, re.I) is not None


OTHER_FOOD = r'\b(?:món(?: ăn)?(?: gì| nào)? khác|đổi món|ăn gì khác)\b'


def requested_foods(text):
    sanitized = re.sub(r'\s+(?:thì sao|thì thế nào|được không)[?.!\s]*$', '', text.casefold())
    sanitized = re.sub(OTHER_FOOD, ' ', sanitized)
    for pat in _STREET_FOOD_FALSE_POSITIVES:
        sanitized = re.sub(pat, ' ', sanitized)
    matches = [food for food in FOODS if contains(sanitized, food)]
    deduped = [food for food in matches if not any(food != other and food in other for other in matches)]
    explicit = re.search(
        r'\bquán\s+(?:(?:bán|chuyên)\s+)?((?:món\s+)?(?:bún|phở|cháo|bánh|mì|cơm|lẩu)\b.*|món\s+.+)',
        sanitized,
    )
    if not explicit:
        explicit = re.search(
            r'(?<!quán )(?<!đồ )\băn\s+(?!gì\b|ở\b|ngoài\b|trong\b|uống\b|chay\b|sáng\b|trưa\b|tối\b)(.+)',
            sanitized,
        )
    if explicit:
        food = re.split(r'[,.;!?]|\s+(?:ở|tại|gần|quanh|dưới|trên|tầm|giá|ngon|gia truyền|trong nhà|ngoài trời|nhé|ạ|không)\b', explicit[1])[0]
        choices = [part.strip().removeprefix('món ').strip() for part in re.split(r'\s+(?:hoặc|hay)\s+', food)]
        dishes = [part for part in choices if part and part not in _GENERIC_DISH_STOPWORDS and not part.isdigit()]
        if dishes and (len(dishes) > 1 or not deduped):
            return dishes
    if deduped:
        return deduped
    m = _EXPLICIT_DISH_RE.search(sanitized.lower())
    if m:
        candidate = m.group(1).strip()
        if candidate and candidate not in _GENERIC_DISH_STOPWORDS and not candidate.isdigit():
            return [candidate]
    return []


def menu_strength(source, foods):
    """A named specialty is stronger evidence than a mention in the description."""
    aliases = [alias for food in foods for alias in FOODS.get(food, (food,))]
    aliases = [alias for alias in aliases if not re.search(
        r'\b(?:không|ngừng)\s+(?:(?:còn|có|bán|phục vụ|món)\s+)*' + re.escape(alias) + r'\b',
        source.description, re.I)]
    if any(contains(source.name, alias) for alias in aliases):
        return 1.0
    if any(contains(source.description, alias) for alias in aliases):
        return 0.7
    return 0.0
