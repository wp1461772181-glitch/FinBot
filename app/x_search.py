"""search_x: recent posts on X through the official API, returned as citable rows.

The owner's bearer token is read from ``X_BEARER_TOKEN`` at call time and goes nowhere but the request's
``Authorization`` header.  Every failure of the HTTP client is reduced to a short code before it is returned or
logged (its own text can carry the URL), and the log line holds counts only: never the query, which can say what
the owner is researching.  X bills by post read, so a daily cap on posts is kept per owner in ``x_search_usage``.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import UTC, date, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .agent_chat_models import XSearchUsage
from .database import SessionLocal

logger = logging.getLogger(__name__)


class _KeepXOutOfTheLog(logging.Filter):
    """httpx logs every request at INFO with its whole URL, and the URL of a search carries the query (what the owner is
    researching): lines about this host are dropped on httpx's own logger, whatever level the application logs at."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "api.x.com" not in record.getMessage()


logging.getLogger("httpx").addFilter(_KeepXOutOfTheLog())

URL = "https://api.x.com/2/tweets/search/recent"
MAX_RESULTS = 50
MIN_RESULTS = 10
DEFAULT_DAILY_POSTS = 2000
TIMEOUT_SECONDS = 15.0
NOTE = "X 上的帖子，未经证实"
_REASONS = {
    "x_auth_failed": "X 的访问令牌无效或没有搜索权限。",
    "x_rate_limited": "X 那边限流了，稍后再试。",
    "x_timeout": "连接 X 超时。",
    "x_unavailable": "X 的搜索这次没有成功。",
}


def configured() -> bool:
    return bool((os.environ.get("X_BEARER_TOKEN") or "").strip())


def daily_posts() -> int:
    try:
        value = int(os.environ.get("X_SEARCH_DAILY_POSTS") or DEFAULT_DAILY_POSTS)
    except ValueError:
        return DEFAULT_DAILY_POSTS
    return value if value >= 0 else DEFAULT_DAILY_POSTS


def _now() -> datetime:
    return datetime.now(UTC)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT_SECONDS)


def _fail(code: str, reason: str | None = None) -> dict:
    from .agent_workflow.tools import error
    reason = reason or _REASONS[code]
    return {**error(code), "reason": reason, "hint": reason}


def _used(owner_hash: str, day: date) -> int:
    with SessionLocal() as db:
        row = db.get(XSearchUsage, (day, owner_hash))
        return row.posts if row else 0


def _add_used(owner_hash: str, day: date, posts: int) -> int:
    """Add to the day's total under a row lock and return the new total (one transaction)."""
    for attempt in range(2):
        with SessionLocal() as db:
            row = db.scalars(select(XSearchUsage).where(XSearchUsage.day == day, XSearchUsage.owner_hash == owner_hash).with_for_update()).first()
            try:
                if row is None:
                    row = XSearchUsage(day=day, owner_hash=owner_hash, posts=posts)
                    db.add(row)
                else:
                    row.posts += posts
                total = row.posts
                db.commit()
                return total
            except IntegrityError:      # another process created the day's row first: add to it on the next pass
                db.rollback()
                if attempt:
                    raise
    return 0


def _line(one_line: str, limit: int = 60) -> str:
    return re.sub(r"\s+", " ", one_line).strip()[:limit]


def _count(value) -> int:
    """A count from the API as an int; anything that is not one (a string, None, a nested object) is 0."""
    return value if type(value) is int else 0


def _rows(payload: dict) -> list[dict]:
    includes = payload.get("includes") if isinstance(payload.get("includes"), dict) else {}
    listed = includes.get("users") if isinstance(includes.get("users"), list) else []
    users = {str(u.get("id")): u for u in listed if isinstance(u, dict)}
    rows = []
    for post in payload.get("data") or []:
        if not isinstance(post, dict) or not post.get("id"):
            continue
        text = str(post.get("text") or "")
        user = users.get(str(post.get("author_id")))
        username = str(user.get("username")) if user and user.get("username") else None
        metrics = post.get("public_metrics") if isinstance(post.get("public_metrics"), dict) else {}
        standing = (user or {}).get("public_metrics")
        followers = _count((standing if isinstance(standing, dict) else {}).get("followers_count"))
        rows.append({
            "id": str(post["id"]), "source_type": "x_post",
            "title": f"@{username or '未知'}：{_line(text)}",
            "url": f"https://x.com/{username or 'i'}/status/{post['id']}",
            "published_at": post.get("created_at"),
            "author": {"username": username, "name": (user or {}).get("name"), "verified": bool((user or {}).get("verified")),
                       "followers": followers},
            "text": text,
            "metrics": {"likes": _count(metrics.get("like_count")), "reposts": _count(metrics.get("retweet_count")),
                        "replies": _count(metrics.get("reply_count"))},
            "note": NOTE,
        })
    return rows


def _outcome(response: httpx.Response) -> tuple[dict | None, str | None]:
    """The payload of an answer, or the code of why it is none."""
    status = response.status_code
    if status in (401, 403):
        return None, "x_auth_failed"
    if status == 429:
        return None, "x_rate_limited"
    if status != 200:
        return None, "x_unavailable"
    try:
        payload = response.json()
    except ValueError:
        return None, "x_unavailable"
    if not isinstance(payload, dict) or payload.get("errors") and not payload.get("data"):
        return None, "x_unavailable"
    if "data" not in payload:
        # X leaves ``data`` out when nothing matched and says so in meta; an answer with neither is not an answer.
        meta = payload.get("meta")
        if not (isinstance(meta, dict) and meta.get("result_count") == 0):
            return None, "x_unavailable"
    return payload, None


async def search(args: dict, *, owner_hash: str) -> dict:
    token = (os.environ.get("X_BEARER_TOKEN") or "").strip()
    if not token:
        return _fail("x_not_configured", "没有配置 X 的访问令牌。")
    now = _now()
    day = now.astimezone(UTC).date()
    cap = daily_posts()
    if _used(owner_hash, day) >= cap:
        logger.info("search_x result=x_daily_cap posts=0 day_total=%s", cap)
        return _fail("x_daily_cap", f"今天搜 X 的额度（{cap} 条）用完了，UTC 零点后恢复。")
    hours = max(1, min(168, int(args.get("hours") or 72)))
    query = str(args["query"])
    if "is:retweet" not in query:
        # In X's grammar OR binds looser than a space: without the brackets ``a OR b -is:retweet`` keeps a's retweets (and bills them).
        query = f"({query}) -is:retweet"
    start = max(now - timedelta(hours=hours), now - timedelta(days=7) + timedelta(minutes=1))
    params = {
        "query": query, "start_time": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "max_results": max(MIN_RESULTS, min(MAX_RESULTS, int(args.get("max_results") or 20))),
        "sort_order": "recency" if args.get("sort") == "recency" else "relevancy",
        "tweet.fields": "created_at,public_metrics,lang,author_id", "expansions": "author_id",
        "user.fields": "username,name,verified,public_metrics",
    }
    payload, code = None, None
    try:
        async with _client() as client:
            response = await client.get(URL, params=params, headers={"Authorization": f"Bearer {token}"})
        payload, code = _outcome(response)
    except (httpx.TimeoutException, httpx.NetworkError):
        code = "x_timeout"      # the exception's own text can carry the URL: it is dropped here, never logged or returned
    except httpx.HTTPError:
        code = "x_unavailable"
    if code:
        logger.info("search_x result=%s posts=0 day_total=%s", code, _used(owner_hash, day))
        return _fail(code)
    rows = _rows(payload)
    total = _add_used(owner_hash, day, len(rows)) if rows else _used(owner_hash, day)
    logger.info("search_x result=ok posts=%s day_total=%s", len(rows), total)
    return {"ok": True, "data": rows, "source": "x",
            "meta": {"query": query, "window_hours": hours, "returned": len(rows), "daily_remaining": max(0, cap - total)}}
