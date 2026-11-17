from core.config import openai_client, supabase_client
from core.nomenclatura import ACERVO

MODELO_EMBEDDING = "text-embedding-3-small"

# A RPC `buscar_literatura` aplica um limiar padrão alto e pode descartar
# trechos relevantes. Usamos um limiar mais permissivo (o conteúdo ainda é
# filtrado pelo ranking e pelo contexto entregue ao modelo).
LIMIAR_SIMILARIDADE = 0.3

TEXTO_PROMPT_ACERVO = (
    f"Você é o {ACERVO} do consultório do Dr. Responsável. "
    "Sua função é fornecer esclarecimentos teóricos, educativos e reflexivos com base nos textos, materiais e literatura "
    "do Dr. Responsável e na tradição dos 12 Passos. "
    "REGRAS ABSOLUTAS: NUNCA prescreva medicações, NUNCA faça diagnósticos e NUNCA dê ordens clínicas. "
    "Mantenha postura acolhedora, respeitosa e convide o paciente a aprofundar dúvidas na consulta com o médico."
)


def _buscar_trechos_acervo_rag(pergunta: str, limite: int = 5) -> list[str]:
    """
    Frente 3B: busca RAG nos textos do Dr. Responsável (Supabase), sem diagnosticar.
    Tenta RPC de busca semântica e, em fallback, busca textual na tabela de acervo.
    """
    if not supabase_client or not pergunta:
        return []

    trechos: list[str] = []

    # Tentativa 1: RPC semântica (ex.: match_acervo / match_documents) se embeddings estiverem configurados
    if openai_client:
        try:
            emb = openai_client.embeddings.create(
                model=MODELO_EMBEDDING,
                input=pergunta,
            )
            query_embedding = emb.data[0].embedding
            for rpc_name in (
                "buscar_literatura",
                "match_acervo",
                "match_acervo_medico",
                "match_documents",
                "match_literatura_chunks",
            ):
                parametros = {
                    "query_embedding": query_embedding,
                    "match_count": limite,
                }
                if rpc_name == "buscar_literatura":
                    parametros["match_threshold"] = LIMIAR_SIMILARIDADE
                try:
                    res = supabase_client.rpc(rpc_name, parametros).execute()
                    if res.data:
                        for item in res.data:
                            conteudo = (
                                item.get("conteudo")
                                or item.get("content")
                                or item.get("texto")
                                or item.get("chunk")
                                or ""
                            )
                            if conteudo:
                                trechos.append(str(conteudo).strip())
                        if trechos:
                            return trechos[:limite]
                except Exception:
                    continue
        except Exception as e:
            print(f"⚠️ [ACERVO] Falha na busca semântica (embeddings): {e}")

    # Tentativa 2: busca textual simples em tabelas comuns de acervo
    termos = " ".join([t for t in (pergunta or "").split() if len(t) > 2])[:120]
    for tabela, coluna in (
        ("literatura_chunks", "conteudo"),
        ("acervo_medico", "conteudo"),
        ("acervo", "conteudo"),
        ("acervo_clinico", "conteudo"),
        ("documentos_acervo", "content"),
    ):
        try:
            query = supabase_client.table(tabela).select(coluna)
            if termos:
                query = query.ilike(coluna, f"%{termos.split()[0]}%")
            res = query.limit(limite).execute()
            if res.data:
                for item in res.data:
                    conteudo = item.get(coluna) or ""
                    if conteudo:
                        trechos.append(str(conteudo).strip())
                if trechos:
                    return trechos[:limite]
        except Exception:
            continue

    return trechos[:limite]


def consultar_acervo_psicoeducativo(pergunta: str, nome_paciente: str = "Paciente") -> str:
    """
    Frente 3B - Acervo Psicoeducativo & Guia Clínico:
    consulta RAG nos textos do Dr. Responsável e gera devolutiva educativa e reflexiva,
    sem diagnóstico, prescrição ou ordens clínicas.
    """
    if not pergunta or len(pergunta.strip()) < 3:
        return (
            f"📚 *{ACERVO}*\n\n"
            "Por favor, me conte qual tema ou conceito você gostaria de pesquisar hoje "
            "(ex.: 'como lidar com a ansiedade à noite', 'o conceito do 10º Passo', 'sobriedade emocional')."
        )

    trechos = _buscar_trechos_acervo_rag(pergunta)
    contexto = ""
    if trechos:
        contexto = "\n\n---\nTrechos do acervo do Dr. Responsável (use como base, sem inventar):\n" + "\n\n".join(
            f"- {t[:1200]}" for t in trechos
        )

    if not openai_client:
        if trechos:
            previa = "\n\n".join(f"• {t[:300]}..." if len(t) > 300 else f"• {t}" for t in trechos[:3])
            return (
                f"📚 *{ACERVO}*\n\n"
                f"Encontrei estes trechos relacionados à sua busca:\n\n{previa}\n\n"
                "🌱 _Leve essas reflexões para o seu próximo diálogo com o Dr. Responsável ou com seu terapeuta._\n"
                "_(Digite *MENU* para retornar ao início)_"
            )
        return (
            f"📚 *{ACERVO}*: Recebi sua busca: \"{pergunta}\".\n\n"
            "Não foi possível consultar o acervo automaticamente neste momento. "
            "Anote sua dúvida para discutir com o Dr. Responsável no seu próximo encontro.\n"
            "_(Digite *MENU* para retornar ao menu principal)_"
        )

    try:
        resposta = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": TEXTO_PROMPT_ACERVO},
                {
                    "role": "user",
                    "content": (
                        f"O paciente {nome_paciente} perguntou: {pergunta}.\n"
                        "Forneça uma reflexão psicoeducativa neutra e acolhedora em até 3 parágrafos curtos, "
                        "baseando-se nos trechos do acervo quando disponíveis. "
                        "Não realize diagnóstico, não prescreva medicações e não dê ordens clínicas."
                        f"{contexto}"
                    ),
                },
            ],
            temperature=0.3,
            max_tokens=450,
        )
        conteudo = (resposta.choices[0].message.content or "").strip()

        return (
            f"📚 *{ACERVO}*\n\n"
            f"{conteudo}\n\n"
            "🌱 _Leve essas reflexões para o seu próximo diálogo com o Dr. Responsável ou com seu terapeuta._\n"
            "_(Digite *MENU* para retornar ao início)_"
        )

    except Exception as e:
        print(f"⚠️ [ACERVO] Erro na consulta ao acervo: {e}")
        if trechos:
            previa = "\n\n".join(f"• {t[:300]}..." if len(t) > 300 else f"• {t}" for t in trechos[:2])
            return (
                f"📚 *{ACERVO}*\n\n"
                "Não consegui gerar a síntese agora, mas encontrei trechos relacionados:\n\n"
                f"{previa}\n\n"
                "_(Digite *MENU* para retornar)_"
            )
        return (
            f"📚 *{ACERVO}*\n\n"
            "Não consegui consultar o acervo neste instante. Por favor, tente novamente em alguns instantes "
            "ou anote sua dúvida para discutir com o Dr. Responsável no seu próximo encontro."
        )
