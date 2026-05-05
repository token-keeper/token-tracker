# dev-mode.sh — 작업 디렉터리 ↔ cache symlink 토글 설계

> 작성일: 2026-05-05
> 상태: design 합의 완료, plan 작성 직전
> 관련: `docs/handoff/2026-05-05-token-tracker-next-steps-v0.9.0.md` §5-A

## 1. 배경 / 동기

token-tracker plugin 은 두 곳에 존재한다:

- **작업 디렉터리**: `/Users/brody/Desktop/token-tracker/plugins/token-tracker/` (코드 수정처, git repo)
- **cache 디렉터리**: `~/.claude/plugins/cache/token-tracker-local/token-tracker/<version>/` (Claude Code 가 실제로 읽는 위치)

이 둘은 별개 사본. 작업 디렉터리에서 코드를 수정해도 cache 는 갱신되지 않으므로, 매 검증마다:

- A: 수동 `cp` 명령
- B: `/plugin uninstall` + `/plugin install` + `/reload-plugins` (3분 의식)

위 마찰을 없애고자 cache 디렉터리를 작업 디렉터리의 **symlink** 로 교체한다. 코드 수정 즉시 반영 → 복사 / 재설치 불필요.

## 2. 비목표

- 옛 cache 디렉터리 (`0.1.0/`, `0.6.0/`, `0.8.1/`) 자동 정리 → 별도 follow-up. 이번 작업 시점에 수동 `rm -rf` 로 일회성 처리.
- multi-plugin / 다른 plugin 으로의 일반화 → 우선 token-tracker 한정.
- daemon 자동 재시작 → 사용자가 `/token-tracker:token-history-stop` 으로 명시 종료. 이번 scope 밖.

## 3. 사용자 인터페이스

`scripts/dev-mode.sh` 단일 스크립트, 3개 서브명령:

```bash
./scripts/dev-mode.sh on      # symlink 로 교체 (실시간 반영 모드)
./scripts/dev-mode.sh off     # 원본 cache 복원 (정상 모드)
./scripts/dev-mode.sh status  # 현재 상태 확인
```

**인자 없음 / 환경변수 없음** — 모든 정보는 자동 추출.

- active version: `plugins/token-tracker/.claude-plugin/plugin.json` 의 `version`
- cache base: 하드코딩 `~/.claude/plugins/cache/token-tracker-local/token-tracker/`
- 작업 폴더 plugin 경로: 스크립트 위치 기준 `dirname $0/../plugins/token-tracker`

## 4. `on` 동작

1. `plugin.json` 에서 active version 읽기 (예: `0.9.0`)
2. cache target 경로 계산: `<cache_base>/0.9.0/`
3. 작업 폴더 plugin 경로 계산 (스크립트 기준 상대 → 절대 경로)
4. **사전 검사**:
   - cache target 이 이미 symlink → "이미 dev mode" 안내 후 종료 (idempotent, exit 0)
   - cache target 이 존재하지 않음 → "plugin install 먼저" 에러 (exit 1)
   - `<cache_base>/0.9.0.backup/` 이 이미 존재 → 충돌 에러 + 수동 정리 안내 (exit 1)
   - 작업 폴더 plugin 경로가 존재하지 않음 → 에러 (exit 1)
5. **실행**:
   - `mv <cache_base>/0.9.0 <cache_base>/0.9.0.backup`
   - `ln -s <abs_work_plugin_path> <cache_base>/0.9.0`
6. 안내 출력:
   - 어느 경로 → 어디로 symlink 됐는지
   - "이제 코드 수정 즉시 반영. daemon 코드 변경 시 `/token-tracker:token-history-stop` 후 재호출."
   - "끄려면: `./scripts/dev-mode.sh off`"

## 5. `off` 동작

1. active version 읽기
2. cache target 경로 계산
3. **사전 검사**:
   - cache target 이 symlink 가 아님 → "이미 정상 mode" 안내 후 종료 (idempotent, exit 0)
   - `<cache_base>/0.9.0.backup/` 이 없음 → 에러 + 수동 복구 안내 (exit 1)
4. **실행**:
   - `rm <cache_base>/0.9.0` (symlink 만 제거)
   - `mv <cache_base>/0.9.0.backup <cache_base>/0.9.0`
5. 안내 출력: "정상 mode 로 복원. cache 가 갱신되려면 reinstall 필요."

## 6. `status` 동작

active version 기준 cache target 의 상태를 한 번에 보고:

- **symlink** → 가리키는 절대 경로 출력, "dev mode ON"
- **일반 dir** → "dev mode OFF (정상 cache)"
- **존재하지 않음** → "cache 없음 — plugin install 필요"
- **`0.9.0.backup/` 만 존재 / `0.9.0/` 자체가 없음** (reinstall 로 symlink 끊긴 케이스) → "dev mode 가 reinstall 로 끊김. `off` 로 백업 정리 후 `on` 다시 실행"

## 7. 검증 단계 (구현 전 사전 단계)

symlink 가 Claude Code plugin 시스템에서 정상 동작하는지 **먼저** 검증한다. 안전하게 더미 검증:

1. 임시 dir 만들기: `~/.claude/plugins/cache/token-tracker-local/token-tracker/symlink-test/`
2. 그 안에 작업 폴더 plugin 을 가리키는 symlink 생성
3. `/plugin reload` 또는 새 Claude Code 세션에서 hook 동작 확인
   - hook 이 동작하면 symlink 인식 OK
   - hook 이 silent 실패하면 **plugin 시스템이 symlink 비호환** → 폴백 (§9)
4. 작업 폴더 코드 한 줄 수정 → symlink 통해 변경이 보이는지 확인

검증 통과 후 `dev-mode.sh` 본격 구현. 검증은 사용자가 수동 step-through 로 진행 (계정 환경 의존).

## 8. Plugin reinstall 시 동작

`/plugin uninstall` + `/plugin install` 흐름은 dev mode 가 켜진 상태에서도 사용자가 실행 가능. 그 결과:

- plugin 시스템이 cache target dir 을 새로 만들면서 **symlink 가 사라질 가능성 매우 높음**
- 하지만 `<cache_base>/0.9.0.backup/` 는 그대로 남음
- 사용자 입장에선 "어? dev mode 였는데 왜 코드 변경이 안 보이지?" 라는 혼란

**대응**: `status` 명령이 이 상태 (`0.9.0/` 은 존재하지만 symlink 가 아니고, `0.9.0.backup/` 도 함께 존재) 를 감지하면 명시적 안내:

```
경고: 이전 dev mode 의 백업 dir 이 남아있습니다.
plugin reinstall 로 symlink 가 끊긴 것 같습니다.
조치: ./scripts/dev-mode.sh off    # 백업을 안전하게 제거
      ./scripts/dev-mode.sh on     # 다시 dev mode 켜기
```

자동 복구는 하지 않는다 (현재 cache 와 backup 어느 쪽이 truth 인지 스크립트가 판단할 수 없음 — 사용자 의도에 의존).

## 9. 폴백 — symlink 미호환 시

§7 검증에서 plugin 시스템이 symlink 를 무시하는 것이 확인되면, 본 design 폐기 후 옵션 B (cp 기반 sync 헬퍼) 로 다운그레이드한다. 그 design 은 별도 spec 으로:

```bash
./scripts/sync-cache.sh   # 작업 폴더 → cache 일방향 cp -R, 매번 호출
```

폴백 시 본 design doc 은 "rejected" 상태로 보존, 새 spec 작성.

## 10. 안전 장치 요약

| 시나리오 | 동작 |
|---|---|
| `on` 인데 이미 dev mode | no-op + 안내 |
| `off` 인데 이미 정상 mode | no-op + 안내 |
| `on` 인데 backup dir 충돌 | 에러 + 수동 정리 요청 |
| `off` 인데 backup 없음 | 에러 + 수동 복구 안내 |
| cache target 자체 없음 | 에러 + plugin install 안내 |
| reinstall 로 symlink 끊김 | `status` 감지 + 안내 |

## 11. 테스트 / 검증 전략

자동화 테스트는 **만들지 않는다**:

- bash 스크립트 + 실제 cache dir + plugin 시스템 의존성
- 가짜 cache 환경 mock 으로는 진짜 plugin 시스템 동작 못 잡음
- 비용 대비 가치 낮음

대신 **README 에 수동 검증 체크리스트** 등재:

1. `./scripts/dev-mode.sh status` → "OFF" 확인
2. `./scripts/dev-mode.sh on` → 안내 출력 확인
3. `./scripts/dev-mode.sh status` → "ON" + 가리키는 경로 확인
4. 작업 폴더에서 `style.css` 한 줄 수정 → 브라우저 새로고침으로 즉시 반영 확인
5. `./scripts/dev-mode.sh off` → 안내 출력 확인
6. `./scripts/dev-mode.sh status` → "OFF" 확인 + backup dir 사라진 것 확인

## 12. 문서화

`README.md` 에 "Development" 섹션 신설:

- dev mode 1~2 줄 설명 (symlink 로 즉시 반영)
- 사용법 (`on/off/status`)
- reinstall 시 주의점 (`status` 가 안내해줌)
- 검증 체크리스트 링크

핸드오프 7.2/7.3 갱신은 본 작업 머지 후 다음 핸드오프 작성 시 반영.

## 13. 폴더 구조 변경

```
plugins/token-tracker/
  ...
scripts/
  diagnose_v0_7_shapes.py   # 기존
  dev-mode.sh                # 신규
README.md                    # Development 섹션 추가
docs/superpowers/specs/
  2026-05-05-dev-mode-symlink-design.md  # 본 문서
```

## 14. 구현 단계 (다음 plan 에서 상세화)

1. (사전) 수동 검증 — symlink 가 plugin 시스템과 호환되는지 사용자가 확인
2. `scripts/dev-mode.sh` 작성 (on/off/status)
3. README "Development" 섹션 추가
4. 수동 검증 체크리스트 step-through (사용자)
5. commit + PR

검증 (1) 이 실패하면 §9 폴백.
