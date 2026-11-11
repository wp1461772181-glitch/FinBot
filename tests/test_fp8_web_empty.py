import asyncio
from datetime import UTC, datetime, timedelta

import app.agent_web_research as web


def _date(days):
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def _rows(count=2):
    return [{"url": f"https://example.com/{i}", "title": f"Page {i}",
             "snippet": f"snippet {i}", "published_at": None} for i in range(count)]


def _install(monkeypatch, rows, page_dates):
    async def search(*args, **kwargs):
        return rows

    async def fetch(url, limit):
        index = int(url.rsplit('/', 1)[-1])
        date = page_dates[index]
        meta = f'<meta property="article:published_time" content="{date}">' if date else ''
        return url, 'text/html', f'<html><head>{meta}</head><body><p>Substantial news content for readers.</p></body></html>'.encode()

    monkeypatch.setattr(web, '_search', search)
    monkeypatch.setattr(web, '_get_public', fetch)


def test_post_fetch_window_empty(monkeypatch):
    _install(monkeypatch, _rows(), [_date(30), _date(30)])
    result = asyncio.run(web._research('news', days_back=7))
    assert result['ok'] is True and result['data'] == [] and result['status'] == 'not_found'
    assert result['error_code'] is None
    assert result['meta']['empty_reason'] == 'date_window'
    assert result['meta']['applied_window_days'] == 7 and result['meta']['results_before_window'] == 2
    assert result['meta']['widen_suggestion'] == '搜索后端有结果，但没有一条能确认发布在最近 7 天内。可以放宽 days_back 重新搜索，或不带 days_back 搜索后自行核对日期。'
    assert result['meta']['hint'] == 'The search ran and found nothing usable; this is not a backend failure. Do not retry the same query unchanged.'


def test_post_fetch_window_counts_undated(monkeypatch):
    _install(monkeypatch, _rows(), [_date(30), None])
    result = asyncio.run(web._research('news', days_back=7))
    assert result['meta']['undated_left_out'] == 1


def test_no_search_results(monkeypatch):
    _install(monkeypatch, [], [])
    for span in (None, 7):
        result = asyncio.run(web._research('news', days_back=span))
        assert result['ok'] is True and result['status'] == 'not_found'
        assert result['meta']['empty_reason'] == 'no_search_results'
        assert result['meta']['widen_suggestion'] == '搜索后端正常返回，但这个查询没有结果。可以换关键词、改用公司全名或代码，或放宽 days_back。'


def test_pre_fetch_window_empty(monkeypatch):
    rows = _rows()
    for row in rows:
        row['published_at'] = _date(30)
    async def search(*args, **kwargs): return rows
    async def fetch(*args, **kwargs): raise AssertionError('must not fetch')
    monkeypatch.setattr(web, '_search', search)
    monkeypatch.setattr(web, '_get_public', fetch)
    result = asyncio.run(web._research('news', days_back=7))
    assert result['ok'] is True and result['status'] == 'not_found'
    assert result['meta']['empty_reason'] == 'date_window' and result['meta']['results_before_window'] == 2
    assert result['meta']['undated_left_out'] == 0


def test_backend_failures_remain_failures(monkeypatch):
    for error, code in [(ValueError('http_5xx'), 'http_5xx'),
                        (ValueError('search_backend_key_missing'), 'search_backend_key_missing'),
                        (TimeoutError(), 'web_research_timeout')]:
        async def search(*args, **kwargs): raise error
        monkeypatch.setattr(web, '_search', search)
        result = asyncio.run(web.web_research.ainvoke({'query': 'news'}))
        assert result['ok'] is False and result['error_code'] == code


def test_all_page_fetches_fail(monkeypatch):
    rows = _rows()
    async def search(*args, **kwargs): return rows
    async def fetch(*args, **kwargs): raise ValueError('failed')
    monkeypatch.setattr(web, '_search', search)
    monkeypatch.setattr(web, '_get_public', fetch)
    result = asyncio.run(web._research('news'))
    assert result['ok'] is True and result['status'] == 'partial'
    assert result['meta']['pages_failed'] == 2
    assert result['meta']['hint'] == "Pages were found but none of their bodies could be read. search_snippet is the search engine's own summary, not the page text."
    assert all(row['fetch_error'] and row['search_snippet'] and row['excerpt'] == '' for row in result['data'])


def test_normal_page_unchanged(monkeypatch):
    _install(monkeypatch, _rows(1), [_date(2)])
    result = asyncio.run(web._research('news', days_back=7))
    assert result['ok'] is True and len(result['data']) == 1
    assert 'status' not in result and 'meta' not in result


def test_flag_off_restores_post_fetch_failure(monkeypatch):
    monkeypatch.setenv('FINBOT_FP8_WEB_EMPTY', 'off')
    _install(monkeypatch, _rows(), [_date(30), _date(30)])
    result = asyncio.run(web._research('news', days_back=7))
    assert result['ok'] is False and result['error_code'] == 'web_research_unavailable'
    assert 'status' not in result and 'meta' not in result


def test_direct_url_fetch_failure(monkeypatch):
    async def fetch(*args, **kwargs): raise ValueError('failed')
    monkeypatch.setattr(web, '_get_public', fetch)
    result = asyncio.run(web._research('https://example.com/report'))
    assert result['ok'] is False and result['error_code'] == 'web_page_unavailable'
