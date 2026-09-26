import hashlib
import re
from datetime import timedelta
from html import unescape
from urllib.parse import urlsplit, urlunsplit

from .models import Category, Event
from .telemetry import event_clock

ATTACKS = {Category.ARTILLERY_ATTACK, Category.AIR_ATTACK, Category.NAVAL_ATTACK}
PHYSICAL = {Category.SEISMIC_EVENT, Category.INFRASOUND_EVENT}
# 도시 중심점은 기사 위치와 센서의 근접성 비교에만 사용한다. 정밀 관측 좌표가 아니다.
PLACES = {
    "seoul": (37.5665, 126.9780),
    "pyongyang": (39.0392, 125.7625),
    "yeonpyeong": (37.6667, 125.7),
}
PLACE_PATTERN = r"(?:seoul|pyongyang|yeonpyeong|south korea|north korea|korea)"
ATTACK_PATTERN = r"(?:artillery (?:attack|fire|strike)|air ?strike|air attack|naval attack|torpedo attack|shelling|bombing|missile (?:launch|strike)|explosion|attack)"
PATTERNS = [
    (Category.ARTILLERY_ATTACK, r"\b(shelling|artillery (attack|fire|strike))\b"),
    (Category.AIR_ATTACK, r"\b(air ?strike|air attack|bombing)\b"),
    (Category.NAVAL_ATTACK, r"\b(naval attack|torpedo attack)\b"),
    (Category.MISSILE_LAUNCH, r"\bmissile.{0,30}\b(launch|fired)|\blaunch.{0,30}\bmissile"),
    (Category.EXPLOSION, r"\bexplosion\b"),
    (Category.CONFLICT_REPORT, r"\b(attack|clash|conflict)\b"),
]


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]*>", " ", text))).strip()


def classify(title: str) -> Category:
    text = title.lower()
    if re.search(
        r"\b(drill|exercise|anniversary|simulation)\b",
        text,
    ):
        return Category.UNKNOWN
    for category, pattern in PATTERNS:
        match = re.search(pattern, text)
        if match:
            # 사건 표현 앞의 같은 절에 적용되는 추측·부정만 제외한다.
            prefix = re.split(r"[,;.!?]", text[: match.start()])[-1]
            if re.search(r"\b(could|might|fear|warns?|denies|denied|no|not)\b", prefix):
                return Category.UNKNOWN
            if re.search(r"\bmay\s+(?:\w+\s+){0,2}(?:launch|fire|strike|attack|bomb)\b", title):
                return Category.UNKNOWN
            return category
    return Category.UNKNOWN


def reported_location(title: str) -> str | None:
    """제목에서 사건 발생 장소를 명시한 제한된 문형만 인정한다."""
    text = title.lower()
    # 외교 논평·인용은 발생 사실의 독립 증거로 사용하지 않는다.
    if re.search(r"\b(condemns?|protests?|criticizes?|discusses?|urges?|says?|said)\b", text):
        return None
    patterns = [
        rf"\b{ATTACK_PATTERN}\s+(?:(?:reported|reported to be|continues)\s+)?(?:on|in|at|hits|strikes)\s+(?P<place>{PLACE_PATTERN})\b",
        rf"\b(?P<place>{PLACE_PATTERN})\s+(?:(?:is|was|has been)\s+)?(?:under|hit by|struck by|rocked by)\s+{ATTACK_PATTERN}\b",
    ]
    for pattern in patterns:
        if match := re.search(pattern, text):
            return match.group("place")
    return None


def normalize(event: Event) -> Event:
    event = event.model_copy(deep=True)
    event.title, event.body = clean(event.title), clean(event.body)
    text = (event.title + " " + event.body).lower()
    if event.source_type == "kr_government":
        raise ValueError("Korean government sources are excluded")
    if re.search(
        r"south korea.{0,30}(military|government|official|ministry)|joint chiefs|yonhap|합참|국방부",
        text,
    ):
        event.origin_claim = "kr_government"
    elif re.search(r"\breuters\b", text):
        event.origin_claim = "reuters"
    elif re.search(r"\bassociated press\b", text):
        event.origin_claim = "associated_press"
    if event.origin_claim not in {"unknown", "original"}:
        event.evidence_family = event.origin_claim
    elif event.origin_claim == "unknown":
        event.evidence_family = "unresolved"
    clock = event_clock(event)
    if clock is None or clock > event.received_at + timedelta(seconds=60):
        event.metadata["clock_invalid"] = True
    event.metadata["relevant"] = bool(
        (
            event.latitude is not None
            and event.longitude is not None
            and 33 <= event.latitude <= 43
            and 124 <= event.longitude <= 132
        )
        or re.search(r"\b(korea|korean|seoul|pyongyang|yeonpyeong)\b|한반도|연평도", text)
    )
    if event.location == "unknown" and event.metadata["relevant"]:
        event.location = next(
            (x for x in ("seoul", "pyongyang", "yeonpyeong") if x in text), "korea"
        )
    if event.metadata.get("rss") and event.category not in {Category.UNKNOWN}:
        location = reported_location(event.title)
        event.metadata["relevant"] = location is not None
        event.location = location or "unknown"
        if location in PLACES:
            event.latitude, event.longitude = PLACES[location]
            event.metadata["location_precision"] = "city_centroid"
    parsed = urlsplit(event.raw_reference)
    reference = urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path, "", ""))
    if parsed.query:
        # 기사 식별용 쿼리는 보존하고 추적용 파라미터만 제거한다.
        from urllib.parse import parse_qsl, urlencode

        query = urlencode(
            sorted(
                (k, v)
                for k, v in parse_qsl(parsed.query)
                if not k.startswith("utm_") and k not in {"fbclid", "gclid"}
            )
        )
        reference = urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path, query, ""))
    event.fingerprint = hashlib.sha256(
        f"{event.source_id}|{reference}|{event.title.lower()}".encode()
    ).hexdigest()
    event.metadata["content_hash"] = hashlib.sha256(event.title.lower().encode()).hexdigest()
    return event
