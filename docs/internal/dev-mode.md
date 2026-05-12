# Dev mode (내부용 참고 문서)

> 공개 README 에서는 제거된 내용. 본인이 token-tracker 코드를 수정할 때 참고하는 토글 스크립트 매뉴얼.

## 무엇인가

`scripts/dev-mode.sh` 는 Claude Code 의 plugin cache 디렉터리(`~/.claude/plugins/cache/token-keeper/token-tracker/<version>/`) 를 작업 폴더(`plugins/token-tracker/`) 의 symlink 로 교체해서, **plugin reinstall 없이 코드 수정이 즉시 반영**되도록 한다.

공개 배포 대상이 아니라 본인 개발 환경 한정으로 사용한다. (외부 사용자는 `/plugin marketplace add ...` + `/plugin install ...` 흐름으로 충분하고, 이 스크립트는 사용자에게 노출할 가치가 없다.)

## 동작

```bash
./scripts/dev-mode.sh on      # cache → 작업 폴더 symlink 로 교체
./scripts/dev-mode.sh off     # 원본 cache 복원
./scripts/dev-mode.sh status  # 현재 상태 확인
```

- `on`: cache 디렉터리를 `<version>.backup/` 으로 백업 후, 그 자리에 작업 폴더 `plugins/token-tracker/` 를 가리키는 symlink 생성.
- `off`: symlink 제거 + backup 을 원위치로 복원.
- `status`: 현재 ON/OFF + 비정상 상태(인터럽트, reinstall 로 인한 disconnect 등) 진단.

## daemon 코드 수정 시

`lib/server_daemon.py`, `lib/http_server.py`, `lib/history_renderer.py` 같은 long-running daemon 코드는 실행 중 daemon 을 재시작해야 반영된다:

```
/token-tracker:token-history-stop
```

`style.css` / `app.js` / 템플릿 같은 정적 파일은 daemon 이 매 요청마다 디스크에서 읽으므로 브라우저 새로고침(cmd+R) 으로 즉시 반영된다.

## plugin reinstall 과의 관계

dev mode 가 켜진 상태에서 `/plugin uninstall` + `/plugin install` 을 하면 plugin 시스템이 cache 디렉터리를 새로 만들면서 symlink 가 사라질 수 있다. 이 상태는 `./scripts/dev-mode.sh status` 가 감지해서 안내한다. 어느 쪽이 truth 인지 스크립트가 판단할 수 없으므로 자동 정리하지 않고 수동 처리 명령만 안내한다.

## 수동 검증 체크리스트

dev mode 를 처음 켜는 환경 / Claude Code 업데이트 후 등 기본 동작이 의심될 때:

1. `./scripts/dev-mode.sh status` → "OFF" 확인
2. `./scripts/dev-mode.sh on` → "ON" + 가리키는 경로 출력 확인
3. `/reload-plugins` 실행
4. 새 prompt 한 번 입력 → 응답 마지막에 토큰 줄 (`비용 $... · ... toks ...`) 출력 확인
5. `/token-tracker:token-history` → daemon 정상 동작 + URL 응답 확인
6. 작업 폴더의 `plugins/token-tracker/skills/token-history/static/style.css` 한 줄 수정 → 위 페이지 새로고침으로 즉시 반영 확인 (빨간색 `#FF0000` 임시 마커가 효과적)
7. `./scripts/dev-mode.sh off` → "OFF" 복원 + `<version>.backup/` 사라짐 확인

3~5 가 실패하면 plugin 시스템이 symlink 를 인식하지 못하는 것이다. 즉시 `off` 로 복원하고 원인 조사.

## 주의

- 이 문서는 본인 참고용. 공개 README 에는 노출하지 않는다.
- `scripts/dev-mode.sh` 가 다시 필요해지면 git history 에서 복구한다 (해당 PR: "공개 정리").
