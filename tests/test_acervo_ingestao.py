"""Testes offline da fragmentação e extração do Acervo."""

from pathlib import Path

from services.acervo_ingestao import (
    dividir_em_blocos,
    extrair_texto,
    id_deterministico,
    montar_chunks,
)


def test_dividir_em_blocos_respeita_limite_e_sobreposicao():
    texto = "\n\n".join(
        f"Parágrafo {i} com uma reflexão clínica sobre sobriedade emocional." for i in range(1, 21)
    )

    blocos = dividir_em_blocos(texto, max_chars=300, overlap=60)

    assert len(blocos) > 1
    assert all(len(bloco) <= 300 for bloco in blocos)
    assert all(bloco.strip() for bloco in blocos)


def test_dividir_em_blocos_rejeita_parametros_inseguros():
    for max_chars, overlap in ((100, 0), (300, -1), (300, 300)):
        try:
            dividir_em_blocos("texto", max_chars=max_chars, overlap=overlap)
        except ValueError:
            continue
        raise AssertionError(f"Esperava ValueError para {max_chars=} {overlap=}")


def test_id_deterministico_e_estavel():
    primeiro = id_deterministico("Obra", "p. 1", 0)
    segundo = id_deterministico("Obra", "p. 1", 0)
    outro = id_deterministico("Obra", "p. 1", 1)

    assert primeiro == segundo
    assert primeiro != outro


def test_extrair_e_montar_chunks_de_txt(tmp_path: Path):
    arquivo = tmp_path / "reflexao.txt"
    arquivo.write_text(
        "Primeiro parágrafo sobre ansiedade.\n\nSegundo parágrafo sobre autocuidado.",
        encoding="utf-8",
    )

    paginas = extrair_texto(arquivo)
    registros = montar_chunks(arquivo, autor="Dr. Responsável", max_chars=400, overlap=40)

    assert paginas[0][1].startswith("Primeiro parágrafo")
    assert registros
    assert registros[0]["id"] == id_deterministico("reflexao", None, 0)
    assert registros[0]["titulo_obra"] == "reflexao"
    assert registros[0]["autor"] == "Dr. Responsável"
    assert registros[0]["pagina_ou_capitulo"] is None
    assert "ansiedade" in registros[0]["conteudo"]


def test_montar_chunks_de_markdown(tmp_path: Path):
    arquivo = tmp_path / "capitulo.md"
    arquivo.write_text("# Título\n\nConteúdo reflexivo sobre o 10º Passo.", encoding="utf-8")

    registros = montar_chunks(arquivo, titulo="Capítulo 1")

    assert len(registros) == 1
    assert registros[0]["titulo_obra"] == "Capítulo 1"
