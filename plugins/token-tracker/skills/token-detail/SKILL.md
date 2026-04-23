---
name: token-detail
description: 직전 request의 turn별 토큰·비용·툴 사용 내역을 표로 출력
disable-model-invocation: true
---

!`python3 ${CLAUDE_SKILL_DIR}/scripts/detail.py "${CLAUDE_SESSION_ID}"`

위 출력 블록을 그대로 사용자에게 전달하세요. 숫자 해석·요약·추가 설명 금지.
