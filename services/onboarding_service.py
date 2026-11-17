from datetime import date, datetime

from agenda import FUSO_HORARIO
from core.config import (
    ESTADO_CONVERSAS_LOCAL,
    limpar_digitos,
    supabase_client,
)
from core.nomenclatura import (
    ACERVO,
    CONSULTA_PONTUAL,
    ESPACO_DECIMO_PASSO_COMPLETO,
    PACIENTE_CONTINUIDADE,
    PROGRAMA_CONTINUIDADE,
    PROGRAMA_CONTINUIDADE_COMPLETO,
    TIPO_ACESSO_CONTINUIDADE,
    TIPO_ACESSO_PONTUAL,
)

TEXTO_TERMO_CONSENTIMENTO = (
    "📄 *TERMO DE ESCLARECIMENTO E CONSENTIMENTO DIGITAL*\n\n"
    f"Antes de liberarmos o seu acesso ao ambiente de {PROGRAMA_CONTINUIDADE}, confirme que está ciente de:\n\n"
    "1. Eu sou um assistente digital acolhedor, mas *NÃO realizo atendimento médico de urgência nem substituo a consulta médica presencial/online*.\n"
    f"2. O *{ESPACO_DECIMO_PASSO_COMPLETO}* é uma ferramenta assíncrona de inventário diário e reflexão contínua.\n"
    "3. Seus relatos são confidenciais e protegidos pela LGPD e pelo sigilo médico do Dr. Responsável.\n"
    "4. Em momentos de sofrimento agudo, recorra imediatamente ao *SAMU (192)* ou ao *CVV (188)*.\n\n"
    "Para validar seu acesso, por favor, responda digitando apenas: *ACEITO*"
)

TEXTO_APRESENTACAO_PROGRAMA = (
    f"🌿 *{PROGRAMA_CONTINUIDADE_COMPLETO}*\n\n"
    "Diferente do modelo tradicional que muitas vezes exige internações hospitalares dolorosas e o afastamento da família, "
    "o Dr. Responsável desenvolveu um acompanhamento intensivo e humanizado no conforto da sua própria casa (no lar).\n\n"
    "✨ *O que contempla o acompanhamento anual:*\n"
    "• *Consulta Clínica Incluída* com o Dr. Responsável.\n"
    "• *Condição Especial de Acompanhamento* para todas as consultas semanais e de retorno com o Dr. Responsável.\n"
    "• *Acesso Facilitado* a profissionais recomendados da rede multidisciplinar (psicólogos e terapeutas).\n"
    f"• *{ESPACO_DECIMO_PASSO_COMPLETO}:* Registro diário contínuo integrado ao seu acompanhamento.\n"
    f"• *{ACERVO}:* Livros, artigos e vídeos exclusivos produzidos pelo médico.\n\n"
    "*Condições de Acompanhamento:* definidas diretamente com a secretaria da clínica.\n\n"
    f"Deseja ingressar no {PROGRAMA_CONTINUIDADE} ou prefere agendar uma {CONSULTA_PONTUAL}?\n"
    f"_(Digite *1* para {CONSULTA_PONTUAL}, *2* se já é {PACIENTE_CONTINUIDADE} ou *MENU* para rever as opções)_"
)


# Versão vigente do termo de consentimento (persistida em pacientes.versao_termo)
VERSAO_TERMO_ATUAL = "v1.0"

# Valores possíveis de pacientes.status_plano
STATUS_CONTINUIDADE_ATIVA = "ativo"

# Mapeamento de estados legados (sessões já persistidas) para a nomenclatura atual
_ESTADOS_LEGADOS = {
    "aguardando_cpf_membro": "aguardando_cpf_continuidade",
    "submenu_membro": "submenu_continuidade",
    "literatura": "acervo",
}


def normalizar_modulo_ativo(modulo: str | None) -> str:
    """Converte nomes de estado legados para a nomenclatura vigente."""
    nome = (modulo or "menu").strip()
    return _ESTADOS_LEGADOS.get(nome, nome)


def carregar_sessao(whatsapp_paciente: str) -> dict:
    """Carrega o estado da sessão do paciente a partir do Supabase ou memória local."""
    sessao_padrao = {
        "modulo_ativo": "menu",
        "historico": [],
        "aguardando_cpf_para": None,
        "em_continuidade": False,
    }

    if supabase_client:
        try:
            res = (
                supabase_client.table("conversas")
                .select("historico, modulo_ativo")
                .eq("whatsapp_paciente", whatsapp_paciente)
                .execute()
            )
            if res.data:
                item = res.data[0]
                return {
                    "modulo_ativo": normalizar_modulo_ativo(item.get("modulo_ativo")),
                    "historico": item.get("historico") or [],
                    "aguardando_cpf_para": None,
                    "em_continuidade": False,
                }
        except Exception as e:
            print(f"⚠️ [ONBOARDING] Erro ao carregar sessão no Supabase: {e}")

    sessao_local = ESTADO_CONVERSAS_LOCAL.get(whatsapp_paciente)
    if sessao_local:
        sessao_local["modulo_ativo"] = normalizar_modulo_ativo(sessao_local.get("modulo_ativo"))
        return sessao_local
    return sessao_padrao


def salvar_sessao(whatsapp_paciente: str, sessao: dict):
    """Persiste o estado da conversa no Supabase e na memória local."""
    ESTADO_CONVERSAS_LOCAL[whatsapp_paciente] = sessao
    if supabase_client:
        try:
            supabase_client.table("conversas").upsert(
                {
                    "whatsapp_paciente": whatsapp_paciente,
                    "historico": sessao.get("historico", []),
                    "modulo_ativo": sessao.get("modulo_ativo", "menu"),
                }
            ).execute()
        except Exception as e:
            print(f"⚠️ [ONBOARDING] Erro ao salvar sessão no Supabase: {e}")


def buscar_paciente_por_telefone_ou_cpf(telefone: str = None, cpf: str = None) -> dict | None:
    """Busca o cadastro clínico do paciente pelo WhatsApp ou CPF."""
    if not supabase_client:
        return None
    try:
        if telefone:
            res = supabase_client.table("pacientes").select("*").eq("telefone", telefone).execute()
            if res.data:
                return res.data[0]
        if cpf:
            cpf_limpo = limpar_digitos(cpf)
            res = supabase_client.table("pacientes").select("*").eq("cpf", cpf_limpo).execute()
            if res.data:
                return res.data[0]
    except Exception as e:
        print(f"⚠️ [ONBOARDING] Erro ao buscar paciente: {e}")
    return None


def _valor_booleano(valor) -> bool:
    """Normaliza valores booleanos vindos do banco (bool, texto ou número)."""
    if valor is True:
        return True
    return str(valor).strip().lower() in {"true", "1", "aceito", "sim"}


def paciente_aceitou_termo(paciente: dict | None) -> bool:
    """Valida se o consentimento (ACEITO) está registrado no cadastro.

    O banco mantém dois pares de campos por compatibilidade histórica
    (`termo_aceito`/`data_aceite_termo` e `aceitou_termos`/`data_aceite_termos`).
    Basta que um deles esteja preenchido para considerar o aceite válido.
    """
    if not paciente:
        return False
    return any(
        _valor_booleano(paciente.get(campo))
        for campo in ("termo_aceito", "aceitou_termos")
    )


def registrar_aceite_termo(paciente_id: int):
    """Registra o consentimento digital (ACEITO) com data e hora exatas no banco.

    Atualiza simultaneamente os dois pares de campos de consentimento para manter
    o cadastro consistente, independentemente de qual deles o painel utiliza.
    """
    if supabase_client and paciente_id:
        try:
            agora_iso = datetime.now(FUSO_HORARIO).isoformat()
            supabase_client.table("pacientes").update(
                {
                    "termo_aceito": True,
                    "data_aceite_termo": agora_iso,
                    "aceitou_termos": True,
                    "data_aceite_termos": agora_iso,
                    "versao_termo": VERSAO_TERMO_ATUAL,
                }
            ).eq("id", paciente_id).execute()
        except Exception as e:
            print(f"⚠️ [ONBOARDING] Erro ao registrar aceite do termo: {e}")


def _converter_para_data(valor) -> date | None:
    """Converte datas/datetimes do Supabase (ISO ou date) para `date` local."""
    if not valor:
        return None
    if isinstance(valor, datetime):
        instante = valor
        if instante.tzinfo is not None:
            instante = instante.astimezone(FUSO_HORARIO)
        return instante.date()
    if isinstance(valor, date):
        return valor
    try:
        texto = str(valor).strip().replace("Z", "+00:00")
        instante = datetime.fromisoformat(texto)
        if instante.tzinfo is not None:
            instante = instante.astimezone(FUSO_HORARIO)
        return instante.date()
    except ValueError:
        print(f"⚠️ [ONBOARDING] Data de vencimento inválida: {valor!r}")
        return None


def avaliar_acesso_continuidade(paciente: dict | None) -> tuple[bool, str]:
    """Avalia se o paciente pode acessar o ambiente de continuidade.

    Critérios clínicos/administrativos:
      1. `tipo_plano == 'anual'` (adesão ao acompanhamento anual);
      2. `status_plano` ausente ou `'ativo'` (suspenso/cancelado bloqueia);
      3. `data_vencimento_plano` ausente ou no futuro (vencido bloqueia).

    Retorna `(permitido, motivo)`. O motivo é o código do bloqueio:
    `"ativo"`, `"sem_adesao"`, `"suspenso"` ou `"vencido"`.
    """
    if not paciente:
        return False, "sem_adesao"

    tipo_acesso = str(paciente.get("tipo_plano") or TIPO_ACESSO_PONTUAL).strip().lower()
    if tipo_acesso != TIPO_ACESSO_CONTINUIDADE:
        return False, "sem_adesao"

    status = str(paciente.get("status_plano") or STATUS_CONTINUIDADE_ATIVA).strip().lower()
    if status != STATUS_CONTINUIDADE_ATIVA:
        return False, "suspenso"

    vencimento = _converter_para_data(paciente.get("data_vencimento_plano"))
    if vencimento and vencimento < datetime.now(FUSO_HORARIO).date():
        return False, "vencido"

    return True, "ativo"


def direcionar_paciente_continuidade(numero_remetente: str, sessao: dict, paciente: dict) -> str:
    """
    Frente 2: valida a adesão ao acompanhamento anual (tipo, status e vencimento)
    e exige o aceite do termo (ACEITO) registrado no banco antes de liberar acesso.
    """
    nome = paciente.get("nome", "Paciente")
    permitido, motivo = avaliar_acesso_continuidade(paciente)

    if not permitido:
        sessao["modulo_ativo"] = "menu"
        salvar_sessao(numero_remetente, sessao)

        if motivo == "suspenso":
            return (
                f"Olá, *{nome}*! Localizamos o seu cadastro, mas o acesso ao "
                f"*{PROGRAMA_CONTINUIDADE}* encontra-se temporariamente suspenso.\n\n"
                "Por favor, fale com a secretaria do consultório para regularizar "
                "a sua situação e reativar os benefícios exclusivos."
            )

        if motivo == "vencido":
            return (
                f"Olá, *{nome}*! Seu ciclo de acompanhamento no "
                f"*{PROGRAMA_CONTINUIDADE}* chegou ao fim.\n\n"
                "Para renovar a sua permanência em continuidade e retomar o acesso ao "
                f"{ESPACO_DECIMO_PASSO_COMPLETO} e ao {ACERVO}, fale com a secretaria "
                "do consultório ou digite *3* para rever o programa."
            )

        return (
            f"Olá, *{nome}*! Localizamos o seu cadastro, "
            f"mas você ainda não possui adesão ativa ao *{PROGRAMA_CONTINUIDADE}*.\n\n"
            f"O acesso ao {ESPACO_DECIMO_PASSO_COMPLETO} e ao {ACERVO} é exclusivo para "
            f"{PACIENTE_CONTINUIDADE}.\n\n"
            f"{TEXTO_APRESENTACAO_PROGRAMA}"
        )

    # Validação obrigatória: só libera acesso se o ACEITO estiver registrado no banco
    if not paciente_aceitou_termo(paciente):
        sessao["modulo_ativo"] = "aguardando_termo"
        salvar_sessao(numero_remetente, sessao)
        return f"Olá, *{nome}*! Seja bem-vindo(a).\n\n{TEXTO_TERMO_CONSENTIMENTO}"

    sessao["modulo_ativo"] = "submenu_continuidade"
    salvar_sessao(numero_remetente, sessao)
    return (
        f"Que alegria te receber, *{nome}*! "
        f"Seu acesso ao *{PROGRAMA_CONTINUIDADE}* está ativo.\n\n"
        "Como deseja seguir hoje?\n\n"
        "1️⃣ *Agendar Consulta de Retorno* (Condição especial de acompanhamento)\n"
        f"2️⃣ *{ACERVO}*\n"
        f"3️⃣ *{ESPACO_DECIMO_PASSO_COMPLETO}* (Registrar inventário do dia)\n\n"
        "_Digite o número da opção desejada:_"
    )
