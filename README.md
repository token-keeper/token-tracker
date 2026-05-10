# token-tracker

Claude Code plugin: display per-request token cost on every `Stop`.

## What it shows

After every assistant response, a one-line summary appears below it:

```
비용 $0.0180 · 1,546 toks · cache 85% · 12.3s
```

- **비용**: retail pay-per-token cost estimate for just this request.
- **toks**: total (input + output + cache_read) tokens consumed.
- **cache**: `cache_read / total_input` hit rate.
- **s**: wall-clock seconds from `UserPromptSubmit` to `Stop`.

## Detail view — 두 가지 방식

### 방식 1 (추천): verbose 모드 — 매 응답마다 자동 출력

`plugins/token-tracker/config.json`에서 `"verbose": true`로 바꾸면 Stop hook이 매 응답 끝에 **한 줄 요약 + turn별 상세 표**를 함께 찍습니다.

```json
{
  "language": "ko",
  "verbose": true
}
```

일회성 디버깅엔 환경변수 쪽이 편합니다:

```bash
export TOKEN_TRACKER_VERBOSE=1
```

이 방식은 Hook이 `systemMessage`로 직접 출력하므로 **LLM을 거치지 않아 결정론적**이고 토큰 비용 0.

### 방식 2 (주문형): `/token-detail` slash skill

직전 request의 turn별 정보를 **원할 때만** 한 번 조회:

```
/token-detail
```

출력 예시:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 직전 request 상세
 총 비용 $0.0180 | 1,546 toks | cache 85% | 12.3s

   #  모델                    툴                 input    cc       cr    output     비용      시간
   1  opus-4-7[1m]            Read×3,Edit×1      120     400      800       450    $0.008     2.1s
   2  opus-4-7[1m]            —                   95       0    1,200       320    $0.006     3.5s
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 범례: cc=cache_creation, cr=cache_read
```

skill은 `disable-model-invocation: true`로 등록돼 있어 Claude가 자동으로 호출하지 않고, 사용자가 `/token-detail`을 직접 입력해야만 실행됩니다. 내부적으로는 script 출력 + minimal SKILL.md 본문이라 호출당 토큰 소비는 수백 단위.

> **주의**: slash skill은 Claude Code 구조상 항상 LLM을 거치므로 가끔 모델이 이전 대화 맥락에 끌려 표 대신 엉뚱한 응답을 낼 수 있습니다. **결정론적 동작을 원하면 방식 1(verbose)** 을 쓰세요.

## Cost is "retail" — it will not match the statusline

Claude Code's statusline `[💰 $X.XXX]` shows its **internal session-cumulative** cost tracker, which may reflect team/enterprise plan discounts or different cache-creation accounting. This plugin computes cost from Anthropic's **public pay-per-token rate card** (values hardcoded in `lib/pricing.py`).

Use this plugin's output for **optimization signal** (did caching improve? is this prompt expensive relative to the last one?), not for billing.

## Files of interest

- `docs/superpowers/specs/` — design specs (Phase 1 overall + Phase 2-B `/token-detail`)
- `docs/superpowers/plans/` — implementation plans per phase
- `docs/handoff/` — cross-session handoff notes
- `plugins/token-tracker/lib/pricing_data.json` — 단가 표 (Anthropic 단가 변경 시 이 파일의 row 만 수정 + `fetched` 날짜 갱신)
- `plugins/token-tracker/lib/pricing.py` — JSON 로드 + cost 계산 로직 (`compute_cost`, prefix-match resolver)
- `plugins/token-tracker/hooks/on_stop.py` — aggregation + output
- `plugins/token-tracker/lib/i18n/` — translated strings for ko/en

## Install

이 repo 자체가 self-contained Claude Code marketplace (`token-keeper`) 입니다. Claude Code CLI에서 한 번만 등록하면 이후 어느 디렉터리에서 Claude Code를 실행해도 hook이 발화합니다.

```bash
# Option A — GitHub에서 바로 등록 (추천)
/plugin marketplace add token-keeper/token-tracker

# Option B — 로컬에 clone 한 경로를 가리키기 (개발/오프라인용)
/plugin marketplace add /absolute/path/to/token-tracker

# plugin 활성화
/plugin install token-tracker@token-keeper
```

활성화 후 Claude Code를 재시작하면 Stop hook이 응답마다 아래 같은 한 줄을 출력합니다:

```
비용 $0.0180 · 1,546 toks · cache 85% · 12.3s
```

비활성화: `/plugin disable token-tracker@token-keeper`
제거: `/plugin uninstall token-tracker@token-keeper`

### 개발 모드

repo 의 코드 변경을 매 reinstall 없이 즉시 반영하려면 [Development 섹션](#development) 의 `scripts/dev-mode.sh` 토글 사용을 권장합니다.

`.claude/settings.local.json` 에 hook 을 직접 등록하던 이전 방식은 더 이상 사용하지 않습니다.

## Development

### dev mode (작업 폴더 ↔ cache 즉시 반영)

플러그인 코드 수정 시 매번 plugin reinstall 하지 않고 작업 폴더 변경을 즉시 반영하려면 `scripts/dev-mode.sh` 의 dev mode 를 사용합니다.

```bash
./scripts/dev-mode.sh on      # cache → 작업 폴더 symlink 로 교체
./scripts/dev-mode.sh off     # 원본 cache 복원
./scripts/dev-mode.sh status  # 현재 상태 확인
```

`on` 시 cache 디렉터리는 `<version>.backup/` 으로 백업되고, 그 자리에 작업 폴더의 `plugins/token-tracker/` 를 가리키는 symlink 가 생깁니다. `off` 는 그 역순으로 원본을 복원합니다.

#### daemon 코드 수정 시

`lib/server_daemon.py`, `lib/http_server.py`, `lib/history_renderer.py` 같은 daemon 코드를 수정하면 실행 중 daemon 을 재시작해야 반영됩니다:

```
/token-tracker:token-history-stop
```

`style.css` / `app.js` / 템플릿 같은 정적 파일은 daemon 이 매 요청마다 디스크에서 읽으므로 브라우저 새로고침 (cmd+R) 만으로 즉시 반영됩니다.

#### plugin reinstall 과의 관계

dev mode 가 켜진 상태에서 `/plugin uninstall` + `/plugin install` 을 하면 plugin 시스템이 cache 디렉터리를 새로 만들면서 symlink 가 사라질 수 있습니다. 이 상태는 `./scripts/dev-mode.sh status` 가 감지해서 안내합니다. 어느 쪽이 truth 인지 스크립트가 판단할 수 없으므로 자동 정리하지 않고 수동 처리 명령만 안내합니다.

#### 수동 검증 체크리스트

dev mode 를 처음 켜는 환경 / Claude Code 업데이트 후 등 기본 동작이 의심될 때:

1. `./scripts/dev-mode.sh status` → "OFF" 확인
2. `./scripts/dev-mode.sh on` → "ON" + 가리키는 경로 출력 확인
3. `/reload-plugins` 실행
4. 새 prompt 한 번 입력 → 응답 마지막에 토큰 줄 (`비용 $... · ... toks ...`) 출력 확인
5. `/token-tracker:token-history` → daemon 정상 동작 + URL 응답 확인
6. 작업 폴더의 `plugins/token-tracker/skills/token-history/static/style.css` 한 줄 수정 → 위 페이지 새로고침으로 즉시 반영 확인 (사용자 메모: 빨간색 `#FF0000` 임시 마커가 효과적)
7. `./scripts/dev-mode.sh off` → "OFF" 복원 + `<version>.backup/` 사라짐 확인

3~5 가 실패하면 plugin 시스템이 symlink 를 인식하지 못하는 것입니다. 즉시 `off` 로 복원하고 이슈 리포트.

## Tests

repo 루트에서:

```bash
./venv/bin/pytest plugins/token-tracker/tests -q
```

80 tests across unit + integration + e2e (hook subprocess, skill script subprocess). Python 3.10+ stdlib only, pytest as the only dev dependency.
