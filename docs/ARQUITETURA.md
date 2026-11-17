# Arquitetura — CLAW (Assistente Clínico Digital)

Documento técnico do runtime: componentes, fluxo de uma mensagem, modelo de
dados e decisões de projeto. Para instalação e operação, consulte o
[README](../README.md) e o [guia do banco](../db/README.md).

---

## 1. Objetivo e limites

O CLAW atende pacientes pelo WhatsApp e organiza três frentes:

1. **Consulta Clínica Pontual** — avaliação isolada, sem recursos contínuos.
2. **Programa de Continuidade Terapêutica** — acompanhamento com acesso ao
   Espaço do 10º Passo e ao Acervo Psicoeducativo.
3. **Acervo Psicoeducativo & Guia Clínico** — respostas educativas e reflexivas
   fundamentadas nos textos autorais do Dr. Responsável (RAG).

Limites clínicos, aplicados no código e nos prompts:

- a IA **não diagnostica**, **não prescreve** e **não substitui** consulta;
- o conteúdo do acervo é educativo e reflexivo, com convite ao atendimento;
- situações de risco são encaminhadas para **CVV 188** / **SAMU 192**.

---

## 2. Componentes

| Caminho | Responsabilidade |
| :--- | :--- |
| `main.py` | Aplicação FastAPI, healthcheck e registro do webhook. |
| `routers/webhook.py` | Jornada do paciente: sessão, menus, guarda de continuidade. |
| `routers/admin.py` | Comandos administrativos `APROVAR` / `RECUSAR`. |
| `services/onboarding_service.py` | Cadastro, consentimento e validação de acesso. |
| `services/agendamento_service.py` | Solicitações, slots e aprovação de consultas. |
| `services/diario_service.py` | Espaço do 10º Passo (1 relato por dia). |
| `services/acervo_service.py` | Busca RAG e composição da resposta educativa. |
| `services/acervo_ingestao.py` | Extração e fragmentação de textos (offline). |
| `core/config.py` | Clientes externos, variáveis de ambiente e helpers. |
| `core/nomenclatura.py` | Fonte única da verdade da nomenclatura do produto. |
| `core/security.py` | Token do webhook e validação de CPF. |
| `agenda.py` | Google Calendar: slots, buffer e fuso `America/Recife`. |
| `scripts/ingest_acervo.py` | CLI de ingestão (chunking + embeddings + Supabase). |
| `db/` | Schema de referência, migrações idempotentes e verificação. |

---

## 3. Fluxo de uma mensagem

```
Paciente (WhatsApp)
   │
   ▼
Evolution API ──POST /webhook──► routers/webhook.py
                                     │
                     core/security.py (token)
                                     │
                     sessão em public.conversas
                     (historico, modulo_ativo)
                                     │
                     onboarding_service
                     (termo + estado_atual)
                                     │
        ┌────────────────┬───────────┴────────────┬──────────────────┐
        ▼                ▼                        ▼                  ▼
 Consulta Pontual   Continuidade          Espaço do 10º Passo   Acervo (RAG)
        │                │                        │                  │
   agendamento      guarda de acesso        diario_service     acervo_service
        └────────────────┴───────────┬────────────┴──────────────────┘
                                     ▼
                        Resposta humanizada no WhatsApp
```

O **estado da conversa** fica em `public.conversas` (`historico`, `modulo_ativo`),
o que mantém o atendimento resiliente a reinícios do servidor.

### Guarda de continuidade

`avaliar_acesso_continuidade()` decide o acesso a recursos exclusivos com base em:

- `pacientes.tipo_plano` (`anual` = continuidade; `avulso` = pontual);
- `pacientes.status_plano`;
- `pacientes.data_vencimento_plano`;
- consentimento registrado.

A validação é **reexecutada a cada acesso** ao submenu, ao 10º Passo e ao acervo.
Assim, uma sessão antiga não contorna vencimento ou suspensão.

---

## 4. Modelo de dados

| Tabela | Papel | Campos relevantes |
| :--- | :--- | :--- |
| `pacientes` | Cadastro e vínculo terapêutico | `telefone`, `estado_atual`, `termo_aceito`/`data_aceite_termo`, `aceitou_termos`/`data_aceite_termos`, `tipo_plano`, `status_plano`, `data_vencimento_plano` |
| `agendamentos` | Consultas e aprovação | `data_hora_inicio/fim`, `status`, `google_event_id`, `aprovado_por` |
| `diario_psi` | Prontuário do 10º Passo | `relato_texto`, `liberado_para_medico`, `data_limite_expiracao`, `criado_em` |
| `literatura_chunks` | Base do Acervo (pgvector) | `titulo_obra`, `autor`, `pagina_ou_capitulo`, `conteudo`, `embedding` `vector(1536)` |
| `alertas_clinicos` | Notificações à equipe | `mensagem_gatilho`, `notificacao_enviada` |
| `conversas` | Sessão do WhatsApp | `whatsapp_paciente`, `historico`, `modulo_ativo` |

O schema de referência está em [`db/schema_atual.sql`](../db/schema_atual.sql).

---

## 5. Nomenclatura

`core/nomenclatura.py` é a única fonte dos termos exibidos ao paciente:

| Conceito | Termo oficial |
| :--- | :--- |
| Consulta isolada | Consulta Clínica Pontual |
| Acompanhamento | Programa de Continuidade Terapêutica (Método Dr. Responsável) |
| Paciente com acesso ativo | Paciente em Continuidade Ativa |
| Diário reflexivo | Espaço do 10º Passo (Inventário Reflexivo Diário) |
| Base de literatura | Acervo Psicoeducativo & Guia Clínico |

Os valores persistidos `avulso` / `anual` existem apenas por compatibilidade com
o banco e **nunca** são exibidos em mensagens.

---

## 6. Segurança e conformidade

- **Consentimento**: a gravação atualiza os dois pares de campos
  (`termo_aceito`/`data_aceite_termo` e `aceitou_termos`/`data_aceite_termos`)
  e `versao_termo`, mantendo compatibilidade com o schema.
- **Retenção de prontuário**: `diario_psi` não possui expurgo automático.
  A rotina `executar_expurgo_diario_psi` é removida pela migração
  `002_remove_expurgo_diario.sql`, em linha com CFM 1.821/2007 e LGPD.
- **Segredos**: credenciais vivem apenas no `.env` (ignorado pelo Git).
  O repositório versiona somente `.env.example` com placeholders.
- **Webhook**: token validado em `core/security.py`.
- **Dados sensíveis**: relatos do 10º Passo só são liberados ao médico quando
  `liberado_para_medico` é verdadeiro.

---

## 7. Acervo Psicoeducativo (RAG)

**Ingestão** (`scripts/ingest_acervo.py`):

1. extrai texto de PDF/DOCX/TXT/MD;
2. fragmenta em blocos de até 1200 caracteres com sobreposição de 200;
3. gera embeddings `text-embedding-3-small` (1536 dimensões);
4. grava em `literatura_chunks` via `upsert` com ID determinístico (`uuid5` de
   obra + página + posição), o que torna a reingestão idempotente.

**Consulta** (`services/acervo_service.py`):

- usa a RPC `buscar_literatura` com `match_threshold = 0.3`;
- se a RPC não existir/falhar, tenta aliases (`match_acervo`, `match_documents`,
  `match_literatura_chunks`) e, por fim, busca textual em `literatura_chunks`;
- a resposta é sempre educativa: cita a obra e convida a levar o tema à consulta.

---

## 8. Operação

```bash
# banco: ordem recomendada
db/migrations/001_align_rag.sql            # opcional (RPCs do acervo)
db/migrations/002_remove_expurgo_diario.sql # obrigatório
db/verify.sql                               # checklist

# acervo
python scripts/ingest_acervo.py --source acervo --dry-run

# aplicação
uvicorn main:app --reload

# qualidade
pytest -q
ruff check .
```

---

## 9. Decisões de projeto

| Decisão | Motivo |
| :--- | :--- |
| Nomenclatura centralizada em módulo | Evitar divergência entre WhatsApp, notificações e docs. |
| `tipo_plano` mantido como `avulso`/`anual` | Compatibilidade com o banco; tradução feita na borda de apresentação. |
| Revalidar acesso a cada recurso exclusivo | Impedir acesso residual após vencimento ou suspensão. |
| ID determinístico na ingestão | Reexecução segura, sem duplicar chunks. |
| RPC `buscar_literatura` com limiar 0.3 | O limiar padrão descartava trechos pertinentes. |
| Fuso `America/Recife` | Alinhar slots ao horário local da clínica. |
| Sem expurgo automático do diário | Obrigação legal de retenção de prontuário. |
