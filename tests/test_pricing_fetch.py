"""pricing_fetch.py 단위 테스트.

네트워크 호출은 모두 monkeypatch 로 mock — 실제 외부 fetch 없이 파서 동작만 가드.
실제 페이지 형식 검증은 사용자가 scripts/update-pricing.sh 한 번 실행해 확인.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from lib import pricing_fetch


# ──────────────────────────────────────────────────────────────────────────
# parse_pricing_html — 정규식 추출 테스트
# ──────────────────────────────────────────────────────────────────────────


def _html_row(name: str, prices: tuple[str, str, str, str, str]) -> str:
    """현재 docs 페이지의 HTML <td> 형식 한 row 생성 (input, 5m, 1h, read, output)."""
    cells = "".join(
        f'<td class="p-2 first:pl-0 last:pr-0 text-text-200">${p} / MTok</td>'
        for p in prices
    )
    return (
        f'<tr class="border-b-0.5"><td class="p-2 first:pl-0 last:pr-0 '
        f'text-text-200">{name}</td>{cells}</tr>'
    )


_SAMPLE_HTML_MIN = (
    _html_row("Claude Fable 5", ("10", "12.50", "20", "1", "50"))
    + _html_row("Claude Opus 4.7", ("5", "6.25", "10", "0.50", "25"))
    + _html_row("Claude Sonnet 4.6", ("3", "3.75", "6", "0.30", "15"))
    + _html_row("Claude Haiku 4.5", ("1", "1.25", "2", "0.10", "5"))
)

# 과거 markdown pipe table 형식 — fallback 경로 가드용.
_SAMPLE_MARKDOWN_MIN = """
| Claude Opus 4.7     | $5 / MTok         | $6.25 / MTok    | $10 / MTok      | $0.50 / MTok | $25 / MTok    |
| Claude Sonnet 4.6   | $3 / MTok         | $3.75 / MTok    | $6 / MTok       | $0.30 / MTok | $15 / MTok    |
| Claude Haiku 4.5  | $1 / MTok         | $1.25 / MTok    | $2 / MTok       | $0.10 / MTok | $5 / MTok     |
"""


def test_parse_pricing_html_extracts_4_models():
    """정상 HTML table 4 row → 4 model 추출."""
    models = pricing_fetch.parse_pricing_html(_SAMPLE_HTML_MIN)
    assert models is not None
    assert len(models) == 4
    assert "claude-fable-5" in models
    assert "claude-opus-4-7" in models
    assert "claude-sonnet-4-6" in models
    assert "claude-haiku-4-5" in models


def test_parse_pricing_html_new_family_detected():
    """Opus/Sonnet/Haiku 외 새 패밀리 (Fable) 도 allowlist 없이 자동 감지 + 단가 정확."""
    models = pricing_fetch.parse_pricing_html(_SAMPLE_HTML_MIN)
    p = models["claude-fable-5"]
    assert p["input"] == 10.0
    assert p["output"] == 50.0
    assert p["cache_creation_5m"] == 12.50
    assert p["cache_creation_1h"] == 20.0
    assert p["cache_read"] == 1.0


def test_parse_pricing_html_opus_4_7_rates_correct():
    """Opus 4.7 row 의 5개 단가가 정확히 추출."""
    models = pricing_fetch.parse_pricing_html(_SAMPLE_HTML_MIN)
    p = models["claude-opus-4-7"]
    assert p["input"] == 5.0
    assert p["output"] == 25.0
    assert p["cache_creation_5m"] == 6.25
    assert p["cache_creation_1h"] == 10.0
    assert p["cache_read"] == 0.50


def test_parse_pricing_html_skips_two_column_batch_table():
    """batch 테이블 (단가 2컬럼) row 는 5컬럼 패턴에 안 걸려야 함."""
    html = _html_row("Claude Fable 5", ("10", "12.50", "20", "1", "50")) + (
        '<tr><td class="p-2">Claude Mythos 5</td>'
        '<td class="p-2">$5 / MTok</td><td class="p-2">$25 / MTok</td></tr>'
    )
    models = pricing_fetch.parse_pricing_html(html)
    assert models is not None
    assert "claude-fable-5" in models
    assert "claude-mythos-5" not in models


def test_parse_pricing_html_markdown_fallback():
    """HTML 매치 0건이면 과거 markdown pipe 형식으로 fallback."""
    models = pricing_fetch.parse_pricing_html(_SAMPLE_MARKDOWN_MIN)
    assert models is not None
    assert len(models) == 3
    assert models["claude-opus-4-7"]["input"] == 5.0
    assert models["claude-sonnet-4-6"]["output"] == 15.0


def test_parse_pricing_html_handles_haiku_3_5():
    """3.5 같은 single-decimal version 도 매핑 ('claude-haiku-3-5')."""
    html = "| Claude Haiku 3.5  | $0.80 / MTok      | $1 / MTok       | $1.6 / MTok     | $0.08 / MTok | $4 / MTok     |"
    models = pricing_fetch.parse_pricing_html(html)
    assert models is not None
    assert "claude-haiku-3-5" in models
    p = models["claude-haiku-3-5"]
    assert p["input"] == 0.80
    assert p["output"] == 4.0


def test_parse_pricing_html_handles_single_digit_version():
    """4 같은 dash 없는 version — 'claude-opus-4' 로 매핑."""
    html = "| Claude Opus 4     | $15 / MTok        | $18.75 / MTok   | $30 / MTok      | $1.50 / MTok | $75 / MTok    |"
    models = pricing_fetch.parse_pricing_html(html)
    assert models is not None
    assert "claude-opus-4" in models


def test_parse_pricing_html_skips_deprecated_link_inline():
    """[deprecated](...) link 가 family 옆에 있어도 파싱 — 그냥 row 추출."""
    # markdown link form — Anthropic docs 의 deprecated 표기
    html = "| Claude Sonnet 3.7 ([deprecated](/docs/foo)) | $3 / MTok         | $3.75 / MTok    | $6 / MTok       | $0.30 / MTok | $15 / MTok    |"
    models = pricing_fetch.parse_pricing_html(html)
    assert models is not None
    assert "claude-sonnet-3-7" in models


def test_parse_pricing_html_returns_none_for_empty():
    """빈 HTML / table 매치 0 → None (페이지 형식 변경 신호)."""
    assert pricing_fetch.parse_pricing_html("") is None
    assert pricing_fetch.parse_pricing_html("no table here") is None
    assert pricing_fetch.parse_pricing_html("<html>random</html>") is None


def test_parse_pricing_html_returns_none_for_corrupt_table():
    """단가 컬럼이 깨진 row 만 있으면 None."""
    # $ 누락 + MTok 누락
    html = "| Claude Opus 4.7 | broken | broken | broken | broken | broken |"
    assert pricing_fetch.parse_pricing_html(html) is None


# ──────────────────────────────────────────────────────────────────────────
# fetch_pricing_models — urllib mock 테스트
# ──────────────────────────────────────────────────────────────────────────


def test_fetch_pricing_models_success(monkeypatch):
    """urllib mock 성공 응답 → parsing 결과 반환."""
    class FakeResp:
        def read(self):
            return _SAMPLE_HTML_MIN.encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout):
        return FakeResp()

    monkeypatch.setattr(pricing_fetch.urllib.request, "urlopen", fake_urlopen)
    models = pricing_fetch.fetch_pricing_models(timeout=1)
    assert models is not None
    assert "claude-opus-4-7" in models


def test_fetch_pricing_models_network_error_returns_none(monkeypatch):
    """네트워크 오류 → silent None (예외 전파 안 함)."""
    import urllib.error

    def fake_urlopen(req, timeout):
        raise urllib.error.URLError("DNS failure")

    monkeypatch.setattr(pricing_fetch.urllib.request, "urlopen", fake_urlopen)
    assert pricing_fetch.fetch_pricing_models(timeout=1) is None


def test_fetch_pricing_models_timeout_returns_none(monkeypatch):
    """TimeoutError → silent None."""
    def fake_urlopen(req, timeout):
        raise TimeoutError("timeout")

    monkeypatch.setattr(pricing_fetch.urllib.request, "urlopen", fake_urlopen)
    assert pricing_fetch.fetch_pricing_models(timeout=1) is None


def test_fetch_pricing_models_unexpected_exception_returns_none(monkeypatch):
    """알려지지 않은 예외도 silent None — hook 흐름 보호 핵심."""
    def fake_urlopen(req, timeout):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(pricing_fetch.urllib.request, "urlopen", fake_urlopen)
    assert pricing_fetch.fetch_pricing_models(timeout=1) is None


def test_fetch_pricing_models_html_parse_fail_returns_none(monkeypatch):
    """fetch 성공이지만 HTML 에 table 없으면 None (페이지 리팩토링 시나리오)."""
    class FakeResp:
        def read(self):
            return b"<html>nothing matches the pattern</html>"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(pricing_fetch.urllib.request, "urlopen", lambda req, timeout: FakeResp())
    assert pricing_fetch.fetch_pricing_models(timeout=1) is None
