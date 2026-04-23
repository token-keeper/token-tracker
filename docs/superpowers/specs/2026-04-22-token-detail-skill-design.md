# `/token-detail` Skill 설계 문서 (v2)

**작성일**: 2026-04-22
**재작성**: 2026-04-22 (서브에이전트 리뷰 반영, Claude Code 공식 skill 메커니즘 확인 후)
**대상 릴리스**: Phase 2-B
**목표 버전 태그**: v0.3.0

---

## 1. 목적과 범위

### 1.1 목적
`/token-detail` 슬래시 명령으로 **직전 request의 turn별 상세 정보**를 한눈에 표시. Stop hook의 한 줄 요약보다 한 단계 깊은 진단 도구.

### 1.2 핵심 사용 시나리오
1. "방금 응답이 왜 비쌌지?" → turn별 비용 breakdown으로 범인 특정.
2. "툴을 과하게 호출한 건 아닐까?" → turn별 tool 리스트 + 호출 횟수.
3. "cache가 잘 작동했나?" → turn별 `cache_read` 비율.

### 1.3 비범위 (Phase 2-C 이후로 미룸)
- 과거 request 조회 (`--index N`)
- 세션 누적·요청 간 비교
- Markdown/JSON export
- ANSI 컬러, 박스 그리기
- 다중 세션 선택 (`--session X`)

---

## 2. Claude Code Skill 메커니즘 (공식 확인)

이 스펙의 전제가 되는 공식 동작:

- **Slash skill은 스크립트 러너가 아니라 "프롬프트 주입 도구"**. skill 호출 시 SKILL.md 본문이 LLM 프롬프트로 전달됨.
- **스크립트 실행**: SKILL.md 본문의 `` !`command` `` 블록이 **렌더링 전에** 실행되고, stdout이 그 자리에 **문자열 치환**됨. 치환 완료된 본문이 LLM에 들어가서 모델이 사용자에게 전달.
- **`disable-model-invocation: true`**: Claude의 **자동** invoke를 막음. slash 입력으로는 여전히 호출 가능. 즉 이 플래그는 "의도치 않은 token 소비 방지"용.
- **공식 환경변수**: `${CLAUDE_SESSION_ID}`, `${CLAUDE_SKILL_DIR}`, `$ARGUMENTS`, `$0`, `$1`...
- **토큰 비용**: 0은 불가능. SKILL.md 본문 + 스크립트 출력만큼 모델이 소비. 본문을 최소화해 수백 tokens 수준에서 억제.

이 전제를 받아들이고 설계한다.

---

## 3. 핵심 결정 사항

| 항목 | 결정 | 근거 |
|---|---|---|
| 데이터 소스 | Stop hook이 `Summary`를 state JSON에 덮어쓰기 → skill 스크립트가 읽음 | DRY, aggregator 재사용 |
| Session ID 획득 | `${CLAUDE_SESSION_ID}` 환경변수, skill 본문에서 argv로 스크립트에 전달 | 공식 변수, 확정적. mtime fallback 제거 |
| Skill 본문 | 스크립트 실행 `!`cmd`` 한 줄 + "그대로 전달" 지시 한 줄 | 토큰 최소화 |
| 출력 매체 | 스크립트 stdout → SKILL.md 치환 → 모델이 사용자 채팅에 삽입 | Claude Code 표준 패턴 |
| 출력 형식 | pre-formatted ASCII 표 (ANSI 없음) | Markdown 코드블록으로 감싸면 고정폭 보장 |
| 언어 | `plugins/token-tracker/config.json`의 `language` 키 (ko/en) | 기존 formatter와 동일 |
| 에러 처리 | 스크립트가 친절한 한 줄 + stderr로 traceback 기록 | exit 0 유지 |
| state 디렉터리 구조 | `state/{session_id}/` 서브디렉터리로 파일 분리 | 네이밍 혼재 방지, Phase 2-C 확장 대비 |

---

## 4. 아키텍처

### 4.1 파일 구조 (신규/수정)

```
plugins/token-tracker/
├── hooks/on_stop.py                          # [수정] 기존 logic 끝에 save_last_summary 한 줄 추가
├── lib/
│   ├── summary_store.py                      # [신규] state I/O 순수 함수
│   ├── detail_formatter.py                   # [신규] Summary → 표 문자열
│   └── i18n/
│       ├── ko.json                           # [신규] 헤더·컬럼명·에러 메시지 리소스
│       └── en.json                           # [신규] 동일
├── skills/
│   └── token-detail/
│       ├── SKILL.md                          # [신규] 최소한의 frontmatter + !`script` + 지시 한 줄
│       └── scripts/
│           └── detail.py                     # [신규] 오케스트레이터
└── tests/
    ├── test_summary_store.py                 # [신규]
    ├── test_detail_formatter.py              # [신규]
    ├── test_detail_script_e2e.py             # [신규] subprocess로 scripts/detail.py 호출
    └── test_hook_end_to_end.py               # [확장] last_summary 저장 검증
```

### 4.2 모듈 책임

- **`lib/summary_store.py`** — state 디렉터리 I/O만. 외부 의존 없음.
  ```python
  def save_last_summary(session_id: str, summary: Summary, state_dir: Path) -> None:
      """tempfile + os.replace로 원자 쓰기. 디렉터리는 mkdir(parents=True, exist_ok=True)."""

  def load_last_summary(session_id: str, state_dir: Path) -> Summary | None:
      """파싱 실패·미지원 schema_version이면 None 반환 + stderr 기록."""
  ```
  함수명이 `save_last`/`load_last`인 것은 의도적. Phase 2-C에서 `append`/`load_indexed`를 추가로 만들되, 현 MVP는 `last` 한 함수만 필요(YAGNI).

- **`lib/detail_formatter.py`** — 순수 함수. I/O 없음.
  ```python
  def format_detail(summary: Summary, language: str) -> str:
      """ko/en 문자열은 i18n/{lang}.json에서 로드. 문자열 하드코딩 금지."""
  ```
  내부에 `COLUMNS = [Column(key, width, align), ...]` 리스트 선언 (Phase 2-C 컬러·컬럼 선택 대비).

- **`lib/i18n/{lang}.json`** — 헤더, 컬럼 라벨, 범례, 에러 메시지 5개의 키 정의.
  ```json
  {
    "header_title": "직전 request 상세",
    "header_total": "총 비용 {cost} · {tokens} toks · cache {rate} · {elapsed}",
    "col_index": "#", "col_model": "모델", "col_tools": "툴",
    "col_input": "input", "col_cc": "cc", "col_cr": "cr",
    "col_output": "output", "col_cost": "비용", "col_time": "시간",
    "legend": "범례: cc=cache_creation, cr=cache_read",
    "err_no_state": "아직 기록된 request가 없습니다. 먼저 Claude에게 질문 후 다시 실행하세요.",
    "err_parse": "상세 정보를 읽지 못했습니다 (파일 손상).",
    "err_unsupported_schema": "이 state 파일은 현재 skill과 호환되지 않습니다 (삭제 후 다음 응답부터 재생성).",
    "err_empty_turns": "직전 request에 assistant 응답이 없습니다."
  }
  ```

- **`skills/token-detail/scripts/detail.py`** — thin 오케스트레이터.
  ```python
  # argv[1] = session_id (SKILL.md에서 ${CLAUDE_SESSION_ID} 치환)
  # 1) config.json 읽어 language 판정
  # 2) summary_store.load_last_summary(session_id, state_dir)
  # 3) 없으면 err_no_state 출력 + exit 0
  # 4) detail_formatter.format_detail(summary, lang) 출력 + exit 0
  # 5) 예외 catch 시 err_parse 또는 err_unsupported_schema 출력 + exit 0, stderr에 traceback
  ```

- **`hooks/on_stop.py`** — 기존 흐름 끝, systemMessage emit 직전에 `summary_store.save_last_summary(session_id, summary, state_dir)` 호출. **turns가 0이면 skip** (기존 policy 유지 — save하지 않음).

### 4.3 데이터 흐름

```
[UserPromptSubmit hook]
   └─→ state/{session_id}/offset.json 기록 (기존 state.py 위치 이동됨, §4.4 참조)

[Stop hook]
   ├─→ [기존] JSONL flush polling (≤500ms) → 파싱 → aggregate → Summary → systemMessage
   └─→ [추가] turns > 0 이면 summary_store.save_last_summary(session_id, summary)
         ↓
         state/{session_id}/last_summary.json  (tempfile + os.replace 원자 쓰기)

[사용자 /token-detail 입력]
   └─→ Claude Code가 SKILL.md 렌더링 시작
         └─→ !`python3 ${CLAUDE_SKILL_DIR}/scripts/detail.py "${CLAUDE_SESSION_ID}"` 실행
               ├─→ detail.py argv[1]로 session_id 수신
               ├─→ summary_store.load_last_summary(session_id) → Summary
               ├─→ detail_formatter.format_detail(summary, lang) → 문자열
               └─→ stdout
         └─→ stdout이 SKILL.md 본문에 치환됨
         └─→ LLM이 본문 읽고 사용자에게 그대로 전달
```

**중요**: `save_last_summary`는 **flush polling이 완료된 뒤 turns가 확정된 상태**에서만 호출. 폴링 전에 호출하면 불완전 스냅샷이 영구화됨 (Phase 1 버그 재발 방지).

### 4.4 state 디렉터리 구조 (기존 네이밍 정리 포함)

**변경 전**
```
~/.claude/plugins/token-tracker/state/
├── {session_id}.json             # offset + started_at
```

**변경 후**
```
~/.claude/plugins/token-tracker/state/
└── {session_id}/
    ├── offset.json                # UserPromptSubmit hook이 기록 (기존)
    └── last_summary.json          # Stop hook이 기록 (신규)
```

마이그레이션: `state.py`의 경로 로직을 `state_dir / session_id / "offset.json"`로 수정. 기존 파일이 남아 있어도 offset 없으면 fallback(`offset=0, started_at=now`)이 작동하므로 사용자 action 불필요. 오래된 파일은 자연 소멸. 첫 새 세션부터 새 구조 사용.

### 4.5 state 파일 스키마

**경로**: `~/.claude/plugins/token-tracker/state/{session_id}/last_summary.json`

```json
{
  "schema_version": 1,
  "session_id": "abc-123",
  "saved_at": 1745301234.567,
  "summary": {
    "total_cost": 0.0180,
    "total_input_tokens": 1546,
    "total_output_tokens": 950,
    "cache_hit_rate": 0.85,
    "total_elapsed": 12.3,
    "turns": [
      {
        "index": 0,
        "model": "claude-opus-4-7[1m]",
        "input_tokens": 120,
        "output_tokens": 450,
        "cache_creation_tokens": 400,
        "cache_read_tokens": 800,
        "tools_used": [{"name": "Read", "count": 3}, {"name": "Edit", "count": 1}],
        "started_at": 1745301222.1,
        "ended_at": 1745301224.2
      }
    ]
  }
}
```

**필드 요건**:
- `schema_version` (int, 필수): 현재 `1`. `load`에서 미지원 version 감지 시 파일 삭제 + `None` 반환 + stderr 기록.
- `turns[].tools_used` (list of `{name, count}`): 기존 aggregator는 중복 없는 list였지만, 사용성 리뷰(MAJOR 15번) 반영으로 **호출 횟수 포함**. aggregator·parser 소규모 변경 필요.
- `turns[].ended_at` (float | null): null 허용. Claude Code JSONL에 `ended_at` 값이 없을 수 있음.
- 기타 모든 숫자 필드 required.

**미래 스키마 변경 정책**:
- v2로 bump 시 `summary_store.load_last_summary`에서 `_migrate_v1_to_v2(data)` dispatcher 호출.
- 마이그레이션 불가 버전(예: 큰 breaking change)은 파일 삭제 + `err_unsupported_schema` 메시지.

---

## 5. SKILL.md

```markdown
---
name: token-detail
description: 직전 request의 turn별 토큰·비용·툴 사용 내역을 표로 출력
disable-model-invocation: true
---

!`python3 ${CLAUDE_SKILL_DIR}/scripts/detail.py "${CLAUDE_SESSION_ID}"`

위 출력 블록을 그대로 사용자에게 전달하세요. 숫자 해석·요약·추가 설명 금지.
```

**토큰 비용 분석**: frontmatter + 본문 3줄 + 스크립트 출력. 보통 request당 총 500~1500 토큰 (스크립트 출력 크기에 비례). `disable-model-invocation: true` 덕분에 Claude의 자동 invoke는 차단되어 명시적 호출 시에만 비용 발생.

---

## 6. 출력 포맷 명세

### 6.1 한국어 (ko)

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 직전 request 상세
 총 비용 $0.0180 | 1,546 toks | cache 85% | 12.3s

  #  모델                    툴                input    cc     cr      output   비용     시간
  1  opus-4-7[1m]            Read×3,Edit×1    120      400    800       450   $0.008   2.1s
  2  opus-4-7[1m]            —                 95        0  1,200       320   $0.006   3.5s
  3  sonnet-4-6              Bash×2            80      200    500       180   $0.004   6.7s
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 범례: cc=cache_creation, cr=cache_read
```

- 출력은 코드블록(``` ``` ```)으로 감싸 고정폭 보장.
- 구분선 폭 = `sum(column_widths) + sum(gaps)`로 동적 계산. 매직 넘버 42자 제거.

### 6.2 영어 (en) — 동일 구조, 라벨만 i18n/en.json에서 로드.

### 6.3 포맷 규칙

| 항목 | 규칙 |
|---|---|
| 모델명 | **표 폭 역산**: 현재 컬럼 총폭에서 최대 22자 할당. 초과 시 `...`로 truncate. |
| 툴 | 각 엔트리 `{이름}×{횟수}`. 최대 3개. 초과 시 `R×3,E×1,...+N`. 없으면 `—`. |
| 숫자 | **우측 정렬**. 천 단위 쉼표. 토큰 정수, 비용 `$0.0000`, 시간 `X.Ys`. |
| 시간(turn별) | `ended_at - started_at` 초. `ended_at`이 null이면 다음 turn의 `started_at - 현재 started_at`. 마지막 turn + null이면 `total_elapsed - 합계`. 음수가 나오면 `?`로 표시. |
| 한글 폭 계산 | `visual_width(s) = len(s) + sum(1 for c in s if ord(c) > 0x2E80)` (한중일 영역은 2칸). |
| 구분선 | `━` 문자. 길이 = `visual_width(header_line)`과 동일. |

### 6.4 80-column 터미널 대응

현재 표는 모두 표시 시 ~80자. 모델명이 긴 경우(`claude-opus-4-7-20260101`)라도 truncate로 맞춤. 실측: 컬럼 총폭 = 4+22+20+8+6+8+8+10+7+9 간격 ≒ 80. 별도 responsive mode 불필요.

---

## 7. 에러 처리 (통합된 표 — §9 엣지 케이스와 병합)

| 상황 | stdout 출력 | stderr (error.log) | 발생 경로 |
|---|---|---|---|
| state 디렉터리/파일 없음 | `err_no_state` | 기록 안 함 | 새 세션 첫 응답 전 호출 / turns=0 Stop (저장 skip됨) |
| JSON 파싱 실패 | `err_parse` | 전체 traceback + 파일 경로 | 파일 손상, partial write 후 복구 실패, UTF-8/BOM 오염 |
| schema_version 미지원 | `err_unsupported_schema` | 현재 version + 파일 경로 | v2→v1 downgrade 또는 수동 편집 |
| turns 리스트 비어있음 (저장되면 안 되지만 방어) | `err_empty_turns` | 기록 안 함 | aggregator 버그 방어 |
| 필수 필드 결손 | `err_parse` | 결손 필드명 + 파일 경로 | 수동 편집, 마이그레이션 누락 |
| 권한/symlink/read-only FS | `err_parse` | `PermissionError` traceback | 드물지만 발생 가능 |
| save 시 ENOSPC/권한 실패 | (hook 측) systemMessage 영향 없음 (기존 hook은 exit 0) | traceback in `log/error.log` | 디스크 풀, 권한 |
| 동시 Stop hook rename 경합 | `os.replace` atomicity로 덮어쓰기 OK | 정상 | 빠른 연속 응답 |
| 시계 역행 (`ended_at < started_at`) | 시간 컬럼 `?` | 기록 안 함 | OS 시계 조정, 드물다 |

**공통 원칙**:
- skill 스크립트는 항상 `exit 0`. non-zero 시 Claude Code 동작 불명확 (공식 문서 미정의).
- `error.log` 자체 쓰기 실패하면 최후 수단으로 `sys.stderr` 출력 (Claude Code가 캡처할 수도 있음).

---

## 8. 테스트 전략 (체크포인트-테스트 매핑 포함)

### Unit

**`test_summary_store.py`**
- `test_save_load_roundtrip` — save 후 load 동일 Summary 복원
- `test_save_is_atomic` — save 중단돼도 기존 파일 보존 (tempfile 확인)
- `test_save_creates_directories` — state/{session_id}/ 자동 생성
- `test_load_missing_returns_none` — 파일 없음 → `None`
- `test_load_corrupted_json_returns_none` — invalid JSON → `None` + stderr
- `test_load_unsupported_schema_returns_none` — schema_version=99 → `None` + 파일 삭제
- `test_load_missing_required_field_returns_none` — turns 필드 결손 → `None`
- `test_load_handles_bom` — UTF-8 BOM 포함 파일 읽기

**`test_detail_formatter.py`**
- `test_ko_structure` — 출력을 행 분해해서 dict(key→value) 검증 (snapshot 아님)
- `test_en_structure` — 동일
- `test_empty_turns_still_formats` — 0-turn도 안전하게 헤더만
- `test_single_turn` / `test_multi_turn`
- `test_model_name_truncation` — 30자 모델명 → "..." 처리
- `test_tools_over_three` — `["R","E","W","T","B"]` → `R×1,E×1,W×1,...+2`
- `test_tools_empty` — `—`
- `test_time_calculation_ended_at_present`
- `test_time_calculation_ended_at_null_uses_next_turn`
- `test_time_calculation_last_turn_null` — `total_elapsed - 합계`
- `test_time_negative_shows_question_mark`
- `test_hangul_width_calculation` — 한글 포함 헤더 정렬
- `test_unknown_language_falls_back_to_en`

### Integration

**`test_hook_end_to_end.py` (확장)**
- `test_last_summary_saved_after_stop` — Stop hook 실행 후 `state/{session}/last_summary.json` 생성 확인
- `test_last_summary_not_saved_when_turns_zero` — 기존 skip policy 유지 확인
- `test_flush_polling_precedes_save` — polling 후에 save 호출되는지 (turn 수가 맞아야 함)

**`test_detail_script_e2e.py` (신규)**
- `test_script_outputs_formatted_detail` — subprocess로 `detail.py <session_id>` 실행 → stdout에 표 구조 확인
- `test_script_missing_session_outputs_err_no_state` — state 없이 호출 → err_no_state
- `test_script_corrupted_state_outputs_err_parse` — state 파일 손상시켜서 호출 → err_parse + stderr에 traceback
- `test_script_unsupported_schema_outputs_err_unsupported` — schema_version=99 파일로 호출
- `test_script_always_exits_zero` — 모든 에러 경로에서 exit code 0

### 수동 인수 기준 (자동화 안 되는 항목만)

1. **실제 Claude Code에서 `/token-detail` 호출 → 표가 채팅창에 정상 표시.**
2. **여러 turn request 직후 호출 → 숫자 합이 Stop 요약과 일치.**
3. **새 세션 첫 응답 전 호출 → "아직 기록된 request가 없습니다."**

### 체크포인트-테스트 매핑

| 구현 체크포인트 | 통과해야 할 테스트 |
|---|---|
| 1. summary_store.py | `test_summary_store.py` 전체 (8건) |
| 2. detail_formatter.py + i18n | `test_detail_formatter.py` 전체 (13건) |
| 3. hooks/on_stop.py 수정 | `test_hook_end_to_end.py::test_last_summary_*` (3건) |
| 4. skills/token-detail/SKILL.md + scripts/detail.py | `test_detail_script_e2e.py` 전체 (5건) |
| 5. state 디렉터리 구조 변경 (offset.json 이동) | 기존 `test_state.py` green 유지 |
| 6. 수동 검증 3가지 | 사용자 실전 체크 |

---

## 9. 검토된 대안

### A안: SKILL.md에 `!`script`` 치환 + 스크립트가 state 읽기 (**채택**)
- **장점**: Claude Code 표준 패턴. `${CLAUDE_SESSION_ID}` 공식. aggregator 재사용.
- **단점**: 모델 토큰 소량 소비 (수백 단위).

### B안: SKILL.md가 직접 Markdown으로 출력
- **기각**: 동적 데이터(매 request 다름) 치환 불가.

### C안: Hook 기반 `/token-detail` 감지
- **기각**: Claude Code가 slash를 먼저 파싱해서 hook에 도달 안 함.

### D안: Skill이 transcript 재파싱 (이전 spec의 대안 B)
- **기각**: aggregator·state·pricing 전부 import → 결합도 증가, DRY 위반.

---

## 10. 엣지 케이스 (§7 표에 흡수된 것 외 추가)

| 케이스 | 동작 |
|---|---|
| turns 수백 개 초과 | 표 그대로 출력. 터미널 스크롤. 상한 정책은 Phase 2-C(`--tail N`)로. |
| 모델 ID에 한글 포함 | visual_width로 정렬 |
| config.json `language` 없음·오타 | `en` fallback |
| 다중 Claude Code 동시 실행 | state 파일은 session_id별이므로 교란 없음 |
| 매우 긴 tool 이름 | tools 컬럼 폭 20자 초과 시 `...`로 잘림 |

---

## 11. 후속 과제 (Phase 2-C 이후)

- `--index N` 과거 N번째 request → `summary_store.append` + `load_indexed` 추가, `history.jsonl` 도입
- ANSI 컬러 + `NO_COLOR` 환경변수 존중
- 비싼 turn 하이라이트 (cost 상위 20%)
- JSON/Markdown export (`--format json|md`)
- 다른 세션 조회 (`--session X`)
- schema_version v2 마이그레이션 예시 추가

---

## 12. 구현 체크포인트 (plan 작성 시 1:1 매핑)

1. `lib/i18n/{ko,en}.json` 리소스 생성
2. `lib/summary_store.py` + `test_summary_store.py` (모두 green)
3. `lib/detail_formatter.py` + `test_detail_formatter.py` (모두 green) — i18n 로드 포함
4. `lib/state.py` 경로 변경 (state/{session_id}/offset.json) + 기존 테스트 green
5. `lib/aggregator.py` + `lib/parser.py` — `tools_used`를 `list[{name, count}]`로 변경 + 기존 테스트 업데이트
6. `hooks/on_stop.py` — flush polling 완료 후 `save_last_summary` 호출 + e2e 테스트 추가
7. `skills/token-detail/SKILL.md` + `scripts/detail.py` + `test_detail_script_e2e.py` (모두 green)
8. 수동 검증 3가지 실행 + 결과 기록
9. README에 `/token-detail` 섹션 추가
10. handoff 문서 B 완료 표시, C를 다음 후보로
11. 버전 범프 0.2.0 → 0.3.0, 태그 `v0.3.0`
