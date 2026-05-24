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

## 토큰 절약 팁

token-tracker 의 숫자를 보면서 직접 발견한 토큰 아끼는 패턴 공유:

- **Claude Code 는 기본적으로 prompt cache 를 약 1시간 유지합니다.** 1시간 넘게 자리를 비우면 cache 가 만료되고, 다음 프롬프트는 cold start 처럼 처리됩니다.
- **자리 비우기 전에 `/compact` 를 실행하거나 새 세션을 여는 게 좋습니다.** context 가 작아진 상태로 다시 시작하면 "첫 프롬프트" 가 큰 대화를 통째로 다시 캐싱하지 않고 작은 베이스에서 출발합니다.
- **1시간 이상 자리를 비운 뒤 세션을 그대로 재개하면, 누적된 context window 전체가 다시 `cache creation` 으로 처리됩니다** — 가장 비싼 토큰 등급이라 한 turn 만에 사용량이 확 뜁니다. 오래 비운 직후 token-tracker 가 찍는 라인의 `cost` 가 비정상적으로 크거나 `cc` 수치가 평소보다 훨씬 큰지 주의 깊게 봐주세요.

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

## 주요 파일

- `docs/superpowers/specs/` — phase별 design specs
- `docs/superpowers/plans/` — phase 별 implementation plan
- `docs/handoff/` — 세션 간 인계 노트
- `lib/pricing_data.json` — 단가 표 (Anthropic 단가 변경 시 이 파일의 row 만 수정 + `fetched` 날짜 갱신)
- `lib/pricing.py` — JSON 로드 + cost 계산 로직 (`compute_cost`, prefix-match resolver)
- `hooks/on_stop.py` — aggregation + output
- `lib/i18n/` — ko/en 번역 문자열

## Tests

repo 루트에서:

```bash
./venv/bin/pytest tests -q
```

436 tests across unit + integration + e2e (hook subprocess, skill script subprocess). Python 3.10+ stdlib only, pytest as the only dev dependency.
