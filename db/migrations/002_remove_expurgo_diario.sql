-- ============================================================
-- 002_remove_expurgo_diario.sql
-- Remove a função de expurgo do prontuário (10º Passo).
--
-- Motivo clínico/legal:
--   diario_psi é prontuário e deve ser preservado por, no mínimo,
--   20 anos (CFM 1.821/2007 e LGPD). Qualquer rotina de DELETE
--   automático viola essa retenção.
--
-- Idempotente: pode ser executado mais de uma vez.
-- ============================================================

drop function if exists public.executar_expurgo_diario_psi();

-- Confirmação: não deve retornar nenhuma linha após a execução.
select routine_name
from information_schema.routines
where routine_schema = 'public'
  and routine_name = 'executar_expurgo_diario_psi';
