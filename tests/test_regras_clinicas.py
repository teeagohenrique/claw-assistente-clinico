from types import SimpleNamespace

import core.config as core_config
import services.diario_service as diario_service
import services.onboarding_service as onboarding_service
from services.diario_service import pode_registrar_diario_hoje, salvar_relato_diario_permanente
from services.onboarding_service import (
    TEXTO_TERMO_CONSENTIMENTO,
    avaliar_acesso_continuidade,
    direcionar_paciente_continuidade,
)


class _FakeQuery:
    def __init__(self, data):
        self._data = data

    def select(self, *args, **kwargs):
        return self

    def eq(self, *args, **kwargs):
        return self

    def gte(self, *args, **kwargs):
        return self

    def insert(self, *args, **kwargs):
        return self

    def execute(self):
        return SimpleNamespace(data=self._data)


class _FakeSupabase:
    def __init__(self, data):
        self._data = data
        self.last_table = None

    def table(self, name):
        self.last_table = name
        return _FakeQuery(self._data)


def test_bloqueio_sem_aceito(monkeypatch):
    # Garante que não haverá chamadas externas de persistência de sessão
    monkeypatch.setattr(core_config, "supabase_client", None)
    monkeypatch.setattr(onboarding_service, "supabase_client", None)
    sessao = {"modulo_ativo": "menu", "historico": []}
    paciente = {
        "id": 1,
        "nome": "Maria",
        "tipo_plano": "anual",
        "termo_aceito": False,
    }

    resposta = direcionar_paciente_continuidade("5511999999999", sessao, paciente)

    assert sessao["modulo_ativo"] == "aguardando_termo"
    assert "ACEITO" in resposta or "ACEITO" in TEXTO_TERMO_CONSENTIMENTO
    assert "Termo" in resposta or "TERMO" in resposta


def test_acesso_continuidade_vencido(monkeypatch):
    monkeypatch.setattr(core_config, "supabase_client", None)
    monkeypatch.setattr(onboarding_service, "supabase_client", None)
    sessao = {"modulo_ativo": "menu", "historico": []}
    paciente = {
        "id": 2,
        "nome": "Ana",
        "tipo_plano": "anual",
        "status_plano": "ativo",
        "data_vencimento_plano": "2025-01-01T00:00:00-03:00",
        "termo_aceito": True,
    }

    permitido, motivo = avaliar_acesso_continuidade(paciente)
    resposta = direcionar_paciente_continuidade("5511999999999", sessao, paciente)

    assert permitido is False
    assert motivo == "vencido"
    assert sessao["modulo_ativo"] == "menu"
    assert "chegou ao fim" in resposta


def test_acesso_continuidade_suspenso(monkeypatch):
    monkeypatch.setattr(core_config, "supabase_client", None)
    monkeypatch.setattr(onboarding_service, "supabase_client", None)
    sessao = {"modulo_ativo": "menu", "historico": []}
    paciente = {
        "id": 3,
        "nome": "Carlos",
        "tipo_plano": "anual",
        "status_plano": "suspenso",
        "data_vencimento_plano": "2030-01-01T00:00:00-03:00",
        "termo_aceito": True,
    }

    permitido, motivo = avaliar_acesso_continuidade(paciente)
    resposta = direcionar_paciente_continuidade("5511999999999", sessao, paciente)

    assert permitido is False
    assert motivo == "suspenso"
    assert "suspenso" in resposta


def test_acesso_continuidade_ativo_com_aceite_legado(monkeypatch):
    monkeypatch.setattr(core_config, "supabase_client", None)
    monkeypatch.setattr(onboarding_service, "supabase_client", None)
    sessao = {"modulo_ativo": "menu", "historico": []}
    paciente = {
        "id": 4,
        "nome": "Beatriz",
        "tipo_plano": "anual",
        "status_plano": "ativo",
        "data_vencimento_plano": "2030-01-01T00:00:00-03:00",
        # Campo legado: o aceite deve ser reconhecido mesmo sem `termo_aceito`
        "aceitou_termos": True,
    }

    permitido, motivo = avaliar_acesso_continuidade(paciente)
    resposta = direcionar_paciente_continuidade("5511999999999", sessao, paciente)

    assert permitido is True
    assert motivo == "ativo"
    assert sessao["modulo_ativo"] == "submenu_continuidade"
    assert "está ativo" in resposta


def test_trava_um_registro_diario_por_dia(monkeypatch):
    fake = _FakeSupabase(data=[{"id": 10, "criado_em": "2026-11-15T08:00:00-03:00"}])
    monkeypatch.setattr(core_config, "supabase_client", fake)
    monkeypatch.setattr(diario_service, "supabase_client", fake)

    pode, mensagem = pode_registrar_diario_hoje(paciente_id=123)

    assert pode is False
    assert "1 registro por dia" in mensagem
    assert "MENU" in mensagem


def test_disparo_alerta_clinico(monkeypatch):
    fake = _FakeSupabase(data=[])
    monkeypatch.setattr(core_config, "supabase_client", fake)
    monkeypatch.setattr(diario_service, "supabase_client", fake)

    resposta = salvar_relato_diario_permanente(
        paciente_id=123,
        whatsapp_paciente="5511999999999",
        relato="Estou pensando em suicidio, não aguento mais.",
    )

    assert resposta.startswith("[ALERTA_CLINICO]")
    assert "CVV" in resposta or "188" in resposta
    assert "192" in resposta


class _FakeUpdateQuery:
    def __init__(self, store):
        self._store = store

    def update(self, payload):
        self._store.append(payload)
        return self

    def eq(self, *args, **kwargs):
        return self

    def execute(self):
        return SimpleNamespace(data=[])


class _FakeUpdateSupabase:
    def __init__(self):
        self.updates = []

    def table(self, name):
        return _FakeUpdateQuery(self.updates)


def test_registrar_aceite_sincroniza_os_dois_pares_de_campos(monkeypatch):
    fake = _FakeUpdateSupabase()
    monkeypatch.setattr(onboarding_service, "supabase_client", fake)

    onboarding_service.registrar_aceite_termo("00000000-0000-0000-0000-000000000001")

    assert len(fake.updates) == 1
    payload = fake.updates[0]
    assert payload["termo_aceito"] is True
    assert payload["aceitou_termos"] is True
    assert payload["data_aceite_termo"] == payload["data_aceite_termos"]
    assert payload["versao_termo"] == onboarding_service.VERSAO_TERMO_ATUAL
