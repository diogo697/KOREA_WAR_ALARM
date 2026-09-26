"""공개 신호를 파싱한다. 신호 종류와 원관측 계열을 구분한다."""

import json
from datetime import UTC, datetime, timedelta

from .models import Category, Event


def parse_emsc(content, source, now):
    message = json.loads(content)
    if message.get("action") not in {"create", "update"}:
        return []
    props = message["data"]["properties"]
    # 검증된 미국 원관측만 허용한다. 미확인 기관·한국 기관은 채택하지 않는다.
    if props.get("auth", "").upper() not in {"NEIC", "USGS"}:
        return []
    lat, lon = float(props["lat"]), float(props["lon"])
    if not (33 <= lat <= 43 and 124 <= lon <= 132):
        return []
    when = datetime.fromisoformat(props["time"].replace("Z", "+00:00"))
    return [
        Event(
            source_id=source.id,
            publisher="USGS",
            evidence_family="usgs",
            origin_claim="original",
            source_type="sensor",
            signal_type="SEISMIC",
            category=Category.SEISMIC_EVENT,
            title=f"Seismic event: {props['unid']}",
            latitude=lat,
            longitude=lon,
            location="korea",
            published_at=when,
            event_time=when,
            event_time_basis="source_reported",
            observed_at=now,
            received_at=now,
            source_observed_time=now,
            source_reliability=source.reliability,
            raw_reference=f"https://www.seismicportal.eu/?eventid={props['unid']}",
            metadata={
                "magnitude": props.get("mag"),
                "authority": props["auth"],
                "action": message["action"],
                "upstream": "usgs",
                "attribution": "EMSC/CSEM; original solution USGS/NEIC",
                "license_url": "https://creativecommons.org/licenses/by/4.0/",
            },
        )
    ]


def parse_adsb(content, source, now):
    data = json.loads(content)
    # readsb now는 epoch milliseconds. 관측 프레임 시각이며 사건 시작 시각이 아니다.
    frame = datetime.fromtimestamp(float(data["now"]) / 1000, UTC)
    if abs((now - frame).total_seconds()) > 120:
        raise ValueError("stale ADS-B frame")
    events = []
    for aircraft in data["ac"]:
        try:
            if str(aircraft.get("squawk", "")) not in {"7500", "7600", "7700"}:
                continue
            # 지상국 재방송(TIS-B)·MLAT과 군 식별 표시는 대상에서 제외한다.
            if aircraft.get("type") != "adsb_icao" or aircraft.get("dbFlags", 0) & 1:
                continue
            lat, lon = float(aircraft["lat"]), float(aircraft["lon"])
            age = max(float(aircraft["seen"]), float(aircraft["seen_pos"]))
            if not (33 <= lat <= 43 and 124 <= lon <= 132 and 0 <= age <= 60):
                continue
            observed = frame - timedelta(seconds=age)
            identity = str(aircraft["hex"])
            events.append(
                Event(
                    source_id=source.id,
                    publisher=source.publisher,
                    evidence_family="adsb-receiver-network",
                    origin_claim="original",
                    source_type="sensor",
                    signal_type="AVIATION",
                    category=Category.AIRSPACE_ANOMALY,
                    title=f"Aircraft emergency indication: {identity} {aircraft['squawk']}",
                    latitude=lat,
                    longitude=lon,
                    location="korea",
                    published_at=observed,
                    source_publish_time=frame,
                    source_observed_time=now,
                    observed_at=now,
                    received_at=now,
                    source_reliability=source.reliability,
                    raw_reference=f"https://globe.adsb.fi/?icao={identity}",
                    metadata={
                        "squawk": aircraft["squawk"],
                        "observation_only": True,
                        "frame_time": frame.isoformat(),
                        "event_onset_unknown": True,
                        "attribution": "adsb.fi https://adsb.fi/",
                        "license_url": source.license_url,
                    },
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return events
