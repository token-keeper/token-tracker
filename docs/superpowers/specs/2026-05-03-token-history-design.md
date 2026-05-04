# /token-history skill — Design Spec

**작성일**: 2026-05-03
**대상 버전**: token-tracker v0.8.0 (예정)
**선행 spec**: `2026-04-22-token-detail-skill-design.md`, `2026-05-03-token-tracker-pricing-accuracy-design.md`

---

## 1. 개요

### 1.1 목적

현재 세션(또는 전체 세션)의 모든 user prompt에 대한 token/cost 요약 + transcript 전체를 **로컬 web 브라우저**에서 표시한다. 기존 `/token-detail`(직전 1건의 turn별 상세, terminal)과 매체·시간 범위·정보량 모두 다른 보완재.

### 1.2 동기

- v0.7.0 pricing 정확도 v2 작업으로 단건(`/token-detail`)은 신뢰 가능. 그러나 **세션 누적/추세 추적 수단이 비어있음**.
- 정액 구독자(rate limit 관리)와 pay-per-token 사용자(예산 추적) 모두에게 필요.
- terminal 표는 `prompt 발췌·tool 인자/결과·긴 응답`을 표시하기엔 width와 가독성 한계가 있음 → web UI가 적합.

### 1.3 범위

- **포함**: web UI 1페이지 (현재세션 탭 + 전체세션 탭, 정렬, 검색, 필터, expand/collapse)
- **포함**: hook이 매 Stop마다 history.jsonl 행 1개 갱신 (in-place rewrite or append)
- **포함**: skill 호출 시 static html 파일 생성 + macOS `open file://` 자동 호출
- **제외 (Future Considerations)**: chart, 자동화 web 테스트, daemon server, non-macOS 자동 open

### 1.4 ⚠️ 사용자 고지 — 어떤 데이터가 어디에 저장되는가

이 skill은 다음 데이터를 **로컬 파일에 평문 저장**한다:

- **저장 위치**: `~/.claude/plugins/token-tracker/state/{session_id}/history.jsonl` (데이터) + `history-{ts}.html` (생성된 web view)
- **저장 내용**: user prompt 전체 텍스트 / AI 응답 텍스트 / **모든 tool call의 인자 + 결과** — 즉 Bash command(예: `curl -H "Authorization: ..."`), Edit content(예: `.env`, credentials.json), Read 결과(secrets, API key 등)가 그대로 저장됨
- **접근 범위**: local 파일 시스템 only. network 전송 없음. file:// URL은 브라우저로 본인만 view
- **정리 방법**:
  - 특정 세션: `rm -rf ~/.claude/plugins/token-tracker/state/{session_id}/`
  - 전체: `rm -rf ~/.claude/plugins/token-tracker/state/`
  - 향후 follow-up: `/token-history --purge`, mask hook 등 (Future Considerations)
- **민감 정보 마스킹**: 첫 iteration에서는 **마스킹 없음**. 사용자가 cap 없이 모든 transcript를 원함을 명시 선택. 마스킹 도입은 Future Considerations.

---

## 2. 사용자 흐름

1. 사용자가 `/token-history` 입력
2. Skill이 다음을 수행:
   - `~/.claude/plugins/token-tracker/state/{current_session_id}/history.jsonl` read → 현재 세션 데이터
   - `~/.claude/plugins/token-tracker/state/*/history.jsonl` glob read → 전체 세션 데이터 (현재 포함)
   - 두 데이터를 inline한 self-contained html 생성 → `state/{current_session_id}/history-{ts}.html` (**timestamp suffix** — 같은 path를 매번 덮어쓰면 브라우저 disk cache로 stale 표시될 수 있어 회피, 부수효과로 이전 스냅샷 보존)
   - macOS `open file://...` 호출 → 기본 브라우저 자동 open
   - chat에는 항상 URL 한 줄 출력 (`opened: file://...`) — 자동 open 실패 시 backup으로도 동작
3. 사용자가 브라우저에서 탭/정렬/검색/필터/expand 조작

### 2.1 `/token-detail` vs `/token-history` 경계

| 축 | `/token-detail` | `/token-history` |
|---|---|---|
| 매체 | terminal text 표 | web UI (브라우저) |
| 시간 범위 | 직전 user prompt 1건 | 세션 전체(또는 전체 세션) |
| 행 단위 | turn 1개 + sub 자식행 | request 1개 (= user prompt 1건) |
| 상세도 | turn별 token/cost 표 | request별 표 + expand 시 transcript 전체 |
| 데이터 source | last_summary.json | history.jsonl |

---

## 3. 아키텍처 (컴포넌트 + 데이터 흐름)

```
┌─────────────────────────────┐
│ Claude Code Stop event      │
└──────────────┬──────────────┘
               ▼
┌─────────────────────────────┐
│ on_stop hook                │
│  - transcript JSONL parse   │
│  - last_summary.json 저장   │  ← 변경 없음
│  - history.jsonl append/upd │  ← 신규 작업
└──────────────┬──────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ ~/.claude/plugins/token-tracker/    │
│   state/                             │
│     {session_id}/                    │
│       last_summary.json   (기존)     │
│       history.jsonl       (신규)     │
│       history.html        (skill 생성) │
└──────────────────────────────────────┘
               ▲
               │
┌──────────────┴──────────────┐
│ /token-history skill        │
│  - history.jsonl read       │
│  - state/*/history.jsonl glob│
│  - HTML render (stdlib only)│
│  - history.html write       │
│  - `open file://...` exec   │
└──────────────────────────────┘
```

### 3.1 신규 파일

| 파일 | 역할 |
|---|---|
| `lib/history_store.py` | history.jsonl append/in-place rewrite/load, schema versioning, atomic write |
| `lib/history_renderer.py` | per-session + cross-session 데이터 → self-contained HTML 생성 |
| `skills/token-history/SKILL.md` | slash command entry, `disable-model-invocation: true` |
| `skills/token-history/scripts/history.py` | renderer 호출 + browser open |
| `skills/token-history/templates/history.html.tmpl` | HTML 템플릿 (Python `str.format` 기반, jinja 등 외부 의존 없음) |
| `skills/token-history/static/style.css` | UI 스타일 (renderer가 inline) |
| `skills/token-history/static/app.js` | sortable / search / filter / expand-collapse JS (renderer가 inline) |

### 3.2 변경되는 기존 파일

| 파일 | 변경 |
|---|---|
| `hooks/on_user_prompt.py` | state에 `prompt_id` + `prompt_text` 추가 저장 |
| `hooks/on_stop.py` | **line 187 `if count_active_async_agents > 0: return 0` 분기 직전, line 163 `if summary.turns:` 가드 시점에** `history_store.append_or_update_history(...)` 호출 추가 (try/except 격리). async early-return 이전이어야 background subagent 진행 중에도 누적 |
| `lib/parser.py` | `parse_user_prompt_text` / `parse_assistant_text` / `parse_tool_call` / `parse_tool_result` / `parse_transcript_for_history` 헬퍼 추가 |
| `lib/i18n/ko.json`, `en.json` | web UI 문자열 키 추가 |

---

## 4. 데이터 모델

### 4.1 `history.jsonl` (per-session, append-only with in-place rewrite)

위치: `~/.claude/plugins/token-tracker/state/{session_id}/history.jsonl`

한 줄 = 한 user prompt에 대한 entry. 같은 user prompt가 여러 Stop event를 발생시키면(서브에이전트 등) **마지막 행을 in-place rewrite**(같은 `prompt_id` → 덮어쓰기).

```jsonc
{
  "schema_version": 1,
  "prompt_id": "p_a3f9b2",         // user prompt 단위 식별자 (on_user_prompt 발급)
  "session_id": "abc123...",
  "started_at": 1730620980.123,    // user_prompt 시점 (UTC unix)
  "ended_at": 1730620988.456,      // 마지막 Stop 시점
  "user_prompt": {
    "text": "1번으로 진행해보자",
    "ts": 1730620980.123
  },
  "summary": {                     // aggregator.Summary 그대로 (cost·tokens·cache·elapsed)
    "total_cost": 0.0123,
    "total_input_tokens": 120,
    "total_output_tokens": 300,
    "cache_hit_rate": 0.72,
    "total_elapsed": 2.1,
    "turns": [ /* TurnUsage[] — last_summary schema_version=3 그대로 */ ]
  },
  "models_used": ["claude-opus-4-7"],   // 이 prompt 안에서 등장한 main turn 모델들(중복 제거). 첫 번째 = primary (= summary.turns[0].model).
  "has_subagent_other_model": false,    // 어떤 sub의 model이라도 그 turn의 main model과 다르면 true. 표 model 컬럼의 "+ⓢ" 시그널 표시 조건.
  "transcript_entries": [               // expand 시 표시할 raw transcript (cap 없음)
    { "type": "thinking", "ts": ..., "text": "..." },
    { "type": "assistant_text", "ts": ..., "text": "..." },
    { "type": "tool_call", "ts": ..., "name": "Bash", "input": {...} },
    { "type": "tool_result", "ts": ..., "tool_use_id": "...", "content": "...", "is_error": false }
  ]
}
```

### 4.2 데이터 수집 흐름 (skill 호출 시)

별도 global index 파일은 만들지 않는다. **매 `/token-history` 호출 시 `state/*/history.jsonl`을 전부 read 해서 한 html에 모두 inline**.

```
1. state/{current_session_id}/history.jsonl 읽기 → 현재세션 탭 데이터
2. state/*/history.jsonl 모두 glob 읽기         → 전체세션 탭 데이터 (현재세션 포함)
3. 두 데이터 set을 한 html의 <script type="application/json">에 inline
4. JS가 탭 전환 시 해당 set 렌더링 / expand-collapse 모두 client-side
```

→ **fetch 0회. 모든 expand/collapse는 inline JSON에서 처리** (file:// 환경에서 fetch가 막히는 문제 회피).

### 4.3 schema 호환

- `history.jsonl` `schema_version=1`로 시작
- summary_store 패턴 따름: `SUPPORTED_SCHEMA_VERSIONS=(1,)`, 미일치 시 stderr emit + 해당 행 skip
- breaking change 시 bump (예: turn schema 변경되면 v2)

### 4.4 prompt_id 발급 / dedupe

- **`on_user_prompt` hook이 prompt_id 발급** (`p_{secrets.token_hex(3)}`) → state에 같이 저장
- **`on_stop` hook이 그 prompt_id로 history.jsonl의 마지막 행을 in-place rewrite** (없으면 append)
- 같은 prompt에 대한 N번의 Stop event(background subagent 등) → 한 행만 갱신, 중복 없음
- last_summary.json과 동일한 "한 user 입력 = 한 누적 출력" 정책

#### 4.4.1 synthetic prompt 처리 (v0.6.4 호환)

`on_user_prompt.py:83`은 synthetic prompt(`<system-reminder>`, `<task-notification>` 등)에서 early return하여 offset 갱신을 건너뛴다 — v0.6.4 "sub 0개" 회귀 가드. **이와 동일한 분기에서 prompt_id도 갱신하지 않는다**. 결과: synthetic event 이후 발생하는 Stop이 background subagent 결과를 가져오면, 그 결과는 직전 실제 user prompt의 prompt_id 행에 in-place rewrite로 누적된다. **이는 의도된 동작** — 그 sub를 dispatch한 user prompt에 token/cost가 자연스럽게 귀속된다.

#### 4.4.2 prompt_id 없을 때 정책

`on_stop` 시점에 state에 prompt_id가 없는 경우(예: v0.7.x에서 업그레이드한 첫 Stop, 또는 hook 호출 누락):
- **history.jsonl 추가 자체를 skip** (append도 in-place rewrite도 안 함)
- 이유: append-only fallback은 동일 user prompt에 대해 N번 Stop이 발생하면 N행으로 부풀어 cost 중복 집계 위험
- 해당 Stop의 last_summary는 정상 저장 (기존 흐름 유지) — `/token-detail`은 그대로 동작
- 다음 정상 user prompt부터 prompt_id 발급되어 history.jsonl 정상 누적

### 4.5 prompt_text source

`on_user_prompt` hook은 Claude Code로부터 stdin에 user prompt JSON을 받는다. 그 안의 user 입력 텍스트 필드(예: `prompt`)를 추출해 state에 `prompt_text`로 저장. 즉 transcript JSONL을 다시 파싱하지 않고 hook이 1차로 받은 값을 그대로 사용 (중복 작업 회피).

---

## 5. Web UI 구조

### 5.1 페이지 레이아웃

```
┌──────────────────────────────────────────────────────────────────┐
│  token-tracker history                       2026-05-03 14:23   │  ← header
├──────────────────────────────────────────────────────────────────┤
│  [현재 세션 (12)]  [전체 세션 (248)]                              │  ← 탭
├──────────────────────────────────────────────────────────────────┤
│  search: [____________]   model: [all ▾]   session: [all ▾]      │  ← 필터(탭별)
├──────────────────────────────────────────────────────────────────┤
│  total  cost $0.2672 · 25,851 toks · 84% cache · 10.4s elapsed   │  ← 합계 (필터 적용 후)
├──────────────────────────────────────────────────────────────────┤
│  #▾│ time │ prompt              │ model       │ cost  │ in │ out │ cc% │ elapsed │
│  ──┼──────┼─────────────────────┼─────────────┼───────┼────┼─────┼─────┼─────────┤
│  1 │14:23 │ /token-history는... │ opus 4.7    │$0.25  │450 │2150 │ 85% │  8.3s   │
│  2 │14:25 │ 1번으로 진행해보자  │ opus 4.7+ⓢ│$0.01  │120 │ 300 │ 72% │  2.1s   │
│  3 │14:28 │ ...                 │ opus 4.7    │$0.05  │... │ ... │ ... │  ...    │
└──────────────────────────────────────────────────────────────────┘

[expand 시 (행 아래에 inline 펼침)]
  ┌─ user prompt ─────────────────────────────────────────────┐
  │ 1번으로 진행해보자                                         │
  └────────────────────────────────────────────────────────────┘
  ┌─ AI response ─────────────────────────────────────────────┐
  │ "좋습니다, 그렇게 진행할게요. 위 Q1부터 답 부탁드립니다."  │
  │ [전체 보기 ▾]   ← 큰 텍스트는 default 접힘                  │
  └────────────────────────────────────────────────────────────┘
  ┌─ tool calls (3) ──────────────────────────────────────────┐
  │ ▸ Bash: ls /Users/brody/.../plugins/token-tracker/        │
  │ ▸ Read: /Users/.../summary_store.py                       │
  │ ▸ TaskCreate: 프로젝트 컨텍스트 탐색                      │
  └────────────────────────────────────────────────────────────┘
```

### 5.2 컴포넌트

| 영역 | 동작 |
|---|---|
| header | 페이지 제목 + 생성 시각 |
| 탭 | "현재 세션 (N)" / "전체 세션 (N)" — 클릭 시 데이터 set 전환, 필터/정렬 상태 reset |
| 필터 | search box (prompt text 부분일치) · model dropdown · session dropdown(전체 세션 탭에서만) |
| 합계 행 | 현재 표시된(필터 적용 후) 행들의 cost/tokens/elapsed 합산 + cache_hit_rate 가중평균 |
| 표 | 9 컬럼 (전체 세션 탭은 +session). 헤더 클릭 → 정렬 토글 (오름/내림). 행 클릭 → expand |
| expand 영역 | (1) user prompt 전체 (2) AI response 전체 (3) tool call 목록. 각 섹션 collapse 가능. **"큰 텍스트"의 기준 = 5줄 이상 또는 visible chars 500자 이상** — 그 경우 default 접힘 + "전체 보기" 토글. |
| footer | 가벼운 메타 (token-tracker version, generated at) |

### 5.3 표 컬럼 정의

| 컬럼 | 내용 | 정렬 |
|---|---|---|
| `#` | 표시 순번 (1부터, 현재 표시 set 기준 — **정렬·필터 시 흔들림**, 식별 불변 ID는 `prompt_id`) | ✓ |
| `time` | started_at HH:MM (local time, **client JS가 변환** — §5.5 참조) | ✓ |
| `prompt` | user_prompt.text (전체 표시, 길면 1줄 truncate + hover tooltip) | ✗ |
| `model` | primary model + sub 시그널 (예: `opus 4.7+ⓢ`). **표시 이름은 기존 `lib/detail_formatter.py:_short_model_name` 재활용** (raw id `claude-opus-4-7` → `opus 4.7`). primary = `summary.turns[0].model` | ✓ |
| `cost` | `$0.0123` | ✓ |
| `in` | input_tokens | ✓ |
| `out` | output_tokens | ✓ |
| `cc%` | cache_hit_rate (%) | ✓ |
| `elapsed` | total_elapsed (s) | ✓ |
| `session` | session_id 앞 8자 (전체 세션 탭에만 추가) | ✓ |

**행 식별자**: 표 `#`은 표시 순번이라 정렬/필터 변경 시 동일 행이 다른 번호가 됨. 안정적 식별이 필요한 expand anchor (예: 페이지 내 deep link `#prompt-p_a3f9b2`) 같은 곳은 `prompt_id`를 사용한다. 행 개수 자체는 **무제한** (페이지네이션·virtual scroll 없음 — 사용자가 cap 없음 명시 선택).

### 5.4 인터랙션 우선순위 (Standard 범위)

- ✓ 탭 전환
- ✓ 컬럼 정렬 (헤더 클릭)
- ✓ search box (prompt text 부분일치, 즉시 필터)
- ✓ model dropdown 필터
- ✓ session dropdown 필터 (전체 세션 탭만)
- ✓ row expand/collapse
- ✓ expand 내 큰 텍스트 collapse
- ✗ chart / 시각화 (Future Considerations)
- ✗ 브라우저 내 다국어 toggle 없음 — language는 generate 시점에 config 기반으로 lookup하여 inline (renderer가 i18n strings 모두 html에 inline). **언어 변경 시 `~/.claude` config 변경 후 `/token-history` 재호출 필요**.

### 5.5 기술 선택

- **Vanilla JS + 단일 html 파일** (라이브러리 0)
- Python stdlib만 사용 (jinja 등 외부 의존 없음)
- 데이터는 `<script id="data-current" type="application/json">{...}</script>` + `<script id="data-all" type="application/json">{...}</script>` 두 개 분리 inline
- 스타일/JS는 generate 시 inline
- 모던 브라우저 (ES2020+) 가정. polyfill 없음
- **i18n lookup**: `lib/config.py:get_language()` 호출 → 결과를 generate 시점에 i18n strings로 inline. JS는 inlined strings를 그대로 사용 (런타임 lookup 없음).
- **timezone 변환**: renderer는 `started_at` 등 모든 시각을 unix epoch (UTC) 그대로 inline. **client JS가 사용자 브라우저의 local timezone으로 변환** (예: `new Date(ts*1000).toLocaleTimeString()`). 정렬은 epoch 기준이라 timezone 무관 일관성 유지.
- **str.format escaping**: 템플릿이 JS/CSS의 `{`/`}` 와 충돌하지 않도록 `{{`/`}}` 또는 placeholder 토큰(예: `__PLACEHOLDER_DATA_CURRENT__`) 방식 사용. 구현 시 escaping 전략 1개 일관 선택.

### 5.6 skill 인자

첫 iteration에서는 인자를 받지 않는다. `${CLAUDE_SESSION_ID}`만 사용. 향후 추가 후보(Future Considerations):
- `--session=<id>`: 다른 세션을 현재 세션 탭으로 표시
- `--filter=<...>`: query string으로 필터 prefilled

---

## 6. 에러 처리 + 엣지 케이스

| 케이스 | 처리 |
|---|---|
| 빈 history (첫 호출, 데이터 없음) | "데이터 없음 — 첫 user prompt 응답 후 다시 호출하세요" 안내 html. browser는 그래도 open. |
| history.jsonl 손상 (JSONDecodeError) | 손상된 행 skip + stderr emit. 나머지 정상 행만 표시. summary_store 패턴 동일. |
| schema_version 미지원 | 해당 행 skip + stderr emit. Web UI는 정상 행만. |
| prompt_id 없음 (구버전 state, 또는 synthetic prompt만 있는 상태) | **history.jsonl 추가 자체를 skip** (§4.4.2 참조). last_summary는 정상 저장되므로 `/token-detail`은 동작. 다음 정상 user prompt부터 누적 시작. |
| history_store 저장 실패 | try/except 격리. error.log 기록. 기존 last_summary / hook stdout 흐름 영향 없음. |
| render 실패 (스킬 호출 시) | error.log 기록 + 사용자에게 "html 생성 실패 — log 확인" 메시지. browser open 안 함. |
| `open` 명령 실패 (non-macOS) | URL만 chat에 출력. 사용자가 클릭. 명시적 에러 안 띄움. |
| state_dir 권한 문제 | error.log + chat에 "쓰기 실패" 메시지. |
| transcript_entries에 binary/긴 텍스트 | JSON serialize 시 모두 string. 비-UTF8은 `errors="replace"`. |
| prompt 발급 전 Stop (예: 첫 세션 시작 system prompt) | prompt_id 없으면 history.jsonl에 추가 안 함. last_summary와 동일. |
| html generate 시간 큰 세션 | spec scope 외 (Future Considerations). 동작은 그대로 진행. |

---

## 7. 테스트 전략

### 7.1 unit (pytest)

| 모듈 | 테스트 |
|---|---|
| `lib/history_store.py` | append vs in-place rewrite (같은 prompt_id) / load 시 schema 검증 / 손상 행 skip / atomic write (tmp+replace) / multi-session glob load |
| `lib/parser.py` 신규 헬퍼 | `parse_user_prompt_text` · `parse_assistant_text` · `parse_tool_call` · `parse_tool_result` 각각 fixture entry 기반 |
| `lib/history_renderer.py` | render output에 data JSON inline 검증 / i18n 문자열 치환 / 빈 데이터 처리 |
| `hooks/on_user_prompt.py` | prompt_id 발급 + state 저장 검증 |
| `hooks/on_stop.py` | history_store.append 호출 검증 / history_store 실패가 last_summary 흐름 안 깨는지 격리 검증 |

### 7.2 integration

- 가짜 transcript JSONL → on_user_prompt → on_stop → history.jsonl 1행 생성 확인
- 같은 prompt_id로 on_stop 2회 → history.jsonl 여전히 1행 (in-place rewrite) 확인
- 새 prompt_id로 on_stop → 2행 됨
- `/token-history` skill 호출 → html 파일 생성 + URL 출력 확인 (subprocess `open`은 mock)
- multi-session: state_dir에 여러 session_id 디렉터리 → 전체 세션 데이터 잘 collect 확인

### 7.3 회귀 가드

- 기존 277개 테스트 통과 유지 (last_summary / token-detail 흐름 무영향)
- on_stop의 history_store 추가가 기존 stdout emit 흐름을 안 깨는지 검증

### 7.4 Web UI 수동 검증 (자동화 X)

첫 iteration: 사용자가 직접 브라우저에서 다음을 확인:
- 탭 전환 동작
- 컬럼 정렬
- search box 필터
- row expand/collapse
- large transcript collapse
- 빈 데이터 안내

JS unit test는 scope 밖 (vanilla JS, framework 없음). 향후 Playwright 도입 가능하면 follow-up.

---

## 8. i18n 추가 키

`lib/i18n/ko.json` / `en.json`에 다음 키 추가:

- `html_title`, `html_generated_at`, `html_version_label`
- `tab_current`, `tab_all`
- `col_index`, `col_time`, `col_prompt`, `col_model`, `col_cost`, `col_in`, `col_out`, `col_cc`, `col_elapsed`, `col_session`
- `search_placeholder`, `filter_model_all`, `filter_session_all`
- `expand_user_prompt`, `expand_ai_response`, `expand_tool_calls`, `expand_show_full`, `expand_collapse`
- `total_label`
- `no_data_message`
- `opened_url`, `open_failed_url_only`

---

## 9. Future Considerations (지금 구현 안 함)

- Cap 도입 (행당/transcript_entries 사이즈) — html 거대화 시
- **transcript_entries sidecar 분리** — history.jsonl에 metadata만 두고 transcript는 `transcript-{prompt_id}.json` 별도 파일. 매 Stop마다 metadata만 atomic rewrite하므로 O(N²) → O(N) I/O. (현재는 단일 jsonl로 진행, 실세션에서 느려지면 도입)
- Disk rotation 정책 (`/token-history --purge-older-than=N` 등 cleanup 명령)
- Mask hook (`lib/redactor.py` placeholder) — 민감 정보(.env, API key, secrets) 자동 마스킹
- Light view 토글 (전체 세션 탭 default light, "show full" 토글)
- Chart (cost timeline, model pie) — Rich interactivity
- N개월 이내 세션 필터 (전체 세션 탭)
- pricing data 분리 (`lib/pricing_data.json`) — 핸드오프 5절 B
- Playwright 기반 web UI 자동화 테스트
- daemon server 옵션 (현재는 static html만)
- non-macOS browser open (`xdg-open` / `start`) — 현재는 macOS만 자동, 그 외는 URL 출력
- skill 인자 (`--session=`, `--filter=`, `--purge` 등)

---

## 10. 결정 요약 (브레인스토밍 정리)

| # | 질문 | 결정 |
|---|---|---|
| Q1 | 1행 단위 | user prompt 1건 |
| Q2 | 행 식별자 | 순번# + prompt 발췌 |
| Q3 | 데이터 source 1차 | hook이 history 파일 갱신 |
| Q4 | 컬럼 set | Full (#, time, prompt, model, cost, in, out, cc%, elapsed) |
| Q5 | 행 개수 제한 | 최근 N=20 (terminal 표 기준이었음 → web에서는 무제한) |
| Q6 | model 컬럼 표시 | main + sub 시그널 (`opus 4.7+ⓢ`) |
| Q7 | prompt 발췌 길이 | 30 cells 고정 (terminal 표 기준이었음 → web에서는 1줄 truncate + tooltip) |
| Q8 | 세션 범위 | 둘 다 제공 (탭 전환) |
| Q9 | 출력 매체 | Web UI |
| Q10 | 상세 범위 | Full Transcript |
| Q11 | 제공 방식 | Static HTML 파일 |
| Q12 | 데이터 source 재결정 | hook이 history.jsonl에 전부 누적 |
| Q13 | browser open | 자동 open + URL chat 표시 |
| Q14 | interactivity | Standard (search + filter 추가, chart 제외) |
| Q15 | i18n | 기존 token-tracker config 따름 |
| Q16 | 데이터 cap | cap 없음 + 펼치기/접기 |
| Q17 | 전체 세션 expand | 한 html에 inline (별도 fetch 없이) |
| Q18 | scope (리뷰 후) | 그대로 진행 (한 plan, 모든 기능 — PR 분해 안 함) |
| Q19 | thinking blocks 포함 (리뷰 후) | 포함 (transcript_entries.type=`thinking`) |
| Q20 | transcript I/O 비용 (리뷰 후) | 그대로 진행 (단일 jsonl) + Future Considerations에 sidecar 분리 메모 |
