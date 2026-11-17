import os
from datetime import datetime

import requests
from dotenv import load_dotenv
from openai import OpenAI
from supabase import Client, create_client

from agenda import FUSO_HORARIO

# Carrega variáveis de ambiente
load_dotenv()

# Credenciais e URLs
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
WHATSAPP_API_URL = os.getenv("WHATSAPP_API_URL")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")

# Clientes Externos
openai_client = OpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None

supabase_client: Client = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"❌ [CORE/CONFIG] Erro ao conectar no Supabase: {e}")

# Administradores da Clínica (nomenclatura atual + compatibilidade legada)
ADMINISTRADORES = {
    "".join(filter(str.isdigit, num))
    for num in [
        os.getenv("NUMERO_MEDICO_ADMIN"),
        os.getenv("NUMERO_RESPONSAVEL_TI"),
        os.getenv("NUMERO_MEDICO_LEGADO"),  # legado
        os.getenv("NUMERO_VOCE"),  # legado
    ]
    if num
}

# Cache local de conversas (fallback caso Supabase oscile)
ESTADO_CONVERSAS_LOCAL: dict[str, dict] = {}


# Funções Auxiliares Centrais
def limpar_digitos(texto: str) -> str:
    """Remove caracteres não numéricos de strings como CPF e Telefone."""
    return "".join(filter(str.isdigit, texto or ""))


def calcular_idade(data_nascimento_str: str) -> int:
    """Calcula a idade exata com base no fuso horário da clínica."""
    try:
        nascimento = datetime.strptime(data_nascimento_str, "%Y-%m-%d").date()
        hoje = datetime.now(FUSO_HORARIO).date()
        return hoje.year - nascimento.year - ((hoje.month, hoje.day) < (nascimento.month, nascimento.day))
    except Exception:
        return 0


# Comunicação WhatsApp (Evolution API)
def enviar_mensagem_whatsapp(numero_destino: str, texto: str):
    """Envia mensagem pelo WhatsApp via Evolution API com fallback seguro."""
    if not WHATSAPP_API_URL or not WHATSAPP_TOKEN or "sua-api-whatsapp" in WHATSAPP_API_URL:
        print(f"📲 [SIMULAÇÃO WHATSAPP -> {numero_destino}]:\n{texto}\n")
        return

    url = f"{WHATSAPP_API_URL}/message/sendText/instancia-medica"
    headers = {"apikey": WHATSAPP_TOKEN, "Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    payload = {"number": numero_destino, "text": texto}

    try:
        requests.post(url, json=payload, headers=headers, timeout=10)
    except Exception as e:
        print(f"❌ [CORE/CONFIG] Erro ao enviar WhatsApp para {numero_destino}: {e}")


def notificar_administradores(mensagem: str):
    """Dispara notificações de urgência ou aprovações para todos os administradores cadastrados."""
    for numero in ADMINISTRADORES:
        enviar_mensagem_whatsapp(numero, mensagem)
