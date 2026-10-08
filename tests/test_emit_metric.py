"""Lab 4 — emit_metric contract. No network: urlopen is replaced."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest import mock

import pytest

from cloudlayer.azure import AzureAdapter

CONN = "InstrumentationKey=test-key;IngestionEndpoint=https://ingest.example/"


class _Resp:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _adapter() -> AzureAdapter:
    adapter = AzureAdapter.__new__(AzureAdapter)  # skip the constructor; only cfg.tags is used
    adapter.cfg = SimpleNamespace(tags=lambda lab: {"course": "itcs355", "lab": str(lab)})
    return adapter


def test_emit_metric_sends_the_expected_envelope(monkeypatch):
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", CONN)
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data)
        return _Resp(b'{"itemsReceived":1,"itemsAccepted":1,"errors":[]}')

    with mock.patch("urllib.request.urlopen", fake_urlopen):
        _adapter().emit_metric("drift.psi.temp_c", 0.31)

    assert captured["url"] == "https://ingest.example/v2/track"
    assert captured["body"]["iKey"] == "test-key"
    base = captured["body"]["data"]["baseData"]
    assert base["metrics"] == [{"name": "drift.psi.temp_c", "value": 0.31}]


def test_emit_metric_raises_when_the_service_rejects_the_item(monkeypatch):
    """A drift score that silently fails to arrive is worse than a crash."""
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", CONN)
    rejected = _Resp(b'{"itemsReceived":1,"itemsAccepted":0,"errors":[{"message":"bad"}]}')
    with mock.patch("urllib.request.urlopen", lambda request, timeout: rejected):
        with pytest.raises(RuntimeError, match="not accepted"):
            _adapter().emit_metric("drift.psi.temp_c", 0.31)


def test_emit_metric_requires_the_connection_string(monkeypatch):
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    with pytest.raises(RuntimeError, match="APPLICATIONINSIGHTS_CONNECTION_STRING"):
        _adapter().emit_metric("drift.psi.temp_c", 0.31)
