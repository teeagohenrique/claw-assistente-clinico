from fastapi import APIRouter, Header, Request

from core.config import (
    ADMINISTRADORES,
    enviar_mensagem_whatsapp,
    notificar_administradores,
    supabase_client,
)
from core.nomenclatura import (
    ACERVO,
    CONSULTA_PONTUAL,
    ESPACO_DECIMO_PASSO_COMPLETO,
    PACIENTE_CONTINUIDADE,
    PROGRAMA_CONTINUIDADE,
    PROGRAMA_CONTINUIDADE_COMPLETO,
)
from core.security import normalizar_cpf, validar_cpf, validar_token
from routers.admin import processar_comando_admin
from services.acervo_service import (
    consultar_acervo_psicoeducativo,
)
from services.agendamento_service import processar_ia_agendamento
from services.diario_service import (
    pode_registrar_diario_hoje,
    salvar_relato_diario_permanente,
)
from services.onboarding_service import (
    TEXTO_APRESENTACAO_PROGRAMA,
    avaliar_acesso_continuidade,
    buscar_paciente_por_telefone_ou_cpf,
    carregar_sessao,
    direcionar_paciente_continuidade,
    paciente_aceitou_termo,
    registrar_aceite_termo,
    salvar_sessao,
)

router = APIRouter()


def _garantir_acesso_continuidade(
    numero_remetente: str, sessao: dict
) -> tuple[dict | None, str | None]:
    """Revalida o acesso antes de qualquer recurso exclusivo da continuidade.

    Evita que sessões antigas (ou adesões vencidas/suspensas) continuem acessando
    o 10º Passo e o Acervo Psicoeducativo. Retorna `(paciente, bloqueio)`:
    quando `bloqueio` não é nulo, a resposta já deve ser devolvida ao paciente.
    """
    paciente = buscar_paciente_por_telefone_ou_cpf(telefone=numero_remetente)
    if not paciente:
        sessao["modulo_ativo"] = "menu"
        salvar_sessao(numero_remetente, sessao)
        return None, (
            "Não localizamos um cadastro vinculado a este número. "
            "Fale com a secretaria do consultório para regularizar o seu acesso.\n\n"
            "_Digite *MENU* para retornar._"
        )

    permitido, _ = avaliar_acesso_continuidade(paciente)
    if not permitido or not paciente_aceitou_termo(paciente):
        return None, direcionar_paciente_continuidade(numero_remetente, sessao, paciente)

    return paciente, None


def rotear_mensagem_paciente(numero_remetente: str, texto_recebido: str, nome_contato: str) -> str:
    """
    [ORQUESTRADOR DE JORNADA DO PACIENTE]
    Conduz o paciente pelas 3 frentes com linguagem humanizada, acolhedora e segura.
    """
    texto_limpo = texto_recebido.strip().lower()
    sessao = carregar_sessao(numero_remetente)
    modulo_atual = sessao.get("modulo_ativo", "menu")

    # Comando universal de retorno ao menu
    if texto_limpo in {"menu", "voltar", "inicio", "início", "sair", "0"}:
        sessao["modulo_ativo"] = "menu"
        sessao["historico"] = []
        sessao["aguardando_cpf_para"] = None
        salvar_sessao(numero_remetente, sessao)
        primeiro_nome = nome_contato.split()[0] if nome_contato and nome_contato != "Paciente" else ""
        cumprimento = f", {primeiro_nome}" if primeiro_nome else ""
        return (
            f"Olá{cumprimento}! Retornamos ao menu principal do consultório do *Dr. Responsável*.\n\n"
            "Como posso te acolher hoje? Escolha uma das opções:\n\n"
            f"1️⃣ *{CONSULTA_PONTUAL}* (Atendimento individual com o Dr. Responsável)\n"
            f"2️⃣ *{PACIENTE_CONTINUIDADE}* (Acesso exclusivo ao acompanhamento contínuo)\n"
            f"3️⃣ *{PROGRAMA_CONTINUIDADE_COMPLETO}* (Tratamento intensivo no lar, sem internação)\n\n"
            "_Digite o número da opção desejada:_"
        )

    # -------------------------------------------------------------
    # ESTADO 1: NO MENU INICIAL
    # -------------------------------------------------------------
    if modulo_atual == "menu":
        # Opção 1: Consulta Clínica Pontual
        if texto_limpo == "1" or any(termo in texto_limpo for termo in ["consulta pontual", "marcar consulta", "agendar"]):
            sessao["modulo_ativo"] = "agendamento_pontual"
            sessao["historico"] = []
            sessao["em_continuidade"] = False
            salvar_sessao(numero_remetente, sessao)
            return (
                f"Perfeito! Vamos iniciar o agendamento da sua *{CONSULTA_PONTUAL}* com o Dr. Responsável.\n\n"
                "Para qual dia você gostaria de verificar a disponibilidade de horários? "
                "Lembrando que os atendimentos ocorrem às *quartas e quintas-feiras*, a partir das 16:00."
            )

        # Opção 2: Paciente em Continuidade Ativa
        elif texto_limpo == "2" or any(
            termo in texto_limpo
            for termo in ["já sou paciente", "ja sou paciente", "continuidade ativa", "sou paciente em continuidade"]
        ):
            paciente = buscar_paciente_por_telefone_ou_cpf(telefone=numero_remetente)
            if not paciente:
                sessao["modulo_ativo"] = "aguardando_cpf_continuidade"
                salvar_sessao(numero_remetente, sessao)
                return (
                    f"Que bom falar com você! Para localizarmos a sua ficha no *{PROGRAMA_CONTINUIDADE}*, "
                    "por favor, digite os *11 números do seu CPF*:"
                )
            return direcionar_paciente_continuidade(numero_remetente, sessao, paciente)

        # Opção 3: Conhecer o Programa
        elif texto_limpo == "3" or any(termo in texto_limpo for termo in ["conhecer", "programa", "sobre o programa", "valores"]):
            return TEXTO_APRESENTACAO_PROGRAMA

        # Saudações Humanizadas
        saudacoes = {"oi", "ola", "olá", "bom dia", "boa tarde", "boa noite", "tudo bem", "opa", "ola!", "oi!"}
        if texto_limpo in saudacoes:
            primeiro_nome = nome_contato.split()[0] if nome_contato and nome_contato != "Paciente" else ""
            cumprimento = f", {primeiro_nome}" if primeiro_nome else ""
            return (
                f"Olá{cumprimento}! Tudo bem com você? É uma alegria te receber por aqui.\n\n"
                "Sou o *Cláudio (Claw)*, assistente do consultório de psiquiatria e saúde mental do *Dr. Responsável*.\n\n"
                "Como posso te acolher hoje? Veja como posso te ajudar:\n\n"
                f"1️⃣ *{CONSULTA_PONTUAL}* (Atendimento individual com o Dr. Responsável)\n"
                f"2️⃣ *{PACIENTE_CONTINUIDADE}* (Acesso exclusivo ao acompanhamento contínuo)\n"
                f"3️⃣ *{PROGRAMA_CONTINUIDADE_COMPLETO}* (Tratamento intensivo no lar, sem internação)\n\n"
                "_Pode me contar com tranquilidade o que procura ou apenas digitar o número correspondente._"
            )

        return (
            "Compreendi a sua mensagem. Para que eu possa te orientar com precisão e calma, como prefere seguir?\n\n"
            f"1️⃣ *{CONSULTA_PONTUAL}*\n"
            f"2️⃣ *{PACIENTE_CONTINUIDADE}*\n"
            f"3️⃣ *{PROGRAMA_CONTINUIDADE_COMPLETO}*\n\n"
            "_Basta digitar 1, 2 ou 3._"
        )

    # -------------------------------------------------------------
    # ESTADO 2: AGUARDANDO CPF DE PACIENTE EM CONTINUIDADE
    # -------------------------------------------------------------
    if modulo_atual == "aguardando_cpf_continuidade":
        cpf_informado = normalizar_cpf(texto_recebido)
        if not validar_cpf(cpf_informado):
            return "Por gentileza, informe um *CPF válido* (11 dígitos) para localizarmos o seu acompanhamento."

        paciente = buscar_paciente_por_telefone_ou_cpf(cpf=cpf_informado)
        if not paciente:
            sessao["modulo_ativo"] = "menu"
            salvar_sessao(numero_remetente, sessao)
            return (
                f"Não localizamos uma adesão ativa com o CPF *{cpf_informado}* no *{PROGRAMA_CONTINUIDADE}*.\n\n"
                "Se você ainda não ingressou no acompanhamento, você pode:\n"
                f"• Digitar *1* para marcar uma *{CONSULTA_PONTUAL}* com o Dr. Responsável.\n"
                f"• Digitar *3* para conhecer todos os benefícios do *{PROGRAMA_CONTINUIDADE_COMPLETO}*."
            )

        if supabase_client and paciente.get("telefone") != numero_remetente:
            supabase_client.table("pacientes").update({"telefone": numero_remetente}).eq("id", paciente["id"]).execute()

        return direcionar_paciente_continuidade(numero_remetente, sessao, paciente)

    # -------------------------------------------------------------
    # ESTADO 3: SUBMENU EXCLUSIVO DO PACIENTE EM CONTINUIDADE ATIVA
    # -------------------------------------------------------------
    if modulo_atual == "submenu_continuidade":
        paciente, bloqueio = _garantir_acesso_continuidade(numero_remetente, sessao)
        if bloqueio:
            return bloqueio

        # Sub-opção 1: Agendar Retorno de Acompanhamento
        if texto_limpo == "1" or "consulta" in texto_limpo:
            sessao["modulo_ativo"] = "agendamento_continuidade"
            sessao["historico"] = []
            sessao["em_continuidade"] = True
            salvar_sessao(numero_remetente, sessao)
            return (
                "Perfeito! Identifiquei o seu benefício de *Acompanhamento Contínuo*.\n\n"
                "Para qual data você deseja verificar horários disponíveis para o seu retorno com o Dr. Responsável? "
                "(Quartas e quintas-feiras, das 16:00 às 20:00)."
            )

        # Sub-opção 2: Acervo Psicoeducativo & Guia Clínico
        elif texto_limpo == "2" or "acervo" in texto_limpo or "literatura" in texto_limpo:
            sessao["modulo_ativo"] = "acervo"
            salvar_sessao(numero_remetente, sessao)
            return (
                f"📚 *{ACERVO} do Dr. Responsável*\n\n"
                "Seja bem-vindo(a) ao seu acervo de leitura e psicoeducação. Aqui você pode explorar "
                "materiais autorais, artigos e reflexões preparados pelo Dr. Responsável.\n\n"
                "Sobre qual conceito, sentimento ou temática você gostaria de pesquisar hoje?\n"
                "_(Digite *MENU* para voltar)_"
            )

        # Sub-opção 3: Espaço do 10º Passo (Inventário Diário)
        elif texto_limpo == "3" or "10 passo" in texto_limpo or "diario" in texto_limpo or "diário" in texto_limpo:
            paciente_id = paciente.get("id") if paciente else None

            pode_registrar, msg_bloqueio = pode_registrar_diario_hoje(paciente_id)
            if not pode_registrar:
                return msg_bloqueio

            sessao["modulo_ativo"] = "diario"
            salvar_sessao(numero_remetente, sessao)
            return (
                f"🌱 *{ESPACO_DECIMO_PASSO_COMPLETO}*\n\n"
                "Este é o seu momento de serenidade para registrar como foi o seu dia, sentimentos e autoavaliações.\n\n"
                "Pode escrever livremente com o coração. Seu relato será guardado com sigilo absoluto no seu prontuário.\n\n"
                "🚨 _Lembrete de segurança: em caso de urgência, ligue 188 ou 192._"
            )

        else:
            return (
                f"Como {PACIENTE_CONTINUIDADE}, você pode:\n"
                "1️⃣ Agendar consulta de retorno\n"
                f"2️⃣ Acessar o {ACERVO}\n"
                f"3️⃣ Registrar o seu {ESPACO_DECIMO_PASSO_COMPLETO} de hoje\n\n"
                "_Por favor, digite 1, 2 ou 3 (ou MENU para sair)._"
            )

    # -------------------------------------------------------------
    # ESTADO 4: AGUARDANDO ACEITE DO TERMO LGPD
    # -------------------------------------------------------------
    if modulo_atual == "aguardando_termo":
        if "aceito" in texto_limpo:
            paciente = buscar_paciente_por_telefone_ou_cpf(telefone=numero_remetente)
            if not paciente:
                sessao["modulo_ativo"] = "menu"
                salvar_sessao(numero_remetente, sessao)
                return (
                    "✅ *Aceite registrado.*\n\n"
                    "Não localizamos um cadastro vinculado a este número. "
                    "Por favor, fale com a secretaria do consultório para vincularmos o seu acesso.\n\n"
                    "_Digite *MENU* para retornar._"
                )

            registrar_aceite_termo(paciente["id"])
            paciente["termo_aceito"] = True
            paciente["aceitou_termos"] = True
            return direcionar_paciente_continuidade(numero_remetente, sessao, paciente)
        else:
            return (
                "Para sua proteção ética e sigilo médico, é necessário que você concorde com os termos acima.\n\n"
                "Por favor, responda com a palavra *ACEITO* (ou digite *MENU* para retornar)."
            )

    # -------------------------------------------------------------
    # ESTADO 5: MOTOR DE AGENDAMENTO COM IA (PONTUAL OU RETORNO)
    # -------------------------------------------------------------
    if modulo_atual in {"agendamento_pontual", "agendamento_continuidade"}:
        em_cont = (modulo_atual == "agendamento_continuidade")
        sessao["historico"].append({"role": "user", "content": texto_recebido})
        resposta_ia = processar_ia_agendamento(sessao["historico"], numero_remetente, em_continuidade=em_cont)
        sessao["historico"].append({"role": "assistant", "content": resposta_ia})
        salvar_sessao(numero_remetente, sessao)
        return resposta_ia

    # -------------------------------------------------------------
    # ESTADO 6: ESPAÇO DO 10º PASSO (DIÁRIO PSI)
    # -------------------------------------------------------------
    if modulo_atual == "diario":
        paciente, bloqueio = _garantir_acesso_continuidade(numero_remetente, sessao)
        if bloqueio:
            return bloqueio
        paciente_id = paciente.get("id") if paciente else None

        pode_registrar, msg_bloqueio = pode_registrar_diario_hoje(paciente_id)
        if not pode_registrar:
            return msg_bloqueio

        return salvar_relato_diario_permanente(paciente_id, numero_remetente, texto_recebido)

    # -------------------------------------------------------------
    # ESTADO 7: ACERVO PSICOEDUCATIVO & GUIA CLÍNICO (RAG)
    # -------------------------------------------------------------
    if modulo_atual == "acervo":
        paciente, bloqueio = _garantir_acesso_continuidade(numero_remetente, sessao)
        if bloqueio:
            return bloqueio
        nome_paciente = paciente.get("nome", "Paciente") if paciente else "Paciente"
        return consultar_acervo_psicoeducativo(texto_recebido, nome_paciente)

    return "Olá! Como posso te acolher hoje? Digite *MENU* para visualizar nossas opções de atendimento."


# -------------------------------------------------------------
# ENDPOINT POST /webhook (EVOLUTION API)
# Roteamento: Admin (APROVAR/RECUSAR) | Frente 1 (agendamento)
#            | Frente 2 (continuidade, exige ACEITO no banco)
#            | Frente 3 (diário 10º passo / acervo)
# -------------------------------------------------------------
@router.post("/webhook")
async def webhook_whatsapp(
    request: Request,
    apikey: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
):
    token = apikey or authorization
    if not validar_token(token):
        return {"status": "erro", "motivo": "token_invalido"}

    dados = await request.json()

    try:
        data_obj = dados.get("data", {})
        key_data = data_obj.get("key", {})

        # Ignora mensagens enviadas pelo próprio bot
        if key_data.get("fromMe", False):
            return {"status": "ignorado", "motivo": "mensagem do bot"}

        # Ignora mensagens de grupos
        remote_jid = key_data.get("remoteJid", "")
        if "@g.us" in remote_jid:
            return {"status": "ignorado", "motivo": "grupo"}

        numero_remetente = remote_jid.split("@")[0]
        msg_obj = data_obj.get("message", {})
        texto_recebido = (
            msg_obj.get("conversation")
            or msg_obj.get("extendedTextMessage", {}).get("text")
            or ""
        ).strip()
        nome_contato = data_obj.get("pushName", "Paciente")

        if not numero_remetente or not texto_recebido:
            return {"status": "ignorado", "motivo": "sem texto ou numero"}

    except Exception as e:
        return {"status": "erro", "detalhes": str(e)}

    # 1. Comandos de Aprovação Médica/Administrativa
    if numero_remetente in ADMINISTRADORES:
        if processar_comando_admin(numero_remetente, texto_recebido):
            return {"status": "comando_admin_processado"}

    # 2. Processamento da Jornada do Paciente
    resposta = rotear_mensagem_paciente(numero_remetente, texto_recebido, nome_contato)

    # 3. Interceptação de Risco e Emergência Clínica
    if "[ALERTA_CLINICO]" in resposta:
        resposta = resposta.replace("[ALERTA_CLINICO]", "").strip()
        notificar_administradores(
            f"🚨 *ALERTA DE URGÊNCIA CLÍNICA*\n"
            f"Paciente: {nome_contato} ({numero_remetente})\n"
            f"Mensagem: {texto_recebido}"
        )

    # 4. Envio de Retorno via WhatsApp
    enviar_mensagem_whatsapp(numero_remetente, resposta)
    return {"status": "sucesso", "resposta": resposta}
