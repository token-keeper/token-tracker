"""Anthropic pricing 페이지 fetch + parse → models dict.

용도:
- SessionStart hook 의 자동 1일 갱신
- compute_cost 의 unknown 모델 감지 시 즉시 갱신 (lib/pricing.py)
- scripts/update-pricing.sh 의 수동 즉시 갱신

설계 원칙:
- **fail-soft**: 네트워크 / HTTP 오류 / 파싱 실패 모두 None 반환 (예외 전파 안 함).
  사용자 hook 흐름이 절대 깨지면 안 됨 — 자동 갱신은 best-effort.
- **stdlib only**: urllib + re. 추가 dep 없음.
- **read-only**: 이 모듈은 fetch/parse 만 담당. write 는 caller 책임 (state override 위치 / 권한 일관성 caller 가 결정).

페이지 형식:
- 현재 (2026-06 기준): HTML `<td>` 셀 형식.
  `<td ...>Claude Fable 5</td><td ...>$10 / MTok</td><td ...>$12.50 / MTok</td>...`
  컬럼 순서: model | input | 5m cache write | 1h cache write | cache read | output.
- 과거: markdown pipe table (`| Claude Opus 4.7 | $5 / MTok | ...`) — fallback 으로 유지.
- family 이름은 allowlist 없이 일반 매치 (`[A-Za-z]+`) — Fable 처럼 새 패밀리가
  나와도 코드 수정 없이 자동 감지되게 함.
- batch/long-context 등 다른 테이블은 단가 컬럼 수가 달라 (2개) 5컬럼 패턴에 안 걸림.
"""
from __future__ import annotations

import re
import urllib.error
import urllib.request
from typing import Optional


_PRICING_URL = "https://platform.claude.com/docs/en/about-claude/pricing"
_USER_AGENT = "token-tracker/auto-fetch (+https://github.com/brody424/TokenTracker)"
_DEFAULT_TIMEOUT_SEC = 3


# HTML <td> 형식 (현재 페이지) — model pricing table 한 줄 매칭.
# 캡처: 1) family 일반 매치 ([A-Za-z]+ — 새 패밀리 자동 감지), 2) version (4.7 / 4 / 3.5),
# 3~7) 5개 단가 ($X / MTok 형식, 컬럼 순서: input, 5m, 1h, read, output).
# name 셀의 deprecated link 등 잔여물은 `(?:(?!</td>).)*?` 로 </td> 까지 흡수.
_PRICE_TD = r"<td[^>]*>\s*\$([0-9.]+)\s*/\s*MTok\s*</td>"
_ROW_RE_HTML = re.compile(
    r"<td[^>]*>\s*Claude\s+([A-Za-z]+)\s+([\d.]+)"       # family + version
    r"(?:(?!</td>).)*?</td>\s*"                           # name 셀 나머지
    + _PRICE_TD + r"\s*"                                  # input
    + _PRICE_TD + r"\s*"                                  # 5m cache write
    + _PRICE_TD + r"\s*"                                  # 1h cache write
    + _PRICE_TD + r"\s*"                                  # cache read
    + _PRICE_TD,                                          # output
    re.DOTALL,
)

# markdown pipe table 형식 (과거 페이지) — fallback 으로 유지.
_ROW_RE_MARKDOWN = re.compile(
    r"\|\s*Claude\s+([A-Za-z]+)\s+([\d.]+)"              # family + version
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

    HTML <td> 형식 우선, 매치 0건이면 markdown pipe 형식 fallback.
    Returns: `{ "claude-opus-4-7": { "input": 5.0, ... }, ... }` 또는 None.
    두 형식 모두 매치 0개면 None — 페이지 형식 변경 신호.
    """
    matches = list(_ROW_RE_HTML.finditer(html))
    if not matches:
        matches = list(_ROW_RE_MARKDOWN.finditer(html))
    models: dict[str, dict[str, float]] = {}
    for m in matches:
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
