import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _disable_unknown_model_pricing_refresh(monkeypatch):
    """compute_cost 의 unknown 모델 즉시 fetch 를 테스트에서 기본 차단.

    안 막으면 unknown 모델을 쓰는 모든 기존 테스트가 실제 네트워크 fetch +
    실제 ~/.claude state 파일 write 를 유발한다. refresh 동작 자체를 검증하는
    테스트는 명시적으로 실제 함수를 다시 setattr 해서 사용.
    """
    from lib import pricing

    monkeypatch.setattr(pricing, "_try_refresh_for_unknown", lambda model: False)
