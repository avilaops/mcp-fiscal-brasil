"""Classificacao tributaria do IBS e da CBS (CST e cClassTrib).

Tabela oficial do Portal Nacional da NF-e, gerada por
scripts/atualizar_tabelas_oficiais.py em data/cclasstrib_oficial.json. Cada
cClassTrib pertence a um CST e so vale em alguns documentos fiscais: e isso que
a SEFAZ confere, e um par errado e rejeicao.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .._core.errors import FiscalValidationError

_TABELA: dict[str, Any] = json.loads(
    (Path(__file__).parent / "data" / "cclasstrib_oficial.json").read_text(encoding="utf-8")
)
_CODIGOS: dict[str, dict[str, Any]] = _TABELA["codigos"]

DOCUMENTOS = ("nfe", "nfce", "cte", "cteos", "bpe", "nf3e", "nfse", "nfcom", "nfag", "nfgas")
LIMITE_DA_LISTA = 60


def _fonte() -> str:
    return f"{_TABELA['fonte']}, {_TABELA['referencia']}"


def _item(codigo: str, dado: dict[str, Any]) -> dict[str, Any]:
    return {
        "cclasstrib": codigo,
        "cst": dado["cst"],
        "descricao_cst": dado["descricao_cst"],
        "nome": dado["nome"],
        "descricao": dado["descricao"],
        "base_legal": dado["base_legal"] or None,
        "tipo_de_aliquota": dado["tipo_de_aliquota"] or None,
        "reducao_ibs": dado["reducao_ibs"],
        "reducao_cbs": dado["reducao_cbs"],
        "grupos_exigidos": dado["grupos"],
        "documentos": dado["documentos"],
        "vigencia_inicio": dado["inicio"],
        "vigencia_fim": dado["fim"],
    }


def consultar_classificacao_tributaria(
    cst: str | None = None,
    cclasstrib: str | None = None,
    documento: str | None = None,
) -> dict[str, Any]:
    """Consulta ou confere a classificacao tributaria do IBS/CBS.

    - Com `cclasstrib`: devolve a classificacao e confere se ela pertence ao
      `cst` informado e se vale no `documento` informado.
    - So com `cst` (e, se quiser, `documento`): lista as classificacoes dele.
    - So com `documento`: lista as que valem naquele documento.
    """
    cst_limpo = (cst or "").strip()
    classe = (cclasstrib or "").strip()
    doc = (documento or "").strip().lower().replace("-", "")
    if doc and doc not in DOCUMENTOS:
        raise FiscalValidationError(
            f"Documento '{documento}' desconhecido. Use um de: {', '.join(DOCUMENTOS)}.",
            field="documento",
            value=documento or "",
        )
    if not cst_limpo and not classe and not doc:
        raise FiscalValidationError(
            "Informe cst, cclasstrib ou documento.", field="cclasstrib", value=""
        )

    if classe:
        dado = _CODIGOS.get(classe)
        if dado is None:
            return {
                "valido": False,
                "motivos": [f"cClassTrib {classe} nao existe na tabela oficial."],
                "fonte": _fonte(),
            }
        motivos: list[str] = []
        if cst_limpo and dado["cst"] != cst_limpo:
            motivos.append(f"O cClassTrib {classe} e do CST {dado['cst']}, nao do CST {cst_limpo}.")
        if doc and doc not in dado["documentos"]:
            motivos.append(
                f"O cClassTrib {classe} nao vale em {doc} (vale em: {', '.join(dado['documentos']) or 'nenhum'})."
            )
        if dado["fim"]:
            motivos.append(f"O cClassTrib {classe} teve a vigencia encerrada em {dado['fim']}.")
        return {"valido": not motivos, "motivos": motivos, **_item(classe, dado), "fonte": _fonte()}

    achados = [
        _item(codigo, dado)
        for codigo, dado in _CODIGOS.items()
        if (not cst_limpo or dado["cst"] == cst_limpo) and (not doc or doc in dado["documentos"])
    ]
    return {
        "total": len(achados),
        "classificacoes": [
            {
                chave: item[chave]
                for chave in (
                    "cclasstrib",
                    "cst",
                    "descricao_cst",
                    "nome",
                    "documentos",
                    "grupos_exigidos",
                )
            }
            for item in achados[:LIMITE_DA_LISTA]
        ],
        "fonte": _fonte(),
    }
