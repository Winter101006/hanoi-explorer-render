"""Data loader for Hanoi places dataset.

Parses hanoi_places_cleaned.json into validated Place domain models,
derives normalized category codes, parses structured price information,
and tracks data quality issues (precision, category conflict, unverified coordinates).
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import List, Optional

from project.bot.src.chatbot.config import BOT_DIR
from project.bot.src.chatbot.schemas import (
    CATEGORY_CODES,
    CategoryCode,
    DataQuality,
    Place,
    PriceInfo,
    RawPlace,
)

logger = logging.getLogger(__name__)


def parse_price(price_str: str) -> PriceInfo:
    """Parse raw price string into a structured PriceInfo dataclass."""
    if not price_str or not isinstance(price_str, str) or not price_str.strip():
        return PriceInfo(status='unknown')

    cleaned = price_str.strip().lower()
    conditions: list[str] = []

    # Free entry / no charge checks
    is_free = (
        'miễn phí' in cleaned
        or 'free' in cleaned
        or 'không tính phí' in cleaned
        or cleaned in ('0', '0đ', '0 đ', '0vnd', '0 vnd', '0vnđ', '0 vnđ')
    )
    if is_free:
        if any(k in cleaned for k in ('tham quan', 'vào cửa', 'bên ngoài', 'gửi xe')):
            conditions.append('vào cửa/tham quan')
        return PriceInfo(minimum=0, maximum=0, unit='VND', conditions=tuple(conditions), status='parsed')

    # Normalize dashes and units
    normalized = cleaned.replace('–', '-').replace('—', '-').replace('~', '-').replace('/', ' / ')

    # Separate digits from attached currency symbols or letters (e.g. 60000đ -> 60000 đ)
    normalized = re.sub(r'(\d+)([^\d\s\.,\-])', r'\1 \2', normalized)

    # Convert 50k -> 50000
    normalized = re.sub(r'(\d+)\s*k\b', lambda m: str(int(m.group(1)) * 1000), normalized)

    # Normalize thousand separators like 30.000 or 30,000 -> 30000
    normalized_digits = re.sub(r'(\d+)[\.,](\d{3})', r'\1\2', normalized)

    # Extract all numbers with 4+ digits
    numbers = [int(n) for n in re.findall(r'\b\d{4,9}\b', normalized_digits)]

    # Handle explicit "nghìn" or "ngàn" (e.g. "30 - 50 nghìn")
    if not numbers and any(k in normalized for k in ('nghìn', 'ngàn')):
        small_nums = [int(n) * 1000 for n in re.findall(r'\b\d{1,3}\b', normalized_digits)]
        if small_nums:
            numbers = small_nums

    if not numbers:
        return PriceInfo(status='unknown')

    if len(numbers) == 1:
        val = numbers[0]
        if any(k in normalized for k in ('từ', 'trên', '>=', 'tối thiểu', 'khởi điểm')):
            return PriceInfo(minimum=val, maximum=None, unit='VND', status='parsed')
        elif any(k in normalized for k in ('dưới', 'đến', '<=', 'tối đa', 'chỉ')):
            return PriceInfo(minimum=None, maximum=val, unit='VND', status='parsed')
        else:
            return PriceInfo(minimum=val, maximum=val, unit='VND', status='parsed')

    num_min = min(numbers[0], numbers[1])
    num_max = max(numbers[0], numbers[1])
    return PriceInfo(minimum=num_min, maximum=num_max, unit='VND', status='parsed')


def assess_quality(raw: RawPlace) -> DataQuality:
    """Assess address precision, category conflict, and coordinate reliability."""
    warnings: list[str] = []

    # Category conflict detection
    # E.g. raw.category indicates food ("Quán ăn", "Nhà hàng", "Bún", "Phở") but code is "tam-linh"
    category_conflict = False
    raw_cat_lower = raw.category.lower()
    raw_name_lower = raw.name.lower()
    raw_code = raw.category_code.lower()

    if ('quán ăn' in raw_cat_lower or 'nhà hàng' in raw_cat_lower) and raw_code not in ('an-uong', 'ca-phe'):
        category_conflict = True
        warnings.append(f'Quán ăn/Nhà hàng bị gán nhầm mã danh mục {raw_code}')
    elif 'quán nước' in raw_cat_lower and raw_code not in ('ca-phe', 'an-uong'):
        category_conflict = True
        warnings.append(f'Quán nước bị gán nhầm mã danh mục {raw_code}')
    elif ('chùa' in raw_name_lower or 'đền' in raw_name_lower or 'miếu' in raw_name_lower) and raw_code == 'an-uong':
        category_conflict = True
        warnings.append('Địa điểm tâm linh bị gán nhầm mã an-uong')

    # Address precision detection
    addr_lower = raw.address.lower().strip()
    if not addr_lower or (addr_lower.startswith('quận ') and len(addr_lower.split(',')) <= 2 and not any(k in addr_lower for k in ('phố', 'đường', 'số', 'ngõ', 'ngách', 'khu', 'thôn', 'xóm'))):
        precision = 'district_only'
    elif any(k in addr_lower for k in ('khu', 'chợ', 'hồ', 'công viên', 'khu đô thị', 'kđt', 'vườn hoa')):
        precision = 'area'
    elif any(k in addr_lower for k in ('số', 'phố', 'đường', 'ngõ', 'ngách', 'tòa', 'tầng', 'ngõ/')):
        precision = 'street_or_specific'
    else:
        precision = 'unknown'

    # Numeric coordinate validity does NOT imply verified coordinates per contract
    coordinates_verified = False

    return DataQuality(
        category_conflict=category_conflict,
        address_precision=precision,
        coordinates_verified=coordinates_verified,
        warnings=tuple(warnings),
    )


def normalize_category(raw: RawPlace) -> Optional[CategoryCode]:
    """Derive normalized category code according to shared contract rules."""
    raw_cat_lower = raw.category.lower()
    raw_code = raw.category_code.strip()

    # Rule: Quán ăn / Nhà hàng with mismatched code (e.g. tam-linh from street name, the-thao) -> an-uong
    if ('quán ăn' in raw_cat_lower or 'nhà hàng' in raw_cat_lower) and raw_code not in ('an-uong', 'ca-phe'):
        return 'an-uong'

    # Rule: Quán nước beverage mapping; unresolved conflicted cases retain None (unknown)
    if 'quán nước' in raw_cat_lower:
        if raw_code in ('ca-phe', 'an-uong'):
            return raw_code  # type: ignore[return-value]
        evidence = f'{raw.name} {raw.description}'.lower()
        if any(k in evidence for k in ('bia hơi', 'quán bia', 'quán nhậu')):
            return 'an-uong'
        if any(k in evidence for k in ('cafe', 'cà phê', 'coffee', 'trà sữa', 'tea', 'trà chanh', 'bar', 'pub', 'lounge', 'matcha', 'sinh tố')):
            return 'ca-phe'
        return None

    if raw_code in CATEGORY_CODES:
        return raw_code  # type: ignore[return-value]

    return None


def load(path: Optional[Path | str] = None) -> List[Place]:
    """Load and validate all places from JSON into rich Place domain objects."""
    if path is None:
        target_path = BOT_DIR / 'data/hanoi_places_cleaned.json'
    else:
        target_path = Path(path)

    if not target_path.exists():
        raise FileNotFoundError(f'Data file not found at: {target_path}')

    raw_items = json.loads(target_path.read_text(encoding='utf-8'))
    places: list[Place] = []

    seen_ids: set[str] = set()
    duplicate_ids: set[str] = set()

    for item in raw_items:
        raw = RawPlace.from_dict(item)
        if raw.id in seen_ids:
            duplicate_ids.add(raw.id)
        seen_ids.add(raw.id)

        norm_cat = normalize_category(raw)
        price_info = parse_price(raw.price_range)
        quality = assess_quality(raw)

        place = Place(
            source=raw,
            normalized_category_code=norm_cat,
            price=price_info,
            quality=quality,
        )
        places.append(place)

    if duplicate_ids:
        logger.warning(f'Found {len(duplicate_ids)} duplicate IDs in dataset: {duplicate_ids}')

    return places


# Alias matching alternative conventions
load_places = load
