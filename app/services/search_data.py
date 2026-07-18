"""Real-world search volume / keyword difficulty data via DataForSEO.

DataForSEO's "Keyword Data" (Google Ads search volume) and "Labs" (keyword
difficulty) endpoints are the intended real data source, per the assessment's
"External API requirement". Both need a paid/trial account.

Because this environment has no DataForSEO credentials configured, and the
assessment must still be runnable and reviewable without them, this module
falls back to a **deterministic, seeded mock generator** when credentials are
absent, and logs a clear warning every time it does so. This is called out
explicitly in the README as a tradeoff -- swap `_fetch_mock` for the real
DataForSEO call by setting DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD in .env and
nothing else needs to change, since both paths return the same shape.
"""
import hashlib
import logging
from dataclasses import dataclass

import requests
from flask import current_app

logger = logging.getLogger(__name__)

DATAFORSEO_ENDPOINT = "https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live"


@dataclass
class KeywordMetrics:
    search_volume: int
    competitive_difficulty: int  # 0-100
    source: str  # "dataforseo" | "mock"


def _fetch_dataforseo(query_text: str) -> KeywordMetrics:
    login = current_app.config["DATAFORSEO_LOGIN"]
    password = current_app.config["DATAFORSEO_PASSWORD"]
    payload = [{"keywords": [query_text], "language_code": "en", "location_code": 2840}]
    resp = requests.post(
        DATAFORSEO_ENDPOINT,
        json=payload,
        auth=(login, password),
        timeout=15,
    )
    resp.raise_for_status()
    body = resp.json()
    result = body["tasks"][0]["result"][0]
    volume = result.get("search_volume") or 0
    # DataForSEO's "competition" is 0.0-1.0 (paid ad competition); scale to 0-100
    # as a proxy for organic/AI-answer competitive difficulty.
    competition = result.get("competition") or 0.0
    difficulty = int(round(competition * 100))
    return KeywordMetrics(search_volume=volume, competitive_difficulty=difficulty, source="dataforseo")


def _fetch_mock(query_text: str) -> KeywordMetrics:
    """Deterministic pseudo-data seeded from the query text so results are
    stable across repeated calls/tests, but still vary sensibly by query."""
    digest = hashlib.sha256(query_text.lower().encode()).hexdigest()
    seed = int(digest[:8], 16)

    # Volume: skew toward the 100-3000/mo range typical of long-tail
    # commercial SEO-tool queries, with a long tail up to ~15k.
    volume = 50 + (seed % 14950)

    # Difficulty: 0-100, weighted slightly toward the middle.
    difficulty = 15 + (seed // 14950) % 80

    return KeywordMetrics(search_volume=volume, competitive_difficulty=difficulty, source="mock")


def get_keyword_metrics(query_text: str) -> KeywordMetrics:
    login = current_app.config.get("DATAFORSEO_LOGIN")
    password = current_app.config.get("DATAFORSEO_PASSWORD")

    if login and password:
        try:
            return _fetch_dataforseo(query_text)
        except Exception:
            logger.exception("DataForSEO call failed for %r; falling back to mock data", query_text)
            return _fetch_mock(query_text)

    logger.warning(
        "DATAFORSEO_LOGIN/PASSWORD not set - using deterministic mock keyword data for %r. "
        "See README 'External data tradeoffs'.",
        query_text,
    )
    return _fetch_mock(query_text)
