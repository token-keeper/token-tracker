"""Anthropic pricing 페이지 fetch + parse → models dict.

용도:
- SessionStart hook 의 자동 7일 갱신
- scripts/update-pricing.sh 의 수동 즉시 갱신

설계 원칙:
- **fail-soft**: 네트워크 / HTTP 오류 / 파싱 실패 모두 None 반환 (예외 전파 안 함).
  사용자 hook 흐름이 절대 깨지면 안 됨 — 자동 갱신은 best-effort.
- **stdlib only**: urllib + re. 추가 dep 없음.
- **read-only**: 이 모듈은 fetch/parse 만 담당. write 는 caller 책임 (state override 위치 / 권한 일관성 caller 가 결정).

페이지 형식:
- markdown table 이 HTML 안에 그대로 박혀 있는 docs.claude.com 형식.
- table row 패턴: `| Claude Opus 4.7     | $5 / MTok         | $6.25 / MTok    | ...`
- (deprecated) 표기는 `[deprecated]` link 가 들어가지만 정규식이 무시.
"""
from __future__ import annotations

import re
import urllib.error
import urllib.request
from typing import Optional


_PRICING_URL = "https://platform.claude.com/docs/en/about-claude/pricing"
_USER_AGENT = "token-tracker/auto-fetch (+https://github.com/brody424/TokenTracker)"
_DEFAULT_TIMEOUT_SEC = 3


# Anthropic docs 의 model pricing table 한 줄 매칭.
# 캡처: 1) family (Opus/Sonnet/Haiku), 2) version 문자열 (4.7 / 4 / 3.5),
# 3~7) 5개 단가 ($X / MTok 형식).
# Family 뒤 optional parenthesized note ([deprecated] link 등) 흡수 — 중첩
# 괄호 회피 위해 `|` 까지 광범위 매치.
_ROW_RE = re.compile(
    r"\|\s*Claude\s+(Opus|Sonnet|Haiku)\s+([\d.]+)"     # family + version
    r"(?:[^|]*?)"                                        # optional notes/links until next |
    r"\|\s*\$([0-9.]+)\s*/\s*MTok"                       # input
    r"\s*\|\s*\$([0-9.]+)\s*/\s*MTok"                    # 5m cache write
    r"\s*\|\s*\$([0-9.]+)\s*/\s*MTok"                    # 1h cache write
    r"\s*\|\s*\$([0-9.]+)\s*/\s*MTok"                    # cache read
    r"\s*\|\s*\$([0-9.]+)\s*/\s*MTok",                   # output
)


def _version_to_id_suffix(version: str) -> str:
    """'4.7' → '4-7', '4' → '4', '3.5' → '3-5'."""
    return version.replace(".", "-")


def parse_pricing_html(html: str) -> Optional[dict[str, dict[str, float]]]:
    """HTML 에서 model 단가 table 추출.

    Returns: `{ "claude-opus-4-7": { "input": 5.0, ... }, ... }` 또는 None.
    매치 행 0개면 None — 페이지 형식 변경 신호.
    """
    models: dict[str, dict[str, float]] = {}
    for m in _ROW_RE.finditer(html):
        family = m.group(1).lower()
        version = m.group(2)
        try:
            input_p = float(m.group(3))
            c5m = float(m.group(4))
            c1h = float(m.group(5))
            cache_read = float(m.group(6))
            output_p = float(m.group(7))
        except ValueError:
            # 숫자 파싱 실패한 row 는 skip (다른 row 는 살아남음)
            continue
        model_id = f"claude-{family}-{_version_to_id_suffix(version)}"
        models[model_id] = {
            "input": input_p,
            "output": output_p,
            "cache_creation_5m": c5m,
            "cache_creation_1h": c1h,
            "cache_read": cache_read,
        }
    return models if models else None


def fetch_pricing_models(
    timeout: int = _DEFAULT_TIMEOUT_SEC,
    url: str = _PRICING_URL,
) -> Optional[dict[str, dict[str, float]]]:
    """Anthropic pricing 페이지 fetch + parse → models dict.

    Returns: parsed models dict 또는 None (실패 시).
    Fail-soft: 모든 예외 (네트워크 / HTTP / decode / parse) silent → None.
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        html = raw.decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    except Exception:
        # 알려지지 않은 예외도 절대 propagate 안 함 — hook 흐름 보호.
        return None
    return parse_pricing_html(html)
