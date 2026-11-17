"""CLI de ingestão do Acervo Psicoeducativo & Guia Clínico.

Fluxo:
  1. lê PDF/DOCX/TXT/MD;
  2. fragmenta em blocos com sobreposição;
  3. gera embeddings com text-embedding-3-small;
  4. grava/atualiza em public.literatura_chunks.

Uso:
  python scripts/ingest_acervo.py --source acervo --dry-run
  python scripts/ingest_acervo.py --source acervo
  python scripts/ingest_acervo.py --source "acervo/livro.pdf" --titulo "Nome da Obra"

As credenciais são lidas do .env na raiz do projeto:
  OPENAI_API_KEY
  SUPABASE_URL
  SUPABASE_KEY (ou SUPABASE_SERVICE_KEY / SUPABASE_SECRET_KEY)
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from dotenv import load_dotenv  # noqa: E402

from services.acervo_ingestao import (  # noqa: E402
    AUTOR_PADRAO,
    EXTENSOES_SUPORTADAS,
    MAX_CHARS_PADRAO,
    OVERLAP_PADRAO,
    hash_conteudo,
    montar_chunks,
)

load_dotenv(RAIZ / ".env")

# Console do Windows (cp1252) não suporta emojis; força UTF-8 com fallback seguro.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

MODELO_PADRAO = "text-embedding-3-small"
DIMENSAO_PADRAO = 1536


def _parse_extensoes(valor: str) -> set[str]:
    extensoes = set()
    for item in valor.split(","):
        item = item.strip().lower()
        if not item:
            continue
        if not item.startswith("."):
            item = f".{item}"
        extensoes.add(item)
    invalidas = extensoes - EXTENSOES_SUPORTADAS
    if invalidas:
        raise argparse.ArgumentTypeError(
            f"Extensões não suportadas: {', '.join(sorted(invalidas))}. "
            f"Use: {', '.join(sorted(EXTENSOES_SUPORTADAS))}"
        )
    return extensoes


def _coletar_arquivos(fonte: Path, extensoes: set[str]) -> list[Path]:
    if fonte.is_file():
        if fonte.suffix.lower() not in extensoes:
            raise SystemExit(f"Arquivo com extensão não suportada: {fonte}")
        return [fonte]
    if not fonte.is_dir():
        raise SystemExit(f"Fonte não encontrada: {fonte}")

    arquivos = sorted(
        caminho
        for caminho in fonte.rglob("*")
        if caminho.is_file() and caminho.suffix.lower() in extensoes
    )
    if not arquivos:
        raise SystemExit(
            f"Nenhum arquivo encontrado em {fonte} com extensões: "
            f"{', '.join(sorted(extensoes))}"
        )
    return arquivos


def _criar_clientes():
    from openai import OpenAI
    from supabase import create_client

    openai_key = os.getenv("OPENAI_API_KEY")
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = (
        os.getenv("SUPABASE_SERVICE_KEY")
        or os.getenv("SUPABASE_SECRET_KEY")
        or os.getenv("SUPABASE_KEY")
    )

    faltando = [
        nome
        for nome, valor in (
            ("OPENAI_API_KEY", openai_key),
            ("SUPABASE_URL", supabase_url),
            ("SUPABASE_KEY", supabase_key),
        )
        if not valor
    ]
    if faltando:
        raise SystemExit(f"Variáveis ausentes no .env: {', '.join(faltando)}")

    return OpenAI(api_key=openai_key), create_client(supabase_url, supabase_key)


def _gerar_embeddings(
    openai_client,
    textos: list[str],
    modelo: str,
    lote: int,
    tentativas: int = 3,
) -> list[list[float]]:
    vetores: list[list[float]] = []

    for inicio in range(0, len(textos), lote):
        fatia = textos[inicio : inicio + lote]
        resposta = None

        for tentativa in range(1, tentativas + 1):
            try:
                resposta = openai_client.embeddings.create(model=modelo, input=fatia)
                break
            except Exception as e:
                if tentativa == tentativas:
                    raise RuntimeError(
                        f"Falha ao gerar embeddings após {tentativas} tentativas: {e}"
                    ) from e
                espera = 2**tentativa
                print(f"  ⚠️  Erro temporário nos embeddings; aguardando {espera}s...")
                time.sleep(espera)

        if resposta is None:
            raise RuntimeError("Resposta vazia da OpenAI ao gerar embeddings.")

        por_indice = sorted(resposta.data, key=lambda item: item.index)
        vetores.extend(item.embedding for item in por_indice)
        print(f"  🔢 Embeddings: {len(vetores)}/{len(textos)}")

    return vetores


def _enviar_ao_banco(supabase_client, registros: list[dict], lote: int) -> int:
    enviados = 0
    for inicio in range(0, len(registros), lote):
        fatia = registros[inicio : inicio + lote]
        supabase_client.table("literatura_chunks").upsert(
            fatia, on_conflict="id"
        ).execute()
        enviados += len(fatia)
        print(f"  💾 Gravados: {enviados}/{len(registros)}")
    return enviados


def _processar_arquivo(
    caminho: Path,
    args,
    openai_client,
    supabase_client,
) -> dict:
    titulo = args.titulo if args.titulo and args.source.is_file() else None
    registros = montar_chunks(
        caminho,
        titulo=titulo,
        autor=args.autor,
        max_chars=args.max_chars,
        overlap=args.overlap,
    )

    if args.limit:
        registros = registros[: args.limit]

    if not registros:
        print(f"⚠️  {caminho.name}: nenhum texto extraído (arquivo vazio ou digitalizado?).")
        return {"arquivo": caminho.name, "chunks": 0, "status": "vazio"}

    total_chars = sum(len(r["conteudo"]) for r in registros)
    media = total_chars // len(registros)
    print(
        f"📄 {caminho.name}: {len(registros)} blocos "
        f"(média {media} caracteres, hash {hash_conteudo(registros[0]['conteudo'])})"
    )

    if args.dry_run:
        return {"arquivo": caminho.name, "chunks": len(registros), "status": "dry-run"}

    titulo_obra = registros[0]["titulo_obra"]
    vetores = _gerar_embeddings(
        openai_client,
        [r["conteudo"] for r in registros],
        modelo=args.model,
        lote=args.embed_batch,
    )

    dimensao = len(vetores[0]) if vetores else 0
    if dimensao != args.dim:
        raise SystemExit(
            f"Dimensão do embedding ({dimensao}) diferente da coluna "
            f"literatura_chunks.embedding ({args.dim}). "
            "Use --model text-embedding-3-small ou ajuste a coluna no banco."
        )

    # Só remove os dados antigos depois que os embeddings foram gerados com sucesso.
    if args.replace:
        print(f"  🗑️  Removendo blocos antigos de “{titulo_obra}”...")
        supabase_client.table("literatura_chunks").delete().eq(
            "titulo_obra", titulo_obra
        ).execute()

    for registro, vetor in zip(registros, vetores, strict=True):
        registro["embedding"] = vetor

    enviados = _enviar_ao_banco(supabase_client, registros, lote=args.db_batch)
    return {"arquivo": caminho.name, "chunks": enviados, "status": "ok"}


def montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ingestão do Acervo Psicoeducativo no Supabase (pgvector)."
    )
    parser.add_argument(
        "--source",
        required=True,
        type=Path,
        help="Arquivo ou pasta com os materiais do Dr. Responsável.",
    )
    parser.add_argument(
        "--extensions",
        default=".pdf,.docx,.txt,.md",
        type=_parse_extensoes,
        help="Extensões aceitas (padrão: .pdf,.docx,.txt,.md).",
    )
    parser.add_argument("--titulo", help="Título da obra (apenas para um único arquivo).")
    parser.add_argument("--autor", default=AUTOR_PADRAO, help="Autor da obra.")
    parser.add_argument(
        "--max-chars",
        type=int,
        default=MAX_CHARS_PADRAO,
        help=f"Tamanho máximo do bloco (padrão: {MAX_CHARS_PADRAO}).",
    )
    parser.add_argument(
        "--overlap",
        type=int,
        default=OVERLAP_PADRAO,
        help=f"Sobreposição entre blocos (padrão: {OVERLAP_PADRAO}).",
    )
    parser.add_argument(
        "--model",
        default=MODELO_PADRAO,
        help=f"Modelo de embedding (padrão: {MODELO_PADRAO}).",
    )
    parser.add_argument(
        "--dim",
        type=int,
        default=DIMENSAO_PADRAO,
        help=f"Dimensão esperada da coluna vector (padrão: {DIMENSAO_PADRAO}).",
    )
    parser.add_argument(
        "--embed-batch",
        type=int,
        default=64,
        help="Textos por chamada à OpenAI (padrão: 64).",
    )
    parser.add_argument(
        "--db-batch",
        type=int,
        default=20,
        help="Registros por gravação no Supabase (padrão: 20).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limita blocos por arquivo (útil para testar).",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Apaga os blocos existentes da mesma obra antes de inserir.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Apenas extrai e fragmenta; não chama OpenAI nem grava no banco.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = montar_parser().parse_args(argv)
    args.source = args.source.expanduser().resolve()

    if args.titulo and not args.source.is_file():
        raise SystemExit("--titulo só pode ser usado com --source apontando para um arquivo.")

    arquivos = _coletar_arquivos(args.source, args.extensions)
    print(f"📚 {len(arquivos)} arquivo(s) encontrado(s) em {args.source}\n")

    openai_client = None
    supabase_client = None
    if not args.dry_run:
        openai_client, supabase_client = _criar_clientes()

    resultados = []
    for caminho in arquivos:
        try:
            resultados.append(
                _processar_arquivo(caminho, args, openai_client, supabase_client)
            )
        except SystemExit:
            raise
        except Exception as e:
            print(f"❌ {caminho.name}: {e}")
            resultados.append(
                {"arquivo": caminho.name, "chunks": 0, "status": "erro", "erro": str(e)}
            )

    total = sum(r["chunks"] for r in resultados)
    falhas = [r for r in resultados if r["status"] == "erro"]
    vazios = [r for r in resultados if r["status"] == "vazio"]

    print("\n" + "=" * 60)
    print(f"Total de blocos: {total}")
    print(f"Arquivos processados: {len(resultados) - len(falhas)}/{len(resultados)}")
    if vazios:
        print(f"Arquivos sem texto: {', '.join(r['arquivo'] for r in vazios)}")
    if falhas:
        print("Falhas:")
        for falha in falhas:
            print(f"  - {falha['arquivo']}: {falha['erro']}")
        return 1
    if args.dry_run:
        print("Modo dry-run: nada foi enviado ao banco.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
