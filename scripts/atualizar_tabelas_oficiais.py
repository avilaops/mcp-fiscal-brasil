#!/usr/bin/env python3
"""Atualiza as tabelas de CFOP, NCM, TIPI e CEST a partir das publicacoes oficiais.

Fontes (baixar e passar o caminho; so --cest aceita tambem um endereco):

  --cfop       "Tabela de CFOP" (.xlsx), Portal Nacional da NF-e, Documentos > Diversos.
  --cclasstrib "Tabela de Classificacao Tributaria do IBS e CBS" (.xlsx), mesmo lugar.
  --ncm        Nomenclatura NCM vigente (.json), Portal Unico Siscomex:
               https://portalunico.siscomex.gov.br/classif/api/publico/nomenclatura/download/json
  --ncm-utrib  "Tabela de NCM e respectiva uTrib" (.xlsx), Portal Nacional da NF-e,
               Documentos > Diversos (traz a unidade tributavel de cada NCM).
  --tipi       Tabela de Incidencia do IPI vigente (.xlsx), Receita Federal:
               https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/legislacao/documentos-e-arquivos/tipi.xlsx
  --cest       Convenio ICMS 142/18, texto consolidado (.html), CONFAZ:
               https://www.confaz.fazenda.gov.br/legislacao/convenios/2018/CV142_18
               O CONFAZ nao responde aos servidores da casa (ficam fora do Brasil):
               abra o endereco de uma rede no Brasil, ou por um proxy com saida no
               Brasil, salve a pagina como HTML e passe o caminho. Passar o endereco
               direto so funciona de uma maquina que o CONFAZ atenda.

Saidas:
  src/mcp_fiscal_brasil/tabelas/data/cfop_oficial.json   (a tabela inteira de CFOP)
  src/mcp_fiscal_brasil/tabelas/data/cclasstrib_oficial.json (CST e cClassTrib do IBS/CBS)
  src/mcp_fiscal_brasil/tabelas/data/tabelas_fiscais.db  (tabela `ncm` completada;
                                                          `cest` e `cest_ncm` refeitas)

Na tabela `ncm`, a aliquota de IPI vem da TIPI (--tipi): numero, ou "NT" (nao
tributado, coluna `ipi_nt`). As excecoes (EX) de cada codigo ficam na tabela
`tipi_ex`. Codigo que a TIPI nao traz fica sem aliquota, e a consulta diz isso.

Do convenio (--cest) entram os itens dos anexos II a XXVI na redacao que vale em
--cest-vigencia (padrao: hoje). Item revogado, redacao anterior e redacao que so
comeca a valer depois dessa data ficam de fora: quando um convenio novo entrar em
vigor, rode de novo. O que o script nao souber classificar ele lista e deixa de
fora, em vez de escolher. Uso:

  python scripts/atualizar_tabelas_oficiais.py --cfop cfop.xlsx --ncm ncm.json \\
      --ncm-utrib ncm_utrib.xlsx --referencia-cfop "publicada em 04/09/2026"
  python scripts/atualizar_tabelas_oficiais.py --cest CV142_18.html \\
      --cest-obtido-em 2026-10-13
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, timedelta
from html.parser import HTMLParser
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


def _aliquota(valor: str) -> tuple[float | None, bool]:
    """A coluna de aliquota da TIPI: um percentual, "NT" ou vazia."""
    texto = valor.strip().upper()
    if texto == "NT":
        return None, True
    try:
        return round(float(texto.replace(",", ".")), 4), False
    except ValueError:
        return None, False


def atualizar_tipi(planilha: Path) -> tuple[int, int, str]:
    """Grava a aliquota de IPI de cada NCM e as excecoes (EX), como a TIPI publicada traz."""
    linhas = list(linhas_xlsx(planilha))
    # O cabecalho lista os atos que atualizaram a tabela; o ultimo diz de quando ela e.
    atos = next(
        (linha["A"] for linha in linhas if linha.get("A", "").startswith("Atualiza")), ""
    ).splitlines()
    referencia = (
        f"Decreto nº 11.158/2022, atualizada até: {atos[-1].strip()}"
        if atos
        else "Decreto nº 11.158/2022"
    )

    banco = sqlite3.connect(DADOS / "tabelas_fiscais.db")
    colunas = {linha[1] for linha in banco.execute("PRAGMA table_info(ncm)")}
    if "ipi_nt" not in colunas:
        banco.execute("ALTER TABLE ncm ADD COLUMN ipi_nt INTEGER NOT NULL DEFAULT 0")
    banco.execute("DROP TABLE IF EXISTS tipi_ex")
    banco.execute(
        "CREATE TABLE tipi_ex (ncm TEXT NOT NULL, ex TEXT NOT NULL, descricao TEXT NOT NULL, aliquota_ipi REAL, ipi_nt INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (ncm, ex))"
    )
    banco.execute(
        "CREATE TABLE IF NOT EXISTS fontes (tabela TEXT PRIMARY KEY, fonte TEXT NOT NULL, referencia TEXT NOT NULL)"
    )
    # So a TIPI diz a aliquota: o que havia de amostra sai, para nao sobrar numero sem fonte.
    banco.execute("UPDATE ncm SET aliquota_ipi = NULL, ex_tipi = NULL, ipi_nt = 0")

    codigos = excecoes = 0
    for linha in linhas:
        codigo = linha.get("A", "").strip()
        if not re.fullmatch(r"\d{4}\.\d{2}\.\d{2}", codigo):
            continue
        ncm = codigo.replace(".", "")
        aliquota, nt = _aliquota(linha.get("D", ""))
        if aliquota is None and not nt:
            continue
        ex = re.sub(r"\D", "", linha.get("B", ""))
        if ex:
            banco.execute(
                "INSERT OR REPLACE INTO tipi_ex VALUES (?, ?, ?, ?, ?)",
                (ncm, ex.zfill(2), _limpo(linha.get("C", "")), aliquota, int(nt)),
            )
            excecoes += 1
        else:
            atualizado = banco.execute(
                "UPDATE ncm SET aliquota_ipi = ?, ipi_nt = ? WHERE codigo = ?",
                (aliquota, int(nt), ncm),
            )
            codigos += atualizado.rowcount
    banco.execute(
        "INSERT OR REPLACE INTO fontes VALUES ('tipi', ?, ?)",
        ("Tabela de Incidência do IPI (TIPI), Receita Federal", referencia),
    )
    banco.commit()
    banco.execute("VACUUM")
    banco.close()
    return codigos, excecoes, referencia


ENDERECO_CEST = "https://www.confaz.fazenda.gov.br/legislacao/convenios/2018/CV142_18"
# Os anexos que trazem CEST: do II (autopecas) ao XXVI (venda porta a porta). O I
# lista os segmentos, e o XXVII repete itens dos outros para outra finalidade.
ANEXOS_CEST = (
    "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII", "XIII", "XIV",
    "XV", "XVI", "XVII", "XVIII", "XIX", "XX", "XXI", "XXII", "XXIII", "XXIV", "XXV", "XXVI",
)  # fmt: skip
_CABECALHO_CEST = ["ITEM", "CEST", "NCM/SH", "DESCRIÇÃO"]

Linha = tuple[list[str], bool]  # (celulas, em verde)


class _TextoDoConvenio(HTMLParser):
    """Paragrafos soltos e linhas de tabela do texto consolidado, na ordem em que aparecem."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        # (tipo, textos, em verde), com tipo "p", "tabela", "linha" ou "fim". O CONFAZ
        # pinta de verde (classes "...verde") a redacao que deixou de valer.
        self.eventos: list[tuple[str, list[str], bool]] = []
        self._celulas: list[str] | None = None
        self._texto: list[str] | None = None
        self._em_celula = False
        self._verde = False

    def _fechar_texto(self) -> str:
        texto = re.sub(r"\s+", " ", "".join(self._texto or [])).strip()
        self._texto = None
        return texto

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classe = dict(attrs).get("class") or ""
        if tag == "table":
            self.eventos.append(("tabela", [], False))
        elif tag == "tr":
            self._celulas, self._verde = [], False
        elif tag in ("td", "th") and self._celulas is not None:
            self._texto, self._em_celula = [], True
        elif tag == "p" and self._em_celula and self._texto is not None:
            self._verde = self._verde or "verde" in classe
            self._texto.append(" ")
        elif tag == "p":
            self._texto = []
        elif tag == "br" and self._texto is not None:
            self._texto.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._em_celula and self._celulas is not None:
            self._celulas.append(self._fechar_texto())
            self._em_celula = False
        elif tag == "tr" and self._celulas is not None:
            self.eventos.append(("linha", self._celulas, self._verde))
            self._celulas = None
        elif tag == "p" and not self._em_celula and self._texto is not None:
            self.eventos.append(("p", [self._fechar_texto()], False))
        elif tag == "table":
            self.eventos.append(("fim", [], False))

    def handle_data(self, data: str) -> None:
        if self._texto is not None:
            self._texto.append(data)


def _anexos_do_convenio(html: str) -> tuple[str, dict[str, tuple[str, list[Linha]]]]:
    """O ultimo convenio que alterou o texto e, por anexo, o titulo e as linhas da tabela."""
    leitor = _TextoDoConvenio()
    leitor.feed(html)
    alterado_ate = ""
    anexos: dict[str, tuple[str, list[Linha]]] = {}
    paragrafos: list[str] = []  # desde a ultima tabela
    linhas: list[Linha] | None = None
    for tipo, textos, verde in leitor.eventos:
        if tipo == "p":
            if textos[0].startswith("Alterado pelo") and not alterado_ate:
                alterado_ate = (re.findall(r"\d+/\d\d", textos[0]) or [""])[-1]
            paragrafos.append(textos[0])
        elif tipo == "tabela":
            # A tabela e do ultimo "ANEXO N" antes dela; o titulo vem logo depois dele.
            # Tabela sem anexo antes (as das retificacoes, no fim do texto) nao entra.
            linhas = None
            for posicao, paragrafo in enumerate(paragrafos):
                if re.fullmatch(r"ANEXO [IVXL]+", paragrafo):
                    titulo = " ".join(
                        p for p in paragrafos[posicao + 1 :] if p and not p.startswith("(")
                    )
                    linhas = []
                    anexos[paragrafo.split()[1]] = (titulo, linhas)
            paragrafos = []
        elif tipo == "fim":
            linhas, paragrafos = None, []
        elif linhas is not None:
            celulas = list(textos)
            while celulas and not celulas[-1]:
                celulas.pop()
            if celulas:
                linhas.append((celulas, verde))
    return alterado_ate, anexos


@dataclass
class _Remissao:
    """A linha que explica a seguinte: "Nova redacao dada ao item 3.0 ... a partir de ..."."""

    anterior: bool  # fala de redacao que deixou de valer
    acrescido: bool
    inicio: date | None
    fim: date | None
    itens: set[str]
    usada: bool = False


@dataclass
class _ItemLido:
    celulas: list[str]  # a primeira redacao que aparece: a ultima publicada
    inicio: date | None = None  # preenchido so quando ela ainda nao vale
    acrescido: bool = False
    anterior: list[str] | None = None  # a redacao que vale ate `inicio`
    tem_anterior: bool = False
    duvida: str = ""


@dataclass
class LeituraCest:
    """O que saiu do convenio: os itens que valem e o que ficou de fora, com o motivo."""

    alterado_ate: str = ""
    itens: dict[str, dict[str, str | list[str]]] = field(default_factory=dict)
    por_anexo: dict[str, int] = field(default_factory=dict)
    revogados: list[str] = field(default_factory=list)
    futuros: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    duvidosos: list[str] = field(default_factory=list)


def _data_do_convenio(texto: str, antes: str) -> date | None:
    """A data "DD.MM.AA" que vem depois de `antes` numa remissao."""
    achado = re.search(antes + r"\s*(\d\d)\.(\d\d)\.(\d\d)", texto)
    if achado is None:
        return None
    dia, mes, ano = (int(parte) for parte in achado.groups())
    return date(2000 + ano, mes, dia)


def _item(texto: str) -> str:
    """O numero do item como a tabela o escreve na maioria das linhas: "2" e "2." viram "2.0"."""
    numero = texto.strip().rstrip(".")
    return numero if "." in numero else f"{numero}.0"


def _ler_remissao(anexo: str, texto: str) -> _Remissao:
    nova = re.match(r"Nova reda|Acrescid|Revogad|Redação acrescida", texto)
    if not nova and not re.search(r"Redação (anterior|original|dada)", texto):
        raise SystemExit(f"Anexo {anexo}: remissao que o script nao conhece: {texto!r}")
    citados = re.search(r"ite(?:m|ns)(.*?)(?:d[oa]|ao) Anexo", texto, flags=re.IGNORECASE)
    return _Remissao(
        anterior=not nova,
        acrescido=texto.startswith("Acrescid"),
        inicio=_data_do_convenio(texto, "a partir de"),
        fim=_data_do_convenio(texto, "até"),
        itens={_item(n) for n in re.findall(r"\d+(?:\.\d+)?", citados.group(1))}
        if citados
        else set(),
    )


def _itens_do_anexo(
    anexo: str, linhas: list[Linha], vigencia: date, avisos: list[str]
) -> dict[str, _ItemLido]:
    """Separa, item a item, a redacao publicada por ultimo das anteriores.

    Na tabela a redacao mais nova vem primeiro e as anteriores vem depois, cada
    uma sob uma remissao ("Redacao original, efeitos ate 31.05.21"). Quem decide
    e a remissao; a cor verde das anteriores serve de conferencia.
    """
    lidos: dict[str, _ItemLido] = {}
    remissao: _Remissao | None = None
    for celulas, verde in linhas:
        if len(celulas) == 1 and not celulas[0][0].isdigit():
            remissao = _ler_remissao(anexo, celulas[0])
            continue
        numero = _item(celulas[0])
        if remissao and remissao.anterior and numero in lidos:
            lido = lidos[numero]
            if not verde:
                avisos.append(
                    f"anexo {anexo}, item {numero}: a remissao diz redacao anterior e a linha "
                    f"nao esta em verde; valeu a remissao e ficou {lido.celulas[1:]}"
                )
            if lido.inicio is not None and not lido.tem_anterior:
                # A redacao nova ainda nao vale: vale esta, se a remissao a leva ate la.
                if remissao.fim is not None and remissao.fim >= vigencia:
                    lido.anterior = celulas
                else:
                    lido.duvida = "redacao futura, e a anterior sem data que alcance a vigencia"
            lido.tem_anterior = True
            continue
        if remissao and remissao.anterior:
            remissao = None  # item que ainda nao tinha aparecido: acabaram as anteriores
        if numero in lidos:
            lidos[numero].duvida = "item repetido sem remissao de redacao anterior"
            continue
        lido = _ItemLido(celulas)
        if verde:
            lido.duvida = "linha em verde sem remissao de redacao anterior"
        if remissao and remissao.inicio is not None and remissao.inicio > vigencia:
            if numero in remissao.itens:
                remissao.usada = True
                lido.inicio, lido.acrescido = remissao.inicio, remissao.acrescido
            elif not remissao.usada:
                raise SystemExit(
                    f"Anexo {anexo}, item {numero}: remissao com data futura que nao cita o item"
                )
        lidos[numero] = lido
    return lidos


def _prefixos_ncm(celula: str) -> tuple[list[str], list[str]]:
    """Os codigos da coluna NCM/SH so com digitos, e os pedacos que nao tem forma de codigo.

    A coluna traz posicao (4 digitos), subposicao, item (8) e, no anexo XXVI,
    capitulos ("Capitulos 13 e 15 a 23"). Cada um fica do tamanho que o convenio escreveu.
    """
    if celula.startswith("Capítulo"):
        capitulos: list[str] = []
        for inicio, fim in re.findall(r"(\d+)(?:\s+a\s+(\d+))?", celula):
            capitulos += [f"{n:02d}" for n in range(int(inicio), int(fim or inicio) + 1)]
        return capitulos, []
    codigos, estranhos = [], []
    for pedaco in celula.replace(",", " ").split():
        if re.fullmatch(r"\d{4}(\.\d{1,2}){0,2}", pedaco):
            codigos.append(pedaco.replace(".", ""))
        else:
            estranhos.append(pedaco)
    return list(dict.fromkeys(codigos)), estranhos


def ler_cest(html: str, vigencia: date) -> LeituraCest:
    """Os itens de CEST dos anexos II a XXVI na redacao que vale em `vigencia`."""
    alterado_ate, anexos = _anexos_do_convenio(html)
    leitura = LeituraCest(alterado_ate=alterado_ate)
    segmentos = {c[2]: c[1] for c, _ in anexos.get("I", ("", []))[1] if len(c) == 3}
    for anexo in ANEXOS_CEST:
        titulo, linhas = anexos.get(anexo, ("", []))
        if not linhas or linhas[0][0] != _CABECALHO_CEST:
            raise SystemExit(f"Anexo {anexo}: nao achei a tabela ITEM | CEST | NCM/SH | DESCRICAO")
        leitura.por_anexo[anexo] = 0
        lidos = _itens_do_anexo(anexo, linhas[1:], vigencia, leitura.avisos)
        for numero, lido in lidos.items():
            onde = f"anexo {anexo}, item {numero}"
            celulas = lido.celulas
            if lido.duvida:
                leitura.duvidosos.append(f"{onde}: {lido.duvida}")
                continue
            if lido.inicio is not None:
                if lido.anterior is None:
                    if lido.acrescido:
                        leitura.futuros.append(f"{onde}: entra em {lido.inicio}, fora por ora")
                    else:
                        leitura.duvidosos.append(f"{onde}: muda em {lido.inicio} e falta a atual")
                    continue
                leitura.futuros.append(f"{onde}: muda em {lido.inicio}, ficou a que vale ate la")
                celulas = lido.anterior
            if any(celula.upper() == "REVOGADO" for celula in celulas):
                leitura.revogados.append(onde)
                continue
            if len(celulas) != 4 or not re.fullmatch(r"\d{2}\.\d{3}\.\d{2}", celulas[1]):
                leitura.duvidosos.append(f"{onde}: linha fora do formato: {celulas}")
                continue
            codigo = celulas[1].replace(".", "")
            if codigo in leitura.itens:
                leitura.duvidosos.append(f"{onde}: CEST {celulas[1]} ja apareceu em outro item")
                continue
            if codigo[:2] not in segmentos:
                leitura.duvidosos.append(f"{onde}: segmento {codigo[:2]} fora do anexo I")
                continue
            prefixos, estranhos = _prefixos_ncm(celulas[2])
            if estranhos:
                leitura.avisos.append(
                    f"{onde} (CEST {celulas[1]}): NCM/SH com codigo fora do formato, "
                    f"mantido so no texto da coluna: {estranhos}"
                )
            leitura.itens[codigo] = {
                "item": numero,
                "descricao": celulas[3],
                "ncm_sh": celulas[2],
                "ncm": prefixos,
                "segmento_nome": segmentos[codigo[:2]],
                "anexo": anexo,
                "anexo_titulo": titulo,
            }
            leitura.por_anexo[anexo] += 1
    leitura.itens = dict(sorted(leitura.itens.items()))
    return leitura


def atualizar_cest(origem: str, vigencia: date, obtido_em: str) -> tuple[LeituraCest, int, str]:
    """Refaz as tabelas `cest` e `cest_ncm` com o texto do Convenio ICMS 142/18."""
    if origem.startswith("https://"):
        pedido = urllib.request.Request(origem, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(pedido, timeout=60) as resposta:
            conteudo: bytes = resposta.read()
        obtido_em = obtido_em or date.today().isoformat()
    else:
        conteudo = Path(origem).read_bytes()
        obtido_em = obtido_em or date.fromtimestamp(Path(origem).stat().st_mtime).isoformat()
    leitura = ler_cest(conteudo.decode("utf-8"), vigencia)
    referencia = (
        f"anexos II a XXVI, alterado até o Conv. ICMS {leitura.alterado_ate}; "
        f"redação vigente em {vigencia.isoformat()}; texto obtido em {obtido_em}; "
        f"sha256 {hashlib.sha256(conteudo).hexdigest()}"
    )

    banco = sqlite3.connect(DADOS / "tabelas_fiscais.db")
    # As duas tabelas saem e entram inteiras: nao sobra codigo que o convenio nao traga.
    banco.execute("DROP TABLE IF EXISTS cest_ncm")
    banco.execute("DROP TABLE IF EXISTS cest")
    banco.execute(
        "CREATE TABLE cest (cest TEXT PRIMARY KEY, descricao TEXT NOT NULL, segmento TEXT NOT NULL, "
        "segmento_nome TEXT NOT NULL, anexo TEXT NOT NULL, anexo_titulo TEXT NOT NULL, "
        "item TEXT NOT NULL, ncm_sh TEXT NOT NULL)"
    )
    banco.execute(
        "CREATE TABLE cest_ncm (cest TEXT NOT NULL REFERENCES cest(cest), ncm TEXT NOT NULL, "
        "ordem INTEGER NOT NULL, PRIMARY KEY (cest, ncm))"
    )
    banco.execute("CREATE INDEX idx_cest_segmento ON cest(segmento)")
    banco.execute(
        "CREATE TABLE IF NOT EXISTS fontes (tabela TEXT PRIMARY KEY, fonte TEXT NOT NULL, referencia TEXT NOT NULL)"
    )
    ligacoes = 0
    for codigo, dado in leitura.itens.items():
        banco.execute(
            "INSERT INTO cest VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                codigo, dado["descricao"], codigo[:2], dado["segmento_nome"], dado["anexo"],
                dado["anexo_titulo"], dado["item"], dado["ncm_sh"],
            ),
        )  # fmt: skip
        for ordem, ncm in enumerate(dado["ncm"]):
            banco.execute("INSERT INTO cest_ncm VALUES (?, ?, ?)", (codigo, ncm, ordem))
            ligacoes += 1
    banco.execute(
        "INSERT OR REPLACE INTO fontes VALUES ('cest', ?, ?)",
        (f"Convênio ICMS 142/18, texto consolidado do CONFAZ ({ENDERECO_CEST})", referencia),
    )
    banco.commit()
    banco.execute("VACUUM")
    banco.close()
    return leitura, ligacoes, referencia


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
    args.add_argument("--tipi", type=Path)
    args.add_argument("--cest", help="caminho do HTML do Convenio ICMS 142/18, ou o endereco")
    args.add_argument("--cest-vigencia", type=date.fromisoformat, default=date.today())
    args.add_argument("--cest-obtido-em", default="", help="AAAA-MM-DD em que o texto foi obtido")
    opcoes = args.parse_args()
    if opcoes.cfop:
        print(f"CFOP: {gerar_cfop(opcoes.cfop, opcoes.referencia_cfop)} codigos")
    if opcoes.cclasstrib:
        total = gerar_classificacao(opcoes.cclasstrib, opcoes.referencia_cclasstrib)
        print(f"cClassTrib: {total} classificacoes")
    if opcoes.ncm:
        novos, total, referencia = atualizar_ncm(opcoes.ncm, opcoes.ncm_utrib)
        print(f"NCM: {novos} novos, {total} no total ({referencia})")
    if opcoes.tipi:
        codigos, excecoes, referencia = atualizar_tipi(opcoes.tipi)
        print(f"TIPI: {codigos} codigos com aliquota, {excecoes} excecoes ({referencia})")
    if opcoes.cest:
        leitura, ligacoes, referencia = atualizar_cest(
            opcoes.cest, opcoes.cest_vigencia, opcoes.cest_obtido_em
        )
        print(f"CEST: {len(leitura.itens)} itens, {ligacoes} ligacoes com NCM/SH ({referencia})")
        print(f"  por anexo: {leitura.por_anexo}")
        for nome in ("revogados", "futuros", "avisos", "duvidosos"):
            print(f"  {nome}: {len(getattr(leitura, nome))}")
            for linha in getattr(leitura, nome):
                print(f"    {linha}")


if __name__ == "__main__":
    main()
