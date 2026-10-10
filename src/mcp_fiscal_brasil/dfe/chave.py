"""Chave de acesso dos documentos fiscais eletronicos (NF-e, NFC-e, CT-e, MDF-e).

Leiaute unico de 44 posicoes, igual nos tres manuais (MOC da NF-e, do CT-e e do
MDF-e):

    cUF(2) AAMM(4) CNPJ(14) mod(2) serie(3) numero(9) tpEmis(1) codigo(8) cDV(1)

O digito verificador e modulo 11 com pesos de 2 a 9, da direita para a
esquerda, sobre as 43 primeiras posicoes. Com o CNPJ alfanumerico (IN RFB
2.229/2024; NT 2026.004 da NF-e e equivalentes do CT-e e do MDF-e) as posicoes
do CNPJ podem trazer letras maiusculas, e o valor de cada caractere no calculo
passa a ser o codigo ASCII menos 48 ('0'..'9' = 0..9, 'A' = 17 ... 'Z' = 42).
Para chave so com digitos o resultado e identico ao calculo antigo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..shared.constants import CODIGO_UF

MODELOS: dict[str, str] = {
    "55": "NF-e",
    "57": "CT-e",
    "58": "MDF-e",
    "65": "NFC-e",
    "67": "CT-e OS",
}

_FORMATO = re.compile(r"^\d{6}[0-9A-Z]{12}\d{26}$")


@dataclass(frozen=True)
class ChaveDeAcesso:
    """As partes de uma chave de acesso de 44 posicoes."""

    chave: str
    c_uf: str
    ano_mes: str
    documento_emitente: str
    modelo: str
    serie: str
    numero: str
    tp_emis: str
    codigo: str
    dv: str


def normalizar_chave(chave: str) -> str:
    """Tira espacos, pontos e o prefixo do atributo Id (NFe, CTe, MDFe)."""
    limpa = re.sub(r"[\s.\-/]", "", chave or "").upper()
    return re.sub(r"^(NFE|CTE|MDFE)(?=[0-9]{6})", "", limpa)


def calcular_dv(base43: str) -> str:
    """Digito verificador (modulo 11, pesos 2 a 9) das 43 primeiras posicoes."""
    soma = 0
    peso = 2
    for caractere in reversed(base43):
        soma += (ord(caractere) - 48) * peso
        peso = 2 if peso == 9 else peso + 1
    resto = soma % 11
    return "0" if resto in (0, 1) else str(11 - resto)


def ler_chave(chave: str) -> ChaveDeAcesso | None:
    """Separa a chave nas partes do leiaute. Devolve None se o formato nao bater."""
    limpa = normalizar_chave(chave)
    if not _FORMATO.match(limpa):
        return None
    return ChaveDeAcesso(
        chave=limpa,
        c_uf=limpa[0:2],
        ano_mes=limpa[2:6],
        documento_emitente=limpa[6:20],
        modelo=limpa[20:22],
        serie=limpa[22:25],
        numero=limpa[25:34],
        tp_emis=limpa[34:35],
        codigo=limpa[35:43],
        dv=limpa[43:44],
    )


def validar_chave_dfe(chave: str) -> dict[str, object]:
    """Confere formato, UF, mes, modelo e digito verificador de uma chave de acesso.

    Nao consulta a SEFAZ: diz se a chave e bem formada, nao se o documento existe.
    """
    partes = ler_chave(chave)
    if partes is None:
        return {
            "valido": False,
            "motivos": [
                "A chave precisa ter 44 posicoes: digitos, com letras maiusculas "
                "aceitas so nas 12 primeiras posicoes do CNPJ (7a a 18a da chave)."
            ],
        }

    motivos: list[str] = []
    if int(partes.c_uf) not in CODIGO_UF:
        motivos.append(f"Codigo de UF desconhecido: {partes.c_uf}.")
    if not 1 <= int(partes.ano_mes[2:4]) <= 12:
        motivos.append(f"Mes de emissao invalido: {partes.ano_mes[2:4]}.")
    if partes.modelo not in MODELOS:
        motivos.append(
            f"Modelo {partes.modelo} nao e de documento fiscal eletronico "
            f"({', '.join(sorted(MODELOS))})."
        )
    esperado = calcular_dv(partes.chave[:43])
    if esperado != partes.dv:
        motivos.append(
            f"Digito verificador nao confere: a chave traz {partes.dv}, o calculo da {esperado}."
        )

    return {
        "valido": not motivos,
        "motivos": motivos,
        "chave": partes.chave,
        "chave_formatada": " ".join(partes.chave[i : i + 4] for i in range(0, 44, 4)),
        "uf": CODIGO_UF.get(int(partes.c_uf)),
        "ano_mes_emissao": f"{partes.ano_mes[2:4]}/20{partes.ano_mes[0:2]}",
        "documento_emitente": partes.documento_emitente,
        "cnpj_alfanumerico": not partes.documento_emitente.isdigit(),
        "modelo": partes.modelo,
        "documento": MODELOS.get(partes.modelo),
        "serie": partes.serie,
        "numero": partes.numero,
        "tipo_emissao": partes.tp_emis,
        "codigo_numerico": partes.codigo,
        "digito_verificador": partes.dv,
    }
