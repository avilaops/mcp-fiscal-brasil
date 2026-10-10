"""Validacao de XML de NF-e, CT-e e MDF-e contra os esquemas oficiais (XSD).

Tres conferencias, nesta ordem:

1. O documento contra o XSD do seu tipo (o que a SEFAZ rejeita como "Falha no
   schema XML", cStat 215/225).
2. As partes que o leiaute principal deixa em aberto (`xs:any` com
   `processContents="skip"`): o modal dentro de `infModal` e o detalhe do
   evento dentro de `detEvento`. A SEFAZ valida essas partes com o XSD proprio
   de cada uma, entao um documento pode passar no XSD principal e ser rejeitado.
3. A chave de acesso do atributo `Id` contra os campos do proprio XML (UF, mes
   de emissao, emitente, modelo, serie, numero, tipo de emissao, codigo e
   digito verificador).

Os esquemas ficam em `esquemas/`, copiados dos pacotes de liberacao oficiais
listados em `PACOTES`. Trocar de pacote e trocar os arquivos e a entrada la.

O que isto NAO faz: aplicar as regras de validacao de negocio dos manuais
(situacao cadastral, duplicidade, datas, calculo de imposto) nem conferir a
assinatura. Passar aqui nao garante autorizacao.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from lxml import etree

from .._core.errors import FiscalValidationError
from ..shared.xml_utils import parse_xml
from .chave import MODELOS, calcular_dv, ler_chave

_ESQUEMAS = Path(__file__).parent / "esquemas"

LIMITE_DE_ERROS = 50
LIMITE_DO_XML_BYTES = 5 * 1024 * 1024

NS_DSIG = "http://www.w3.org/2000/09/xmldsig#"

# De onde veio cada conjunto de esquemas. Quem recebe o resultado precisa saber
# contra qual pacote o XML foi conferido: o grupo de IBS/CBS (reforma
# tributaria) e o CNPJ alfanumerico mudam de pacote para pacote.
PACOTES: dict[str, dict[str, Any]] = {
    "nfe": {
        "pacote": "PL_010f",
        "publicado_em": "2026-08-31",
        "notas_tecnicas": ["NT 2025.002 v1.50", "NT 2026.007 v1.00"],
        "fonte": "https://www.nfe.fazenda.gov.br/portal (Documentos > Esquemas XML)",
        "complementos": [
            "procNFe, inutNFe e consSitNFe do Pacote de Liberacao 9 (leiaute 4.00, sem mudanca desde entao)",
            "Evento de cancelamento v1.00 (atualizado em 21/12/2018)",
            "Carta de correcao v1.00 (PL Evento CCe v1.01, 30/05/2014)",
            "Eventos da NT 2025.002 v1.40 - RTC (publicado em 27/07/2026)",
        ],
    },
    "cte": {
        "pacote": "PL_CTe_400_NT2026.004 RTC_1.00",
        "publicado_em": "2026-10-02",
        "notas_tecnicas": ["NT 2026.004 RTC v1.00"],
        "fonte": "https://dfe-portal.svrs.rs.gov.br/CTE/Documentos",
        "complementos": [],
    },
    "mdfe": {
        "pacote": "PL_MDFe_300b_NT012025_1.05",
        "publicado_em": "2026-04-25",
        "notas_tecnicas": ["NT 2025.001 v1.04"],
        "fonte": "https://dfe-portal.svrs.rs.gov.br/Mdfe/Documentos",
        "complementos": [],
    },
}

_NAMESPACES = {
    "http://www.portalfiscal.inf.br/nfe": "nfe",
    "http://www.portalfiscal.inf.br/cte": "cte",
    "http://www.portalfiscal.inf.br/mdfe": "mdfe",
}

# Elemento raiz -> arquivo XSD, por tipo de documento.
_RAIZES: dict[str, dict[str, str]] = {
    "nfe": {
        "NFe": "nfe_v4.00.xsd",
        "nfeProc": "procNFe_v4.00.xsd",
        "inutNFe": "inutNFe_v4.00.xsd",
        "consSitNFe": "consSitNFe_v4.00.xsd",
    },
    "cte": {
        "CTe": "cte_v4.00.xsd",
        "cteProc": "procCTe_v4.00.xsd",
        "CTeSimp": "cteSimp_v4.00.xsd",
        "cteSimpProc": "procCTeSimp_v4.00.xsd",
        "CTeOS": "cteOS_v4.00.xsd",
        "cteOSProc": "procCTeOS_v4.00.xsd",
        "GTVe": "GTVe_v4.00.xsd",
        "eventoCTe": "eventoCTe_v4.00.xsd",
        "procEventoCTe": "procEventoCTe_v4.00.xsd",
        "consSitCTe": "consSitCTe_v4.00.xsd",
        "consStatServCTe": "consStatServCTe_v4.00.xsd",
    },
    "mdfe": {
        "MDFe": "mdfe_v3.00.xsd",
        "mdfeProc": "procMDFe_v3.00.xsd",
        "enviMDFe": "enviMDFe_v3.00.xsd",
        "eventoMDFe": "eventoMDFe_v3.00.xsd",
        "procEventoMDFe": "procEventoMDFe_v3.00.xsd",
        "consSitMDFe": "consSitMDFe_v3.00.xsd",
        "consStatServMDFe": "consStatServMDFe_v3.00.xsd",
        "consMDFeNaoEnc": "consMDFeNaoEnc_v3.00.xsd",
        "consReciMDFe": "consReciMDFe_v3.00.xsd",
    },
}

# Eventos da NF-e com envelope proprio no pacote: tpEvento -> (pasta, raiz -> arquivo).
_EVENTOS_NFE: dict[str, tuple[str, dict[str, str]]] = {
    "110111": (
        "evento-cancelamento",
        {
            "envEvento": "envEventoCancNFe_v1.00.xsd",
            "evento": "eventoCancNFe_v1.00.xsd",
            "procEventoNFe": "procEventoCancNFe_v1.00.xsd",
        },
    ),
    "110110": (
        "evento-cce",
        {
            "envEvento": "envCCe_v1.00.xsd",
            "evento": "CCe_v1.00.xsd",
            "procEventoNFe": "procCCeNFe_v1.00.xsd",
        },
    ),
}

# Filho de infModal -> arquivo XSD do modal.
_MODAIS: dict[str, dict[str, str]] = {
    "cte": {
        "rodo": "cteModalRodoviario_v4.00.xsd",
        "rodoOS": "cteModalRodoviarioOS_v4.00.xsd",
        "aereo": "cteModalAereo_v4.00.xsd",
        "aquav": "cteModalAquaviario_v4.00.xsd",
        "ferrov": "cteModalFerroviario_v4.00.xsd",
        "duto": "cteModalDutoviario_v4.00.xsd",
        "multimodal": "cteMultiModal_v4.00.xsd",
    },
    "mdfe": {
        "rodo": "mdfeModalRodoviario_v3.00.xsd",
        "aereo": "mdfeModalAereo_v3.00.xsd",
        "aquav": "mdfeModalAquaviario_v3.00.xsd",
        "ferrov": "mdfeModalFerroviario_v3.00.xsd",
    },
}

_VERSAO_DO_DETALHE = {"cte": "4.00", "mdfe": "3.00"}

# Onde esta a chave e de que campos ela e feita, por tipo de documento.
_CAMPOS_DA_CHAVE: dict[str, dict[str, str]] = {
    "nfe": {"inf": "infNFe", "prefixo": "NFe", "numero": "nNF", "codigo": "cNF"},
    "cte": {"inf": "infCte", "prefixo": "CTe", "numero": "nCT", "codigo": "cCT"},
    "mdfe": {"inf": "infMDFe", "prefixo": "MDFe", "numero": "nMDF", "codigo": "cMDF"},
}


class XmlFiscalInvalidoError(FiscalValidationError):
    """O conteudo recebido nao pode nem ser conferido (vazio, grande demais, de outro tipo)."""

    def __init__(self, reason: str) -> None:
        super().__init__(message=reason, field="xml_content", value="<xml>")


def recusar_doctype(raiz: etree._Element) -> None:
    """Documento fiscal nao tem DOCTYPE. Com ele vem entidade declarada no proprio
    XML, que a SEFAZ recusa e que derruba a validacao de esquema da libxml."""
    if raiz.getroottree().docinfo.doctype:
        raise XmlFiscalInvalidoError("XML com DOCTYPE nao e aceito em documento fiscal.")


def _local(elemento: etree._Element) -> str:
    return str(etree.QName(elemento).localname)


@lru_cache(maxsize=64)
def _esquema(caminho_relativo: str) -> etree.XMLSchema:
    """Compila um XSD do pacote. Os `include` sao resolvidos pela pasta do arquivo."""
    return etree.XMLSchema(etree.parse(str(_ESQUEMAS / caminho_relativo)))


def _sem_namespace(texto: str) -> str:
    return re.sub(r"\{[^}]*\}", "", texto)


def _erros_do_esquema(
    esquema: etree.XMLSchema, alvo: etree._Element, origem: str
) -> list[dict[str, Any]]:
    try:
        if esquema.validate(alvo):
            return []
    except etree.XMLSchemaValidateError as exc:
        raise XmlFiscalInvalidoError(
            f"O XML nao pode ser conferido contra o esquema: {exc}"
        ) from exc
    erros: list[dict[str, Any]] = []
    for entrada in esquema.error_log:
        campo = re.search(r"Element '(?:\{[^}]*\})?([^']+)'", entrada.message)
        erros.append(
            {
                "linha": entrada.line,
                "coluna": entrada.column,
                "campo": campo.group(1) if campo else None,
                "mensagem": _sem_namespace(entrada.message),
                "origem": origem,
            }
        )
    return erros


def _texto(pai: etree._Element | None, ns: str, nome: str) -> str | None:
    if pai is None:
        return None
    filho = pai.find(f"{{{ns}}}{nome}")
    return filho.text.strip() if filho is not None and filho.text else None


def _conferir_chave(
    raiz: etree._Element, tipo: str, ns: str
) -> tuple[str | None, list[dict[str, Any]]]:
    """Confere a chave do atributo Id contra os campos do documento."""
    campos = _CAMPOS_DA_CHAVE[tipo]
    inf = raiz if _local(raiz) == campos["inf"] else raiz.find(f".//{{{ns}}}{campos['inf']}")
    if inf is None:
        return None, []
    identificador = inf.get("Id") or ""
    linha = inf.sourceline

    def erro(mensagem: str, campo: str = "Id") -> dict[str, Any]:
        return {
            "linha": linha,
            "coluna": None,
            "campo": campo,
            "mensagem": mensagem,
            "origem": "chave",
        }

    if not identificador.startswith(campos["prefixo"]):
        return None, [
            erro(
                f"O atributo Id precisa comecar com '{campos['prefixo']}' seguido da chave de acesso."
            )
        ]
    partes = ler_chave(identificador[len(campos["prefixo"]) :])
    if partes is None:
        return None, [erro("A chave do atributo Id nao tem o formato de 44 posicoes.")]

    erros: list[dict[str, Any]] = []
    esperado = calcular_dv(partes.chave[:43])
    if esperado != partes.dv:
        erros.append(
            erro(
                f"Digito verificador da chave nao confere: traz {partes.dv}, o calculo da {esperado}."
            )
        )

    ide = inf.find(f"{{{ns}}}ide")
    emit = inf.find(f"{{{ns}}}emit")
    emissao = _texto(ide, ns, "dhEmi") or ""
    documento = _texto(emit, ns, "CNPJ") or _texto(emit, ns, "CPF")
    comparacoes = [
        ("cUF", partes.c_uf, _texto(ide, ns, "cUF"), 2),
        ("dhEmi", partes.ano_mes, emissao[2:4] + emissao[5:7] if len(emissao) >= 7 else None, 4),
        ("emit", partes.documento_emitente, documento, 14),
        ("mod", partes.modelo, _texto(ide, ns, "mod"), 2),
        ("serie", partes.serie, _texto(ide, ns, "serie"), 3),
        (campos["numero"], partes.numero, _texto(ide, ns, campos["numero"]), 9),
        ("tpEmis", partes.tp_emis, _texto(ide, ns, "tpEmis"), 1),
        (campos["codigo"], partes.codigo, _texto(ide, ns, campos["codigo"]), 8),
        ("cDV", partes.dv, _texto(ide, ns, "cDV"), 1),
    ]
    for campo, na_chave, no_xml, largura in comparacoes:
        if no_xml is None:
            continue
        if no_xml.zfill(largura) != na_chave:
            erros.append(
                erro(f"A chave traz {na_chave} e o campo {campo} do XML traz {no_xml}.", campo)
            )
    return partes.chave, erros


def _evento_da_nfe(raiz: etree._Element, ns: str) -> tuple[str | None, str | None, list[str]]:
    """Escolhe o XSD do envelope de evento da NF-e pelo tpEvento."""
    tipo_evento = None
    achado = raiz.find(f".//{{{ns}}}tpEvento")
    if achado is not None and achado.text:
        tipo_evento = achado.text.strip()
    if tipo_evento in _EVENTOS_NFE:
        pasta, raizes = _EVENTOS_NFE[tipo_evento]
        arquivo = raizes.get(_local(raiz))
        return (f"nfe/{pasta}/{arquivo}" if arquivo else None), tipo_evento, []
    return None, tipo_evento, []


def validar_xml_fiscal(xml_content: str | bytes, tipo: str | None = None) -> dict[str, Any]:
    """Confere um XML de NF-e, CT-e ou MDF-e contra os esquemas oficiais.

    Args:
        xml_content: o XML como texto (documento, documento com protocolo,
            evento, inutilizacao ou consulta).
        tipo: opcional, "nfe", "cte" ou "mdfe". Quando informado e o XML for
            de outro tipo, a conferencia e recusada em vez de seguir com o
            esquema errado.

    Returns:
        dict com `valido`, `tipo`, `modelo`, `documento` (elemento raiz),
        `versao` (a declarada no XML), `versao_esquema`, `pacote` (de onde
        vieram os XSD), `esquemas_usados`, `chave_acesso`, `erros` (linha,
        coluna, campo, mensagem, origem) e `avisos`.

    Raises:
        XmlFiscalInvalidoError: conteudo vazio, grande demais ou que nao e um
            documento fiscal conhecido.
        XMLParseError: XML malformado.
    """
    bruto = xml_content.encode("utf-8") if isinstance(xml_content, str) else xml_content
    if not bruto.strip():
        raise XmlFiscalInvalidoError("XML vazio.")
    if len(bruto) > LIMITE_DO_XML_BYTES:
        raise XmlFiscalInvalidoError("XML maior que 5 MB.")

    raiz = parse_xml(bruto)
    recusar_doctype(raiz)
    ns = etree.QName(raiz).namespace or ""
    achado = _NAMESPACES.get(ns)
    if achado is None:
        raise XmlFiscalInvalidoError(
            "O elemento raiz nao esta num namespace de documento fiscal "
            "(http://www.portalfiscal.inf.br/nfe, /cte ou /mdfe)."
        )
    pedido = tipo.strip().lower() if tipo else None
    if pedido and pedido not in PACOTES:
        raise XmlFiscalInvalidoError("tipo precisa ser nfe, cte ou mdfe.")
    if pedido and pedido != achado:
        raise XmlFiscalInvalidoError(
            f"O XML e de {achado}, mas a conferencia pedida foi de {pedido}."
        )

    nome = _local(raiz)
    avisos: list[str] = []
    erros: list[dict[str, Any]] = []
    usados: list[str] = []

    caminho = None
    if nome in _RAIZES[achado]:
        caminho = f"{achado}/{_RAIZES[achado][nome]}"
    elif achado == "nfe" and nome in ("envEvento", "evento", "procEventoNFe"):
        caminho, tipo_evento, _ = _evento_da_nfe(raiz, ns)
        if caminho is None:
            # Eventos da reforma tributaria (e os demais sem envelope no pacote):
            # o pacote traz so o XSD do detEvento, conferido logo abaixo.
            detalhe = _ESQUEMAS / "nfe" / "evento-rtc" / f"e{tipo_evento}_v1.00.xsd"
            if tipo_evento and detalhe.is_file():
                relativo = f"nfe/evento-rtc/{detalhe.name}"
                usados.append(relativo)
                for det in raiz.iter(f"{{{ns}}}detEvento"):
                    erros += _erros_do_esquema(_esquema(relativo), det, "evento")
                avisos.append(
                    "Evento sem envelope proprio no pacote: so o detEvento foi "
                    "conferido; infEvento e a assinatura nao foram."
                )
            else:
                raise XmlFiscalInvalidoError(
                    f"Nao ha esquema neste servico para o evento {tipo_evento or 'sem tpEvento'} da NF-e."
                )
    else:
        raise XmlFiscalInvalidoError(
            f"Nao ha esquema neste servico para o elemento raiz <{nome}> de {achado}."
        )

    if caminho is not None:
        usados.append(caminho)
        erros += _erros_do_esquema(_esquema(caminho), raiz, "esquema")

    # Partes que o leiaute principal nao confere (xs:any).
    if achado in _MODAIS:
        for modal in raiz.iter(f"{{{ns}}}infModal"):
            for filho in modal:
                if not isinstance(filho.tag, str):
                    continue
                arquivo = _MODAIS[achado].get(_local(filho))
                if arquivo is None:
                    erros.append(
                        {
                            "linha": filho.sourceline,
                            "coluna": None,
                            "campo": _local(filho),
                            "mensagem": f"Modal <{_local(filho)}> desconhecido em infModal.",
                            "origem": "modal",
                        }
                    )
                    continue
                relativo = f"{achado}/{arquivo}"
                usados.append(relativo)
                erros += _erros_do_esquema(_esquema(relativo), filho, "modal")
        versao_detalhe = _VERSAO_DO_DETALHE[achado]
        for detalhe in raiz.iter(f"{{{ns}}}detEvento"):
            for filho in detalhe:
                if not isinstance(filho.tag, str):
                    continue
                do_detalhe = _ESQUEMAS / achado / f"{_local(filho)}_v{versao_detalhe}.xsd"
                if not do_detalhe.is_file():
                    avisos.append(
                        f"Detalhe de evento <{_local(filho)}> sem esquema neste servico: nao foi conferido."
                    )
                    continue
                relativo = f"{achado}/{do_detalhe.name}"
                usados.append(relativo)
                erros += _erros_do_esquema(_esquema(relativo), filho, "evento")

    chave, erros_da_chave = _conferir_chave(raiz, achado, ns)
    erros += erros_da_chave

    campos = _CAMPOS_DA_CHAVE[achado]
    inf = raiz if _local(raiz) == campos["inf"] else raiz.find(f".//{{{ns}}}{campos['inf']}")
    modelo = _texto(inf.find(f"{{{ns}}}ide"), ns, "mod") if inf is not None else None
    if modelo is None and chave:
        modelo = chave[20:22]
    if inf is not None and raiz.find(f".//{{{NS_DSIG}}}Signature") is not None:
        avisos.append("A assinatura esta presente, mas nao foi conferida aqui.")

    total = len(erros)
    return {
        "valido": total == 0,
        "tipo": achado,
        "modelo": modelo,
        "nome_do_modelo": MODELOS.get(modelo or ""),
        "documento": nome,
        "versao": raiz.get("versao") or (inf.get("versao") if inf is not None else None),
        "versao_esquema": usados[0].rsplit("_v", 1)[-1].removesuffix(".xsd") if usados else None,
        "pacote": PACOTES[achado],
        "esquemas_usados": list(dict.fromkeys(usados)),
        "chave_acesso": chave,
        "total_de_erros": total,
        "erros": erros[:LIMITE_DE_ERROS],
        "avisos": avisos,
    }
