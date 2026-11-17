"""Configuração comum dos testes.

Isola os testes de qualquer dependência externa (Supabase/OpenAI) e limpa o
estado em memória das sessões entre execuções. Assim, a suíte roda offline e
de forma determinística.
"""

import pytest

import core.config as core_config
import services.acervo_service as acervo_service
import services.agendamento_service as agendamento_service
import services.diario_service as diario_service
import services.onboarding_service as onboarding_service


@pytest.fixture(autouse=True)
def isolar_servicos_externos(monkeypatch):
    monkeypatch.setattr(core_config, "supabase_client", None)
    monkeypatch.setattr(core_config, "openai_client", None)

    for modulo in (onboarding_service, diario_service, acervo_service, agendamento_service):
        if hasattr(modulo, "supabase_client"):
            monkeypatch.setattr(modulo, "supabase_client", None)
        if hasattr(modulo, "openai_client"):
            monkeypatch.setattr(modulo, "openai_client", None)

    core_config.ESTADO_CONVERSAS_LOCAL.clear()
    yield
