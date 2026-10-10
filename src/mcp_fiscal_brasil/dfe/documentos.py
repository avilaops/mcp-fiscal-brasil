"""DACTE e DAMDFE em PDF, a partir do XML do CT-e e do MDF-e.

Mesmo contrato do DANFE (`nfe/danfe.py`): entra o XML, sai o PDF em base64 com
a chave, o numero e a serie. O desenho do documento e da biblioteca
brazilfiscalreport, que segue os anexos de DACTE e DAMDFE dos manuais.

Seguranca: o XML passa por parse_xml() (sem entidades externas, sem rede)
antes de chegar a biblioteca, que usa xml.etree sem protecao propria.
"""

from __future__ import annotations

import base64
from collections.abc import Callable

from lxml import etree
from pydantic import BaseModel

from .._core.errors import FiscalValidationError
from ..shared.xml_utils import parse_xml
from .chave import calcular_dv, ler_chave
from .validacao import recusar_doctype

NS_CTE = "http://www.portalfiscal.inf.br/cte"
NS_MDFE = "http://www.portalfiscal.inf.br/mdfe"

LIMITE_DO_XML_BYTES = 5 * 1024 * 1024


class DocumentoAuxiliarError(FiscalValidationError):
    """Erro ao gerar o DACTE ou o DAMDFE."""

    def __init__(self, field: str, value: str, reason: str) -> None:
        super().__init__(message=reason, field=field, value=value)


class DocumentoAuxiliar(BaseModel):
    """PDF do documento auxiliar e os dados do documento fiscal."""

    pdf_base64: str
    """Conteudo do PDF codificado em base64."""

    modelo: int
    """Modelo do documento fiscal: 57 para CT-e, 58 para MDF-e."""

    nome_arquivo: str
    """Nome de arquivo sugerido, com a chave de acesso."""

    chave_acesso: str
    """Chave de acesso de 44 posicoes."""

    numero: str | None = None
    serie: str | None = None

    autorizado: bool
    """Ha protocolo de autorizacao no XML (cStat 100)? Sem ele o PDF nao vale como documento."""


def _gerar(
    xml_content: str | bytes,
    *,
    sigla: str,
    namespace: str,
    elemento_inf: str,
    prefixo_id: str,
    modelo: int,
    campo_numero: str,
    elemento_protocolo: str,
    desenhar: Callable[[str], bytes],
) -> DocumentoAuxiliar:
    bruto = xml_content.encode("utf-8") if isinstance(xml_content, str) else xml_content
    if len(bruto) > LIMITE_DO_XML_BYTES:
        raise DocumentoAuxiliarError("xml", "<xml>", "XML maior que 5 MB.")
    raiz = parse_xml(bruto)
    recusar_doctype(raiz)

    ns = {"d": namespace}
    inf = (
        raiz
        if etree.QName(raiz).localname == elemento_inf
        else raiz.find(f".//d:{elemento_inf}", ns)
    )
    if inf is None:
        raise DocumentoAuxiliarError(
            "xml",
            "<xml>",
            f"XML sem <{elemento_inf}> no namespace {namespace}: nao e um {sigla}.",
        )
    identificador = inf.get("Id") or ""
    partes = (
        ler_chave(identificador[len(prefixo_id) :])
        if identificador.startswith(prefixo_id)
        else None
    )
    if partes is None or calcular_dv(partes.chave[:43]) != partes.dv:
        raise DocumentoAuxiliarError(
            "Id",
            identificador,
            f"O atributo Id de <{elemento_inf}> nao traz uma chave de acesso valida.",
        )
    informado = inf.findtext("d:ide/d:mod", namespaces=ns)
    if (informado or partes.modelo) != str(modelo) or partes.modelo != str(modelo):
        raise DocumentoAuxiliarError(
            "ide/mod", informado or partes.modelo, f"O documento nao e modelo {modelo} ({sigla})."
        )

    situacao = raiz.findtext(f".//d:{elemento_protocolo}/d:infProt/d:cStat", namespaces=ns)

    try:
        pdf = desenhar(bruto.decode("utf-8", errors="replace"))
    except Exception as exc:
        raise DocumentoAuxiliarError(
            "xml", partes.chave, f"Erro ao gerar o PDF do {sigla}: {exc}"
        ) from exc
    if not pdf.startswith(b"%PDF-"):
        raise DocumentoAuxiliarError(
            "xml", partes.chave, f"A geracao do PDF do {sigla} nao devolveu um PDF."
        )

    auxiliar = "DACTE" if modelo == 57 else "DAMDFE"
    return DocumentoAuxiliar(
        pdf_base64=base64.b64encode(pdf).decode("ascii"),
        modelo=modelo,
        nome_arquivo=f"{auxiliar}_{partes.chave}.pdf",
        chave_acesso=partes.chave,
        numero=inf.findtext(f"d:ide/d:{campo_numero}", namespaces=ns),
        serie=inf.findtext("d:ide/d:serie", namespaces=ns),
        autorizado=situacao == "100",
    )


def _xml_para_o_dacte(xml: str) -> tuple[str, bool]:
    """Ajusta o XML so para o desenho do DACTE. Devolve o XML e se ha IBS/CBS.

    A biblioteca escreve no quadro OBSERVACOES apenas o `xTexto` dos grupos
    `ObsCont`/`ObsFisco` e ignora `compl/xObs`, que e onde a observacao do
    emitente vai. Para ela aparecer, a copia entregue ao desenho ganha um
    `ObsCont` com o mesmo texto. O XML do documento nao e tocado: esta copia
    serve so de entrada para o PDF.
    """
    raiz = parse_xml(xml.encode("utf-8"))
    ns = {"d": NS_CTE}
    compl = raiz.find(".//d:infCte/d:compl", ns)
    observacao = compl.findtext("d:xObs", namespaces=ns) if compl is not None else None
    if compl is not None and observacao and observacao.strip():
        extra = etree.SubElement(compl, f"{{{NS_CTE}}}ObsCont", xCampo="OBSERVACAO")
        etree.SubElement(extra, f"{{{NS_CTE}}}xTexto").text = observacao.strip()
    tem_ibs_cbs = raiz.find(".//d:infCte/d:imp/d:IBSCBS", ns) is not None
    return etree.tostring(raiz, encoding="unicode"), tem_ibs_cbs


def _desenhar_dacte(xml: str) -> bytes:
    from brazilfiscalreport.dacte import Dacte, DacteConfig

    ajustado, tem_ibs_cbs = _xml_para_o_dacte(xml)
    # O quadro de IBS/CBS da biblioteca vem desligado por padrao.
    return bytes(Dacte(xml=ajustado, config=DacteConfig(display_ibs_cbs=tem_ibs_cbs)).output())


def _desenhar_damdfe(xml: str) -> bytes:
    from brazilfiscalreport.damdfe import Damdfe

    return bytes(Damdfe(xml=xml).output())


def gerar_dacte(xml_content: str | bytes) -> DocumentoAuxiliar:
    """Gera o DACTE em PDF a partir do XML de um CT-e (modelo 57), com ou sem `cteProc`."""
    return _gerar(
        xml_content,
        sigla="CT-e",
        namespace=NS_CTE,
        elemento_inf="infCte",
        prefixo_id="CTe",
        modelo=57,
        campo_numero="nCT",
        elemento_protocolo="protCTe",
        desenhar=_desenhar_dacte,
    )


def gerar_damdfe(xml_content: str | bytes) -> DocumentoAuxiliar:
    """Gera o DAMDFE em PDF a partir do XML de um MDF-e (modelo 58), com ou sem `mdfeProc`."""
    return _gerar(
        xml_content,
        sigla="MDF-e",
        namespace=NS_MDFE,
        elemento_inf="infMDFe",
        prefixo_id="MDFe",
        modelo=58,
        campo_numero="nMDF",
        elemento_protocolo="protMDFe",
        desenhar=_desenhar_damdfe,
    )
