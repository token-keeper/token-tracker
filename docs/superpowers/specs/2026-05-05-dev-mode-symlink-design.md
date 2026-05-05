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

- **`MANIFEST_VERSION`**: `plugins/token-tracker/.claude-plugin/plugin.json` 의 `version`
- **`DEV_VERSION`**: `<cache_base>` 를 스캔해서 dev mode artifact (symlink 또는 `<X>.backup` dir) 가 있는 version. 없으면 빈 문자열.
- **실제 사용 `VERSION`**: `DEV_VERSION` 이 있으면 그쪽 (active dev mode 가 truth), 없으면 `MANIFEST_VERSION`.
- cache base: 하드코딩 `~/.claude/plugins/cache/token-tracker-local/token-tracker/`
- 작업 폴더 plugin 경로: 스크립트 위치 기준 `dirname $0/../plugins/token-tracker`

> **왜 `DEV_VERSION` 이 우선인가**: 사용자가 dev mode 를 켠 후 release 흐름에서 plugin.json 의 version 을 bump 하는 일이 흔하다. manifest 만 보면 `off` 가 새 version path 를 찾지만 cache 의 dev mode 는 옛 version 위에 있어 strand 됨. cache 자체를 truth source 로 두면 manifest bump 후에도 자가복구 가능.
>
> **여러 version 동시 dev artifact**: 비정상 상태로 간주, `find_active_dev_version` 이 stderr 안내 + exit 1.

## 4. `on` 동작

1. `MANIFEST_VERSION` (`plugin.json`) + `DEV_VERSION` (cache 스캔) 추출
2. **다른 version 의 dev mode 가 활성 상태에서 manifest 만 bump 된 경우 명시 안내**:
   - `DEV_VERSION` 이 있고 `MANIFEST_VERSION` 과 다르면 → "이미 다른 version 의 dev mode 가 활성. 먼저 `off` 후 다시 `on`" 에러 (exit 1)
3. `VERSION = MANIFEST_VERSION` (이 시점에 `DEV_VERSION` 은 빈 문자열이거나 manifest 와 동일)
4. cache target 경로 계산: `<cache_base>/$VERSION/`
5. 작업 폴더 plugin 경로 계산 (스크립트 기준 상대 → 절대 경로)
6. **사전 검사**:
   - cache target 이 이미 symlink → "이미 dev mode" 안내 후 종료 (idempotent, exit 0)
   - cache target 이 존재하지 않음 → "plugin install 먼저" 에러 (exit 1)
   - `<cache_base>/$VERSION.backup/` 이 이미 존재 → 충돌 에러 + 수동 정리 안내 (exit 1)
   - 작업 폴더 plugin 경로가 존재하지 않음 → 에러 (exit 1)
5. **트랜잭션 실행**:
   - `mv <cache_base>/0.9.0 <cache_base>/0.9.0.backup`
   - `ln -s <abs_work_plugin_path> <cache_base>/0.9.0`
   - **`ln -s` 가 실패하면 즉시 backup 을 target 으로 되돌려 cache 를 원상복구 후 exit 1.** `mv` 만 끝난 상태로 cache 가 사라진 채 멈추는 일이 없도록 한다.
6. 안내 출력:
   - 어느 경로 → 어디로 symlink 됐는지
   - "이제 코드 수정 즉시 반영. daemon 코드 변경 시 `/token-tracker:token-history-stop` 후 재호출."
   - "끄려면: `./scripts/dev-mode.sh off`"

## 5. `off` 동작

cache 의 현재 상태가 6개 케이스 중 어디에 해당하는지 분기해서 처리한다 (§10 의 안전 장치 표와 일치).

1. active version 읽기 + cache target / backup 경로 계산
2. **케이스별 분기**:
   1. **인터럽트 잔재** (target 없음 + backup 만) → backup → target 으로 mv 하여 자가복구. exit 0.
   2. **이미 정상 mode** (정상 dir + backup 없음) → no-op + 안내. exit 0.
   3. **reinstall 로 끊긴 상태** (정상 dir + backup 둘 다 존재) → **자동 정리 안 함**. 어느 쪽이 truth 인지 스크립트가 판단할 수 없으므로 사용자가 수동으로 결정하도록 두 가지 명령 (`rm -rf "$backup"` 또는 `rm -rf "$target" && mv "$backup" "$target"`) 안내 후 exit 1.
   4. **정상 dev mode** (symlink + backup) → 표준 off: `rm <symlink>` + `mv <backup> <target>`. exit 0.
   5. **symlink 만 있고 backup 없음** (이상 상태) → 에러 + 수동 복구 안내 (`rm <symlink>` + plugin reinstall). exit 1.
   6. **알 수 없는 상태** → 에러 + `ls -la` 로 확인 안내. exit 1.
3. 안내 출력: 해당 케이스에 맞는 메시지.

## 6. `status` 동작

active version 기준 cache target 의 상태를 한 번에 보고:

- **인터럽트 잔재** (target 없음 + backup 만 존재) → "경고: 인터럽트된 on 작업 잔재 감지. `off` 로 backup 복원."
- **symlink** → 가리키는 절대 경로 출력, "dev mode ON"
- **일반 dir + backup 동시 존재** (reinstall 끊김) → "경고: dev mode 가 reinstall 로 끊긴 것 같습니다. `off` 안내 메시지를 따라 수동 처리."
- **일반 dir, backup 없음** → "dev mode OFF (정상 cache)"
- **둘 다 존재하지 않음** → "cache 없음 — plugin install 필요"

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

**대응**: `status` / `off` 명령이 이 상태 (`0.9.0/` 은 존재하지만 symlink 가 아니고, `0.9.0.backup/` 도 함께 존재) 를 감지하면 **자동 정리하지 않고** 명시적 안내만 한다:

```
경고: dev mode 가 reinstall 로 끊긴 것 같습니다.
어느 쪽이 truth 인지 스크립트가 판단할 수 없으므로 자동 정리하지 않습니다.
조치: 어느 쪽이 정상인지 확인 후 수동 처리:
  - 현재 cache 가 정상이면:  rm -rf <cache_base>/0.9.0.backup
  - backup 이 정상이면:      rm -rf <cache_base>/0.9.0 && mv <cache_base>/0.9.0.backup <cache_base>/0.9.0
```

자동 복구는 하지 않는다. 부분 실패한 reinstall 이 target 에 partial 상태를 남겨도 backup 이 마지막 known-good 일 수 있으므로, "정상 dir 이 존재한다" 만으로는 truth 를 가릴 수 없다 — 사용자 명시 결정에 의존.

## 9. 폴백 — symlink 미호환 시

§7 검증에서 plugin 시스템이 symlink 를 무시하는 것이 확인되면, 본 design 폐기 후 옵션 B (cp 기반 sync 헬퍼) 로 다운그레이드한다. 그 design 은 별도 spec 으로:

```bash
./scripts/sync-cache.sh   # 작업 폴더 → cache 일방향 cp -R, 매번 호출
```

폴백 시 본 design doc 은 "rejected" 상태로 보존, 새 spec 작성.

## 10. 안전 장치 요약

### `on`

| 사전 상태 | 동작 |
|---|---|
| 다른 version 의 dev mode 활성 (manifest bump 후) | 에러 + `off` 안내, exit 1 |
| 이미 symlink (dev mode) | no-op + 안내, exit 0 |
| backup dir 이 이미 존재 | 에러 + 수동 정리 안내, exit 1 |
| cache target 자체 없음 | 에러 + plugin install 안내, exit 1 |
| 작업 폴더 plugin 경로 없음 | 에러, exit 1 |
| `mv` 후 `ln -s` 실패 | backup → target rollback + exit 1 |
| 여러 version 동시 dev artifact | 에러 + 수동 정리 안내, exit 1 (`find_active_dev_version` 단계) |

### `off`

| cache 상태 | 동작 |
|---|---|
| 1. target 없음 + backup 만 (인터럽트 잔재) | backup → target 복원, exit 0 |
| 2. 정상 dir + backup 없음 (이미 OFF) | no-op + 안내, exit 0 |
| 3. 정상 dir + backup 둘 다 (reinstall 끊김) | **자동 정리 안 함**, 수동 안내 + exit 1 |
| 4. symlink + backup (정상 dev mode) | symlink 제거 + backup 복원, exit 0 |
| 5. symlink 만 있고 backup 없음 (이상) | 에러 + 수동 복구 안내, exit 1 |
| 6. 알 수 없는 상태 | 에러 + `ls -la` 안내, exit 1 |

### `status`

| cache 상태 | 출력 |
|---|---|
| target 없음 + backup 만 | "경고: 인터럽트된 on 작업 잔재 감지" |
| symlink | "dev mode ON" + 가리키는 경로 |
| 정상 dir + backup 동시 | "경고: reinstall 로 끊김. `off` 안내 따라 수동 처리" |
| 정상 dir, backup 없음 | "dev mode OFF (정상 cache)" |
| 둘 다 없음 | 에러: "cache 없음 — plugin install 필요" |

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
