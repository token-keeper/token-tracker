# CLAUDE.md

이 파일은 Claude Code 가 이 repo 에서 작업할 때 따라야 할 프로젝트 규칙을 기록한다.

---

## 릴리즈 / marketplace 동기화 규칙

이 repo (`token-keeper/token-tracker`) 는 marketplace repo (`token-keeper/plugins`) 의 **git submodule** 로 포함되어 있다. submodule 은 특정 commit SHA 를 고정해서 가리키므로, 본체에 push 해도 marketplace 의 pointer 는 자동으로 따라오지 않는다.

따라서 **`main` 에 새 commit 이 올라가면 반드시 marketplace 의 submodule pointer 도 같이 갱신해야 한다.** 안 그러면 marketplace 를 통해 설치하는 사용자는 새 버전을 못 받는다.

### 작업 순서

1. 이 repo 의 `main` 에 commit + push (`origin/main`)
2. marketplace repo (`token-keeper/plugins`) clone 위치로 이동
3. submodule 갱신 + commit + push:
   ```bash
   cd plugins/token-tracker
   git fetch && git checkout main && git pull
   cd ../..
   git add plugins/token-tracker
   git commit -m "chore: bump token-tracker to vX.Y.Z"
   git push
   ```

### 참고

- marketplace clone 위치 (현재 사용자 환경): `~/.claude/plugins/marketplaces/token-keeper`
- 별도 dev clone 이 있다면 거기서 작업하는 게 안전 (Claude Code 가 marketplace 를 refresh 할 때 install cache 가 덮어씌워질 수 있음).
