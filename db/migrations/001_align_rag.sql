-- ============================================================
-- 001_align_rag.sql
-- Alinhamento do Acervo Psicoeducativo (RAG) com o runtime atual.
--
-- Contexto:
--   O banco possui a tabela public.literatura_chunks (conteudo + embedding).
--   O código tenta as RPCs: match_acervo, match_acervo_medico,
--   match_documents e match_literatura_chunks.
--
-- Requisitos:
--   - Extensão pgvector ativa.
--   - Coluna literatura_chunks.embedding do tipo vector(1536)
--     (compatível com text-embedding-3-small).
--
-- Idempotente: pode ser executado mais de uma vez.
-- ============================================================

create extension if not exists vector;

-- ------------------------------------------------------------
-- Índice vetorial para busca por similaridade de cosseno
-- ------------------------------------------------------------
create index if not exists idx_literatura_chunks_embedding
  on public.literatura_chunks
  using ivfflat (embedding vector_cosine_ops)
  with (lists = 100);

-- ------------------------------------------------------------
-- RPC principal
-- Assinatura esperada pelo runtime:
--   rpc("match_acervo", {"query_embedding": [...], "match_count": 5})
-- ------------------------------------------------------------
create or replace function public.match_acervo(
  query_embedding vector(1536),
  match_count int default 5
)
returns table (
  id uuid,
  content text,
  similarity float
)
language sql
stable
as $$
  select
    l.id,
    l.conteudo as content,
    1 - (l.embedding <=> query_embedding) as similarity
  from public.literatura_chunks l
  where l.embedding is not null
  order by l.embedding <=> query_embedding
  limit greatest(match_count, 1);
$$;

-- ------------------------------------------------------------
-- Aliases de compatibilidade (o runtime tenta múltiplos nomes)
-- ------------------------------------------------------------
create or replace function public.match_acervo_medico(
  query_embedding vector(1536),
  match_count int default 5
)
returns table (id uuid, content text, similarity float)
language sql
stable
as $$
  select * from public.match_acervo(query_embedding, match_count);
$$;

create or replace function public.match_documents(
  query_embedding vector(1536),
  match_count int default 5
)
returns table (id uuid, content text, similarity float)
language sql
stable
as $$
  select * from public.match_acervo(query_embedding, match_count);
$$;

create or replace function public.match_literatura_chunks(
  query_embedding vector(1536),
  match_count int default 5
)
returns table (id uuid, content text, similarity float)
language sql
stable
as $$
  select * from public.match_acervo(query_embedding, match_count);
$$;

-- ------------------------------------------------------------
-- Observações
-- ------------------------------------------------------------
-- 1) Se a dimensão do embedding não for 1536, ajuste a assinatura das funções
--    e recrie o índice vetorial de acordo com a dimensão real.
-- 2) As funções usam SQL puro e respeitam RLS da tabela base.
-- 3) A busca textual de fallback do runtime consulta diretamente
--    public.literatura_chunks (colunas conteudo/titulo_obra), não exigindo RPC.
