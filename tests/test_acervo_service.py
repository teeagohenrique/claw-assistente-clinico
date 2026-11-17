"""Compatibilidade do Acervo com a RPC real (`buscar_literatura`)."""

from types import SimpleNamespace

import services.acervo_service as acervo_service


class _FakeRpc:
    def __init__(self, data):
        self._data = data

    def execute(self):
        return SimpleNamespace(data=self._data)


class _FakeSupabase:
    def __init__(self, data):
        self._data = data
        self.calls = []

    def rpc(self, nome, params):
        self.calls.append((nome, params))
        if nome == "buscar_literatura":
            return _FakeRpc(self._data)
        raise AssertionError(f"RPC inesperada: {nome}")


class _FakeOpenAI:
    def __init__(self):
        self.embeddings = SimpleNamespace(
            create=lambda **kwargs: SimpleNamespace(
                data=[SimpleNamespace(embedding=[0.1] * 1536)]
            )
        )


def test_busca_usa_rpc_buscar_literatura_e_le_conteudo(monkeypatch):
    fake_supabase = _FakeSupabase(
        [
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "titulo_obra": "Sobriedade Emocional",
                "conteudo": "Trecho reflexivo sobre ansiedade e autocuidado.",
                "similarity": 0.91,
            }
        ]
    )
    monkeypatch.setattr(acervo_service, "supabase_client", fake_supabase)
    monkeypatch.setattr(acervo_service, "openai_client", _FakeOpenAI())

    trechos = acervo_service._buscar_trechos_acervo_rag("ansiedade à noite", limite=3)

    assert trechos == ["Trecho reflexivo sobre ansiedade e autocuidado."]
    assert [chamada[0] for chamada in fake_supabase.calls] == ["buscar_literatura"]
    assert fake_supabase.calls[0][1]["match_count"] == 3
    assert fake_supabase.calls[0][1]["match_threshold"] == acervo_service.LIMIAR_SIMILARIDADE
