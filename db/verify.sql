-- ============================================================
-- VERIFICAÇÃO DO SCHEMA — Assistente Médico (CLAW)
-- Rode este arquivo no SQL Editor do Supabase e compare as saídas
-- com o checklist operacional do projeto.
-- Somente leitura: não altera dados.
-- ============================================================

-- 1) Tabelas esperadas pelo runtime
select table_name
from information_schema.tables
where table_schema = 'public'
  and table_name in (
    'pacientes',
    'agendamentos',
    'diario_psi',
    'conversas',
    'literatura_chunks',
    'alertas_clinicos'
  )
order by table_name;

-- 2) Colunas de pacientes (acesso, termo e dados básicos)
select column_name, data_type, is_nullable, column_default
from information_schema.columns
where table_schema = 'public' and table_name = 'pacientes'
order by ordinal_position;

-- 3) Colunas de diario_psi (10º Passo)
select column_name, data_type, is_nullable, column_default
from information_schema.columns
where table_schema = 'public' and table_name = 'diario_psi'
order by ordinal_position;

-- 4) Colunas de agendamentos (status e aprovação)
select column_name, data_type, is_nullable, column_default
from information_schema.columns
where table_schema = 'public' and table_name = 'agendamentos'
order by ordinal_position;

-- 5) Valores válidos do enum de status dos agendamentos
select t.typname as enum_name, e.enumlabel as valor
from pg_type t
join pg_enum e on e.enumtypid = t.oid
where t.typname like '%status%'
order by t.typname, e.enumsortorder;

-- 6) Extensão pgvector ativa
select extname, extversion
from pg_extension
where extname = 'vector';

-- 7) Dimensão da coluna de embeddings do acervo
select
  table_name,
  column_name,
  udt_name,
  coalesce(
    (
      select atttypmod
      from pg_attribute a
      where a.attrelid = (quote_ident(table_schema) || '.' || quote_ident(table_name))::regclass
        and a.attname = column_name
    ),
    -1
  ) as atttypmod
from information_schema.columns
where table_schema = 'public'
  and table_name = 'literatura_chunks'
  and column_name = 'embedding';

-- 8) Funções RPC existentes (busca do acervo e expurgo indevido)
select routine_name
from information_schema.routines
where routine_schema = 'public'
  and routine_name in (
    'buscar_literatura',
    'match_acervo',
    'match_acervo_medico',
    'match_documents',
    'match_literatura_chunks',
    'executar_expurgo_diario_psi'
  )
order by routine_name;

-- 9) Volume atual do acervo e registros com embedding preenchido
select
  count(*) as total_chunks,
  count(embedding) as chunks_com_embedding
from public.literatura_chunks;

-- 10) Últimos registros do diário (amostra para conferir retenção e data)
select id, paciente_id, criado_em, data_limite_expiracao
from public.diario_psi
order by criado_em desc
limit 5;

-- 11) Agendamentos por status
select status, count(*) as total
from public.agendamentos
group by status
order by total desc;
