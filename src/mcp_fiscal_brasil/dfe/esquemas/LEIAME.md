# Esquemas XSD oficiais

Cópia sem alteração dos pacotes de liberação publicados pelos portais. O
conteúdo de `PACOTES`, em `../validacao.py`, precisa acompanhar o que está aqui.

| Pasta | Pacote | Publicado em | Fonte |
|---|---|---|---|
| `nfe/` | `PL_010f` (NT 2025.002 v1.50 e NT 2026.007 v1.00) | 31/08/2026 | Portal Nacional da NF-e, Documentos → Esquemas XML |
| `nfe/procNFe_v4.00.xsd` | Pacote de Liberação 9, leiaute 4.00 | — | idem |
| `nfe/pl010d-evento/` | `PL_010d v1.03` (NT 2026.004 v1.01, CNPJ alfanumérico): envelope genérico de evento | 10/07/2026 | idem |
| `nfe/pl010d-nfe/` | `PL_010d v1.03`: consulta de situação e inutilização. O `inutNFe_v4.00.xsd` (elemento raiz) não vem nesse pacote e é o do Pacote 9 | 10/07/2026 | idem |
| `nfe/evento-cancelamento/` | Evento de cancelamento v1.00: usado só o `e110111` (detEvento) | 21/12/2018 | idem |
| `nfe/evento-cce/` | PL Evento CCe v1.01: usado só o `e110110` (detEvento) | 30/05/2014 | idem |
| `nfe/evento-rtc/` | Eventos da NT 2025.002 v1.40 (reforma tributária), só detEvento | 27/07/2026 | idem |
| `cte/` | `PL_CTe_400_NT2026.004 RTC_1.00` | 02/10/2026 | <https://dfe-portal.svrs.rs.gov.br/CTE/Documentos> |
| `mdfe/` | `PL_MDFe_300b_NT012025_1.05` | 25/04/2026 | <https://dfe-portal.svrs.rs.gov.br/Mdfe/Documentos> |

Os pacotes da NF-e ficam em pastas separadas porque cada um traz o seu
`tiposBasico`, e eles não são iguais entre si. O evento da NF-e é conferido em
duas partes: o envelope pelo esquema genérico do `PL_010d` (que aceita CNPJ
alfanumérico) e o `detEvento` pelo `e<tpEvento>_v1.00.xsd` do pacote do evento.
Os arquivos do `PL_010d` vieram da cópia conferida por SHA-256 no repositório
do ERP (`tests/fixtures/nfe-xsd/ORIGEM.md`).

## Atualizar

1. Baixar o pacote novo do portal e trocar os arquivos da pasta (sem editar).
2. Ajustar a entrada em `PACOTES` (nome, data e notas técnicas).
3. Rodar `pytest tests/test_dfe.py`: os XML de teste têm de continuar válidos;
   se o leiaute mudou, o teste mostra onde.
