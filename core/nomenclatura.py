"""
Nomenclatura oficial do produto — fonte única da verdade.

Regra editorial: evitar a palavra "plano" em qualquer texto voltado ao paciente
(ela remete a convênio/plano de saúde). Usar sempre os termos clínicos abaixo.

Este módulo centraliza os rótulos para que a experiência verbal permaneça
consistente em todo o sistema (WhatsApp, notificações internas, documentação).
"""

# ------------------------------------------------------------
# Termos oficiais (uso em textos para pacientes)
# ------------------------------------------------------------
CONSULTA_PONTUAL = "Consulta Clínica Pontual"
CONSULTA_PONTUAL_DESCRICAO = (
    "Atendimento diagnóstico ou de avaliação isolada com o Dr. Responsável"
)

PROGRAMA_CONTINUIDADE = "Programa de Continuidade Terapêutica"
PROGRAMA_CONTINUIDADE_COMPLETO = (
    "Programa de Continuidade Terapêutica (Método Dr. Responsável)"
)

PACIENTE_CONTINUIDADE = "Paciente em Continuidade Ativa"

ESPACO_DECIMO_PASSO = "Espaço do 10º Passo"
ESPACO_DECIMO_PASSO_COMPLETO = "Espaço do 10º Passo (Inventário Reflexivo Diário)"

ACERVO = "Acervo Psicoeducativo & Guia Clínico"

# ------------------------------------------------------------
# Valores persistidos em pacientes.tipo_plano
# (mantidos por compatibilidade com o banco; NÃO são exibidos ao paciente)
# ------------------------------------------------------------
TIPO_ACESSO_PONTUAL = "avulso"
TIPO_ACESSO_CONTINUIDADE = "anual"

# Rótulos de modalidade usados em notificações administrativas
ROTULO_MODALIDADE_CONTINUIDADE = f"{PROGRAMA_CONTINUIDADE} (Acompanhamento Contínuo)"
ROTULO_MODALIDADE_PONTUAL = f"{CONSULTA_PONTUAL} (Atendimento Isolado)"


def rotulo_modalidade(tipo_consulta: str | None) -> str:
    """Retorna o rótulo institucional da modalidade para uso interno."""
    if (tipo_consulta or "").lower() == "continuidade":
        return ROTULO_MODALIDADE_CONTINUIDADE
    return ROTULO_MODALIDADE_PONTUAL
