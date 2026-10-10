"""Testes das ferramentas comuns de documento fiscal: chave, XSD, DACTE e DAMDFE."""

from __future__ import annotations

import base64

import pytest

from mcp_fiscal_brasil._core.errors import FiscalValidationError
from mcp_fiscal_brasil.dfe import (
    PACOTES,
    gerar_dacte,
    gerar_damdfe,
    validar_chave_dfe,
    validar_xml_fiscal,
)
from mcp_fiscal_brasil.dfe.chave import calcular_dv, ler_chave, normalizar_chave
from mcp_fiscal_brasil.dfe.documentos import DocumentoAuxiliarError
from mcp_fiscal_brasil.dfe.validacao import XmlFiscalInvalidoError
from mcp_fiscal_brasil.server import app
from mcp_fiscal_brasil.shared.validators import validate_chave_nfe
from mcp_fiscal_brasil.shared.xml_utils import XMLParseError

from . import dfe_amostras as amostras


class TestChave:
    def test_dv_bate_com_o_validador_antigo_em_chave_numerica(self) -> None:
        # O calculo novo (ASCII menos 48) tem de dar o mesmo que o antigo quando so ha digitos.
        for numero in (1, 45, 999, 123456789):
            for modelo in ("55", "57", "58"):
                chave = amostras.chave(modelo, numero)
                assert validate_chave_nfe(chave) is True
                errada = chave[:-1] + str((int(chave[-1]) + 1) % 10)
                assert validate_chave_nfe(errada) is False
                assert validar_chave_dfe(errada)["valido"] is False

    @pytest.mark.parametrize("modelo", ["55", "57", "58", "65", "67"])
    def test_aceita_os_modelos_de_documento_eletronico(self, modelo: str) -> None:
        resultado = validar_chave_dfe(amostras.chave(modelo, 9))
        assert resultado["valido"] is True
        assert resultado["modelo"] == modelo
        assert resultado["uf"] == "SP"
        assert resultado["ano_mes_emissao"] == "10/2026"
        assert resultado["numero"] == "000000009"

    def test_aceita_espacos_e_prefixo_do_id(self) -> None:
        chave = amostras.chave("57", 45)
        formatada = " ".join(chave[i : i + 4] for i in range(0, 44, 4))
        assert normalizar_chave("CTe" + chave) == chave
        assert validar_chave_dfe(formatada)["valido"] is True
        assert validar_chave_dfe("MDFe" + amostras.chave("58", 7))["valido"] is True

    def test_cnpj_alfanumerico_entra_no_calculo_pelo_ascii_menos_48(self) -> None:
        # 12ABC34501DE35: raiz e ordem com letras, os dois ultimos sao digitos.
        chave = amostras.chave("57", 45, cnpj="12ABC34501DE35")
        resultado = validar_chave_dfe(chave)
        assert resultado["valido"] is True
        assert resultado["cnpj_alfanumerico"] is True
        assert resultado["documento_emitente"] == "12ABC34501DE35"
        # 'A' vale 17, nao 1: trocar a letra muda o digito.
        outra = chave.replace("ABC", "1BC", 1)
        assert validar_chave_dfe(outra)["valido"] is False

    def test_recusa_dv_errado_modelo_uf_e_mes_invalidos(self) -> None:
        chave = amostras.chave("57", 45)
        errada = chave[:-1] + ("0" if chave[-1] != "0" else "1")
        assert "Digito verificador" in validar_chave_dfe(errada)["motivos"][0]

        def refeita(base: str) -> str:
            return base + calcular_dv(base)

        assert any(
            "Modelo 99" in m
            for m in validar_chave_dfe(refeita(chave[:20] + "99" + chave[22:43]))["motivos"]
        )
        assert any("UF" in m for m in validar_chave_dfe(refeita("99" + chave[2:43]))["motivos"])
        assert any(
            "Mes" in m
            for m in validar_chave_dfe(refeita(chave[:4] + "13" + chave[6:43]))["motivos"]
        )

    @pytest.mark.parametrize(
        "ruim", ["", "123", "x" * 44, "3526101122233300018A57001000000045100000123"]
    )
    def test_recusa_formato_errado(self, ruim: str) -> None:
        assert validar_chave_dfe(ruim)["valido"] is False
        assert ler_chave(ruim) is None

    def test_letra_fora_do_cnpj_nao_passa(self) -> None:
        chave = amostras.chave("57", 45)
        assert ler_chave(chave[:30] + "A" + chave[31:]) is None
        # Os dois digitos verificadores do CNPJ continuam numericos.
        assert ler_chave(chave[:18] + "AB" + chave[20:]) is None


class TestValidacaoDeEsquema:
    def test_cte_e_mdfe_validos_passam_com_o_modal_conferido(self) -> None:
        cte = validar_xml_fiscal(amostras.cte())
        assert cte["valido"] is True, cte["erros"]
        assert (cte["tipo"], cte["modelo"], cte["documento"], cte["versao_esquema"]) == (
            "cte",
            "57",
            "CTe",
            "4.00",
        )
        assert cte["esquemas_usados"] == ["cte/cte_v4.00.xsd", "cte/cteModalRodoviario_v4.00.xsd"]
        assert cte["chave_acesso"] == amostras.chave("57", 45)
        assert cte["pacote"] == PACOTES["cte"]
        assert cte["pacote"]["pacote"].startswith("PL_CTe_400")

        mdfe = validar_xml_fiscal(amostras.mdfe(), tipo="mdfe")
        assert mdfe["valido"] is True, mdfe["erros"]
        assert (mdfe["tipo"], mdfe["modelo"], mdfe["versao_esquema"]) == ("mdfe", "58", "3.00")
        assert "mdfe/mdfeModalRodoviario_v3.00.xsd" in mdfe["esquemas_usados"]

    def test_documento_com_protocolo(self) -> None:
        assert validar_xml_fiscal(amostras.cte(com_protocolo=True))["documento"] == "cteProc"
        resultado = validar_xml_fiscal(amostras.mdfe(com_protocolo=True))
        assert resultado["valido"] is True, resultado["erros"]
        assert resultado["versao"] == "3.00"

    def test_erro_de_leiaute_vem_com_linha_e_campo(self) -> None:
        xml = amostras.cte().replace("<CFOP>5353</CFOP>", "<CFOP>53</CFOP>")
        resultado = validar_xml_fiscal(xml)
        assert resultado["valido"] is False
        erro = resultado["erros"][0]
        assert erro["campo"] == "CFOP"
        assert erro["origem"] == "esquema"
        assert erro["linha"] == 2
        assert "{http" not in erro["mensagem"]

    def test_modal_errado_passa_no_esquema_principal_mas_e_pego_aqui(self) -> None:
        # O XSD do CT-e aceita qualquer coisa dentro de infModal; so o XSD do modal recusa.
        xml = amostras.cte(modal="<rodo><RNTRC>1234</RNTRC></rodo>")
        resultado = validar_xml_fiscal(xml)
        assert resultado["valido"] is False
        assert [e["origem"] for e in resultado["erros"]] == ["modal"]
        assert resultado["erros"][0]["campo"] == "RNTRC"

        sem_condutor = amostras.mdfe(
            modal="<rodo><veicTracao><placa>ABC1D23</placa><tara>8000</tara>"
            "<tpRod>03</tpRod><tpCar>02</tpCar><UF>SP</UF></veicTracao></rodo>"
        )
        resultado = validar_xml_fiscal(sem_condutor)
        assert resultado["valido"] is False
        assert resultado["erros"][0]["origem"] == "modal"

        desconhecido = validar_xml_fiscal(amostras.cte(modal="<foguete/>"))
        assert desconhecido["erros"][0]["mensagem"] == "Modal <foguete> desconhecido em infModal."

    def test_chave_que_nao_bate_com_os_campos(self) -> None:
        xml = amostras.cte().replace("<nCT>45</nCT>", "<nCT>46</nCT>")
        resultado = validar_xml_fiscal(xml)
        assert resultado["valido"] is False
        assert [(e["origem"], e["campo"]) for e in resultado["erros"]] == [("chave", "nCT")]

        outro_emitente = amostras.mdfe().replace(
            f"<emit><CNPJ>{amostras.CNPJ_EMITENTE}", "<emit><CNPJ>22333444000181"
        )
        assert [e["campo"] for e in validar_xml_fiscal(outro_emitente)["erros"]] == ["emit"]

        mes = amostras.cte().replace("2026-10-10T09:00:00", "2026-11-10T09:00:00")
        assert [e["campo"] for e in validar_xml_fiscal(mes)["erros"]] == ["dhEmi"]

    def test_evento_de_cancelamento_do_cte_e_do_mdfe(self) -> None:
        chave = amostras.chave("57", 45)

        def evento(detalhe: str) -> str:
            return (
                '<eventoCTe xmlns="http://www.portalfiscal.inf.br/cte" versao="4.00">'
                f'<infEvento Id="ID110111{chave}001"><cOrgao>35</cOrgao><tpAmb>2</tpAmb>'
                f"<CNPJ>{amostras.CNPJ_EMITENTE}</CNPJ><chCTe>{chave}</chCTe>"
                "<dhEvento>2026-10-10T10:00:00-03:00</dhEvento><tpEvento>110111</tpEvento><nSeqEvento>1</nSeqEvento>"
                f'<detEvento versaoEvento="4.00">{detalhe}</detEvento></infEvento>'
                f"{amostras.assinatura('ID110111' + chave + '001')}</eventoCTe>"
            )

        bom = evento(
            "<evCancCTe><descEvento>Cancelamento</descEvento><nProt>135260000000001</nProt>"
            "<xJust>Erro no preenchimento do tomador do servico</xJust></evCancCTe>"
        )
        resultado = validar_xml_fiscal(bom)
        assert resultado["valido"] is True, resultado["erros"]
        assert resultado["esquemas_usados"] == [
            "cte/eventoCTe_v4.00.xsd",
            "cte/evCancCTe_v4.00.xsd",
        ]

        # Justificativa com menos de 15 caracteres: o envelope aceita, o detalhe nao.
        curto = evento(
            "<evCancCTe><descEvento>Cancelamento</descEvento><nProt>135260000000001</nProt>"
            "<xJust>curta</xJust></evCancCTe>"
        )
        resultado = validar_xml_fiscal(curto)
        assert resultado["valido"] is False
        assert (resultado["erros"][0]["origem"], resultado["erros"][0]["campo"]) == (
            "evento",
            "xJust",
        )

        sem_esquema = validar_xml_fiscal(evento("<evInventado><x>1</x></evInventado>"))
        assert any("evInventado" in aviso for aviso in sem_esquema["avisos"])

    def test_evento_cujo_arquivo_tem_nome_diferente_do_elemento(self) -> None:
        # Inclusao de DF-e do MDF-e: o elemento e evIncDFeMDFe, o arquivo e evInclusaoDFeMDFe.
        chave = amostras.chave("58", 7)

        def evento(detalhe: str) -> str:
            return (
                '<eventoMDFe xmlns="http://www.portalfiscal.inf.br/mdfe" versao="3.00">'
                f'<infEvento Id="ID110115{chave}001"><cOrgao>35</cOrgao><tpAmb>2</tpAmb>'
                f"<CNPJ>{amostras.CNPJ_EMITENTE}</CNPJ><chMDFe>{chave}</chMDFe>"
                "<dhEvento>2026-10-10T10:00:00-03:00</dhEvento><tpEvento>110115</tpEvento><nSeqEvento>1</nSeqEvento>"
                f'<detEvento versaoEvento="3.00">{detalhe}</detEvento></infEvento>'
                f"{amostras.assinatura('ID110115' + chave + '001')}</eventoMDFe>"
            )

        bom = evento(
            "<evIncDFeMDFe><descEvento>Inclusao DF-e</descEvento><nProt>935260000000001</nProt>"
            "<cMunCarrega>3549805</cMunCarrega><xMunCarrega>Sao Jose do Rio Preto</xMunCarrega>"
            "<infDoc><cMunDescarga>3550308</cMunDescarga><xMunDescarga>Sao Paulo</xMunDescarga>"
            f"<chNFe>{amostras.CHAVE_NFE}</chNFe></infDoc></evIncDFeMDFe>"
        )
        resultado = validar_xml_fiscal(bom)
        assert resultado["valido"] is True, resultado["erros"]
        assert "mdfe/evInclusaoDFeMDFe_v3.00.xsd" in resultado["esquemas_usados"]
        assert not any("sem esquema" in aviso for aviso in resultado["avisos"])
        ruim = validar_xml_fiscal(bom.replace("<cMunCarrega>3549805<", "<cMunCarrega>35<"))
        assert (ruim["erros"][0]["origem"], ruim["erros"][0]["campo"]) == ("evento", "cMunCarrega")

    def test_nfe_sem_assinatura_e_recusada_pelo_esquema(self) -> None:
        chave = amostras.CHAVE_NFE
        xml = (
            '<NFe xmlns="http://www.portalfiscal.inf.br/nfe">'
            f'<infNFe versao="4.00" Id="NFe{chave}"><ide><cUF>35</cUF></ide></infNFe></NFe>'
        )
        resultado = validar_xml_fiscal(xml, tipo="nfe")
        assert resultado["valido"] is False
        assert resultado["tipo"] == "nfe"
        assert resultado["pacote"]["pacote"] == "PL_010f"
        assert resultado["chave_acesso"] == chave
        assert resultado["total_de_erros"] >= 1

    @staticmethod
    def _cancelamento_nfe(
        chave: str, cnpj: str, justificativa: str = "Pedido cancelado pelo cliente"
    ) -> str:
        return (
            '<envEvento xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.00"><idLote>1</idLote>'
            '<evento versao="1.00">'
            f'<infEvento Id="ID110111{chave}01"><cOrgao>35</cOrgao><tpAmb>2</tpAmb>'
            f"<CNPJ>{cnpj}</CNPJ><chNFe>{chave}</chNFe>"
            "<dhEvento>2026-10-10T10:00:00-03:00</dhEvento><tpEvento>110111</tpEvento>"
            "<nSeqEvento>1</nSeqEvento><verEvento>1.00</verEvento>"
            '<detEvento versao="1.00"><descEvento>Cancelamento</descEvento>'
            f"<nProt>135260000000001</nProt><xJust>{justificativa}</xJust></detEvento>"
            f"</infEvento>{amostras.assinatura('ID110111' + chave + '01')}</evento></envEvento>"
        )

    def test_evento_de_cancelamento_da_nfe_confere_envelope_e_detalhe(self) -> None:
        chave = amostras.CHAVE_NFE
        resultado = validar_xml_fiscal(self._cancelamento_nfe(chave, amostras.CNPJ_EMITENTE))
        assert resultado["valido"] is True, resultado["erros"]
        assert resultado["esquemas_usados"] == [
            "nfe/pl010d-evento/envEvento_v1.00.xsd",
            "nfe/evento-cancelamento/e110111_v1.00.xsd",
        ]
        curto = validar_xml_fiscal(self._cancelamento_nfe(chave, amostras.CNPJ_EMITENTE, "curta"))
        assert (curto["erros"][0]["origem"], curto["erros"][0]["campo"]) == ("evento", "xJust")
        # Erro no envelope (orgao inexistente) vem antes e com outra origem.
        orgao = validar_xml_fiscal(
            self._cancelamento_nfe(chave, amostras.CNPJ_EMITENTE).replace(
                "<cOrgao>35<", "<cOrgao>99999<"
            )
        )
        assert (orgao["erros"][0]["origem"], orgao["erros"][0]["campo"]) == ("esquema", "cOrgao")

    def test_evento_e_inutilizacao_da_nfe_com_cnpj_alfanumerico(self) -> None:
        # NT 2026.004: CNPJ com letras no evento, na chave e na inutilizacao.
        cnpj = "12ABC34501DE35"
        chave = amostras.chave("55", 123, cnpj=cnpj)
        evento = validar_xml_fiscal(self._cancelamento_nfe(chave, cnpj))
        assert evento["valido"] is True, evento["erros"]

        identificador = f"ID35{'26'}{cnpj}55001000000010000000020"
        inutilizacao = (
            '<inutNFe xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">'
            f'<infInut Id="{identificador}"><tpAmb>2</tpAmb><xServ>INUTILIZAR</xServ><cUF>35</cUF>'
            f"<ano>26</ano><CNPJ>{cnpj}</CNPJ><mod>55</mod><serie>1</serie><nNFIni>10</nNFIni>"
            "<nNFFin>20</nNFFin><xJust>Falha na numeracao do sistema</xJust></infInut>"
            f"{amostras.assinatura(identificador)}</inutNFe>"
        )
        resultado = validar_xml_fiscal(inutilizacao)
        assert resultado["valido"] is True, resultado["erros"]
        assert resultado["esquemas_usados"] == ["nfe/pl010d-nfe/inutNFe_v4.00.xsd"]

    def test_evento_avulso_e_evento_sem_esquema_de_detalhe_avisam(self) -> None:
        chave = amostras.CHAVE_NFE
        envelope = self._cancelamento_nfe(chave, amostras.CNPJ_EMITENTE)
        inicio = envelope.index("<evento ")
        avulso = envelope[inicio : envelope.index("</envEvento>")].replace(
            '<evento versao="1.00">',
            '<evento xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.00">',
        )
        resultado = validar_xml_fiscal(avulso)
        assert resultado["esquemas_usados"] == ["nfe/evento-cancelamento/e110111_v1.00.xsd"]
        assert any("Evento avulso" in aviso for aviso in resultado["avisos"])

        desconhecido = validar_xml_fiscal(
            envelope.replace("<tpEvento>110111<", "<tpEvento>999999<")
        )
        assert any("999999" in aviso for aviso in desconhecido["avisos"])

    def test_recusas(self) -> None:
        with pytest.raises(XmlFiscalInvalidoError, match="vazio"):
            validar_xml_fiscal("  ")
        with pytest.raises(XmlFiscalInvalidoError, match="namespace"):
            validar_xml_fiscal("<CTe><infCte/></CTe>")
        with pytest.raises(XmlFiscalInvalidoError, match="e de cte"):
            validar_xml_fiscal(amostras.cte(), tipo="mdfe")
        with pytest.raises(XmlFiscalInvalidoError, match="tipo precisa"):
            validar_xml_fiscal(amostras.cte(), tipo="nfse")
        with pytest.raises(XmlFiscalInvalidoError, match="elemento raiz"):
            validar_xml_fiscal('<retCTe xmlns="http://www.portalfiscal.inf.br/cte"/>')
        with pytest.raises(XmlFiscalInvalidoError, match="5 MB"):
            validar_xml_fiscal("<a>" + "x" * (5 * 1024 * 1024) + "</a>")
        with pytest.raises(XMLParseError):
            validar_xml_fiscal("<CTe")

    def test_doctype_e_recusado_antes_de_qualquer_conferencia(self) -> None:
        xml = (
            '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>'
            + amostras.cte().replace("<natOp>PRESTACAO", "<natOp>&e;PRESTACAO")
        )
        with pytest.raises(FiscalValidationError, match="DOCTYPE"):
            validar_xml_fiscal(xml)
        with pytest.raises(FiscalValidationError, match="DOCTYPE"):
            gerar_dacte(xml)

    def test_limite_de_erros_devolvidos(self) -> None:
        resultado = validar_xml_fiscal(
            amostras.cte().replace("<cMun>", "<cMunX>").replace("</cMun>", "</cMunX>")
        )
        assert resultado["valido"] is False
        assert len(resultado["erros"]) <= 50
        assert resultado["total_de_erros"] >= len(resultado["erros"])


class TestDocumentosAuxiliares:
    def test_dacte(self) -> None:
        resultado = gerar_dacte(amostras.cte(com_protocolo=True))
        pdf = base64.b64decode(resultado.pdf_base64)
        assert pdf.startswith(b"%PDF-")
        assert len(pdf) > 2000
        assert resultado.modelo == 57
        assert resultado.chave_acesso == amostras.chave("57", 45)
        assert resultado.nome_arquivo == f"DACTE_{amostras.chave('57', 45)}.pdf"
        assert (resultado.numero, resultado.serie, resultado.autorizado) == ("45", "1", True)

    def test_damdfe(self) -> None:
        resultado = gerar_damdfe(amostras.mdfe(com_protocolo=True).encode("utf-8"))
        pdf = base64.b64decode(resultado.pdf_base64)
        assert pdf.startswith(b"%PDF-")
        assert resultado.modelo == 58
        assert resultado.nome_arquivo == f"DAMDFE_{amostras.chave('58', 7)}.pdf"
        assert (resultado.numero, resultado.autorizado) == ("7", True)

    def test_sem_protocolo_gera_e_avisa_que_nao_esta_autorizado(self) -> None:
        assert gerar_dacte(amostras.cte()).autorizado is False
        assert gerar_damdfe(amostras.mdfe()).autorizado is False

    def test_recusa_documento_trocado_ou_chave_ruim(self) -> None:
        with pytest.raises(DocumentoAuxiliarError, match="nao e um CT-e"):
            gerar_dacte(amostras.mdfe())
        with pytest.raises(DocumentoAuxiliarError, match="nao e um MDF-e"):
            gerar_damdfe(amostras.cte())
        chave = amostras.chave("57", 45)
        ruim = amostras.cte().replace(f'Id="CTe{chave}"', f'Id="CTe{chave[:-1]}X"')
        with pytest.raises(DocumentoAuxiliarError, match="chave de acesso valida"):
            gerar_dacte(ruim)
        with pytest.raises(XMLParseError):
            gerar_dacte("<CTe")


class TestFerramentasMcp:
    async def test_as_quatro_ferramentas_estao_registradas(self) -> None:
        nomes = {ferramenta.name for ferramenta in await app.list_tools()}
        assert {"gerar_dacte", "gerar_damdfe", "validar_xml_fiscal", "validar_chave_dfe"} <= nomes

    async def test_chamada_pelo_servidor(self) -> None:
        resultado = await app.call_tool(
            "validar_xml_fiscal", {"xml_content": amostras.cte(), "tipo": "cte"}
        )
        dados = resultado.structured_content
        assert dados["valido"] is True
        assert dados["pacote"]["publicado_em"] == "2026-10-02"
        pdf = await app.call_tool(
            "gerar_damdfe", {"xml_content": amostras.mdfe(com_protocolo=True)}
        )
        assert base64.b64decode(pdf.structured_content["pdf_base64"]).startswith(b"%PDF-")
        chave = await app.call_tool("validar_chave_dfe", {"chave_acesso": amostras.chave("58", 7)})
        assert chave.structured_content["documento"] == "MDF-e"
