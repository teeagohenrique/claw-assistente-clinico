from datetime import datetime

from fastapi import APIRouter

from agenda import FUSO_HORARIO, agendar_consulta
from core.config import enviar_mensagem_whatsapp, supabase_client

router = APIRouter(prefix="/admin", tags=["admin"])


def processar_comando_admin(numero_admin: str, texto: str) -> bool:
    """Processa comandos APROVAR/RECUSAR enviados pelo médico via WhatsApp.

    Retorna True quando a mensagem foi tratada como comando administrativo.
    """
    partes = (texto or "").strip().split()
    if not partes:
        return False

    acao = partes[0].upper()
    if acao not in {"APROVAR", "RECUSAR"}:
        return False

    if len(partes) < 2:
        enviar_mensagem_whatsapp(
            numero_admin,
            "⚠️ Formato inválido. Use: *APROVAR [ID]* ou *RECUSAR [ID]*.",
        )
        return True

    id_busca = partes[1]

    if not supabase_client:
        enviar_mensagem_whatsapp(numero_admin, "⚠️ Supabase indisponível.")
        return True

    try:
        ag_res = (
            supabase_client.table("agendamentos")
            .select("*, pacientes(*)")
            .eq("status", "pendente")
            .order("criado_em", desc=True)
            .limit(50)
            .execute()
        )

        agendamento = next(
            (
                item
                for item in (ag_res.data or [])
                if str(item.get("id", "")).startswith(id_busca)
            ),
            None,
        )

        if not agendamento:
            enviar_mensagem_whatsapp(
                numero_admin,
                f"❌ Agendamento com identificador *{id_busca}* não localizado entre as solicitações pendentes.",
            )
            return True

        paciente = agendamento.get("pacientes", {}) or {}
        ag_id = agendamento["id"]
        tel_paciente = paciente.get("telefone")

        if acao == "APROVAR":
            dt_inicio = datetime.fromisoformat(agendamento["data_hora_inicio"])
            if dt_inicio.tzinfo is not None:
                dt_inicio = dt_inicio.astimezone(FUSO_HORARIO)
            data_str = dt_inicio.strftime("%Y-%m-%d")
            hora_str = dt_inicio.strftime("%H:%M")

            res_google = agendar_consulta(
                data_str=data_str,
                hora_str=hora_str,
                nome_paciente=paciente.get("nome", "Paciente"),
                email_paciente=paciente.get("email"),
                telefone_paciente=tel_paciente,
                cpf_paciente=paciente.get("cpf"),
            )

            if not res_google.get("sucesso"):
                enviar_mensagem_whatsapp(
                    numero_admin,
                    f"❌ Erro ao sincronizar com Google Agenda: {res_google.get('mensagem')}",
                )
                return True

            supabase_client.table("agendamentos").update(
                {
                    "status": "confirmado",
                    "google_event_id": res_google.get("evento_id"),
                    "aprovado_por": numero_admin,
                    "data_aprovacao": datetime.now(FUSO_HORARIO).isoformat(),
                    "atualizado_em": datetime.now(FUSO_HORARIO).isoformat(),
                }
            ).eq("id", ag_id).execute()
            enviar_mensagem_whatsapp(
                numero_admin,
                f"✅ Consulta de *{paciente.get('nome')}* em *{data_str} às {hora_str}* APROVADA.",
            )
            if tel_paciente:
                enviar_mensagem_whatsapp(
                    tel_paciente,
                    (
                        "🎉 *Consulta Confirmada!*\n\n"
                        f"Olá, {paciente.get('nome')}! Sua consulta com o Dr. Responsável foi confirmada para "
                        f"*{data_str} às {hora_str}*."
                    ),
                )

        elif acao == "RECUSAR":
            supabase_client.table("agendamentos").update(
                {
                    "status": "cancelado",
                    "aprovado_por": numero_admin,
                    "data_aprovacao": datetime.now(FUSO_HORARIO).isoformat(),
                    "atualizado_em": datetime.now(FUSO_HORARIO).isoformat(),
                }
            ).eq("id", ag_id).execute()
            enviar_mensagem_whatsapp(
                numero_admin,
                f"🚫 Solicitação de *{paciente.get('nome')}* foi RECUSADA.",
            )
            if tel_paciente:
                enviar_mensagem_whatsapp(
                    tel_paciente,
                    (
                        f"Olá, {paciente.get('nome')}. Não foi possível confirmar seu agendamento no horário solicitado. "
                        "Por favor, acesse o canal novamente para escolhermos uma nova data."
                    ),
                )

        return True

    except Exception as e:
        print(f"❌ [ADMIN] Erro ao processar comando: {e}")
        enviar_mensagem_whatsapp(numero_admin, f"❌ Erro técnico ao processar comando: {e}")
        return True
