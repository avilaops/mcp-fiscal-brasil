"""Contrato de autenticação da API de documentos compartilhada."""

import pytest
from fastapi import HTTPException
from mcp_fiscal_brasil.api import _authorized_consumer


def test_shared_api_requires_configuration(monkeypatch):
    monkeypatch.delenv("FISCAL_SHARED_CLIENT_KEYS", raising=False)
    with pytest.raises(HTTPException) as error:
        _authorized_consumer("some-secret")
    assert error.value.status_code == 401


def test_shared_api_restricts_service_names_and_secret_length(monkeypatch):
    monkeypatch.setenv("FISCAL_SHARED_CLIENT_KEYS", '{"tms":"short","admin":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","erp":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}')
    for token in ("short", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"):
        with pytest.raises(HTTPException) as error:
            _authorized_consumer(token)
        assert error.value.status_code == 401
    assert _authorized_consumer("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb") == "erp"


def test_shared_api_rejects_invalid_json(monkeypatch):
    monkeypatch.setenv("FISCAL_SHARED_CLIENT_KEYS", "invalid")
    with pytest.raises(HTTPException):
        _authorized_consumer("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
