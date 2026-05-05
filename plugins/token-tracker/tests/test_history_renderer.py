from __future__ import annotations
import json


def _entry(**overrides):
    base = {
        "prompt_id": "p_1",
        "session_id": "1f4c5def-abc",
        "user_prompt": {"text": "hi", "ts": 1.0},
        "started_at": 1.0,
        "ended_at": 2.0,
        "summary": {
            "total_cost": 0.01,
            "total_input_tokens": 100,
            "total_output_tokens": 20,
            "cache_hit_rate": 0.85,
            "total_elapsed": 1.5,
            "turns": [],
        },
        "models_used": ["claude-opus-4-7"],
        "has_subagent_other_model": False,
        "transcript_entries": [],
    }
    base.update(overrides)
    return base


def test_render_empty_data_includes_empty_message():
    from lib.history_renderer import render_history_html
    html = render_history_html(current=[], all_sessions=[], lang="ko")
    assert "데이터 없음" in html


def test_render_inlines_data_current_and_data_all():
    from lib.history_renderer import render_history_html
    html = render_history_html(current=[_entry()], all_sessions=[_entry()], lang="ko")
    assert html.count('id="data-current"') == 1
    assert html.count('id="data-all"') == 1
    assert html.count('"p_1"') >= 2


def test_render_escapes_script_tag_in_user_prompt():
    """JSON inlined in <script> must not break out via </script>."""
    from lib.history_renderer import render_history_html
    payload = [_entry(user_prompt={"text": "</script><script>alert(1)</script>", "ts": 1.0})]
    html = render_history_html(current=payload, all_sessions=[], lang="ko")
    assert "</script><script>alert(1)</script>" not in html


def test_render_uses_lang_attr():
    from lib.history_renderer import render_history_html
    html = render_history_html(current=[], all_sessions=[], lang="en")
    assert 'lang="en"' in html
    html_ko = render_history_html(current=[], all_sessions=[], lang="ko")
    assert 'lang="ko"' in html_ko


def test_render_escapes_script_data_double_escaped_breakout():
    """`<!--<script>...</script><script>` triggers HTML5 script-data-double-escaped
    state where normal `</` escape is neutralized. Verify `<!--` is also escaped."""
    from lib.history_renderer import render_history_html
    payload = [_entry(user_prompt={"text": "<!--<script>alert(1)</script><script>", "ts": 1.0})]
    html = render_history_html(current=payload, all_sessions=[], lang="ko")
    assert "<!--<script>" not in html


def _extract_inline_payload(html: str, script_id: str) -> str:
    """Pull the textContent of <script id="..."> from rendered HTML."""
    import re
    m = re.search(
        rf'<script[^>]*id="{re.escape(script_id)}"[^>]*>(.*?)</script>',
        html, re.DOTALL,
    )
    assert m, f"no <script id={script_id!r}> in html"
    return m.group(1)


def test_inline_payload_is_valid_json_with_html_comment():
    """Regression: data containing `<!--` must yield JSON.parse-able payload.
    Earlier `<\\!--` escape produced invalid JSON `\\!` and broke the page."""
    from lib.history_renderer import render_history_html
    payload = [_entry(user_prompt={"text": "before <!-- mid --> after", "ts": 1.0})]
    html = render_history_html(current=payload, all_sessions=payload, lang="ko")
    for sid in ("data-current", "data-all"):
        body = _extract_inline_payload(html, sid)
        decoded = json.loads(body)
        assert decoded[0]["prompt"] == "before <!-- mid --> after"


def test_inline_payload_safe_against_placeholder_collision():
    """Regression: data containing a literal placeholder token (e.g.
    `__DATA_ALL__`) must not be re-substituted into the previous payload."""
    from lib.history_renderer import render_history_html
    poison = "lib/history_renderer.py:90:        \"__DATA_ALL__\": _safe_json_for_script(all_sessions)"
    payload = [_entry(prompt_id="p", user_prompt={"text": poison, "ts": 1.0})]
    other = [_entry(prompt_id="q", session_id="s2", user_prompt={"text": "other", "ts": 1.0})]
    html = render_history_html(current=payload, all_sessions=other, lang="ko")
    body = _extract_inline_payload(html, "data-current")
    decoded = json.loads(body)
    assert decoded[0]["prompt"] == poison


def test_inline_payload_is_valid_json_with_script_close():
    """`</script>` in data must not break inline payload — JSON.parse-able."""
    from lib.history_renderer import render_history_html
    payload = [_entry(user_prompt={"text": "x </script><script>y", "ts": 1.0})]
    html = render_history_html(current=payload, all_sessions=[], lang="ko")
    body = _extract_inline_payload(html, "data-current")
    decoded = json.loads(body)
    assert decoded[0]["prompt"] == "x </script><script>y"


def test_flatten_entry_maps_to_design_schema():
    from lib.history_renderer import _flatten_entry
    f = _flatten_entry(_entry(prompt_id="p_X", session_id="abcdef12-rest"))
    assert f["n"] == "p_X"
    assert f["prompt"] == "hi"
    assert f["model"] == "opus 4.7"
    assert f["session"] == "abcdef12"
    assert f["cost"] == 0.01
    assert f["in"] == 100
    assert f["out"] == 20
    assert f["cache"] == 0.85
    assert f["elapsed"] == 1.5
    assert "timeLabel" in f and isinstance(f["timeLabel"], str)
    assert isinstance(f["time"], float)


def test_flatten_entry_handles_empty_models():
    from lib.history_renderer import _flatten_entry
    f = _flatten_entry(_entry(models_used=[]))
    assert f["model"] == ""


def test_build_turn_cards_basic_mapping_and_grouping():
    """Each turn N owns transcript entries in [turn[N].started_at,
    turn[N+1].started_at). Verify thinking/assistant/tool_pairs are
    routed correctly and turn-level token/cost fields populated."""
    from lib.history_renderer import _build_turn_cards
    summary = {
        "turns": [
            {
                "model": "claude-opus-4-7", "started_at": 100.0,
                "input_tokens": 5, "output_tokens": 50,
                "cache_creation_5m_tokens": 0, "cache_creation_1h_tokens": 200,
                "cache_read_tokens": 1000,
                "tools_used": [{"name": "Read", "count": 1}],
            },
            {
                "model": "claude-opus-4-7", "started_at": 110.0,
                "input_tokens": 3, "output_tokens": 30,
                "cache_creation_5m_tokens": 0, "cache_creation_1h_tokens": 0,
                "cache_read_tokens": 500,
                "tools_used": [],
            },
        ]
    }
    transcript = [
        {"type": "thinking", "ts": 100.5, "text": "T1 thought"},
        {"type": "tool_call", "ts": 100.7, "id": "tu_a", "name": "Read", "input": {"path": "/x"}},
        {"type": "tool_result", "ts": 100.9, "tool_use_id": "tu_a", "content": "ok", "is_error": False},
        {"type": "assistant_text", "ts": 110.5, "text": "done"},
    ]
    cards = _build_turn_cards(summary, transcript, ended_at=115.0)
    assert len(cards) == 2
    c1, c2 = cards
    assert c1["n"] == 1 and c1["model"] == "opus 4.7"
    assert c1["thinking"] == "T1 thought"
    assert c1["tool_pairs"] == [
        {"name": "Read", "input": {"path": "/x"}, "tool_use_id": "tu_a",
         "content": "ok", "is_error": False, "has_result": True}
    ]
    assert c1["assistant_text"] == ""
    assert c1["elapsed"] == 10.0  # 110 - 100
    assert c1["cost"] > 0
    assert c2["n"] == 2
    assert c2["assistant_text"] == "done"
    assert c2["thinking"] == ""
    assert c2["tool_pairs"] == []
    assert c2["elapsed"] == 5.0  # ended_at(115) - started_at(110)


def test_build_turn_cards_empty_when_no_turns():
    from lib.history_renderer import _build_turn_cards
    assert _build_turn_cards({}, [], ended_at=0.0) == []
    assert _build_turn_cards({"turns": []}, [{"type": "thinking", "ts": 1.0, "text": "x"}], ended_at=2.0) == []


def test_build_turn_cards_caps_tool_result_content():
    from lib.history_renderer import _build_turn_cards
    big = "y" * (60 * 1024)
    summary = {"turns": [{"model": "claude-opus-4-7", "started_at": 1.0,
                          "input_tokens": 1, "output_tokens": 1,
                          "cache_creation_5m_tokens": 0, "cache_creation_1h_tokens": 0,
                          "cache_read_tokens": 0, "tools_used": []}]}
    transcript = [
        {"type": "tool_call", "ts": 1.4, "id": "tu_big", "name": "Bash", "input": {}},
        {"type": "tool_result", "ts": 1.5, "tool_use_id": "tu_big", "content": big, "is_error": False},
    ]
    cards = _build_turn_cards(summary, transcript, ended_at=2.0)
    assert len(cards[0]["tool_pairs"][0]["content"]) <= 50 * 1024


def test_build_turn_cards_multi_tool_in_single_turn():
    """한 turn 안의 parallel tool_call/tool_result 가 모두 tool_pairs 에 들어간다
    (v0.8.1 회귀 가드 — 이전엔 첫 1쌍만 emit 됐음)."""
    from lib.history_renderer import _build_turn_cards
    summary = {
        "turns": [
            {
                "model": "claude-opus-4-7", "started_at": 100.0,
                "input_tokens": 5, "output_tokens": 50,
                "cache_creation_5m_tokens": 0, "cache_creation_1h_tokens": 0,
                "cache_read_tokens": 0,
                "tools_used": [
                    {"name": "Bash", "count": 1},
                    {"name": "Read", "count": 1},
                    {"name": "Grep", "count": 1},
                ],
            }
        ]
    }
    transcript = [
        {"type": "tool_call", "ts": 100.1, "id": "tu_1", "name": "Bash", "input": {"command": "ls"}},
        {"type": "tool_call", "ts": 100.2, "id": "tu_2", "name": "Read", "input": {"file_path": "/x"}},
        {"type": "tool_call", "ts": 100.3, "id": "tu_3", "name": "Grep", "input": {"pattern": "foo"}},
        {"type": "tool_result", "ts": 100.4, "tool_use_id": "tu_1", "content": "out1", "is_error": False},
        {"type": "tool_result", "ts": 100.5, "tool_use_id": "tu_3", "content": "out3", "is_error": True},
        # tu_2 의 result 는 누락 (has_result=False 검증)
    ]
    cards = _build_turn_cards(summary, transcript, ended_at=110.0)
    assert len(cards) == 1
    pairs = cards[0]["tool_pairs"]
    assert len(pairs) == 3
    # 순서: tool_call 순서대로 emit
    assert pairs[0] == {"name": "Bash", "input": {"command": "ls"}, "tool_use_id": "tu_1",
                        "content": "out1", "is_error": False, "has_result": True}
    assert pairs[1] == {"name": "Read", "input": {"file_path": "/x"}, "tool_use_id": "tu_2",
                        "content": "", "is_error": False, "has_result": False}
    assert pairs[2] == {"name": "Grep", "input": {"pattern": "foo"}, "tool_use_id": "tu_3",
                        "content": "out3", "is_error": True, "has_result": True}


def test_build_turn_cards_orphan_tool_result_skipped():
    """매칭되는 tool_call 이 없는 tool_result 는 무시된다."""
    from lib.history_renderer import _build_turn_cards
    summary = {"turns": [{"model": "claude-opus-4-7", "started_at": 1.0,
                          "input_tokens": 1, "output_tokens": 1,
                          "cache_creation_5m_tokens": 0, "cache_creation_1h_tokens": 0,
                          "cache_read_tokens": 0, "tools_used": []}]}
    transcript = [
        {"type": "tool_result", "ts": 1.5, "tool_use_id": "tu_orphan", "content": "lost", "is_error": False},
    ]
    cards = _build_turn_cards(summary, transcript, ended_at=2.0)
    assert cards[0]["tool_pairs"] == []


def test_build_turn_cards_no_tools_emits_empty_pairs():
    """도구 호출 없는 turn 은 tool_pairs 가 빈 list."""
    from lib.history_renderer import _build_turn_cards
    summary = {"turns": [{"model": "claude-opus-4-7", "started_at": 1.0,
                          "input_tokens": 1, "output_tokens": 1,
                          "cache_creation_5m_tokens": 0, "cache_creation_1h_tokens": 0,
                          "cache_read_tokens": 0, "tools_used": []}]}
    transcript = [{"type": "assistant_text", "ts": 1.5, "text": "no tools used"}]
    cards = _build_turn_cards(summary, transcript, ended_at=2.0)
    assert cards[0]["tool_pairs"] == []


def test_flatten_entry_includes_turns_array():
    from lib.history_renderer import _flatten_entry
    summary = {
        "total_cost": 0.05, "total_input_tokens": 10, "total_output_tokens": 5,
        "cache_hit_rate": 0.9, "total_elapsed": 5.0,
        "turns": [{"model": "claude-opus-4-7", "started_at": 1.0,
                   "input_tokens": 1, "output_tokens": 1,
                   "cache_creation_5m_tokens": 0, "cache_creation_1h_tokens": 0,
                   "cache_read_tokens": 0, "tools_used": []}],
    }
    f = _flatten_entry(_entry(summary=summary))
    assert isinstance(f["turns"], list)
    assert len(f["turns"]) == 1
    assert f["turns"][0]["n"] == 1


def test_render_includes_meta_block_with_version():
    from lib.history_renderer import render_history_html
    html = render_history_html(current=[], all_sessions=[], lang="ko")
    assert 'id="meta"' in html
    body = _extract_inline_payload(html, "meta")
    decoded = json.loads(body)
    assert "ts" in decoded and "ver" in decoded
