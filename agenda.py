import os
from datetime import datetime, time, timedelta, timezone

from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/calendar"]
CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "google_credentials.json")
CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID")

# Fuso oficial da clínica (America/Recife). Fallback para UTC-3 caso a base
# de fusos IANA não esteja disponível no ambiente.
try:
    from zoneinfo import ZoneInfo

    FUSO_HORARIO = ZoneInfo("America/Recife")
except Exception:  # pragma: no cover - fallback de ambiente
    FUSO_HORARIO = timezone(timedelta(hours=-3))

# Regras de negócio do consultório
DIAS_ATENDIMENTO = {2: "Quarta-feira", 3: "Quinta-feira"}  # 0=Seg, 1=Ter, 2=Qua, 3=Qui
HORA_ABERTURA = time(16, 0)         # Primeiro horário possível de início
HORA_LIMITE_INICIO = time(20, 0)    # Último horário possível de início (termina às 21:00)
DURACAO_CONSULTA_MIN = 60           # 1 hora de consulta
INTERVALO_ANOTACOES_MIN = 30        # 30 minutos de pausa entre atendimentos


def _conectar_calendar():
    """Autentica via Service Account e retorna o cliente da Google Calendar API."""
    if not CALENDAR_ID:
        raise ValueError("GOOGLE_CALENDAR_ID não definido no arquivo .env")
    if not os.path.exists(CREDENTIALS_FILE):
        raise FileNotFoundError(f"Arquivo de credenciais não encontrado: {CREDENTIALS_FILE}")

    creds = service_account.Credentials.from_service_account_file(
        CREDENTIALS_FILE, scopes=SCOPES
    )
    return build("calendar", "v3", credentials=creds)


def _buscar_eventos_do_dia(service, data_alvo) -> list[tuple[datetime, datetime]]:
    """Retorna lista de tuplas (inicio, fim) dos eventos já marcados na data."""
    inicio_dia = datetime(data_alvo.year, data_alvo.month, data_alvo.day, 0, 0, tzinfo=FUSO_HORARIO)
    fim_dia = datetime(data_alvo.year, data_alvo.month, data_alvo.day, 23, 59, 59, tzinfo=FUSO_HORARIO)

    eventos_res = (
        service.events()
        .list(
            calendarId=CALENDAR_ID,
            timeMin=inicio_dia.isoformat(),
            timeMax=fim_dia.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    ocupados = []
    for evento in eventos_res.get("items", []):
        inicio_ev_str = evento["start"].get("dateTime")
        fim_ev_str = evento["end"].get("dateTime")
        if inicio_ev_str and fim_ev_str:
            ocupados.append(
                (
                    datetime.fromisoformat(inicio_ev_str),
                    datetime.fromisoformat(fim_ev_str),
                )
            )
    return ocupados


def _horario_esta_livre(slot_inicio: datetime, ocupados: list[tuple[datetime, datetime]]) -> bool:
    """
    Valida se uma consulta de 1h iniciando em `slot_inicio` respeita a janela
    (16h às 20h) e os 30 minutos de intervalo antes e depois de eventos existentes.
    """
    agora = datetime.now(FUSO_HORARIO)
    if slot_inicio <= agora:
        return False

    hora_local = slot_inicio.time()
    if hora_local < HORA_ABERTURA or hora_local > HORA_LIMITE_INICIO:
        return False

    slot_fim = slot_inicio + timedelta(minutes=DURACAO_CONSULTA_MIN)
    buffer = timedelta(minutes=INTERVALO_ANOTACOES_MIN)

    for ev_inicio, ev_fim in ocupados:
        bloqueio_inicio = ev_inicio - buffer
        bloqueio_fim = ev_fim + buffer
        if slot_inicio < bloqueio_fim and slot_fim > bloqueio_inicio:
            return False

    return True


def consultar_horarios_disponiveis(data_str: str) -> dict:
    """
    Consulta os horários livres para uma data específica ('YYYY-MM-DD').
    Calcula os horários ideais respeitando 1h de consulta + 30min de anotações.
    """
    try:
        data_alvo = datetime.strptime(data_str, "%Y-%m-%d").date()
    except ValueError:
        return {
            "disponivel": False,
            "horarios_sugeridos": [],
            "horarios_possiveis": [],
            "mensagem": "Formato de data inválido. Use AAAA-MM-DD (ex: 2026-11-18).",
        }

    dia_semana = data_alvo.weekday()
    if dia_semana not in DIAS_ATENDIMENTO:
        return {
            "disponivel": False,
            "data": data_str,
            "horarios_sugeridos": [],
            "horarios_possiveis": [],
            "mensagem": "Não há atendimento nessa data. As consultas ocorrem apenas às quartas e quintas-feiras, com início entre 16:00 e 20:00.",
        }

    service = _conectar_calendar()
    ocupados = _buscar_eventos_do_dia(service, data_alvo)

    inicio_janela = datetime.combine(data_alvo, HORA_ABERTURA, tzinfo=FUSO_HORARIO)
    fim_janela = datetime.combine(data_alvo, HORA_LIMITE_INICIO, tzinfo=FUSO_HORARIO)

    # 1. Todos os horários possíveis em passos de 30 min (ex: 16:00, 16:30 ... 20:00)
    horarios_possiveis = []
    ponteiro = inicio_janela
    while ponteiro <= fim_janela:
        if _horario_esta_livre(ponteiro, ocupados):
            horarios_possiveis.append(ponteiro.strftime("%H:%M"))
        ponteiro += timedelta(minutes=30)

    # 2. Grade otimizada (encaixa 1h de consulta + 30m de pausa sequencialmente)
    horarios_sugeridos = []
    ponteiro = inicio_janela
    while ponteiro <= fim_janela:
        if _horario_esta_livre(ponteiro, ocupados):
            horarios_sugeridos.append(ponteiro.strftime("%H:%M"))
            ponteiro += timedelta(minutes=DURACAO_CONSULTA_MIN + INTERVALO_ANOTACOES_MIN)
        else:
            ponteiro += timedelta(minutes=30)

    nome_dia = DIAS_ATENDIMENTO[dia_semana]
    if not horarios_possiveis:
        return {
            "disponivel": False,
            "data": data_str,
            "dia_semana": nome_dia,
            "horarios_sugeridos": [],
            "horarios_possiveis": [],
            "mensagem": f"Todos os horários de {nome_dia} ({data_str}) já estão ocupados.",
        }

    return {
        "disponivel": True,
        "data": data_str,
        "dia_semana": nome_dia,
        "horarios_sugeridos": horarios_sugeridos,
        "horarios_possiveis": horarios_possiveis,
        "mensagem": (
            f"Horários sugeridos em {nome_dia} ({data_str}): {', '.join(horarios_sugeridos)}. "
            f"(Outros inícios livres entre 16:00 e 20:00: {', '.join(horarios_possiveis)})"
        ),
    }


def agendar_consulta(
    data_str: str,
    hora_str: str,
    nome_paciente: str,
    telefone_paciente: str = "",
    observacoes: str = "",
    email_paciente: str | None = None,
    cpf_paciente: str | None = None,
    **kwargs,
) -> dict:
    """
    Cria o evento da consulta (1h de duração) no Google Calendar após validar
    os dias permitidos (quarta/quinta), janela (16h-20h) e margem de 30 minutos.
    Aceita campos extras (ex.: e-mail, CPF) para compatibilidade com fluxos administrativos.
    """
    try:
        data_alvo = datetime.strptime(data_str, "%Y-%m-%d").date()
        hora_alvo = datetime.strptime(hora_str.strip(), "%H:%M").time()
    except ValueError:
        return {
            "sucesso": False,
            "mensagem": "Data ou horário inválido. Use data AAAA-MM-DD e horário HH:MM (ex: 19:30).",
        }

    if data_alvo.weekday() not in DIAS_ATENDIMENTO:
        return {
            "sucesso": False,
            "mensagem": "Atendimentos ocorrem apenas às quartas e quintas-feiras.",
        }

    if hora_alvo < HORA_ABERTURA or hora_alvo > HORA_LIMITE_INICIO:
        return {
            "sucesso": False,
            "mensagem": "Horário fora do expediente. O início da consulta deve ser entre 16:00 e 20:00.",
        }

    inicio = datetime.combine(data_alvo, hora_alvo, tzinfo=FUSO_HORARIO)
    fim = inicio + timedelta(minutes=DURACAO_CONSULTA_MIN)
    fim_com_pausa = fim + timedelta(minutes=INTERVALO_ANOTACOES_MIN)

    try:
        service = _conectar_calendar()
        ocupados = _buscar_eventos_do_dia(service, data_alvo)
    except Exception as e:
        return {
            "sucesso": False,
            "mensagem": f"Não foi possível acessar a agenda no momento: {e}",
        }

    if not _horario_esta_livre(inicio, ocupados):
        return {
            "sucesso": False,
            "mensagem": (
                f"O horário {hora_alvo.strftime('%H:%M')} do dia {data_str} está indisponível "
                f"ou conflita com o intervalo obrigatório de 30 minutos entre consultas."
            ),
        }

    descricao_linhas = [
        f"Paciente: {nome_paciente}",
        f"WhatsApp: {telefone_paciente or 'não informado'}",
    ]
    if cpf_paciente:
        descricao_linhas.append(f"CPF: {cpf_paciente}")
    if email_paciente:
        descricao_linhas.append(f"E-mail: {email_paciente}")
    descricao_linhas.extend(
        [
            f"Duração da consulta: 1h (término às {fim.strftime('%H:%M')} + 30 min para anotações até {fim_com_pausa.strftime('%H:%M')})",
            f"Observações: {observacoes or 'Agendado automaticamente pelo Assistente'}",
        ]
    )

    evento = {
        "summary": f"Consulta - {nome_paciente}",
        "description": "\n".join(descricao_linhas),
        "start": {"dateTime": inicio.isoformat(), "timeZone": "America/Recife"},
        "end": {"dateTime": fim.isoformat(), "timeZone": "America/Recife"},
    }

    try:
        evento_criado = service.events().insert(calendarId=CALENDAR_ID, body=evento).execute()
    except Exception as e:
        return {
            "sucesso": False,
            "mensagem": f"Erro ao criar evento no Google Calendar: {e}",
        }

    return {
        "sucesso": True,
        "evento_id": evento_criado.get("id"),
        "link": evento_criado.get("htmlLink"),
        "mensagem": (
            f"Consulta confirmada para {nome_paciente} no dia {data_str} "
            f"das {inicio.strftime('%H:%M')} às {fim.strftime('%H:%M')}."
        ),
    }


if __name__ == "__main__":
    # Teste seguro apenas de leitura para a próxima quarta-feira (weekday == 2)
    hoje = datetime.now(FUSO_HORARIO).date()
    dias_ate_quarta = (2 - hoje.weekday()) % 7
    if dias_ate_quarta == 0:
        dias_ate_quarta = 7
    proxima_quarta = (hoje + timedelta(days=dias_ate_quarta)).strftime("%Y-%m-%d")

    print(f"Testando conexão real com Google Calendar para {proxima_quarta}...")
    resultado = consultar_horarios_disponiveis(proxima_quarta)
    print("Resultado:", resultado)