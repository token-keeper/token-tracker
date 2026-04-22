# token-tracker 플러그인 설계 문서

- 작성일: 2026-04-22
- 작성자: brody
- 상태: Draft (사용자 리뷰 전)

## 1. 목적과 범위

### 1.1 목적
Claude Code 사용자가 **한 번의 프롬프트**로 소비하는 토큰·비용을 즉시 확인해 **프롬프팅·컨텍스트 관리 최적화**를 지속적으로 수행하게 한다.

### 1.2 핵심 사용 시나리오
1. 사용자가 프롬프트를 입력하고 Enter
2. Claude가 여러 turn·tool 호출을 거쳐 응답 완료(Stop)
3. 응답 바로 아래에 한 줄 요약이 뜸: `비용 $0.018 · 1,546 toks · cache 85% · 12.3s`
4. 사용자가 자세히 보고 싶으면 `/token-detail` → turn별 breakdown 표

### 1.3 비범위 (MVP에서 제외)
- 예산 경고/차단
- 세션 누적 표시 (Claude Code 기본 statusline이 이미 제공)
- 여러 프로젝트·여러 세션 집계
- 외부 시스템 전송·대시보드

## 2. 핵심 결정 사항 요약

| 항목 | 결정 |
|---|---|
| 핵심 가치 | 한 번의 request(UserPromptSubmit → Stop)의 실시간 비용 피드백 |
| 집계 단위 | 1 request = UserPromptSubmit 발화 이후 Stop 발화 시점까지 JSONL에 append된 모든 turn 합산 |
| 데이터 소스 | hook input의 `transcript_path`로 받은 session JSONL |
| 경계 식별 | UserPromptSubmit에서 JSONL byte offset 기록, Stop에서 offset~EOF 파싱 |
| 비용 계산 | 플러그인 내장 정적 가격표 (모델 ID → $/MTok) |
| 캐시 표시 | `cache_read / 전체_input` 적중률 % |
| 출력 채널 | Stop hook의 JSON stdout `{"systemMessage": "...", "continue": true}` |
| 조회 UX | `/token-detail`, `/token-history`, `/token-verbose` 모두 `skills/` 디렉터리, `disable-model-invocation: true` |
| 서브에이전트 비용 | 부모 request에 포함 (같은 session JSONL에 append되므로 자연스럽게 합산) |
| 언어 | 플러그인 `config.json`의 `language: ko|en` 설정 |
| 성능 목표 | Stop hook 실행 50~200ms (offset 기반이라 세션 길이 무관) |
| 구현 언어 | Python 3 (표준 라이브러리만) |
| 배포 형태 | Claude Code marketplace plugin 포맷 |
| MVP 범위 | Phase 1: Stop hook 한 줄 요약만. 검증 후 Phase 2~3로 확장 |

## 3. 단계별 릴리스 계획

### Phase 1 (MVP)
- `.claude-plugin/plugin.json`, `hooks/hooks.json`
- `hooks/on_user_prompt.py` (offset 기록)
- `hooks/on_stop.py` (집계 + 한 줄 출력)
- `lib/` 핵심 모듈
- `config.json` (언어 설정)
- 기본 `tests/`

**완성 기준:** 실제 Claude Code 세션에서 매 응답 끝에 안정적으로 한 줄 요약 표시.

### Phase 2
- `skills/token-detail/` — 직전 request의 turn별 상세 표 (순서/툴/모델/토큰 breakdown/turn별 비용/turn별 소요시간)

### Phase 3
- `skills/token-history/` — 세션 내 발생한 모든 request 리스트
- `skills/token-verbose/` — 상세 출력을 세션 내내 토글

## 4. 아키텍처

### 4.1 파일 구조

```
token-tracker/
├── .claude-plugin/
│   └── plugin.json                    # 플러그인 메타데이터
├── hooks/
│   ├── hooks.json                     # UserPromptSubmit + Stop 등록
│   ├── on_user_prompt.py              # offset 기록
│   └── on_stop.py                     # 집계 + 한 줄 출력
├── skills/                            # Phase 2+
│   ├── token-detail/
│   │   ├── SKILL.md
│   │   └── scripts/detail.py
│   ├── token-history/
│   │   ├── SKILL.md
│   │   └── scripts/history.py
│   └── token-verbose/
│       └── SKILL.md
├── lib/
│   ├── __init__.py
│   ├── parser.py
│   ├── pricing.py
│   ├── aggregator.py
│   ├── state.py
│   ├── formatter.py
│   └── paths.py
├── config.json
└── tests/
    ├── fixtures/sample_session.jsonl
    ├── test_parser.py
    ├── test_pricing.py
    ├── test_aggregator.py
    ├── test_state.py
    ├── test_formatter.py
    └── test_hook_end_to_end.py
```

### 4.2 런타임 경로 & 환경변수

| 용도 | 위치 |
|---|---|
| 플러그인 루트 | `${CLAUDE_PLUGIN_ROOT}` (Claude Code 주입) |
| Skill 디렉터리 (skill 내부에서) | `${CLAUDE_SKILL_DIR}` |
| Session JSONL | `hook_input["transcript_path"]` (stdin으로 전달됨) |
| Session ID | `hook_input["session_id"]` |
| State file | `~/.claude/plugins/token-tracker/state/<session_id>.json` |
| 진단 로그 | `~/.claude/plugins/token-tracker/log/error.log` (1MB 넘으면 rotate) |

### 4.3 플러그인 선언

**`.claude-plugin/plugin.json`** (메타데이터만):
```json
{
  "name": "token-tracker",
  "description": "한 번의 프롬프트가 소비한 토큰·비용을 실시간 표시",
  "version": "0.1.0",
  "author": { "name": "brody" }
}
```

**`hooks/hooks.json`**:
```json
{
  "hooks": {
    "UserPromptSubmit": [{
      "matcher": "*",
      "hooks": [{
        "type": "command",
        "command": "python \"${CLAUDE_PLUGIN_ROOT}/hooks/on_user_prompt.py\""
      }]
    }],
    "Stop": [{
      "matcher": "*",
      "hooks": [{
        "type": "command",
        "command": "python \"${CLAUDE_PLUGIN_ROOT}/hooks/on_stop.py\""
      }]
    }]
  }
}
```

**`config.json`** (사용자 편집 가능):
```json
{
  "language": "ko",
  "verbose": false
}
```

## 5. 데이터 흐름

### 5.1 UserPromptSubmit hook
1. stdin으로 JSON 입력: `{session_id, transcript_path, cwd, hook_event_name}`
2. `transcript_path`의 현재 파일 크기(byte) 측정
3. state 파일에 `{offset, started_at}` 기록 (atomic: tempfile + rename)
4. exit 0 (아무 출력 없음)

### 5.2 Stop hook
1. stdin으로 JSON 입력 수신
2. state 파일 읽기 → `offset`, `started_at`
3. `transcript_path`를 `offset`부터 EOF까지 한 줄씩 읽음
4. 각 줄을 `parser.parse_line`에 넣어 assistant 라인의 usage 추출 → `TurnUsage` 리스트
5. `aggregator.aggregate(turns, elapsed=now-started_at)` → `Summary`
6. `formatter.format_summary(summary, language)` → 한 줄 문자열
7. stdout에 `{"systemMessage": "<요약>", "continue": true}` JSON 출력
8. exit 0

### 5.3 데이터 모델

**용어 정의**
- **turn**: JSONL에 기록된 assistant 라인 1개. usage 필드를 그 단위로 보유. tool 호출이 포함되면 결과 도착 후 후속 assistant 라인이 새 turn이 됨.
- **request**: UserPromptSubmit → Stop 사이에 발생한 모든 turn의 집합. 한 번의 사용자 프롬프트가 유발한 전체 단위.

Python 3.10+ 전제 (dataclass / `|` union 문법 사용).

```python
# parser.py
@dataclass
class TurnUsage:
    index: int
    model: str
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    tools_used: list[str]
    started_at: float
    ended_at: float

# aggregator.py
@dataclass
class Summary:
    total_cost: float
    total_input_tokens: int
    total_output_tokens: int
    cache_hit_rate: float    # cache_read / total_input
    total_elapsed: float     # 전체 request 소요시간(초)
    turns: list[TurnUsage]
```

## 6. 모듈별 책임 (단일 책임 원칙)

### 6.1 `lib/parser.py`
- `parse_line(json_dict: dict) -> TurnUsage | None`
- 순수 함수. assistant type만 처리, 나머지 None.
- 외부 의존 없음. 테스트는 fixture dict로 완전 커버 가능.

### 6.2 `lib/pricing.py`
- 정적 테이블 `PRICING: dict[str, dict[str, float]]` — 모델 ID → `{input, output, cache_creation, cache_read}` (per MTok)
- `compute_cost(model: str, usage: TurnUsage) -> float`
- 미등록 모델: 0.0 반환 + 진단 로그 경고
- 업데이트 정책: 새 모델 출시 시 plugin 버전 bump

### 6.3 `lib/aggregator.py`
- `aggregate(turns: list[TurnUsage], elapsed: float) -> Summary`
- 합산, 캐시 적중률 계산 (`total_input == 0`이면 0.0)

### 6.4 `lib/state.py`
- `save_state(session_id: str, data: dict)` — tempfile + rename으로 atomic
- `load_state(session_id: str) -> dict | None` — 없거나 손상이면 None
- 디렉터리 자동 생성

### 6.5 `lib/formatter.py`
- i18n 문자열 테이블: `MESSAGES = {"ko": {...}, "en": {...}}`
- `format_summary(summary, lang) -> str`
- Phase 2+ `format_detail(summary, lang) -> str` (turn별 표)

### 6.6 `lib/paths.py`
- `plugin_data_dir()`, `state_dir()`, `log_dir()` 등 디렉터리 해결
- `CLAUDE_PLUGIN_ROOT` env 없으면 `__file__` 기반 fallback

### 6.7 `hooks/on_user_prompt.py` & `hooks/on_stop.py`
- 얇은 조립층. stdin JSON 파싱 → lib 호출 → stdout 출력.
- 최상위 `try/except`로 모든 예외 포착 → 진단 로그만 기록 → exit 0

## 7. 에러 처리

| 상황 | 동작 |
|---|---|
| state 없음 | transcript의 마지막 user 메시지 이후로 fallback |
| offset > file_size | 전체 집계로 fallback |
| JSONL 한 줄 파싱 실패 | 해당 줄만 skip |
| 미등록 모델 | cost=0, 진단 로그, 표시는 "?" |
| pricing 테이블 완전 결손 | `[token-tracker] pricing missing` systemMessage |
| `CLAUDE_PLUGIN_ROOT` 미설정 | `__file__` 기반 fallback |
| 기타 모든 예외 | 최상위 포괄 catch, hook 항상 exit 0 |

원칙: **플러그인이 사용자 작업을 방해하지 않는다.** 조용히 실패하되 진단 로그에는 남긴다.

## 8. 테스트 전략

### Unit
- `test_parser.py`: fixture JSONL의 각 라인 케이스 커버 (user/assistant/tool_result/thinking 등)
- `test_pricing.py`: 등록된 모델 전수 + 미등록 경로
- `test_aggregator.py`: 빈 리스트, 단일 turn, 캐시 전체 hit, 전체 miss
- `test_state.py`: 정상, 파일 없음, JSON 손상, 동시 쓰기 안전성
- `test_formatter.py`: ko/en snapshot

### Integration
- `test_hook_end_to_end.py`: fixture JSONL + mock stdin → hook subprocess → stdout JSON 파싱·검증

### 수동 (MVP 인수 기준)
- 실제 Claude Code에 플러그인 로드 → 3턴 이상 대화
- 각 턴 종료 후 한 줄 요약이 떴는지
- 비용·토큰 숫자가 그럴듯한지 (Anthropic 콘솔 실사용량과 대조)
- 캐시 hit/miss 케이스 모두 확인

## 9. 검토된 대안

### A안: 마커 기반 byte offset (채택)
세션이 길어져도 O(new lines)로 선형 증가 없음. state file 1개 추가 복잡도.

### B안: timestamp 필터링
state는 timestamp 하나만 저장. 하지만 매 Stop마다 전체 JSONL 스캔 → 100턴짜리 세션에서 매 턴 200ms 위험.

### C안: Stop hook 단독 + 누적 diff
UserPromptSubmit 없이 매 Stop에서 전체 집계 → 이전 대비 diff. B와 같은 O(N) 문제, 상세 모드에서 "이번 request의 turn들" 식별 불가.

→ **A 채택.** "정확성 우선 50~200ms" 요구 충족.

## 10. 리뷰된 엣지 케이스

1. **state file 누락** — UserPromptSubmit이 미발화된 상태에서 Stop. transcript 마지막 user 메시지 이후로 fallback.
2. **JSONL truncate (/clear)** — `offset > file_size` 감지 시 전체 파일 집계로 fallback.
3. **동일 프로젝트 여러 인스턴스** — session_id가 다르므로 state file 충돌 없음.
4. **`CLAUDE_PLUGIN_ROOT` 미주입** — `__file__` 기반 fallback.
5. **`systemMessage` 프로토콜 미지원 구버전** — plugin.json에 최소 버전 명시, 미지원 버전에서는 평문 fallback도 같이 출력.
6. **transcript 디스크 flush 타이밍** — Stop hook 발화 시점에 마지막 assistant 메시지가 JSONL에 쓰이지 않았을 가능성. 파일 크기 변화가 없으면 최대 100ms 폴링 후 재시도.

## 11. 후속 과제 (범위 외)

### Phase 2+ 기능
- 예산 경고 기능
- statusline 통합 (기본 statusline과 공존 여부 검토)
- 다국어 추가 (일본어 등)
- `/token-analyze` skill (자연어 분석·코칭, model invocation 허용)
- 가격표 원격 업데이트 메커니즘
- 플러그인 self-test 명령어

### Phase 1에서 의도적으로 deferred된 엣지케이스 (최종 code review에서 식별됨)
- **JSONL flush 타이밍 폴링**: Stop hook 발화 시 마지막 assistant 라인이 아직 flush 안 됐을 가능성. 현재는 단일 read. 실제로 "0 toks"가 빈번히 목격되면 ≤100ms 폴링 추가.
- **state 누락 fallback 정교화**: 현재는 `offset=0, started_at=now`로 폴백하며, turns가 0이면 조용히 skip. 더 정교한 동작(마지막 user 메시지 역검색 기반 경계 추정)은 Phase 2로 연기.
- **미등록 단일 모델 경고**: 전체 pricing 테이블 결손 시 systemMessage 진단은 존재. 개별 모델 ID만 미매치일 때는 prefix match로 대부분 커버하지만, prefix도 실패하면 cost=0으로 조용히 under-report. 첫 발생 시 warn.log 기록 추가 검토.
- **hooks 공용 유틸 DRY**: `_setup_sys_path`, `_log_error`가 두 hook 파일에 중복. Phase 2에서 `hooks/_common.py`로 통합.
