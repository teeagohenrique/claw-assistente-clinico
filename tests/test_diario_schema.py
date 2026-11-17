"""Contrato do runtime com o schema de diario_psi.

Garante que o código grava exatamente as colunas existentes no Supabase,
protegendo a compatibilidade com o banco real.
"""

from types import SimpleNamespace

import services.diario_service as diario_service


class _FakeQuery:
    def __init__(self, store):
        self._store = store

    def insert(self, payload):
        self._store.append(payload)
        return self

    def execute(self):
        return SimpleNamespace(data=[])


class _FakeSupabase:
    def __init__(self):
        self.inserts = []
        self.tables = []

    def table(self, nome):
        self.tables.append(nome)
        return _FakeQuery(self.inserts)


def test_payload_do_diario_respeita_schema_real(monkeypatch):
    fake = _FakeSupabase()
    monkeypatch.setattr(diario_service, "supabase_client", fake)

    resposta = diario_service.salvar_relato_diario_permanente(
        paciente_id="00000000-0000-0000-0000-000000000001",
        whatsapp_paciente="5511999999999",
        relato="Hoje consegui manter a calma durante uma conversa difícil.",
    )

    assert "10º Passo" in resposta
    assert fake.tables == ["diario_psi"]
    assert len(fake.inserts) == 1

    payload = fake.inserts[0]
    assert payload["paciente_id"] == "00000000-0000-0000-0000-000000000001"
    assert payload["relato_texto"].startswith("Hoje consegui")
    assert "criado_em" in payload
    assert "data_limite_expiracao" in payload
    assert "relato" not in payload
    assert "whatsapp_paciente" not in payload
    assert "alerta_emitido" not in payload
