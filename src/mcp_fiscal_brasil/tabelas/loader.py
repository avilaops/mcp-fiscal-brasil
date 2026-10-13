"""
Loader de tabelas fiscais estáticas para o módulo tabelas.

Estratégia de armazenamento:
  - CFOP, CST/CSOSN, alíquotas ICMS: dicionários em memória (pequenos e estáveis).
  - NCM e CEST: SQLite bundled em data/tabelas_fiscais.db (tabelas grandes).

O banco traz as tabelas oficiais inteiras: a NCM do Siscomex, a alíquota de IPI da
TIPI e o CEST do Convênio ICMS 142/18 (anexos II a XXVI, redação vigente). A fonte e
a data de cada uma ficam na tabela `fontes`. Para atualizar, baixe as publicações e
rode scripts/atualizar_tabelas_oficiais.py (as fontes estão no cabeçalho dele).
"""

from __future__ import annotations

import importlib.resources
import json
import sqlite3
from pathlib import Path
from typing import Any

from mcp_fiscal_brasil._core import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# CFOP - Código Fiscal de Operações e Prestações (Convênio SINIEF s/n, 1970)
# Tabela completa com os grupos principais. Formato: código -> (descrição, tipo, aplicação)
# tipo: "entrada" | "saida"
# aplicacao: "estadual" | "interestadual" | "exterior"
# ---------------------------------------------------------------------------

# Tabela oficial de CFOP (Portal Nacional da NF-e), gerada por
# scripts/atualizar_tabelas_oficiais.py. Ate 10/10/2026 esta tabela era escrita
# a mao e tinha descricoes trocadas (6107 e 6108 entre elas).
_CFOP_OFICIAL: dict[str, Any] = json.loads(
    (Path(__file__).parent / "data" / "cfop_oficial.json").read_text(encoding="utf-8")
)

_TIPO_POR_GRUPO = {
    "1": "entrada",
    "2": "entrada",
    "3": "entrada",
    "5": "saida",
    "6": "saida",
    "7": "saida",
}
_APLICACAO_POR_GRUPO = {
    "1": "estadual", "5": "estadual",
    "2": "interestadual", "6": "interestadual",
    "3": "exterior", "7": "exterior",
}  # fmt: skip

# codigo -> (titulo, tipo, aplicacao), no formato que o resto do modulo ja usava.
CFOP_TABLE: dict[str, tuple[str, str, str]] = {
    codigo: (dado["titulo"], _TIPO_POR_GRUPO[codigo[0]], _APLICACAO_POR_GRUPO[codigo[0]])
    for codigo, dado in _CFOP_OFICIAL["codigos"].items()
}

# ---------------------------------------------------------------------------
# CST - Código de Situação Tributária
# ---------------------------------------------------------------------------

# CST ICMS - regime normal (Lucro Real/Presumido): código = origem (1 dígito) + tributação (2 dígitos)
CST_ICMS_NORMAL: dict[str, str] = {
    "000": "Nacional - Tributada integralmente",
    "010": "Nacional - Tributada e com cobrança do ICMS por substituição tributária",
    "020": "Nacional - Com redução de base de cálculo",
    "030": "Nacional - Isenta ou não tributada e com cobrança do ICMS por substituição tributária",
    "040": "Nacional - Isenta",
    "041": "Nacional - Não tributada",
    "050": "Nacional - Suspensão",
    "051": "Nacional - Diferimento",
    "060": "Nacional - ICMS cobrado anteriormente por substituição tributária",
    "070": "Nacional - Com redução da base de cálculo e cobrança do ICMS por ST",
    "090": "Nacional - Outras",
    "100": "Estrangeira (importação direta) - Tributada integralmente",
    "110": "Estrangeira (importação direta) - Tributada e com cobrança do ICMS por ST",
    "120": "Estrangeira (importação direta) - Com redução de base de cálculo",
    "130": "Estrangeira (importação direta) - Isenta ou não tributada e com cobrança do ICMS por ST",
    "140": "Estrangeira (importação direta) - Isenta",
    "141": "Estrangeira (importação direta) - Não tributada",
    "150": "Estrangeira (importação direta) - Suspensão",
    "151": "Estrangeira (importação direta) - Diferimento",
    "160": "Estrangeira (importação direta) - ICMS cobrado anteriormente por ST",
    "170": "Estrangeira (importação direta) - Com redução da BC e cobrança do ICMS por ST",
    "190": "Estrangeira (importação direta) - Outras",
    "200": "Estrangeira (mercado interno) - Tributada integralmente",
    "210": "Estrangeira (mercado interno) - Tributada e com cobrança do ICMS por ST",
    "220": "Estrangeira (mercado interno) - Com redução de base de cálculo",
    "230": "Estrangeira (mercado interno) - Isenta ou não tributada e com cobrança do ICMS por ST",
    "240": "Estrangeira (mercado interno) - Isenta",
    "241": "Estrangeira (mercado interno) - Não tributada",
    "250": "Estrangeira (mercado interno) - Suspensão",
    "251": "Estrangeira (mercado interno) - Diferimento",
    "260": "Estrangeira (mercado interno) - ICMS cobrado anteriormente por ST",
    "270": "Estrangeira (mercado interno) - Com redução da BC e cobrança do ICMS por ST",
    "290": "Estrangeira (mercado interno) - Outras",
    "300": "Nacional com > 40% de conteúdo de importação - Tributada integralmente",
    "310": "Nacional com > 40% de conteúdo de importação - Tributada e com cobrança do ICMS por ST",
    "320": "Nacional com > 40% de conteúdo de importação - Com redução de base de cálculo",
    "330": "Nacional com > 40% de conteúdo de importação - Isenta ou não tributada com cobrança do ICMS por ST",
    "340": "Nacional com > 40% de conteúdo de importação - Isenta",
    "341": "Nacional com > 40% de conteúdo de importação - Não tributada",
    "350": "Nacional com > 40% de conteúdo de importação - Suspensão",
    "351": "Nacional com > 40% de conteúdo de importação - Diferimento",
    "360": "Nacional com > 40% de conteúdo de importação - ICMS cobrado anteriormente por ST",
    "370": "Nacional com > 40% de conteúdo de importação - Com redução da BC e cobrança do ICMS por ST",
    "390": "Nacional com > 40% de conteúdo de importação - Outras",
    "400": "Nacional com processo produtivo básico - Tributada integralmente",
    "410": "Nacional com processo produtivo básico - Tributada e com cobrança do ICMS por ST",
    "420": "Nacional com processo produtivo básico - Com redução de base de cálculo",
    "430": "Nacional com processo produtivo básico - Isenta ou não tributada com cobrança do ICMS por ST",
    "440": "Nacional com processo produtivo básico - Isenta",
    "441": "Nacional com processo produtivo básico - Não tributada",
    "450": "Nacional com processo produtivo básico - Suspensão",
    "451": "Nacional com processo produtivo básico - Diferimento",
    "460": "Nacional com processo produtivo básico - ICMS cobrado anteriormente por ST",
    "470": "Nacional com processo produtivo básico - Com redução da BC e cobrança do ICMS por ST",
    "490": "Nacional com processo produtivo básico - Outras",
    "500": "Nacional com < 40% de conteúdo de importação - Tributada integralmente",
    "510": "Nacional com < 40% de conteúdo de importação - Tributada e com cobrança do ICMS por ST",
    "520": "Nacional com < 40% de conteúdo de importação - Com redução de base de cálculo",
    "530": "Nacional com < 40% de conteúdo de importação - Isenta ou não tributada com cobrança do ICMS por ST",
    "540": "Nacional com < 40% de conteúdo de importação - Isenta",
    "541": "Nacional com < 40% de conteúdo de importação - Não tributada",
    "550": "Nacional com < 40% de conteúdo de importação - Suspensão",
    "551": "Nacional com < 40% de conteúdo de importação - Diferimento",
    "560": "Nacional com < 40% de conteúdo de importação - ICMS cobrado anteriormente por ST",
    "570": "Nacional com < 40% de conteúdo de importação - Com redução da BC e cobrança do ICMS por ST",
    "590": "Nacional com < 40% de conteúdo de importação - Outras",
    "600": "Estrangeira (importação direta) sem similar nacional - Tributada integralmente",
    "610": "Estrangeira (importação direta) sem similar nacional - Tributada e com cobrança do ICMS por ST",
    "620": "Estrangeira (importação direta) sem similar nacional - Com redução de base de cálculo",
    "630": "Estrangeira (importação direta) sem similar nacional - Isenta ou não tributada com cobrança do ICMS por ST",
    "640": "Estrangeira (importação direta) sem similar nacional - Isenta",
    "641": "Estrangeira (importação direta) sem similar nacional - Não tributada",
    "650": "Estrangeira (importação direta) sem similar nacional - Suspensão",
    "651": "Estrangeira (importação direta) sem similar nacional - Diferimento",
    "660": "Estrangeira (importação direta) sem similar nacional - ICMS cobrado anteriormente por ST",
    "670": "Estrangeira (importação direta) sem similar nacional - Com redução da BC e cobrança do ICMS por ST",
    "690": "Estrangeira (importação direta) sem similar nacional - Outras",
    "700": "Estrangeira (mercado interno) sem similar nacional - Tributada integralmente",
    "710": "Estrangeira (mercado interno) sem similar nacional - Tributada e com cobrança do ICMS por ST",
    "720": "Estrangeira (mercado interno) sem similar nacional - Com redução de base de cálculo",
    "730": "Estrangeira (mercado interno) sem similar nacional - Isenta ou não tributada com cobrança do ICMS por ST",
    "740": "Estrangeira (mercado interno) sem similar nacional - Isenta",
    "741": "Estrangeira (mercado interno) sem similar nacional - Não tributada",
    "750": "Estrangeira (mercado interno) sem similar nacional - Suspensão",
    "751": "Estrangeira (mercado interno) sem similar nacional - Diferimento",
    "760": "Estrangeira (mercado interno) sem similar nacional - ICMS cobrado anteriormente por ST",
    "770": "Estrangeira (mercado interno) sem similar nacional - Com redução da BC e cobrança do ICMS por ST",
    "790": "Estrangeira (mercado interno) sem similar nacional - Outras",
    "800": "Nacional com > 70% de conteúdo de importação - Tributada integralmente",
    "810": "Nacional com > 70% de conteúdo de importação - Tributada e com cobrança do ICMS por ST",
    "820": "Nacional com > 70% de conteúdo de importação - Com redução de base de cálculo",
    "830": "Nacional com > 70% de conteúdo de importação - Isenta ou não tributada com cobrança do ICMS por ST",
    "840": "Nacional com > 70% de conteúdo de importação - Isenta",
    "841": "Nacional com > 70% de conteúdo de importação - Não tributada",
    "850": "Nacional com > 70% de conteúdo de importação - Suspensão",
    "851": "Nacional com > 70% de conteúdo de importação - Diferimento",
    "860": "Nacional com > 70% de conteúdo de importação - ICMS cobrado anteriormente por ST",
    "870": "Nacional com > 70% de conteúdo de importação - Com redução da BC e cobrança do ICMS por ST",
    "890": "Nacional com > 70% de conteúdo de importação - Outras",
}

# CSOSN - Código de Situação da Operação no Simples Nacional (Resolução CGSN 94/2011)
CSOSN_TABLE: dict[str, str] = {
    "101": "Tributada pelo Simples Nacional com permissão de crédito",
    "102": "Tributada pelo Simples Nacional sem permissão de crédito",
    "103": "Isenção do ICMS no Simples Nacional para faixa de receita bruta",
    "201": "Tributada pelo Simples Nacional com permissão de crédito e com cobrança do ICMS por ST",
    "202": "Tributada pelo Simples Nacional sem permissão de crédito e com cobrança do ICMS por ST",
    "203": "Isenção do ICMS no Simples Nacional para faixa de receita bruta e com cobrança do ICMS por ST",
    "300": "Imune",
    "400": "Não tributada pelo Simples Nacional",
    "500": "ICMS cobrado anteriormente por ST ou por antecipação",
    "900": "Outros",
}

# CST PIS/COFINS (IN SRF 247/2002, Tabela 4.3.3 e 4.3.4 do SPED)
CST_PIS_COFINS: dict[str, str] = {
    "01": "Operação tributável - base de cálculo = valor da operação (alíquota normal)",
    "02": "Operação tributável - base de cálculo = valor da operação (alíquota diferenciada)",
    "03": "Operação tributável - base de cálculo = quantidade vendida x alíquota por unidade",
    "04": "Operação tributável - tributação monofásica (alíquota zero para o revendedor)",
    "05": "Operação tributável - substituição tributária",
    "06": "Operação tributável - alíquota zero",
    "07": "Operação isenta da contribuição",
    "08": "Operação sem incidência da contribuição",
    "09": "Operação com suspensão da contribuição",
    "49": "Outras operações de saída",
    "50": "Operação com direito a crédito - vinculada exclusivamente a receita tributada no mercado interno",
    "51": "Operação com direito a crédito - vinculada exclusivamente a receita não tributada no mercado interno",
    "52": "Operação com direito a crédito - vinculada exclusivamente a receita de exportação",
    "53": "Operação com direito a crédito - vinculada a receitas tributadas e não tributadas no mercado interno",
    "54": "Operação com direito a crédito - vinculada a receitas tributadas no mercado interno e de exportação",
    "55": "Operação com direito a crédito - vinculada a receitas não tributadas no mercado interno e de exportação",
    "56": "Operação com direito a crédito - vinculada a receitas tributadas e não tributadas e de exportação",
    "60": "Crédito presumido - operação de aquisição vinculada exclusivamente a receita tributada no mercado interno",
    "61": "Crédito presumido - operação de aquisição vinculada exclusivamente a receita não tributada no mercado interno",
    "62": "Crédito presumido - operação de aquisição vinculada exclusivamente a receita de exportação",
    "63": "Crédito presumido - operação de aquisição vinculada a receitas tributadas e não tributadas no mercado interno",
    "64": "Crédito presumido - operação de aquisição vinculada a receitas tributadas no mercado interno e de exportação",
    "65": "Crédito presumido - operação de aquisição vinculada a receitas não tributadas no mercado interno e de exportação",
    "66": "Crédito presumido - operação de aquisição vinculada a receitas tributadas e não tributadas e de exportação",
    "67": "Crédito presumido - outras operações",
    "70": "Operação de aquisição sem direito a crédito",
    "71": "Operação de aquisição com isenção",
    "72": "Operação de aquisição com suspensão",
    "73": "Operação de aquisição com alíquota zero",
    "74": "Operação de aquisição sem incidência da contribuição",
    "75": "Operação de aquisição por ST",
    "98": "Outras operações de entrada",
    "99": "Outras operações",
}

# CST IPI (Tabela Anexo à IN SRF 422/2004)
CST_IPI_ENTRADA: dict[str, str] = {
    "00": "Entrada com recuperação de crédito",
    "01": "Entrada tributada com alíquota zero",
    "02": "Entrada isenta",
    "03": "Entrada não tributada",
    "04": "Entrada imune",
    "05": "Entrada com suspensão",
    "49": "Outras entradas",
}

CST_IPI_SAIDA: dict[str, str] = {
    "50": "Saída tributada",
    "51": "Saída tributável com alíquota zero",
    "52": "Saída isenta",
    "53": "Saída não tributada",
    "54": "Saída imune",
    "55": "Saída com suspensão",
    "99": "Outras saídas",
}

# ---------------------------------------------------------------------------
# ICMS - Alíquotas interestaduais e internas (EC 87/2015, Resolução do Senado Federal nº 22/1989)
# ---------------------------------------------------------------------------

# Alíquotas internas do ICMS por UF (valores predominantes para cálculo do DIFAL)
# Fonte: legislação estadual compilada (CONFAZ/SEFAZ estaduais) - atualizado em 2026-06-21
# AVISO: alíquotas internas podem variar por produto/operação; estes são os valores
# gerais de referência (alíquota geral, sem FECP). Consultar o RICMS estadual vigente
# ou contador para produto/operação específicos.
#
# Alterações recentes incorporadas:
#   AC: 17% -> 19% (RICMS/AC art. 17, inc. I - vigente em 2025)
#   AL: 19% -> 20,5% (Lei AL 9776/2025, vigência 01/04/2026)
#   BA: 19,5% -> 20,5% (legislação estadual BA, vigente em 2025)
#   MA: 22% -> 23% (Lei MA 12.426/2024, vigência 23/02/2025)
#   PI: 21% -> 22,5% (Lei PI 8.558/2024, vigência 01/04/2025)
#   RS: 17,5% -> 17% (RICMS/RS art. 27, inc. X - taxa geral vigente em 2026)
ICMS_ALIQUOTA_INTERNA: dict[str, float] = {
    "AC": 19.0,  # RICMS/AC art. 17, inc. I
    "AL": 20.5,  # Lei AL 9776/2025, vigência 01/04/2026
    "AM": 20.0,
    "AP": 18.0,
    "BA": 20.5,  # legislação estadual BA 2025
    "CE": 20.0,
    "DF": 20.0,
    "ES": 17.0,
    "GO": 19.0,
    "MA": 23.0,  # Lei MA 12.426/2024, vigência 23/02/2025
    "MT": 17.0,
    "MS": 17.0,
    "MG": 18.0,  # RICMS/MG subitem 7.1 Parte 1 Anexo I
    "PA": 19.0,
    "PB": 20.0,
    "PR": 19.5,
    "PE": 20.5,
    "PI": 22.5,  # Lei PI 8.558/2024, vigência 01/04/2025
    "RJ": 22.0,  # 20% + 2% FECP (LC RJ 210/2023, vigência 20/03/2024)
    "RN": 20.0,
    "RS": 17.0,  # RICMS/RS art. 27, inc. X
    "RO": 19.5,
    "RR": 20.0,
    "SC": 17.0,
    "SP": 18.0,  # RICMS/SP art. 52, inc. I (Decreto 45.490/2000)
    "SE": 19.0,  # RICMS/SE art. 40, inc. I (+ 1% FECP totaliza 20%)
    "TO": 20.0,
}

# Sul e Sudeste, EXCETO ES: únicos estados que praticam a alíquota reduzida de 7%
# como origem (Resolução do Senado Federal nº 22/1989)
_UFS_ORIGEM_ALIQUOTA_REDUZIDA = {"SP", "RJ", "MG", "PR", "RS", "SC"}

# Destinos que recebem 7% quando a origem é uma das UFs acima:
# Norte, Nordeste, Centro-Oeste e Espírito Santo
_UFS_DESTINO_ALIQUOTA_REDUZIDA = {
    "AC",
    "AL",
    "AM",
    "AP",
    "BA",
    "CE",
    "DF",
    "ES",
    "GO",
    "MA",
    "MT",
    "MS",
    "PA",
    "PB",
    "PE",
    "PI",
    "RN",
    "RO",
    "RR",
    "SE",
    "TO",
}


def _calcular_aliquota_interestadual(uf_origem: str, uf_destino: str) -> float:
    """
    Calcula a alíquota interestadual do ICMS conforme Resolução do Senado Federal nº 22/1989.

    Regra:
    - 4%: operações com bens importados (Resolução SF nº 13/2012) - NÃO tratado aqui.
    - 7%: quando a origem é Sul ou Sudeste EXCETO ES (SP, RJ, MG, PR, RS, SC)
          E o destino é Norte, Nordeste, Centro-Oeste ou ES.
    - 12%: todos os demais casos, incluindo:
           - origem em N/NE/CO ou ES (ex.: ES->SP, BA->SP, AM->SP);
           - operações dentro do bloco Sul/Sudeste (ex.: SP->RJ, SP->MG, RS->SP).
    """
    if uf_origem in _UFS_ORIGEM_ALIQUOTA_REDUZIDA and uf_destino in _UFS_DESTINO_ALIQUOTA_REDUZIDA:
        return 7.0
    return 12.0


# ---------------------------------------------------------------------------
# NCM/CEST - SQLite bundled
# ---------------------------------------------------------------------------

_DB_PATH: Path | None = None
_DB_CONN: sqlite3.Connection | None = None


def _get_db_path() -> Path:
    """Retorna o caminho do banco SQLite bundled."""
    global _DB_PATH
    if _DB_PATH is None:
        try:
            # Tenta localizar via importlib.resources (instalado como pacote)
            ref = importlib.resources.files("mcp_fiscal_brasil.tabelas.data").joinpath(
                "tabelas_fiscais.db"
            )
            _DB_PATH = Path(str(ref))
        except (TypeError, FileNotFoundError):
            # Fallback: caminho relativo ao módulo (desenvolvimento local)
            _DB_PATH = Path(__file__).parent / "data" / "tabelas_fiscais.db"
    return _DB_PATH


def _get_conn() -> sqlite3.Connection | None:
    """Retorna a conexão SQLite, inicializando se necessário. Retorna None se DB não existir."""
    global _DB_CONN
    if _DB_CONN is not None:
        return _DB_CONN

    db_path = _get_db_path()
    if not db_path.exists():
        logger.warning(
            "tabelas_db_not_found",
            path=str(db_path),
            hint="O banco vem no pacote (tabelas/data); scripts/atualizar_tabelas_oficiais.py o atualiza.",
        )
        return None

    _DB_CONN = sqlite3.connect(str(db_path), check_same_thread=False)
    _DB_CONN.row_factory = sqlite3.Row
    logger.info("tabelas_db_connected", path=str(db_path))
    return _DB_CONN


# ---------------------------------------------------------------------------
# Funções públicas de consulta
# ---------------------------------------------------------------------------


def buscar_cfop(codigo: str) -> dict[str, Any] | None:
    """Retorna dados do CFOP ou None se não encontrado."""
    codigo_limpo = codigo.strip().lstrip("0")
    # Normaliza: CFOP pode vir como "5102" ou "5.102"
    codigo_norm = codigo.replace(".", "").strip()
    dado = CFOP_TABLE.get(codigo_norm)
    if dado is None:
        # Tenta com zero à esquerda removido e recomposto
        dado = CFOP_TABLE.get(codigo_limpo.zfill(4))
    if dado is None:
        return None
    descricao, tipo, aplicacao = dado
    grupo = codigo_norm[0] if codigo_norm else ""
    oficial = (
        _CFOP_OFICIAL["codigos"].get(codigo_norm) or _CFOP_OFICIAL["codigos"][codigo_limpo.zfill(4)]
    )
    return {
        "codigo": codigo_norm,
        "descricao": descricao,
        "tipo": tipo,
        "aplicacao": aplicacao,
        "grupo": grupo,
        "nota_explicativa": oficial["nota"] or None,
        "vigencia_inicio": oficial["inicio"],
        "vigencia_fim": oficial["fim"],
        "indicadores": oficial["indicadores"],
        "fonte": f"{_CFOP_OFICIAL['fonte']}, {_CFOP_OFICIAL['referencia']}",
    }


def validar_cst(cst: str, regime: str) -> dict[str, Any]:
    """
    Valida um código CST ou CSOSN conforme o regime tributário.

    Args:
        cst: Código CST/CSOSN a validar.
        regime: 'normal' (Lucro Real/Presumido) ou 'simples' (Simples Nacional).

    Returns:
        Dicionário com valido, descricao, regime e tabela.
    """
    cst_upper = cst.strip().upper()
    regime_lower = regime.strip().lower()

    if regime_lower == "simples":
        # CSOSN para Simples Nacional
        desc = CSOSN_TABLE.get(cst_upper)
        if desc:
            return {
                "cst": cst_upper,
                "valido": True,
                "descricao": desc,
                "regime": "simples",
                "tabela": "CSOSN",
            }
        # Tenta PIS/COFINS e IPI (também usados no Simples para documentos específicos)
        for tabela, dados in [
            ("CST_PIS_COFINS", CST_PIS_COFINS),
            ("CST_IPI_ENTRADA", CST_IPI_ENTRADA),
            ("CST_IPI_SAIDA", CST_IPI_SAIDA),
        ]:
            if cst_upper in dados:
                return {
                    "cst": cst_upper,
                    "valido": True,
                    "descricao": dados[cst_upper],
                    "regime": "simples",
                    "tabela": tabela,
                }
        return {
            "cst": cst_upper,
            "valido": False,
            "descricao": None,
            "regime": "simples",
            "tabela": None,
        }

    # Regime normal: Lucro Real, Presumido, Arbitrado
    # CST ICMS (3 dígitos)
    if len(cst_upper) == 3:
        desc = CST_ICMS_NORMAL.get(cst_upper)
        if desc:
            return {
                "cst": cst_upper,
                "valido": True,
                "descricao": desc,
                "regime": "normal",
                "tabela": "CST_ICMS",
            }
    # CST PIS/COFINS (2 dígitos)
    if len(cst_upper) == 2:
        desc = CST_PIS_COFINS.get(cst_upper)
        if desc:
            return {
                "cst": cst_upper,
                "valido": True,
                "descricao": desc,
                "regime": "normal",
                "tabela": "CST_PIS_COFINS",
            }
        desc_e = CST_IPI_ENTRADA.get(cst_upper)
        if desc_e:
            return {
                "cst": cst_upper,
                "valido": True,
                "descricao": desc_e,
                "regime": "normal",
                "tabela": "CST_IPI_ENTRADA",
            }
        desc_s = CST_IPI_SAIDA.get(cst_upper)
        if desc_s:
            return {
                "cst": cst_upper,
                "valido": True,
                "descricao": desc_s,
                "regime": "normal",
                "tabela": "CST_IPI_SAIDA",
            }

    return {
        "cst": cst_upper,
        "valido": False,
        "descricao": None,
        "regime": regime_lower,
        "tabela": None,
    }


def buscar_aliquota_icms(uf_origem: str, uf_destino: str) -> dict[str, Any] | None:
    """Retorna as alíquotas ICMS para uma operação interestadual ou intraestadual.

    Para operações interestaduais (UF origem != UF destino), retorna a alíquota
    interestadual (7% ou 12%) e o DIFAL conforme EC 87/2015.

    Para operações intraestaduais (UF origem == UF destino), retorna a alíquota
    interna da UF com alíquota_interestadual == alíquota interna e diferencial == 0.

    Retorna None se alguma UF for inválida.
    """
    uf_o = uf_origem.strip().upper()
    uf_d = uf_destino.strip().upper()

    aliq_interna_d = ICMS_ALIQUOTA_INTERNA.get(uf_d)
    aliq_interna_o = ICMS_ALIQUOTA_INTERNA.get(uf_o)

    if aliq_interna_d is None or aliq_interna_o is None:
        return None

    # Operação intraestadual: usa a alíquota interna da UF, DIFAL = 0
    if uf_o == uf_d:
        return {
            "uf_origem": uf_o,
            "uf_destino": uf_d,
            "aliquota_interestadual": aliq_interna_o,
            "aliquota_interna_destino": aliq_interna_d,
            "diferencial_aliquota": 0.0,
            "fundamento": "Operação intraestadual - aplica-se a alíquota interna da UF",
        }

    aliq_inter = _calcular_aliquota_interestadual(uf_o, uf_d)
    difal = round(aliq_interna_d - aliq_inter, 4)

    fundamento = (
        "Res. Senado Federal nº 22/1989 (alíquotas interestaduais 7%/12%) + EC 87/2015 (DIFAL)"
    )
    if aliq_inter == 4.0:
        fundamento = "Resolução SF 13/2012 (4% para bens importados) + EC 87/2015 (DIFAL)"

    return {
        "uf_origem": uf_o,
        "uf_destino": uf_d,
        "aliquota_interestadual": aliq_inter,
        "aliquota_interna_destino": aliq_interna_d,
        "diferencial_aliquota": difal,
        "fundamento": fundamento,
    }


def buscar_ncm(codigo: str) -> dict[str, Any] | None:
    """
    Busca um NCM no banco SQLite bundled.

    Retorna None se o banco não existir ou o código não for encontrado.
    """
    conn = _get_conn()
    if conn is None:
        return None
    codigo_limpo = codigo.replace(".", "").replace("-", "").strip()
    row = conn.execute(
        "SELECT codigo, descricao, aliquota_ipi, ipi_nt, unidade_tributavel, ex_tipi, hierarquia FROM ncm WHERE codigo = ?",
        (codigo_limpo,),
    ).fetchone()
    if row is None:
        return None
    dado = dict(row)
    dado["ipi_nao_tributado"] = bool(dado.pop("ipi_nt"))
    # As exceções (EX) da TIPI: o mesmo código com outra alíquota para um produto descrito.
    dado["excecoes_tipi"] = [
        {
            "ex": ex["ex"],
            "descricao": ex["descricao"],
            "aliquota_ipi": ex["aliquota_ipi"],
            "ipi_nao_tributado": bool(ex["ipi_nt"]),
        }
        for ex in conn.execute(
            "SELECT ex, descricao, aliquota_ipi, ipi_nt FROM tipi_ex WHERE ncm = ? ORDER BY ex",
            (codigo_limpo,),
        )
    ]
    fontes = {
        linha["tabela"]: f"{linha['fonte']} ({linha['referencia']})"
        for linha in conn.execute("SELECT tabela, fonte, referencia FROM fontes")
    }
    dado["fonte"] = fontes.get("ncm")
    dado["fonte_ipi"] = fontes.get("tipi")
    return dado


def buscar_cest(codigo: str) -> dict[str, Any] | None:
    """
    Busca um CEST no banco SQLite bundled.

    Retorna None se o banco não existir ou o código não for encontrado.
    """
    conn = _get_conn()
    if conn is None:
        return None
    codigo_limpo = codigo.replace(".", "").strip()
    row = conn.execute(
        "SELECT cest, descricao, segmento, segmento_nome, anexo, anexo_titulo, item, ncm_sh "
        "FROM cest WHERE cest = ?",
        (codigo_limpo,),
    ).fetchone()
    if row is None:
        return None
    # Os códigos da coluna NCM/SH, só com dígitos e do tamanho que o convênio escreveu:
    # capítulo (2), posição (4), subposição ou o código inteiro (8).
    ncm_rows = conn.execute(
        "SELECT ncm FROM cest_ncm WHERE cest = ? ORDER BY ordem",
        (codigo_limpo,),
    ).fetchall()
    ncm_relacionados = [r["ncm"] for r in ncm_rows]
    resultado = dict(row)
    resultado["ncm_relacionados"] = ncm_relacionados
    resultado["fonte"] = fonte_da_tabela("cest")
    return resultado


def fonte_da_tabela(tabela: str) -> str | None:
    """De onde veio e de quando é uma tabela do banco ('ncm', 'tipi', 'cest')."""
    conn = _get_conn()
    if conn is None:
        return None
    linha = conn.execute(
        "SELECT fonte, referencia FROM fontes WHERE tabela = ?", (tabela,)
    ).fetchone()
    return f"{linha['fonte']} ({linha['referencia']})" if linha else None
