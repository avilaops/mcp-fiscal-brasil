"""XML de CT-e e MDF-e para os testes, montados para passar nos esquemas oficiais.

Os dados sao de mentira (CNPJ e chaves com digito valido, nenhuma empresa
real). A assinatura tem a estrutura que o XSD exige e valores sem sentido: os
testes daqui conferem leiaute e PDF, nao criptografia.
"""

from __future__ import annotations

from mcp_fiscal_brasil.dfe.chave import calcular_dv

CNPJ_EMITENTE = "11222333000181"


def chave(
    modelo: str,
    numero: int,
    codigo: str = "00000123",
    cnpj: str = CNPJ_EMITENTE,
    tp_emis: str = "1",
) -> str:
    base = f"352610{cnpj}{modelo}001{numero:09d}{tp_emis}{codigo}"
    return base + calcular_dv(base)


CHAVE_NFE = chave("55", 123)


def assinatura(referencia: str) -> str:
    return (
        '<Signature xmlns="http://www.w3.org/2000/09/xmldsig#"><SignedInfo>'
        '<CanonicalizationMethod Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315"/>'
        '<SignatureMethod Algorithm="http://www.w3.org/2000/09/xmldsig#rsa-sha1"/>'
        f'<Reference URI="#{referencia}"><Transforms>'
        '<Transform Algorithm="http://www.w3.org/2000/09/xmldsig#enveloped-signature"/>'
        '<Transform Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315"/>'
        '</Transforms><DigestMethod Algorithm="http://www.w3.org/2000/09/xmldsig#sha1"/>'
        "<DigestValue>AAAAAAAAAAAAAAAAAAAAAAAAAAA=</DigestValue></Reference></SignedInfo>"
        "<SignatureValue>AAAA</SignatureValue>"
        "<KeyInfo><X509Data><X509Certificate>AAAA</X509Certificate></X509Data></KeyInfo>"
        "</Signature>"
    )


ENDERECO = (
    "<xLgr>Rua das Cargas</xLgr><nro>100</nro><xBairro>Centro</xBairro>"
    "<cMun>3549805</cMun><xMun>Sao Jose do Rio Preto</xMun><CEP>15010000</CEP><UF>SP</UF>"
)


def cte(numero: int = 45, *, modal: str | None = None, com_protocolo: bool = False) -> str:
    ch = chave("57", numero)
    rodo = modal if modal is not None else "<rodo><RNTRC>12345678</RNTRC></rodo>"
    doc = f"""<CTe xmlns="http://www.portalfiscal.inf.br/cte"><infCte versao="4.00" Id="CTe{ch}">
<ide><cUF>35</cUF><cCT>00000123</cCT><CFOP>5353</CFOP><natOp>PRESTACAO DE SERVICO DE TRANSPORTE</natOp>
<mod>57</mod><serie>1</serie><nCT>{numero}</nCT><dhEmi>2026-10-10T09:00:00-03:00</dhEmi><tpImp>1</tpImp>
<tpEmis>1</tpEmis><cDV>{ch[-1]}</cDV><tpAmb>2</tpAmb><tpCTe>0</tpCTe><procEmi>0</procEmi><verProc>teste-1.0</verProc>
<cMunEnv>3549805</cMunEnv><xMunEnv>Sao Jose do Rio Preto</xMunEnv><UFEnv>SP</UFEnv><modal>01</modal><tpServ>0</tpServ>
<cMunIni>3549805</cMunIni><xMunIni>Sao Jose do Rio Preto</xMunIni><UFIni>SP</UFIni>
<cMunFim>3550308</cMunFim><xMunFim>Sao Paulo</xMunFim><UFFim>SP</UFFim><retira>1</retira><indIEToma>1</indIEToma>
<toma3><toma>0</toma></toma3></ide>
<emit><CNPJ>{CNPJ_EMITENTE}</CNPJ><IE>123456789012</IE><xNome>CT-E EMITIDO EM AMBIENTE DE HOMOLOGACAO - SEM VALOR FISCAL</xNome>
<enderEmit>{ENDERECO}</enderEmit><CRT>3</CRT></emit>
<rem><CNPJ>22333444000181</CNPJ><IE>123456789012</IE><xNome>CT-E EMITIDO EM AMBIENTE DE HOMOLOGACAO - SEM VALOR FISCAL</xNome>
<enderReme>{ENDERECO}</enderReme></rem>
<dest><CNPJ>33444555000181</CNPJ><IE>123456789012</IE><xNome>CT-E EMITIDO EM AMBIENTE DE HOMOLOGACAO - SEM VALOR FISCAL</xNome>
<enderDest><xLgr>Avenida Destino</xLgr><nro>200</nro><xBairro>Centro</xBairro><cMun>3550308</cMun><xMun>Sao Paulo</xMun><CEP>01001000</CEP><UF>SP</UF></enderDest></dest>
<vPrest><vTPrest>500.00</vTPrest><vRec>500.00</vRec><Comp><xNome>FRETE PESO</xNome><vComp>500.00</vComp></Comp></vPrest>
<imp><ICMS><ICMS00><CST>00</CST><vBC>500.00</vBC><pICMS>12.00</pICMS><vICMS>60.00</vICMS></ICMS00></ICMS></imp>
<infCTeNorm><infCarga><vCarga>10000.00</vCarga><proPred>MAQUINAS</proPred>
<infQ><cUnid>01</cUnid><tpMed>PESO BRUTO</tpMed><qCarga>1200.0000</qCarga></infQ></infCarga>
<infDoc><infNFe><chave>{CHAVE_NFE}</chave></infNFe></infDoc>
<infModal versaoModal="4.00">{rodo}</infModal></infCTeNorm>
</infCte>{assinatura("CTe" + ch)}</CTe>"""
    if not com_protocolo:
        return doc
    return (
        '<cteProc xmlns="http://www.portalfiscal.inf.br/cte" versao="4.00">'
        + doc
        + f'<protCTe versao="4.00"><infProt><tpAmb>2</tpAmb><verAplic>SP-CTe-1</verAplic><chCTe>{ch}</chCTe>'
        "<dhRecbto>2026-10-10T09:00:05-03:00</dhRecbto><nProt>135260000000001</nProt>"
        "<digVal>AAAAAAAAAAAAAAAAAAAAAAAAAAA=</digVal><cStat>100</cStat>"
        "<xMotivo>Autorizado o uso do CT-e</xMotivo></infProt></protCTe></cteProc>"
    )


def mdfe(
    numero: int = 7,
    *,
    modal: str | None = None,
    com_protocolo: bool = False,
    tp_amb: str = "2",
    tp_emis: str = "1",
) -> str:
    ch = chave("58", numero, tp_emis=tp_emis)
    rodo = (
        modal
        if modal is not None
        else (
            "<rodo><infANTT><RNTRC>12345678</RNTRC></infANTT>"
            "<veicTracao><placa>ABC1D23</placa><tara>8000</tara>"
            "<condutor><xNome>MOTORISTA DE TESTE</xNome><CPF>52998224725</CPF></condutor>"
            "<tpRod>03</tpRod><tpCar>02</tpCar><UF>SP</UF></veicTracao></rodo>"
        )
    )
    doc = f"""<MDFe xmlns="http://www.portalfiscal.inf.br/mdfe"><infMDFe versao="3.00" Id="MDFe{ch}">
<ide><cUF>35</cUF><tpAmb>{tp_amb}</tpAmb><tpEmit>1</tpEmit><mod>58</mod><serie>1</serie><nMDF>{numero}</nMDF><cMDF>00000123</cMDF>
<cDV>{ch[-1]}</cDV><modal>1</modal><dhEmi>2026-10-10T09:30:00-03:00</dhEmi><tpEmis>{tp_emis}</tpEmis><procEmi>0</procEmi>
<verProc>teste-1.0</verProc><UFIni>SP</UFIni><UFFim>SP</UFFim>
<infMunCarrega><cMunCarrega>3549805</cMunCarrega><xMunCarrega>Sao Jose do Rio Preto</xMunCarrega></infMunCarrega></ide>
<emit><CNPJ>{CNPJ_EMITENTE}</CNPJ><IE>123456789012</IE><xNome>MDF-E EMITIDO EM AMBIENTE DE HOMOLOGACAO - SEM VALOR FISCAL</xNome>
<enderEmit>{ENDERECO}</enderEmit></emit>
<infModal versaoModal="3.00">{rodo}</infModal>
<infDoc><infMunDescarga><cMunDescarga>3550308</cMunDescarga><xMunDescarga>Sao Paulo</xMunDescarga>
<infCTe><chCTe>{chave("57", 45)}</chCTe></infCTe></infMunDescarga></infDoc>
<tot><qCTe>1</qCTe><vCarga>10000.00</vCarga><cUnid>01</cUnid><qCarga>1200.0000</qCarga></tot>
</infMDFe>{assinatura("MDFe" + ch)}</MDFe>"""
    if not com_protocolo:
        return doc
    return (
        '<mdfeProc xmlns="http://www.portalfiscal.inf.br/mdfe" versao="3.00">'
        + doc
        + f'<protMDFe versao="3.00"><infProt><tpAmb>2</tpAmb><verAplic>SP-MDFe-1</verAplic><chMDFe>{ch}</chMDFe>'
        "<dhRecbto>2026-10-10T09:30:05-03:00</dhRecbto><nProt>935260000000001</nProt>"
        "<digVal>AAAAAAAAAAAAAAAAAAAAAAAAAAA=</digVal><cStat>100</cStat>"
        "<xMotivo>Autorizado o uso do MDF-e</xMotivo></infProt></protMDFe></mdfeProc>"
    )
