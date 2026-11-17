"""Extração e fragmentação de textos para o Acervo Psicoeducativo.

Este módulo é puro (sem rede) e concentra as regras de:
- extração de texto de PDF, DOCX, TXT e Markdown;
- fragmentação em blocos com sobreposição (overlap);
- geração de IDs determinísticos para ingestão idempotente.

O envio para o Supabase e a geração de embeddings ficam no CLI
`scripts/ingest_acervo.py`, mantendo esta parte testável offline.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path

AUTOR_PADRAO = "Dr. Responsável"
EXTENSOES_SUPORTADAS = {".pdf", ".docx", ".txt", ".md"}
MAX_CHARS_PADRAO = 1200
OVERLAP_PADRAO = 200


def normalizar_texto(texto: str) -> str:
    """Normaliza espaços e quebras de linha preservando parágrafos."""
    texto = (texto or "").replace("\r\n", "\n").replace("\r", "\n")
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def _paragrafos(texto: str) -> list[str]:
    """Divide o texto em parágrafos por linhas em branco."""
    return [p.strip() for p in re.split(r"\n\s*\n", normalizar_texto(texto)) if p.strip()]


def _fatiar_paragrafo(paragrafo: str, limite: int) -> list[str]:
    """Divide um parágrafo muito longo em partes menores, respeitando frases."""
    if len(paragrafo) <= limite:
        return [paragrafo]

    frases = re.split(r"(?<=[.!?…])\s+", paragrafo)
    partes: list[str] = []
    atual = ""

    for frase in frases:
        if len(frase) > limite:
            if atual:
                partes.append(atual.strip())
                atual = ""
            for inicio in range(0, len(frase), limite):
                partes.append(frase[inicio : inicio + limite].strip())
            continue

        candidato = f"{atual} {frase}".strip() if atual else frase
        if len(candidato) <= limite:
            atual = candidato
        else:
            partes.append(atual.strip())
            atual = frase

    if atual.strip():
        partes.append(atual.strip())
    return [p for p in partes if p]


def _cauda(texto: str, overlap: int) -> str:
    """Retorna o final do bloco, cortado em limite de palavra, para sobreposição."""
    if overlap <= 0 or not texto:
        return ""
    cauda = texto[-overlap:]
    if " " in cauda:
        cauda = cauda.split(" ", 1)[1]
    return cauda.strip()


def dividir_em_blocos(
    texto: str,
    max_chars: int = MAX_CHARS_PADRAO,
    overlap: int = OVERLAP_PADRAO,
) -> list[str]:
    """Fragmenta o texto em blocos de até `max_chars`, com sobreposição opcional."""
    if max_chars < 200:
        raise ValueError("max_chars deve ser >= 200 para preservar contexto clínico.")
    if overlap < 0 or overlap >= max_chars:
        raise ValueError("overlap deve ser >= 0 e menor que max_chars.")

    blocos: list[str] = []
    atual = ""
    limite_parte = max_chars - overlap if overlap else max_chars

    for paragrafo in _paragrafos(texto):
        for parte in _fatiar_paragrafo(paragrafo, limite_parte):
            candidato = f"{atual}\n\n{parte}" if atual else parte
            if len(candidato) <= max_chars:
                atual = candidato
                continue

            if atual:
                blocos.append(atual.strip())

            cauda = _cauda(atual, overlap)
            atual = f"{cauda}\n\n{parte}".strip() if cauda else parte

            # Segurança: se a sobreposição + parte exceder o limite, recomeça sem cauda.
            if len(atual) > max_chars:
                if cauda:
                    blocos.append(cauda)
                atual = parte

    if atual.strip():
        blocos.append(atual.strip())

    return [bloco for bloco in blocos if bloco]


def id_deterministico(titulo: str, pagina: str | None, indice: int) -> str:
    """Gera um UUID estável para permitir reingestão sem duplicar registros.

    O ID depende apenas da obra, da página/capítulo e da posição do bloco.
    Assim, ao corrigir um texto e rodar novamente, o mesmo registro é atualizado.
    """
    base = f"{titulo.strip()}|{pagina or ''}|{indice}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, base))


def _ler_txt(caminho: Path) -> str:
    try:
        return caminho.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return caminho.read_text(encoding="latin-1")


def _extrair_pdf(caminho: Path) -> list[tuple[str | None, str]]:
    try:
        from pypdf import PdfReader
    except ImportError as e:  # pragma: no cover - depende de instalação opcional
        raise RuntimeError(
            "Para ler PDFs instale as dependências de ingestão: "
            "pip install -r requirements-ingest.txt"
        ) from e

    leitor = PdfReader(str(caminho))
    paginas: list[tuple[str | None, str]] = []
    for numero, pagina in enumerate(leitor.pages, start=1):
        texto = pagina.extract_text() or ""
        if texto.strip():
            paginas.append((f"p. {numero}", texto))
    return paginas


def _extrair_docx(caminho: Path) -> list[tuple[str | None, str]]:
    try:
        from docx import Document
    except ImportError as e:  # pragma: no cover - depende de instalação opcional
        raise RuntimeError(
            "Para ler DOCX instale as dependências de ingestão: "
            "pip install -r requirements-ingest.txt"
        ) from e

    documento = Document(str(caminho))
    texto = "\n\n".join(p.text for p in documento.paragraphs if p.text.strip())
    return [(None, texto)] if texto.strip() else []


def extrair_texto(caminho: Path) -> list[tuple[str | None, str]]:
    """Extrai `(pagina_ou_capitulo, texto)` de um arquivo suportado."""
    caminho = Path(caminho)
    extensao = caminho.suffix.lower()

    if extensao == ".pdf":
        return _extrair_pdf(caminho)
    if extensao == ".docx":
        return _extrair_docx(caminho)
    if extensao in {".txt", ".md"}:
        return [(None, _ler_txt(caminho))]
    raise ValueError(f"Extensão não suportada: {extensao}")


def montar_chunks(
    caminho: Path,
    titulo: str | None = None,
    autor: str = AUTOR_PADRAO,
    max_chars: int = MAX_CHARS_PADRAO,
    overlap: int = OVERLAP_PADRAO,
) -> list[dict]:
    """Monta os registros prontos para ingestão (sem embeddings)."""
    caminho = Path(caminho)
    titulo_obra = (titulo or caminho.stem).strip()
    autor = (autor or AUTOR_PADRAO).strip()

    registros: list[dict] = []
    indice = 0

    for pagina, texto in extrair_texto(caminho):
        for bloco in dividir_em_blocos(texto, max_chars=max_chars, overlap=overlap):
            registros.append(
                {
                    "id": id_deterministico(titulo_obra, pagina, indice),
                    "titulo_obra": titulo_obra,
                    "autor": autor,
                    "pagina_ou_capitulo": pagina,
                    "conteudo": bloco,
                }
            )
            indice += 1

    return registros


def hash_conteudo(texto: str) -> str:
    """Hash estável do conteúdo (útil para logs e auditoria)."""
    return hashlib.sha256((texto or "").encode("utf-8")).hexdigest()[:12]
