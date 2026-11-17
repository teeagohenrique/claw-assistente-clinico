import json
from datetime import datetime, timedelta

from agenda import (
    DIAS_ATENDIMENTO,
    FUSO_HORARIO,
    consultar_horarios_disponiveis,
)
from core.config import (
    calcular_idade,
    limpar_digitos,
    notificar_administradores,
    openai_client,
    supabase_client,
)
from core.nomenclatura import rotulo_modalidade
from services.onboarding_service import buscar_paciente_por_telefone_ou_cpf


def criar_solicitacao_atendimento(
    whatsapp_paciente: str,
    nome_paciente: str,
    cpf: str,
    data_nascimento: str,
    data_str: str,
    hora_str: str,
    rg: str = None,
    email: str = None,
    endereco_completo: str = None,
    cep: str = None,
    observacoes: str = "",
    tipo_consulta: str = "pontual",
) -> dict:
    """
    [FRENTE 1: CONSULTA CLÍNICA PONTUAL]
    Registra a solicitação de consulta, valida idade mínima (>=18 anos),
    verifica slots no Google Calendar e notifica o médico via WhatsApp para aprovação humana.
    """
    cpf_limpo = limpar_digitos(cpf)
    if len(cpf_limpo) != 11:
        return {
            "sucesso": False,
            "mensagem": "O CPF informado parece incompleto. Peça gentilmente os 11 dígitos do CPF.",
        }

    try:
        idade = calcular_idade(data_nascimento)
    except Exception:
        return {
            "sucesso": False,
            "mensagem": "Data de nascimento inválida. Peça novamente dia, mês e ano de nascimento.",
        }

    if idade < 18:
        return {
            "sucesso": False,
            "motivo": "menor_de_idade",
            "mensagem": (
                f"BLOQUEADO: O paciente tem {idade} anos. O Dr. Responsável atende EXCLUSIVAMENTE maiores de idade (>= 18 anos). "
                "Explique isso de forma gentil e acolhedora."
            ),
        }

    status_agenda = consultar_horarios_disponiveis(data_str)
    if not status_agenda.get("disponivel") or hora_str not in status_agenda.get("horarios_possiveis", []):
        return {
            "sucesso": False,
            "mensagem": f"O horário {hora_str} no dia {data_str} não está disponível. {status_agenda.get('mensagem', '')}",
        }

    agendamento_id = None
    dados_faltantes = []

    if supabase_client:
        try:
            pac_res = supabase_client.table("pacientes").select("*").eq("cpf", cpf_limpo).execute()

            dados_paciente = {
                "cpf": cpf_limpo,
                "telefone": whatsapp_paciente,
                "nome": nome_paciente,
                "data_nascimento": data_nascimento,
                "ultima_interacao": datetime.now(FUSO_HORARIO).isoformat(),
            }
            if rg:
                dados_paciente["rg"] = rg.strip()
            if email:
                dados_paciente["email"] = email.strip()
            if endereco_completo:
                dados_paciente["endereco_completo"] = endereco_completo.strip()
            if cep:
                dados_paciente["cep"] = cep.strip()

            if pac_res.data:
                paciente = pac_res.data[0]
                paciente_id = paciente["id"]
                supabase_client.table("pacientes").update(dados_paciente).eq("id", paciente_id).execute()
                paciente.update(dados_paciente)
            else:
                novo_pac = supabase_client.table("pacientes").insert(dados_paciente).execute()
                paciente = novo_pac.data[0]
                paciente_id = paciente["id"]

            if not paciente.get("rg"):
                dados_faltantes.append("RG")
            if not paciente.get("email"):
                dados_faltantes.append("E-mail")
            if not paciente.get("endereco_completo") or not paciente.get("cep"):
                dados_faltantes.append("Endereço completo com CEP")

            dt_naive = datetime.strptime(f"{data_str} {hora_str}", "%Y-%m-%d %H:%M")
            dt_inicio = dt_naive.replace(tzinfo=FUSO_HORARIO)
            dt_fim = dt_inicio + timedelta(hours=1)

            ag_res = (
                supabase_client.table("agendamentos")
                .insert(
                    {
                        "paciente_id": paciente_id,
                        "data_hora_inicio": dt_inicio.isoformat(),
                        "data_hora_fim": dt_fim.isoformat(),
                        "status": "pendente",
                    }
                )
                .execute()
            )
            if ag_res.data:
                agendamento_id = ag_res.data[0].get("id")

        except Exception as e:
            print(f"⚠️ Erro ao registrar paciente/agendamento no Supabase: {e}")

    id_curto = str(agendamento_id)[:8] if agendamento_id else cpf_limpo
    rotulo_plano = rotulo_modalidade(tipo_consulta)

    notificar_administradores(
        f"📋 *NOVA SOLICITAÇÃO ({id_curto})*\n"
        f"• *Modalidade:* {rotulo_plano}\n"
        f"• *Paciente:* {nome_paciente} ({idade} anos)\n"
        f"• *CPF:* {cpf_limpo} | *Tel:* {whatsapp_paciente}\n"
        f"• *Data:* {data_str} às {hora_str} (duração 1h)\n"
        f"• *Obs:* {observacoes or 'Nenhuma'}\n\n"
        f"Responda *APROVAR {id_curto}* ou *RECUSAR {id_curto}*."
    )

    aviso_complementar = ""
    if dados_faltantes:
        aviso_complementar = f" Faltam estes dados na ficha: {', '.join(dados_faltantes)}. Peça gentilmente após a confirmação."

    return {
        "sucesso": True,
        "mensagem": (
            f"Solicitação registrada com sucesso para {nome_paciente} ({rotulo_plano}) no dia {data_str} às {hora_str}. "
            f"Avise que o pedido foi enviado à equipe do Dr. Responsável para validação.{aviso_complementar}"
        ),
    }


def atualizar_dados_complementares(
    cpf: str,
    rg: str = None,
    email: str = None,
    endereco_completo: str = None,
    cep: str = None,
) -> dict:
    """Atualiza dados cadastrais adicionais exigidos pelo prontuário (RG, E-mail, CEP)."""
    cpf_limpo = limpar_digitos(cpf)
    if not supabase_client or len(cpf_limpo) != 11:
        return {"sucesso": False, "mensagem": "Não foi possível localizar o cadastro pelo CPF."}

    campos = {}
    if rg:
        campos["rg"] = rg.strip()
    if email:
        campos["email"] = email.strip()
    if endereco_completo:
        campos["endereco_completo"] = endereco_completo.strip()
    if cep:
        campos["cep"] = cep.strip()

    if not campos:
        return {"sucesso": False, "mensagem": "Nenhum dado novo informado."}

    try:
        supabase_client.table("pacientes").update(campos).eq("cpf", cpf_limpo).execute()
        return {"sucesso": True, "mensagem": "Dados complementares salvos com sucesso!"}
    except Exception as e:
        print(f"⚠️ Erro ao atualizar dados complementares: {e}")
        return {"sucesso": False, "mensagem": "Erro técnico ao salvar dados."}


TOOLS_AGENDAMENTO = [
    {
        "type": "function",
        "function": {
            "name": "consultar_agenda",
            "description": "Consulta horários livres na agenda do Dr. Responsável para uma data (AAAA-MM-DD).",
            "parameters": {
                "type": "object",
                "properties": {
                    "data": {"type": "string", "description": "Data no formato AAAA-MM-DD."}
                },
                "required": ["data"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "solicitar_agendamento",
            "description": "Registra consulta após o paciente escolher data/horário e passar Nome, CPF e Data de Nascimento.",
            "parameters": {
                "type": "object",
                "properties": {
                    "data": {"type": "string", "description": "Data da consulta (AAAA-MM-DD)."},
                    "hora": {"type": "string", "description": "Horário de início (HH:MM)."},
                    "nome_paciente": {"type": "string", "description": "Nome completo."},
                    "cpf": {"type": "string", "description": "CPF (11 dígitos)."},
                    "data_nascimento": {"type": "string", "description": "Data de nascimento (AAAA-MM-DD)."},
                    "rg": {"type": "string", "description": "RG."},
                    "email": {"type": "string", "description": "E-mail."},
                    "endereco_completo": {"type": "string", "description": "Endereço completo."},
                    "cep": {"type": "string", "description": "CEP."},
                    "observacoes": {"type": "string", "description": "Observações."},
                },
                "required": ["data", "hora", "nome_paciente", "cpf", "data_nascimento"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "salvar_dados_complementares",
            "description": "Atualiza RG, E-mail, Endereço ou CEP do paciente pelo CPF.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cpf": {"type": "string", "description": "CPF do paciente."},
                    "rg": {"type": "string", "description": "RG."},
                    "email": {"type": "string", "description": "E-mail."},
                    "endereco_completo": {"type": "string", "description": "Endereço."},
                    "cep": {"type": "string", "description": "CEP."},
                },
                "required": ["cpf"],
            },
        },
    },
]


def _gerar_calendario_referencia() -> str:
    hoje = datetime.now(FUSO_HORARIO).date()
    proximos_dias = []
    for i in range(15):
        dia = hoje + timedelta(days=i)
        if dia.weekday() in DIAS_ATENDIMENTO:
            proximos_dias.append(f"- {DIAS_ATENDIMENTO[dia.weekday()]}: {dia.strftime('%Y-%m-%d')}")
    return f"Hoje é {hoje.strftime('%Y-%m-%d')}.\nPróximas datas de atendimento:\n" + "\n".join(proximos_dias)


def processar_ia_agendamento(historico_conversas: list, numero_paciente: str, em_continuidade: bool = False) -> str:
    """Motor de IA da Frente 1 com Function Calling para conduzir agendamento humanizado."""
    if not openai_client:
        return "Olá! O serviço de agendamento está em manutenção temporária."

    paciente = buscar_paciente_por_telefone_ou_cpf(telefone=numero_paciente)
    contexto_cadastro = ""
    if paciente:
        contexto_cadastro = f"\n[CADASTRO LOCALIZADO]: Nome: {paciente.get('nome')}, CPF: {paciente.get('cpf')}, Nascimento: {paciente.get('data_nascimento')}."

    tipo_modalidade = "continuidade" if em_continuidade else "pontual"
    rotulo_aviso = rotulo_modalidade(tipo_modalidade)

    system_prompt = (
        f"Você é o Cláudio (Claw), assistente acolhedor do psiquiatra Dr. Responsável.\n"
        f"Modalidade atual deste agendamento: {rotulo_aviso}.\n\n"
        "REGRAS DE CONVERSA:\n"
        "- Linguagem humana, empática e acolhedora.\n"
        "- Escreva datas por extenso (ex: quarta-feira, 18 de novembro).\n"
        "- Consultas duram 1h, quartas e quintas, das 16:00 às 20:00.\n"
        "- Pacientes estritamente maiores de 18 anos.\n"
        "- Se o paciente escolher o horário e passar Nome, CPF e Nascimento, acione `solicitar_agendamento` imediatamente.\n"
        "- O paciente pode digitar 'MENU' ou 'VOLTAR' para regressar à tela inicial.\n\n"
        f"{_gerar_calendario_referencia()}"
        f"{contexto_cadastro}"
    )

    mensagens = [{"role": "system", "content": system_prompt}] + historico_conversas

    try:
        resposta = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=mensagens,
            tools=TOOLS_AGENDAMENTO,
            tool_choice="auto",
            temperature=0.5,
        )

        msg = resposta.choices[0].message

        if msg.tool_calls:
            mensagens.append(msg.model_dump(exclude_none=True))

            for tool_call in msg.tool_calls:
                nome_funcao = tool_call.function.name
                args = json.loads(tool_call.function.arguments)

                if nome_funcao == "consultar_agenda":
                    res = consultar_horarios_disponiveis(args["data"])
                elif nome_funcao == "solicitar_agendamento":
                    res = criar_solicitacao_atendimento(
                        whatsapp_paciente=numero_paciente,
                        nome_paciente=args["nome_paciente"],
                        cpf=args["cpf"],
                        data_nascimento=args["data_nascimento"],
                        data_str=args["data"],
                        hora_str=args["hora"],
                        rg=args.get("rg"),
                        email=args.get("email"),
                        endereco_completo=args.get("endereco_completo"),
                        cep=args.get("cep"),
                        observacoes=args.get("observacoes", ""),
                        tipo_consulta=tipo_modalidade,
                    )
                elif nome_funcao == "salvar_dados_complementares":
                    res = atualizar_dados_complementares(
                        cpf=args["cpf"],
                        rg=args.get("rg"),
                        email=args.get("email"),
                        endereco_completo=args.get("endereco_completo"),
                        cep=args.get("cep"),
                    )
                else:
                    res = {"erro": "Ferramenta desconhecida"}

                mensagens.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(res, ensure_ascii=False),
                    }
                )

            resposta_final = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=mensagens,
                temperature=0.5,
            )
            return resposta_final.choices[0].message.content.strip()

        return msg.content.strip()

    except Exception as e:
        print(f"⚠️ Erro no processamento da IA: {e}")
        return (
            "No momento não consegui acessar a agenda em tempo real. "
            "Por favor, tente novamente em instantes ou digite *MENU*."
        )
