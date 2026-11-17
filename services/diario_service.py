from datetime import datetime, timedelta

from agenda import FUSO_HORARIO
from core.config import supabase_client

# Guarda de prontuário: registros preservados por no mínimo 20 anos (CFM 1.821/2007 & LGPD),
# sem exclusão destrutiva pelo fluxo do assistente.
GARANTIA_GUARDA_ANOS = 20

TERMOS_RISCO_GRAVE = [
    "suicidio", "suicídio", "me matar", "tirar minha vida", "acabar com a minha vida",
    "acabar com tudo", "não quero mais viver", "nao quero mais viver",
    "não aguento mais", "nao aguento mais", "desespero total",
    "morrer", "overdose", "despedida", "sem saída", "sem saida",
]

ORIENTACAO_EMERGENCIA = (
    "━━━━━━━━━━━━━━━━━━━━━━\n"
    "🆘 *Canais de Urgência (24 horas):*\n"
    "• *CVV (Apoio Emocional):* Ligue *188*\n"
    "• *SAMU (Emergência Médica):* Ligue *192*\n"
    "━━━━━━━━━━━━━━━━━━━━━━"
)


def pode_registrar_diario_hoje(paciente_id) -> tuple[bool, str]:
    """
    Frente 3A - 10º Passo: trava rígida de 1 registro por dia civil
    (fuso America/Recife), incentivando pausa reflexiva.
    """
    if not supabase_client or not paciente_id:
        return True, ""

    try:
        hoje_inicio = (
            datetime.now(FUSO_HORARIO)
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .isoformat()
        )
        res = (
            supabase_client.table("diario_psi")
            .select("id, criado_em")
            .eq("paciente_id", paciente_id)
            .gte("criado_em", hoje_inicio)
            .execute()
        )
        if res.data and len(res.data) > 0:
            return False, (
                "🌱 *Você já registrou seu 10º Passo de hoje!*\n\n"
                "A metodologia valoriza a pausa de autorreflexão para processar com serenidade as vivências do dia. "
                "Por isso, permitimos apenas *1 registro por dia*.\n\n"
                "Guarde novas observações para o seu registro de amanhã ou leve-as para o seu próximo encontro terapêutico.\n\n"
                f"{ORIENTACAO_EMERGENCIA}\n"
                "_(Digite *MENU* para retornar)_"
            )
    except Exception as e:
        print(f"⚠️ [DIARIO] Erro ao verificar limite diário: {e}")

    return True, ""


def analisar_urgencia_clinica(texto: str) -> bool:
    """Detecta sinais de sofrimento agudo/risco para disparo de alerta clínico."""
    texto_lower = (texto or "").lower()
    return any(termo in texto_lower for termo in TERMOS_RISCO_GRAVE)


def _registrar_alerta_clinico(paciente_id, relato: str):
    """Registra alerta na tabela alertas_clinicos, se existir no banco."""
    if not supabase_client or not paciente_id:
        return
    try:
        supabase_client.table("alertas_clinicos").insert(
            {
                "paciente_id": paciente_id,
                "mensagem_gatilho": (relato or "").strip()[:2000],
                "notificacao_enviada": True,
            }
        ).execute()
    except Exception as e:
        # Tabela pode não existir em todos os ambientes; não bloqueia o fluxo principal.
        print(f"ℹ️ [DIARIO] Alerta clínico não registrado em alertas_clinicos: {e}")


def salvar_relato_diario_permanente(paciente_id, whatsapp_paciente: str, relato: str) -> str:
    """
    Frente 3A - Espaço do 10º Passo:
    - Guarda de prontuário por 20 anos (sem exclusão destrutiva).
    - Acolhimento neutro, sem diagnóstico e sem prescrição.
    - Em risco grave, adiciona tag [ALERTA_CLINICO] e orienta CVV 188 / SAMU 192.

    Compatível com o schema atual do banco (diario_psi.relato_texto, data_limite_expiracao).
    """
    alerta_disparado = analisar_urgencia_clinica(relato)
    agora = datetime.now(FUSO_HORARIO)
    relato_limpo = (relato or "").strip()

    if supabase_client and paciente_id:
        try:
            payload = {
                "paciente_id": paciente_id,
                "relato_texto": relato_limpo,
                "criado_em": agora.isoformat(),
                "data_limite_expiracao": (agora + timedelta(days=365 * GARANTIA_GUARDA_ANOS)).isoformat(),
            }
            supabase_client.table("diario_psi").insert(payload).execute()

            if alerta_disparado:
                _registrar_alerta_clinico(paciente_id, relato_limpo)
        except Exception as e:
            print(f"⚠️ [DIARIO] Erro ao gravar relato no Supabase: {e}")
            return (
                "Não consegui salvar seu registro agora por uma instabilidade técnica. "
                "Por favor, tente novamente em instantes. Se houver urgência, ligue 188 (CVV) ou 192 (SAMU).\n\n"
                "_(Digite *MENU* para retornar)_"
            )

    prefixo_alerta = "[ALERTA_CLINICO] " if alerta_disparado else ""

    resposta = (
        f"{prefixo_alerta}Recebi e acolhi com total sigilo o seu registro diário do *10º Passo*.\n\n"
        "🌱 A prática diária de inventário pessoal fortalece a sua autonomia emocional. "
        "Este é um espaço de escuta e reflexão; não realizo diagnósticos nem avaliações clínicas. "
        "Leve essas percepções para a sua próxima sessão com o Dr. Responsável.\n\n"
        f"{ORIENTACAO_EMERGENCIA}\n"
        "_(Digite *MENU* a qualquer momento para voltar)_"
    )

    if alerta_disparado:
        resposta += (
            "\n\n⚠️ Percebo que você pode estar passando por um momento de muito sofrimento. "
            "Se houver risco imediato, procure ajuda agora: ligue *CVV 188* ou *SAMU 192*."
        )

    return resposta
