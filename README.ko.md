<p align="center">
  <img src="assets/banner.png" alt="Token Tracker" width="420">
</p>

<p align="center">
  <a href="README.md">English</a> · <strong>한국어</strong>
</p>

# Token Tracker

매 `Stop` 마다 응답 한 건의 토큰·비용을 한 줄로 표시하는 Claude Code 플러그인.

## 무엇을 보여주는가

매 응답 끝에 아래 같은 한 줄 요약이 붙습니다:

```
비용 $0.0180 · 1,546 toks · cache 85% · 12.3s
```

- **비용**: 이번 요청 한 건의 retail pay-per-token 단가 추정.
- **toks**: input + output + cache_read 합산.
- **cache**: `cache_read / total_input` 적중률.
- **s**: `UserPromptSubmit` 부터 `Stop` 까지의 wall-clock 초.

## Detail view (verbose 모드)

매 응답 끝에 turn별 상세 표를 함께 보고 싶다면 verbose 모드를 켜세요. Stop hook이 한 줄 요약 **+ turn별 상세 표**를 같이 출력합니다.

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

켜고 끄는 방법 세 가지:

### 1. 슬래시 명령 (추천)

```
/token-verbose on        # 켜기
/token-verbose off       # 끄기
/token-verbose status    # 현재 상태 표시 (인자 없이 호출해도 동일)
```

### 2. `config.json`

```json
{
  "language": "ko",
  "verbose": true
}
```

### 3. 환경변수 (일회성 디버깅)

```bash
export TOKEN_TRACKER_VERBOSE=1
```

세 가지 모두 Hook이 `systemMessage`로 직접 출력하므로 **LLM을 거치지 않아 결정론적**이고 토큰 비용 0.

## Cost is "retail" — statusline 값과 일치하지 않습니다

Claude Code의 statusline `[💰 $X.XXX]` 은 **세션 누적 비용 tracker (내부)** 라서 team/enterprise plan 할인이나 cache-creation 회계 차이가 반영될 수 있습니다. 이 플러그인은 Anthropic의 **공식 pay-per-token rate card** 기준으로 계산합니다 (단가는 `lib/pricing.py` 에 하드코딩).

이 플러그인의 출력은 **최적화 signal** (캐시가 개선됐나? 직전 prompt 보다 비싸졌나?) 용도이지 청구 금액이 아닙니다.

## 설치

이 repo 자체가 self-contained Claude Code marketplace (`token-keeper`) 입니다. Claude Code CLI에서 한 번만 등록하면 이후 어느 디렉터리에서 Claude Code를 실행해도 hook이 발화합니다.

```bash
# Option A — GitHub에서 바로 등록 (추천)
/plugin marketplace add token-keeper/token-tracker

# Option B — 로컬에 clone 한 경로를 가리키기 (개발/오프라인용)
/plugin marketplace add /absolute/path/to/token-tracker

# plugin 활성화
/plugin install token-tracker@token-keeper
```

활성화 후 Claude Code를 재시작하면 Stop hook이 응답마다 위에 보인 것과 같은 한 줄을 출력합니다.

비활성화: `/plugin disable token-tracker@token-keeper`
제거: `/plugin uninstall token-tracker@token-keeper`

### 개발 모드

repo 의 코드 변경을 매 reinstall 없이 즉시 반영하려면 [Development 섹션](#development) 의 `scripts/dev-mode.sh` 토글 사용을 권장합니다.

`.claude/settings.local.json` 에 hook 을 직접 등록하던 이전 방식은 더 이상 사용하지 않습니다.

## 주요 파일

- `docs/superpowers/specs/` — phase별 design specs
- `docs/superpowers/plans/` — phase 별 implementation plan
- `docs/handoff/` — 세션 간 인계 노트
- `plugins/token-tracker/lib/pricing_data.json` — 단가 표 (Anthropic 단가 변경 시 이 파일의 row 만 수정 + `fetched` 날짜 갱신)
- `plugins/token-tracker/lib/pricing.py` — JSON 로드 + cost 계산 로직 (`compute_cost`, prefix-match resolver)
- `plugins/token-tracker/hooks/on_stop.py` — aggregation + output
- `plugins/token-tracker/lib/i18n/` — ko/en 번역 문자열

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
