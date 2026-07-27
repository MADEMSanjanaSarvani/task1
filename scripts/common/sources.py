"""Fetches raw trend items from the 6 free sources and normalizes them into
{title, source, window, signal} dicts ready for scoring.scoring.score_topics.

Every fetch function swallows its own errors and returns [] on failure, mirroring
the n8n version's continueOnFail behavior - one dead source degrades gracefully
instead of failing the whole run.
"""
import logging
import os
import time

import requests

log = logging.getLogger(__name__)


def _safe_get(url, **kwargs):
    try:
        resp = requests.get(url, timeout=15, **kwargs)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        log.warning("GET %s failed: %s", url, e)
        return None


def _safe_post(url, **kwargs):
    try:
        resp = requests.post(url, timeout=15, **kwargs)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        log.warning("POST %s failed: %s", url, e)
        return None


def fetch_reddit(access_token: str) -> list[dict]:
    subs = "Entrepreneur+freelance+SideProject+juststart+passive_income+SaaS+digitalnomad+WorkOnline"
    data = _safe_get(
        f"https://oauth.reddit.com/r/{subs}/hot",
        params={"limit": 40},
        headers={"Authorization": f"Bearer {access_token}", "User-Agent": "ai-content-automation/1.0"},
    )
    if not data:
        return []
    items = []
    for child in data.get("data", {}).get("children", []):
        d = child.get("data", {})
        items.append({
            "title": d.get("title", ""), "source": "reddit", "window": "24h",
            "signal": (d.get("score") or 0) + (d.get("num_comments") or 0),
        })
    return items


def fetch_product_hunt(token: str) -> list[dict]:
    query = "{ posts(first: 30, order: VOTES) { edges { node { name tagline votesCount } } } }"
    data = _safe_post(
        "https://api.producthunt.com/v2/api/graphql",
        json={"query": query},
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    if not data:
        return []
    items = []
    for edge in data.get("data", {}).get("posts", {}).get("edges", []):
        n = edge.get("node", {})
        items.append({
            "title": f"{n.get('name', '')} — {n.get('tagline', '')}",
            "source": "product_hunt", "window": "24h", "signal": n.get("votesCount", 0),
        })
    return items


def fetch_hacker_news() -> list[dict]:
    base = os.environ.get("HN_ALGOLIA_BASE", "https://hn.algolia.com/api/v1")
    cutoff = int(time.time()) - 7 * 86400
    data = _safe_get(f"{base}/search", params={"tags": "front_page", "numericFilters": f"created_at_i>{cutoff}"})
    if not data:
        return []
    return [
        {"title": h.get("title", ""), "source": "hacker_news", "window": "7d", "signal": h.get("points") or 0}
        for h in data.get("hits", [])
    ]


def fetch_github_trending(token: str) -> list[dict]:
    since = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 7 * 86400))
    data = _safe_get(
        "https://api.github.com/search/repositories",
        params={"q": f"created:>{since} stars:>50", "sort": "stars", "order": "desc", "per_page": 30},
        headers={"Authorization": f"Bearer {token}"} if token else {},
    )
    if not data:
        return []
    items = []
    for r in data.get("items", []):
        title = f"{r.get('full_name', '')} — {r.get('description') or ''}"[:200]
        items.append({"title": title, "source": "github_trending", "window": "7d", "signal": r.get("stargazers_count", 0)})
    return items


def fetch_news(api_key: str) -> list[dict]:
    query = '"AI tools" OR "side hustle" OR "digital product" OR "SaaS" OR "remote jobs" OR "startup idea" OR "passive income"'
    data = _safe_get(
        "https://newsapi.org/v2/everything",
        params={"q": query, "sortBy": "publishedAt", "pageSize": 30, "apiKey": api_key},
    )
    if not data:
        return []
    return [
        {"title": a.get("title", ""), "source": "news", "window": "30d", "signal": 40}
        for a in data.get("articles", [])
    ]


def fetch_youtube_trending(api_key: str) -> list[dict]:
    data = _safe_get(
        "https://www.googleapis.com/youtube/v3/videos",
        params={"part": "snippet,statistics", "chart": "mostPopular", "videoCategoryId": 28,
                "maxResults": 25, "key": api_key},
    )
    if not data:
        return []
    items = []
    for v in data.get("items", []):
        snippet = v.get("snippet", {})
        stats = v.get("statistics", {})
        view_count = int(stats.get("viewCount", 0) or 0)
        items.append({
            "title": snippet.get("title", ""), "source": "youtube", "window": "24h",
            "signal": view_count / 50000 if view_count else 20,
        })
    return items


def fetch_reddit_access_token(client_id: str, client_secret: str) -> str | None:
    """Reddit's OAuth client-credentials flow (script-type app) - exchanges
    client id/secret for a short-lived access token."""
    try:
        resp = requests.post(
            "https://www.reddit.com/api/v1/access_token",
            data={"grant_type": "client_credentials"},
            auth=(client_id, client_secret),
            headers={"User-Agent": "ai-content-automation/1.0"},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("access_token")
    except requests.RequestException as e:
        log.warning("Reddit auth failed: %s", e)
        return None


def fetch_all_sources() -> list[dict]:
    """Fetches every source, using whatever credentials are present in env vars.
    Returns the combined, un-scored raw item list."""
    items = []

    reddit_token = None
    if os.environ.get("REDDIT_CLIENT_ID") and os.environ.get("REDDIT_CLIENT_SECRET"):
        reddit_token = fetch_reddit_access_token(os.environ["REDDIT_CLIENT_ID"], os.environ["REDDIT_CLIENT_SECRET"])
    if reddit_token:
        items += fetch_reddit(reddit_token)

    if os.environ.get("PRODUCTHUNT_TOKEN"):
        items += fetch_product_hunt(os.environ["PRODUCTHUNT_TOKEN"])

    items += fetch_hacker_news()
    items += fetch_github_trending(os.environ.get("GH_SEARCH_TOKEN", ""))

    if os.environ.get("NEWSAPI_KEY"):
        items += fetch_news(os.environ["NEWSAPI_KEY"])

    if os.environ.get("YOUTUBE_API_KEY"):
        items += fetch_youtube_trending(os.environ["YOUTUBE_API_KEY"])

    return items
