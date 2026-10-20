"""Contrato HTTP autenticado de DACTE para clientes internos."""

import json

from fastapi.testclient import TestClient

from mcp_fiscal_brasil.api import app
from tests.dfe_amostras import cte

client = TestClient(app)
KEY = "a" * 40


def test_dacte_endpoint_rejeita_chamada_sem_credencial(monkeypatch):
    monkeypatch.setenv("FISCAL_SHARED_CLIENT_KEYS", json.dumps({"tms": KEY}))
    response = client.post("/v1/documentos/cte/dacte.pdf", json={"xml": cte(com_protocolo=True)})
    assert response.status_code == 401


def test_dacte_endpoint_retorna_pdf_autorizado(monkeypatch):
    monkeypatch.setenv("FISCAL_SHARED_CLIENT_KEYS", json.dumps({"tms": KEY}))
    response = client.post(
        "/v1/documentos/cte/dacte.pdf",
        json={"xml": cte(com_protocolo=True)},
        headers={"X-Fiscal-Service-Key": KEY},
    )
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-")
    assert response.headers["content-type"].startswith("application/pdf")


def test_dacte_endpoint_recusa_cte_sem_protocolo(monkeypatch):
    monkeypatch.setenv("FISCAL_SHARED_CLIENT_KEYS", json.dumps({"tms": KEY}))
    response = client.post(
        "/v1/documentos/cte/dacte.pdf",
        json={"xml": cte(com_protocolo=False)},
        headers={"X-Fiscal-Service-Key": KEY},
    )
    assert response.status_code == 422
