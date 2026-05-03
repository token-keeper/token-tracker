from lib.i18n_loader import load_strings


def test_load_ko_has_required_keys():
    s = load_strings("ko")
    assert s["header_title"] == "직전 request 상세"
    assert "col_model" in s
    assert "err_no_state" in s


def test_load_en_has_required_keys():
    s = load_strings("en")
    assert s["header_title"] == "Last request detail"


def test_unknown_language_falls_back_to_en():
    s = load_strings("zz")
    assert s["header_title"] == "Last request detail"


def test_all_expected_keys_present_both_languages():
    expected_keys = {
        "header_title", "header_total",
        "col_index", "col_model", "col_tools",
        "col_input", "col_cc", "col_cr",
        "col_output", "col_cost", "col_time",
        "legend",
        "err_no_state", "err_parse", "err_unsupported_schema", "err_empty_turns",
        "verbose_on", "verbose_off",
        "verbose_status", "verbose_changed", "verbose_no_change",
        "verbose_usage", "verbose_error", "verbose_error_io",
        "subagent_row_prefix", "subagent_legend",
        "html_title", "html_generated_at", "html_version_label",
        "tab_current", "tab_all",
        "col_history_index", "col_history_time", "col_history_prompt",
        "col_history_model", "col_history_cost", "col_history_in",
        "col_history_out", "col_history_cc", "col_history_elapsed",
        "col_history_session",
        "search_placeholder", "filter_model_all", "filter_session_all",
        "expand_user_prompt", "expand_ai_response", "expand_thinking",
        "expand_tool_calls", "expand_show_full", "expand_collapse",
        "total_label", "no_data_message",
        "opened_url",
    }
    assert set(load_strings("ko").keys()) == expected_keys
    assert set(load_strings("en").keys()) == expected_keys


def test_ko_has_history_keys():
    s = load_strings("ko")
    for key in [
        "html_title", "html_generated_at", "html_version_label",
        "tab_current", "tab_all",
        "col_history_index", "col_history_time", "col_history_prompt",
        "col_history_model", "col_history_cost", "col_history_in",
        "col_history_out", "col_history_cc", "col_history_elapsed",
        "col_history_session",
        "search_placeholder", "filter_model_all", "filter_session_all",
        "expand_user_prompt", "expand_ai_response", "expand_thinking",
        "expand_tool_calls", "expand_show_full", "expand_collapse",
        "total_label", "no_data_message",
        "opened_url",
    ]:
        assert key in s, f"missing ko key: {key}"


def test_en_has_history_keys():
    s = load_strings("en")
    for key in [
        "html_title", "tab_current", "tab_all",
        "col_history_prompt", "search_placeholder", "no_data_message",
        "opened_url",
    ]:
        assert key in s
