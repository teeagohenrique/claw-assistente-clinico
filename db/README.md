# Banco de dados — Assistente Médico (CLAW)

Esta pasta concentra a documentação e os scripts SQL do Supabase.

## Arquivos

| Arquivo | Uso |
| :--- | :--- |
| `schema_atual.sql` | Referência (somente leitura): fotografia do schema atual do Supabase. |
| `migrations/001_align_rag.sql` | Padroniza o Acervo Psicoeducativo (pgvector + RPCs). Opcional: o runtime já usa `buscar_literatura`. |
| `migrations/002_remove_expurgo_diario.sql` | Remove a função `executar_expurgo_diario_psi` (proteção do prontuário). **Recomendado.** |
| `verify.sql` | Checklist de verificação em SQL (somente leitura). |

## Como aplicar

1. Abra o **SQL Editor** do Supabase.
2. Execute `migrations/001_align_rag.sql` (opcional, padroniza os nomes das RPCs).
3. Execute `migrations/002_remove_expurgo_diario.sql` (**obrigatório** para conformidade com a retenção de 20 anos).
4. Execute `verify.sql` e confira:
   - `literatura_chunks.embedding` com dimensão `vector(1536)` (compatível com `text-embedding-3-small`);
   - funções `buscar_literatura` e/ou `match_acervo` presentes;
   - **ausência** de `executar_expurgo_diario_psi`;
   - `chunks_com_embedding > 0` para habilitar busca semântica.

## RPCs do acervo

O runtime tenta, nesta ordem:

1. `buscar_literatura` (já existente no projeto, com `match_threshold` opcional);
2. `match_acervo` (criada por `001_align_rag.sql`);
3. `match_acervo_medico`, `match_documents`, `match_literatura_chunks` (aliases);
4. busca textual direta em `public.literatura_chunks` (fallback).

Todas as RPCs de busca semântica exigem `literatura_chunks.embedding` preenchido.

## Regras de retenção

- `diario_psi` é prontuário: **não** criar rotinas de `DELETE`/purge.
- O runtime grava `data_limite_expiracao = criado_em + 20 anos`.
- Backups e políticas de retenção devem preservar no mínimo 20 anos (CFM 1.821/2007 e LGPD).
