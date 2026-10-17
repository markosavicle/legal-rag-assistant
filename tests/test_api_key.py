from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import main
from app.rag import answer_status


def request(path: str):
    return SimpleNamespace(url=SimpleNamespace(path=path))


@pytest.fixture
def with_key(monkeypatch):
    monkeypatch.setattr(main, "settings", replace(main.settings, api_key="secret"))


def test_no_key_configured_means_open(monkeypatch):
    monkeypatch.setattr(main, "settings", replace(main.settings, api_key=None))
    main.require_api_key(request("/ask"), None)


def test_key_required_when_configured(with_key):
    with pytest.raises(HTTPException) as e:
        main.require_api_key(request("/ask"), None)
    assert e.value.status_code == 401
    with pytest.raises(HTTPException):
        main.require_api_key(request("/documents"), "wrong")
    main.require_api_key(request("/documents"), "secret")


def test_page_and_health_stay_open(with_key):
    main.require_api_key(request("/"), None)
    main.require_api_key(request("/health"), None)


def test_answer_status():
    assert answer_status("Najmanje 20 radnih dana [1].", 5) == (True, [1])
    assert answer_status("Najmanje 20 radnih dana [1][9].", 5) == (True, [1])  # [9] does not exist
    assert answer_status("Najmanje 20 radnih dana.", 5) == (False, [])
    assert answer_status("Ne mogao sam da pronađem odgovor u dokumentima [1][2].", 5)[0] is False
    assert answer_status("Адреса није наведена [1].", 5)[0] is False  # Cyrillic refusal
