#!/usr/bin/env python3
"""Atualiza as tabelas de CFOP e NCM a partir das publicacoes oficiais.

Fontes (baixar e passar o caminho; o script nao acessa a rede):

  --cfop       "Tabela de CFOP" (.xlsx), Portal Nacional da NF-e, Documentos > Diversos.
  --cclasstrib "Tabela de Classificacao Tributaria do IBS e CBS" (.xlsx), mesmo lugar.
  --ncm        Nomenclatura NCM vigente (.json), Portal Unico Siscomex:
               https://portalunico.siscomex.gov.br/classif/api/publico/nomenclatura/download/json
  --ncm-utrib  "Tabela de NCM e respectiva uTrib" (.xlsx), Portal Nacional da NF-e,
               Documentos > Diversos (traz a unidade tributavel de cada NCM).

Saidas:
  src/mcp_fiscal_brasil/tabelas/data/cfop_oficial.json   (a tabela inteira de CFOP)
  src/mcp_fiscal_brasil/tabelas/data/cclasstrib_oficial.json (CST e cClassTrib do IBS/CBS)
  src/mcp_fiscal_brasil/tabelas/data/tabelas_fiscais.db  (tabela `ncm` completada)

Na tabela `ncm`, a aliquota de IPI e o EX das linhas que ja existiam sao
mantidos (vieram da amostra da TIPI); as linhas novas ficam sem aliquota, e a
consulta diz isso. Uso:

  python scripts/atualizar_tabelas_oficiais.py --cfop cfop.xlsx --ncm ncm.json \\
      --ncm-utrib ncm_utrib.xlsx --referencia-cfop "publicada em 04/09/2026"
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

DADOS = Path(__file__).parent.parent / "src" / "mcp_fiscal_brasil" / "tabelas" / "data"
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
TAG_T = f"{{{NS['m']}}}t"
TAG_ROW = f"{{{NS['m']}}}row"


def linhas_xlsx(caminho: Path) -> Iterator[dict[str, str]]:
    """Linhas da primeira planilha de um .xlsx, por letra de coluna (so biblioteca padrao)."""
    with zipfile.ZipFile(caminho) as z:
        textos: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
                textos.append("".join(t.text or "" for t in si.iter(TAG_T)))
        planilha = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    for linha in planilha.iter(TAG_ROW):
        saida: dict[str, str] = {}
        for celula in linha.findall("m:c", NS):
            coluna = re.match(r"[A-Z]+", celula.get("r", ""))
            if coluna is None:
                continue
            valor = celula.find("m:v", NS)
            if valor is None:
                embutido = celula.find("m:is", NS)
                texto = (
                    "".join(t.text or "" for t in embutido.iter(TAG_T))
                    if embutido is not None
                    else ""
                )
            else:
                texto = (
                    textos[int(valor.text or 0)] if celula.get("t") == "s" else (valor.text or "")
                )
            saida[coluna.group(0)] = texto.strip()
        yield saida


def data_do_excel(valor: str) -> str | None:
    """Numero de serie do Excel -> AAAA-MM-DD."""
    if not valor or not valor.replace(".", "").isdigit():
        return None
    return (date(1899, 12, 30) + timedelta(days=int(float(valor)))).isoformat()


def gerar_cfop(planilha: Path, referencia: str) -> int:
    indicadores = {
        "D": "nfe", "E": "comunicacao", "F": "transporte", "G": "devolucao", "H": "retorno",
        "I": "anulacao", "J": "remessa", "K": "combustivel", "L": "exclusao_ibs_cbs",
    }  # fmt: skip
    codigos: dict[str, dict[str, object]] = {}
    for linha in linhas_xlsx(planilha):
        codigo = linha.get("A", "")
        if not re.fullmatch(r"[1-7]\d{3}", codigo):
            continue
        codigos[codigo] = {
            "titulo": linha.get("M", "").rstrip(". ").strip(),
            "nota": linha.get("N", ""),
            "inicio": data_do_excel(linha.get("B", "")),
            "fim": data_do_excel(linha.get("C", "")),
            "indicadores": sorted(
                nome for coluna, nome in indicadores.items() if linha.get(coluna) == "1"
            ),
        }
    saida = {
        "fonte": "Tabela de CFOP, Portal Nacional da NF-e (Documentos > Diversos)",
        "referencia": referencia,
        "arquivo": planilha.name,
        "codigos": dict(sorted(codigos.items())),
    }
    (DADOS / "cfop_oficial.json").write_text(
        json.dumps(saida, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return len(codigos)


def gerar_classificacao(planilha: Path, referencia: str) -> int:
    """Tabela de Classificacao Tributaria do IBS e da CBS (cClassTrib), primeira planilha."""
    documentos = {
        "Z": "nfe", "AA": "nfce", "AB": "cte", "AC": "cteos", "AD": "bpe", "AG": "nf3e",
        "AH": "nfse", "AJ": "nfcom", "AK": "nfag", "AL": "nfgas",
    }  # fmt: skip
    grupos = {
        "M": "gTribRegular", "N": "gCredPresOper", "O": "gMonoPadrao", "P": "gMonoReten",
        "Q": "gMonoRet", "R": "gpBioDiferenca", "S": "gEstornoCred",
    }  # fmt: skip
    codigos: dict[str, dict[str, object]] = {}
    for linha in linhas_xlsx(planilha):
        codigo = linha.get("C", "")
        if not re.fullmatch(r"\d{6}", codigo) or not re.fullmatch(r"\d{3}", linha.get("A", "")):
            continue
        codigos[codigo] = {
            "cst": linha["A"],
            "descricao_cst": linha.get("B", ""),
            "nome": linha.get("D", ""),
            "descricao": linha.get("E", ""),
            "base_legal": linha.get("G", ""),
            "tipo_de_aliquota": linha.get("J", ""),
            "reducao_ibs": float(linha.get("K") or 0),
            "reducao_cbs": float(linha.get("L") or 0),
            "grupos": sorted(nome for coluna, nome in grupos.items() if linha.get(coluna) == "1"),
            "documentos": sorted(
                nome for coluna, nome in documentos.items() if linha.get(coluna) == "1"
            ),
            "inicio": data_do_excel(linha.get("V", "")),
            "fim": data_do_excel(linha.get("W", "")),
        }
    saida = {
        "fonte": "Tabela de Classificacao Tributaria do IBS e CBS, Portal Nacional da NF-e (Documentos > Diversos)",
        "referencia": referencia,
        "arquivo": planilha.name,
        "codigos": dict(sorted(codigos.items())),
    }
    (DADOS / "cclasstrib_oficial.json").write_text(
        json.dumps(saida, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return len(codigos)


def _limpo(texto: str) -> str:
    # A nomenclatura traz marcacao HTML (cm<sup>2</sup>): fica so o texto.
    sem_marcacao = re.sub(r"<[^>]+>", "", texto)
    return re.sub(r"\s+", " ", sem_marcacao.lstrip("- ").strip()).rstrip(".:;")


def atualizar_ncm(nomenclatura: Path, utrib: Path | None) -> tuple[int, int, str]:
    dados = json.loads(nomenclatura.read_text(encoding="utf-8"))
    por_codigo = {
        re.sub(r"\D", "", item["Codigo"]): _limpo(item["Descricao"])
        for item in dados["Nomenclaturas"]
    }
    unidades: dict[str, str] = {}
    if utrib is not None:
        for linha in linhas_xlsx(utrib):
            if re.fullmatch(r"\d{8}", linha.get("A", "")) and linha.get("D") and not linha.get("C"):
                unidades[linha["A"]] = linha["D"]

    referencia = f"{dados.get('Ato', '')}, {dados.get('Data_Ultima_Atualizacao_NCM', '')}".strip(
        ", "
    )
    banco = sqlite3.connect(DADOS / "tabelas_fiscais.db")
    colunas = {linha[1] for linha in banco.execute("PRAGMA table_info(ncm)")}
    if "hierarquia" not in colunas:
        banco.execute("ALTER TABLE ncm ADD COLUMN hierarquia TEXT")
    banco.execute(
        "CREATE TABLE IF NOT EXISTS fontes (tabela TEXT PRIMARY KEY, fonte TEXT NOT NULL, referencia TEXT NOT NULL)"
    )
    existentes = {linha[0] for linha in banco.execute("SELECT codigo FROM ncm")}

    novos = 0
    for codigo, descricao in por_codigo.items():
        if len(codigo) != 8:
            continue
        # Do capitulo ate o item: a descricao do codigo de 8 digitos sozinha
        # ("Outros") nao diz nada sem a posicao a que pertence.
        caminho = []
        for tamanho in (4, 5, 6, 7):
            pai = por_codigo.get(codigo[:tamanho])
            if pai and pai not in caminho and pai != descricao:
                caminho.append(pai)
        hierarquia = " > ".join([*caminho, descricao])
        if codigo in existentes:
            banco.execute(
                "UPDATE ncm SET descricao = ?, hierarquia = ?, unidade_tributavel = COALESCE(?, unidade_tributavel) WHERE codigo = ?",
                (descricao, hierarquia, unidades.get(codigo), codigo),
            )
        else:
            banco.execute(
                "INSERT INTO ncm (codigo, descricao, aliquota_ipi, unidade_tributavel, ex_tipi, hierarquia) VALUES (?, ?, NULL, ?, NULL, ?)",
                (codigo, descricao, unidades.get(codigo), hierarquia),
            )
            novos += 1
    banco.execute(
        "INSERT OR REPLACE INTO fontes VALUES ('ncm', ?, ?)",
        (
            "Nomenclatura NCM, Portal Unico Siscomex; uTrib da Tabela de NCM do Portal Nacional da NF-e",
            referencia,
        ),
    )
    banco.commit()
    total = banco.execute("SELECT COUNT(*) FROM ncm").fetchone()[0]
    banco.execute("VACUUM")
    banco.close()
    return novos, total, referencia


def main() -> None:
    args = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    args.add_argument("--cfop", type=Path)
    args.add_argument("--referencia-cfop", default="")
    args.add_argument("--cclasstrib", type=Path)
    args.add_argument("--referencia-cclasstrib", default="")
    args.add_argument("--ncm", type=Path)
    args.add_argument("--ncm-utrib", type=Path)
    opcoes = args.parse_args()
    if opcoes.cfop:
        print(f"CFOP: {gerar_cfop(opcoes.cfop, opcoes.referencia_cfop)} codigos")
    if opcoes.cclasstrib:
        total = gerar_classificacao(opcoes.cclasstrib, opcoes.referencia_cclasstrib)
        print(f"cClassTrib: {total} classificacoes")
    if opcoes.ncm:
        novos, total, referencia = atualizar_ncm(opcoes.ncm, opcoes.ncm_utrib)
        print(f"NCM: {novos} novos, {total} no total ({referencia})")


if __name__ == "__main__":
    main()
