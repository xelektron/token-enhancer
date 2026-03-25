"""
Agent Cost Proxy v0.2
Layer 1: Prompt Refiner (opt-in)
Layer 2: Data Proxy (automatic)

Usage:
    python proxy.py
"""

import json
import time
import sqlite3
import uuid
from flask import Flask, request, jsonify
from optimizer import optimize_prompt
from data_proxy import fetch_and_clean, init_data_db
from url_validator import validate_batch, URLValidationError

app = Flask(__name__)

PROXY_PORT = 8080
DB_PATH = "agent_proxy.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prompt_log (
            request_id TEXT PRIMARY KEY,
            timestamp INTEGER,
            original_tokens INTEGER,
            optimized_tokens INTEGER,
            confidence REAL,
            sent_optimized INTEGER,
            skip_reason TEXT,
            savings_pct REAL
        )
    """)
    conn.commit()
    conn.close()
    init_data_db()


def log_result(result):
    conn = sqlite3.connect(DB_PATH)
    rid = str(uuid.uuid4())[:8]
    savings = 0
    if result.original_tokens > 0:
        savings = (1 - result.optimized_tokens / result.original_tokens) * 100
    conn.execute(
        "INSERT INTO prompt_log VALUES (?,?,?,?,?,?,?,?)",
        (rid, int(time.time()), result.original_tokens,
         result.optimized_tokens, result.confidence,
         int(result.sent_optimized), result.skip_reason, savings)
    )
    conn.commit()
    conn.close()
    return rid


def get_stats():
    conn = sqlite3.connect(DB_PATH)
    prompt_row = conn.execute("""
        SELECT COUNT(*), COALESCE(SUM(original_tokens), 0),
            COALESCE(SUM(optimized_tokens), 0)
        FROM prompt_log
    """).fetchone()
    data_row = conn.execute("""
        SELECT COUNT(*), COALESCE(SUM(original_tokens), 0),
            COALESCE(SUM(cleaned_tokens), 0),
            COALESCE(SUM(from_cache), 0)
        FROM data_log
    """).fetchone()
    conn.close()

    prompt_saved = prompt_row[1] - prompt_row[2]
    data_saved = data_row[1] - data_row[2]
    total_saved = prompt_saved + data_saved

    return {
        "layer1_refine_requests": prompt_row[0],
        "layer1_tokens_saved": prompt_saved,
        "layer2_fetch_requests": data_row[0],
        "layer2_tokens_saved": data_saved,
        "layer2_cache_hits": data_row[3],
        "total_tokens_saved": total_saved,
        "est_cost_saved": total_saved * 0.000015
    }


# ============================================================
#  LAYER 1: Prompt Refiner (opt-in)
# ============================================================

@app.route("/refine", methods=["POST"])
def refine():
    body = request.get_json(force=True)
    text = body.get("text", body.get("prompt", ""))
    if not text:
        return jsonify({"error": "Send {\"text\": \"your prompt\"}"}), 400
    result = optimize_prompt(text)
    rid = log_result(result)
    savings = 0
    if result.original_tokens > 0:
        savings = round((1 - result.optimized_tokens / result.original_tokens) * 100, 1)
    print(f"\n  [{rid}] REFINE | {result.original_tokens} -> {result.optimized_tokens} tokens ({savings}%)")
    return jsonify({
        "original": result.original,
        "suggested": result.optimized,
        "original_tokens": result.original_tokens,
        "suggested_tokens": result.optimized_tokens,
        "savings_pct": savings,
        "confidence": round(result.confidence, 2),
        "protected_entities": result.protected_entities
    })


# ============================================================
#  LAYER 2: Data Proxy (the big one)
# ============================================================

@app.route("/fetch", methods=["POST"])
def fetch():
    """Fetch a URL, strip noise, return clean content."""
    body = request.get_json(force=True)
    url = body.get("url", "")
    ttl = body.get("ttl", 300)

    if not url:
        return jsonify({"error": "Send {\"url\": \"https://...\"}"}), 400

    result = fetch_and_clean(url, ttl)

    if result.error:
        print(f"\n  [FETCH] ERROR | {url[:50]} | {result.error[:50]}")
        return jsonify({"error": result.error, "url": url}), 502

    reduction = 0
    if result.original_tokens > 0:
        reduction = round((1 - result.cleaned_tokens / result.original_tokens) * 100, 1)

    cache_str = "CACHE HIT" if result.from_cache else "FETCHED"
    print(f"\n  [FETCH] {cache_str} | {url[:50]}")
    print(f"    {result.original_tokens:,} -> {result.cleaned_tokens:,} tokens ({reduction}% reduced)")

    return jsonify({
        "url": result.url,
        "content": result.content,
        "content_type": result.content_type,
        "original_tokens": result.original_tokens,
        "cleaned_tokens": result.cleaned_tokens,
        "reduction_pct": reduction,
        "from_cache": result.from_cache
    })


@app.route("/fetch/batch", methods=["POST"])
def fetch_batch():
    """Fetch multiple URLs at once."""
    body = request.get_json(force=True)
    urls = body.get("urls", [])
    ttl = body.get("ttl", 300)

    if not urls:
        return jsonify({"error": "Send {\"urls\": [\"https://...\", ...]}"}), 400

    try:
        validate_batch(urls)
    except URLValidationError as e:
        return jsonify({"error": str(e)}), 400

    results = []
    total_original = 0
    total_cleaned = 0

    for url in urls:
        r = fetch_and_clean(url, ttl)
        total_original += r.original_tokens
        total_cleaned += r.cleaned_tokens
        results.append({
            "url": r.url,
            "content": r.content,
            "content_type": r.content_type,
            "original_tokens": r.original_tokens,
            "cleaned_tokens": r.cleaned_tokens,
            "from_cache": r.from_cache,
            "error": r.error
        })

    total_reduction = 0
    if total_original > 0:
        total_reduction = round((1 - total_cleaned / total_original) * 100, 1)

    print(f"\n  [BATCH] {len(urls)} URLs | {total_original:,} -> {total_cleaned:,} tokens ({total_reduction}%)")

    return jsonify({
        "results": results,
        "total_original_tokens": total_original,
        "total_cleaned_tokens": total_cleaned,
        "total_reduction_pct": total_reduction
    })


# ============================================================
#  STATS + HOME
# ============================================================

@app.route("/stats", methods=["GET"])
def stats():
    return jsonify(get_stats())


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "name": "Agent Cost Proxy",
        "version": "0.2",
        "layers": {
            "1": "Prompt Refiner (opt-in) - /refine",
            "2": "Data Proxy (active) - /fetch, /fetch/batch",
            "3": "Output Compressor (coming v0.4)"
        },
        "endpoints": {
            "/refine": "POST {\"text\": \"...\"}",
            "/fetch": "POST {\"url\": \"https://...\"}",
            "/fetch/batch": "POST {\"urls\": [\"...\", \"...\"]}",
            "/stats": "GET"
        },
        "stats": get_stats()
    })


if __name__ == "__main__":
    init_db()
    print("\n" + "=" * 52)
    print("  AGENT COST PROXY v0.2 [TEST MODE]")
    print("  Layer 1: Prompt Refiner  -> /refine")
    print("  Layer 2: Data Proxy      -> /fetch")
    print(f"  Running: http://localhost:{PROXY_PORT}")
    print(f"  Stats:   http://localhost:{PROXY_PORT}/stats")
    print("=" * 52 + "\n")
    app.run(host="127.0.0.1", port=PROXY_PORT, debug=False)
