"""Fluxo administrativo APROVAR/RECUSAR.

Valida que a aprovação persiste status, google_event_id e auditoria,
sem depender de Supabase ou Google Calendar reais.
"""

from types import SimpleNamespace

import routers.admin as admin


class _FakeQuery:
    def __init__(self, dados, updates):
        self._dados = dados
        self._updates = updates
        self._filtros = {}

    def select(self, *args, **kwargs):
        return self

    def eq(self, campo, valor):
        self._filtros[campo] = valor
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def update(self, payload):
        self._updates.append(payload)
        return self

    def execute(self):
        return SimpleNamespace(data=self._dados)


class _FakeSupabase:
    def __init__(self, dados):
        self._dados = dados
        self.updates = []

    def table(self, nome):
        return _FakeQuery(self._dados, self.updates)


def test_aprovar_grava_status_e_google_event_id(monkeypatch):
    fake = _FakeSupabase(
        [
            {
                "id": "abcd1234-0000-0000-0000-000000000000",
                "data_hora_inicio": "2026-11-18T19:00:00-03:00",
                "pacientes": {
                    "nome": "Maria",
                    "telefone": "5511999999999",
                    "email": "maria@example.com",
                    "cpf": "12345678900",
                },
            }
        ]
    )

    monkeypatch.setattr(admin, "supabase_client", fake)
    monkeypatch.setattr(admin, "enviar_mensagem_whatsapp", lambda *a, **k: None)
    monkeypatch.setattr(
        admin,
        "agendar_consulta",
        lambda **kwargs: {"sucesso": True, "evento_id": "evt_123"},
    )

    tratado = admin.processar_comando_admin("5511888888888", "APROVAR abcd1234")

    assert tratado is True
    assert len(fake.updates) == 1
    atualizacao = fake.updates[0]
    assert atualizacao["status"] == "confirmado"
    assert atualizacao["google_event_id"] == "evt_123"
    assert atualizacao["aprovado_por"] == "5511888888888"
    assert "data_aprovacao" in atualizacao
    assert "atualizado_em" in atualizacao
