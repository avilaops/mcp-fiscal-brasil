"""Schemas Pydantic para consultas de tabelas fiscais estáticas."""

from pydantic import Field

from ..shared.schemas import BaseResponse


class ExcecaoTipi(BaseResponse):
    """Uma exceção (EX) da TIPI: o mesmo NCM com outra alíquota para um produto descrito."""

    ex: str = Field(description="Número da exceção, com dois dígitos")
    descricao: str = Field(description="Produto a que a exceção se aplica")
    aliquota_ipi: float | None = Field(default=None, description="Alíquota do IPI em percentual")
    ipi_nao_tributado: bool = Field(default=False, description="A TIPI marca a exceção como NT")


class NCMResponse(BaseResponse):
    """Resposta de consulta de NCM (Nomenclatura Comum do Mercosul)."""

    codigo: str = Field(description="Código NCM com 8 dígitos")
    descricao: str = Field(description="Descrição do produto conforme TIPI")
    aliquota_ipi: float | None = Field(
        default=None,
        description="Alíquota do IPI em percentual, da TIPI. Vazia quando o produto é NT ou a TIPI não traz o código",
    )
    ipi_nao_tributado: bool = Field(
        default=False,
        description="A TIPI marca o código como NT (não tributado), que não é o mesmo que 0%",
    )
    excecoes_tipi: list[ExcecaoTipi] = Field(
        default_factory=list, description="Exceções (EX) da TIPI para este código"
    )
    fonte_ipi: str | None = Field(
        default=None, description="De onde vem a alíquota do IPI e de quando é"
    )
    unidade_tributavel: str | None = Field(
        default=None, description="Unidade tributável (ex: UN, KG, L)"
    )
    ex_tipi: str | None = Field(default=None, description="Código de exceção TIPI (EX), se existir")
    capitulo: str = Field(description="Capítulo TIPI (primeiros 2 dígitos)")
    posicao: str = Field(description="Posição TIPI (primeiros 4 dígitos)")
    hierarquia: str | None = Field(
        default=None,
        description="Descrição da posição até o item (a do código sozinha pode ser só 'Outros')",
    )
    fonte: str | None = Field(default=None, description="De onde vem a nomenclatura e de quando é")


class CFOPResponse(BaseResponse):
    """Resposta de consulta de CFOP (Código Fiscal de Operações e Prestações)."""

    codigo: str = Field(description="Código CFOP com 4 dígitos")
    descricao: str = Field(description="Descrição da operação ou prestação")
    tipo: str = Field(description="Tipo da operação: 'entrada' ou 'saida'")
    aplicacao: str = Field(
        description="Âmbito da operação: 'estadual', 'interestadual' ou 'exterior'"
    )
    grupo: str = Field(description="Número do grupo CFOP (1=entrada est., 2=entrada int., etc.)")
    nota_explicativa: str | None = Field(
        default=None, description="Nota explicativa oficial do código"
    )
    vigencia_inicio: str | None = Field(default=None, description="Início de vigência (AAAA-MM-DD)")
    vigencia_fim: str | None = Field(default=None, description="Fim de vigência; nulo = vigente")
    indicadores: list[str] = Field(
        default_factory=list,
        description="Usos marcados na tabela oficial: nfe, transporte, comunicacao, devolucao, retorno, anulacao, remessa, combustivel, exclusao_ibs_cbs",
    )
    fonte: str | None = Field(default=None, description="Tabela oficial usada e a data dela")


class CSTResponse(BaseResponse):
    """Resposta de validação de CST/CSOSN (Código de Situação Tributária)."""

    cst: str = Field(description="Código CST ou CSOSN informado")
    valido: bool = Field(description="Indica se o código é válido para o regime informado")
    descricao: str | None = Field(default=None, description="Descrição do código, se válido")
    regime: str = Field(
        description="Regime tributário: 'normal' (Lucro Real/Presumido) ou 'simples'"
    )
    tabela: str | None = Field(
        default=None,
        description="Tabela de origem: 'CST_ICMS', 'CSOSN', 'CST_PIS_COFINS', 'CST_IPI'",
    )


class CESTResponse(BaseResponse):
    """Resposta de consulta de CEST (Código Especificador da Substituição Tributária)."""

    cest: str = Field(description="Código CEST com 7 dígitos")
    descricao: str = Field(description="Descrição do item no convênio")
    segmento: str = Field(description="Número do segmento CEST (primeiros 2 dígitos)")
    segmento_nome: str | None = Field(
        default=None, description="Nome do segmento (anexo I do Convênio ICMS 142/18)"
    )
    anexo: str | None = Field(default=None, description="Anexo do convênio que traz o item")
    anexo_titulo: str | None = Field(default=None, description="Título do anexo")
    item: str | None = Field(default=None, description="Número do item dentro do anexo")
    ncm_sh: str | None = Field(
        default=None, description="Coluna NCM/SH do item, como o convênio a escreve"
    )
    ncm_relacionados: list[str] = Field(
        default_factory=list,
        description=(
            "Códigos da coluna NCM/SH só com dígitos, do tamanho que o convênio traz: "
            "capítulo (2), posição (4), subposição ou código inteiro (8). O NCM do produto "
            "se enquadra quando começa por um deles e o produto atende à descrição"
        ),
    )
    fonte: str | None = Field(
        default=None, description="Texto do convênio usado, a data da redação e de onde veio"
    )


class ICMSAliquotaResponse(BaseResponse):
    """Resposta de consulta de alíquota interestadual do ICMS."""

    uf_origem: str = Field(description="UF de origem da operação (sigla, ex: SP)")
    uf_destino: str = Field(description="UF de destino da operação (sigla, ex: MG)")
    aliquota_interestadual: float = Field(
        description="Alíquota interestadual do ICMS em percentual"
    )
    aliquota_interna_destino: float = Field(
        description="Alíquota interna do ICMS no estado de destino em percentual"
    )
    diferencial_aliquota: float = Field(
        description="Diferencial de alíquota (DIFAL = alíquota interna - alíquota interestadual)"
    )
    fundamento: str = Field(
        description="Fundamento legal da alíquota (ex: Resolução SF 13/2012, EC 87/2015)"
    )
