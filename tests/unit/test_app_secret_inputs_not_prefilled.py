from pathlib import Path


def test_sidebar_secret_inputs_do_not_prefill_saved_credentials() -> None:
    source = (Path(__file__).resolve().parents[2] / "app.py").read_text(encoding="utf-8")

    assert 'value=default_token' not in source
    assert 'value=default_llm_api_key' not in source
    assert 'token = token_input.strip() or default_token' in source
    assert 'llm_api_key = llm_api_key_input.strip() or default_llm_api_key' in source
