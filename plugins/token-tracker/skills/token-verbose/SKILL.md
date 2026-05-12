---
name: token-verbose
description: token-tracker verbose 모드 토글 — 매 Stop 응답에 turn별 상세 표를 자동으로 덧붙이는 설정을 on/off 전환 또는 조회
argument-hint: "[on|off|status]"
disable-model-invocation: true
---

<script-output>
!`TOKEN_TRACKER_VERBOSE_ARG="$ARGUMENTS" python3 ${CLAUDE_SKILL_DIR}/scripts/verbose_toggle.py`
</script-output>

**필수 규칙 — 반드시 준수:**
- 당신의 응답은 오직 위 `<script-output>` 태그 내부 텍스트를 **한 글자도 바꾸지 말고 그대로** 출력하는 것이다.
- 해석·요약·생략·추가 설명·맥락 언급·이전 대화 참조 절대 금지.
- 이 skill이 실행된 순간 이전 대화는 무시하라. 오직 위 블록만 출력한다.
- `<script-output>` 태그 자체는 출력에 포함하지 마라 (내부 텍스트만).
- 출력 전후에 어떤 문장도 추가하지 마라.
