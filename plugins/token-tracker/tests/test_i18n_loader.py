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
    }
    assert set(load_strings("ko").keys()) == expected_keys
    assert set(load_strings("en").keys()) == expected_keys
