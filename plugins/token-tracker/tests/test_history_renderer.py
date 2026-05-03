from __future__ import annotations
import json


def test_render_empty_data_includes_empty_message():
    from lib.history_renderer import render_history_html
    html = render_history_html(current=[], all_sessions=[], lang="ko")
    assert "데이터 없음" in html


def test_render_inlines_data_current_and_data_all():
    from lib.history_renderer import render_history_html
    sample = [{"prompt_id": "p_1", "session_id": "s",
               "user_prompt": {"text": "hi", "ts": 1.0},
               "started_at": 1.0, "ended_at": 2.0,
               "summary": {"total_cost": 0.01, "total_input_tokens": 1,
                           "total_output_tokens": 1, "cache_hit_rate": 0.0,
                           "total_elapsed": 1.0, "turns": []},
               "models_used": ["claude-opus-4-7"],
               "has_subagent_other_model": False,
               "transcript_entries": []}]
    html = render_history_html(current=sample, all_sessions=sample, lang="ko")
    assert html.count('id="data-current"') == 1
    assert html.count('id="data-all"') == 1
    assert html.count('"p_1"') >= 2


def test_render_escapes_script_tag_in_user_prompt():
    """JSON inlined in <script> must not break out via </script>."""
    from lib.history_renderer import render_history_html
    payload = [{"prompt_id": "p", "session_id": "s",
                "user_prompt": {"text": "</script><script>alert(1)</script>", "ts": 1.0},
                "started_at": 1.0, "ended_at": 2.0,
                "summary": {"total_cost": 0, "total_input_tokens": 0,
                            "total_output_tokens": 0, "cache_hit_rate": 0,
                            "total_elapsed": 0, "turns": []},
                "models_used": [], "has_subagent_other_model": False,
                "transcript_entries": []}]
    html = render_history_html(current=payload, all_sessions=[], lang="ko")
    assert "</script><script>alert(1)</script>" not in html


def test_render_uses_lang_attr():
    from lib.history_renderer import render_history_html
    html = render_history_html(current=[], all_sessions=[], lang="en")
    assert 'lang="en"' in html
    html_ko = render_history_html(current=[], all_sessions=[], lang="ko")
    assert 'lang="ko"' in html_ko
