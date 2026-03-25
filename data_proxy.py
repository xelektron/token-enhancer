"""
Agent Cost Proxy - Layer 2: Data Proxy
Fetches URLs, strips HTML noise, caches results.
Returns clean text instead of raw HTML.
"""

import re
import json
import time
import sqlite3
import hashlib
from dataclasses import dataclass

import requests as http_requests
from bs4 import BeautifulSoup
from url_validator import validate_url, URLValidationError


DB_PATH = "agent_proxy.db"


@dataclass
class DataResult:
    url: str
    original_size: int
    cleaned_size: int
    original_tokens: int
    cleaned_tokens: int
    from_cache: bool
    content: str
    content_type: str
    error: str = ""


# ============================================================
#  DATABASE
# ============================================================

def init_data_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS data_cache (
            cache_key TEXT PRIMARY KEY,
            url TEXT,
            payload TEXT,
            original_tokens INTEGER,
            cleaned_tokens INTEGER,
            fetched_at INTEGER,
            ttl_sec INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS data_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER,
            url TEXT,
            original_tokens INTEGER,
            cleaned_tokens INTEGER,
            from_cache INTEGER,
            reduction_pct REAL,
            error TEXT
        )
    """)
    conn.commit()
    conn.close()


def cache_key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def cache_get(url: str):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT payload, original_tokens, cleaned_tokens, fetched_at, ttl_sec "
        "FROM data_cache WHERE cache_key = ?",
        (cache_key(url),)
    ).fetchone()
    conn.close()
    if row and (time.time() - row[3]) < row[4]:
        return {
            "payload": row[0],
            "original_tokens": row[1],
            "cleaned_tokens": row[2]
        }
    return None


def cache_set(url: str, payload: str, original_tokens: int,
              cleaned_tokens: int, ttl: int = 300):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO data_cache VALUES (?,?,?,?,?,?,?)",
        (cache_key(url), url, payload, original_tokens,
         cleaned_tokens, int(time.time()), ttl)
    )
    conn.commit()
    conn.close()


def log_fetch(url, original_tokens, cleaned_tokens, from_cache, error=""):
    reduction = 0
    if original_tokens > 0:
        reduction = (1 - cleaned_tokens / original_tokens) * 100
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO data_log (timestamp, url, original_tokens, "
        "cleaned_tokens, from_cache, reduction_pct, error) "
        "VALUES (?,?,?,?,?,?,?)",
        (int(time.time()), url, original_tokens, cleaned_tokens,
         int(from_cache), reduction, error)
    )
    conn.commit()
    conn.close()


# ============================================================
#  HTML CLEANING
# ============================================================

# Tags that are pure noise
REMOVE_TAGS = [
    "script", "style", "nav", "footer", "header", "aside",
    "iframe", "noscript", "svg", "form", "button",
]

# CSS classes/ids that are noise
NOISE_PATTERNS = re.compile(
    r'(ad[-_]?|sidebar|cookie|consent|popup|modal|newsletter|'
    r'social|share|comment|related|promo|banner|sponsor|'
    r'disclaimer|footer|nav|menu|breadcrumb)',
    re.IGNORECASE
)


def clean_html(raw_html: str, url: str = "") -> str:
    """Strip HTML down to readable text content."""
    soup = BeautifulSoup(raw_html, "html.parser")

    # Step 1: Find the best content container FIRST
    target = (
        soup.find("div", id=re.compile(r"mw-content-text|main-content", re.I)) or
        soup.find("article") or
        soup.find("main") or
        soup.find("div", {"role": "main"}) or
        soup.find("div", class_=re.compile(r"article.?body|post.?content|entry.?content", re.I)) or
        soup
    )

    # Step 2: Remove noise tags INSIDE the content container
    for tag_name in REMOVE_TAGS:
        for tag in target.find_all(tag_name):
            tag.decompose()

    # Step 3: Remove noisy elements INSIDE the content container
    for tag in target.find_all(True):
        if tag.attrs is None:
            continue
        classes = " ".join(tag.get("class", []))
        tag_id = tag.get("id", "") or ""
        combined = f"{classes} {tag_id}"
        if NOISE_PATTERNS.search(combined):
            tag.decompose()

    # Step 4: Extract text
    text = target.get_text(separator="\n", strip=True)

    # Clean up whitespace
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    text = "\n".join(lines)

    # Collapse multiple blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text


def clean_json_response(raw_json: str) -> str:
    """Remove common junk keys from JSON API responses."""
    junk_keys = {
        "meta", "metadata", "tracking", "ads", "advertisement",
        "pagination", "paging", "links", "_links", "debug",
        "request_id", "trace_id", "server", "timing",
        "disclaimer", "copyright", "legal",
    }

    try:
        data = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError):
        return raw_json

    def strip_junk(obj):
        if isinstance(obj, dict):
            return {k: strip_junk(v) for k, v in obj.items()
                    if k.lower() not in junk_keys}
        elif isinstance(obj, list):
            return [strip_junk(item) for item in obj]
        return obj

    cleaned = strip_junk(data)
    return json.dumps(cleaned, indent=2)


# ============================================================
#  MAIN FETCH + CLEAN
# ============================================================

def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def fetch_and_clean(url: str, ttl: int = 300) -> DataResult:
    """Fetch a URL, clean it, cache it, return clean content."""

    # Validate URL before doing anything (SSRF protection)
    try:
        validate_url(url)
    except URLValidationError as e:
        error = str(e)
        log_fetch(url, 0, 0, from_cache=False, error=error)
        return DataResult(
            url=url, original_size=0, cleaned_size=0,
            original_tokens=0, cleaned_tokens=0,
            from_cache=False, content="", content_type="error",
            error=error
        )

    # Check cache first
    cached = cache_get(url)
    if cached:
        log_fetch(url, cached["original_tokens"],
                  cached["cleaned_tokens"], from_cache=True)
        return DataResult(
            url=url,
            original_size=cached["original_tokens"] * 4,
            cleaned_size=cached["cleaned_tokens"] * 4,
            original_tokens=cached["original_tokens"],
            cleaned_tokens=cached["cleaned_tokens"],
            from_cache=True,
            content=cached["payload"],
            content_type="cached"
        )

    # Fetch
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; AgentCostProxy/0.1)"
        }
        resp = http_requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
    except http_requests.RequestException as e:
        error = str(e)
        log_fetch(url, 0, 0, from_cache=False, error=error)
        return DataResult(
            url=url, original_size=0, cleaned_size=0,
            original_tokens=0, cleaned_tokens=0,
            from_cache=False, content="", content_type="error",
            error=error
        )

    raw = resp.text
    original_tokens = estimate_tokens(raw)
    content_type_header = resp.headers.get("content-type", "")

    # Route to correct cleaner
    if "json" in content_type_header:
        cleaned = clean_json_response(raw)
        ctype = "json"
    elif "html" in content_type_header or raw.strip().startswith("<"):
        cleaned = clean_html(raw, url)
        ctype = "html_cleaned"
    else:
        cleaned = raw.strip()
        ctype = "text"

    cleaned_tokens = estimate_tokens(cleaned)

    # Cache it
    cache_set(url, cleaned, original_tokens, cleaned_tokens, ttl)

    # Log it
    log_fetch(url, original_tokens, cleaned_tokens, from_cache=False)

    return DataResult(
        url=url,
        original_size=len(raw),
        cleaned_size=len(cleaned),
        original_tokens=original_tokens,
        cleaned_tokens=cleaned_tokens,
        from_cache=False,
        content=cleaned,
        content_type=ctype
    )
