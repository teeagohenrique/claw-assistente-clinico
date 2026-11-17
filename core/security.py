import re

from core.config import WHATSAPP_TOKEN


def validar_token(token: str | None) -> bool:
    """Valida token simples de autenticação do webhook (Evolution API).

    Aceita o token no header/campo informado se corresponder ao WHATSAPP_TOKEN
    configurado. Se não houver token configurado no ambiente, não bloqueia
    (modo compatível para desenvolvimento).
    """
    esperado = (WHATSAPP_TOKEN or "").strip()
    if not esperado:
        return True
    if not token:
        return False
    recebido = token.strip()
    # Aceita com ou sem prefixo Bearer
    if recebido.lower().startswith("bearer "):
        recebido = recebido[7:].strip()
    return recebido == esperado


def normalizar_cpf(cpf: str | None) -> str:
    """Remove caracteres não numéricos do CPF."""
    return re.sub(r"\D", "", cpf or "")


def validar_cpf(cpf: str | None) -> bool:
    """Valida CPF por formato e dígitos verificadores."""
    cpf_num = normalizar_cpf(cpf)
    if len(cpf_num) != 11:
        return False
    if cpf_num == cpf_num[0] * 11:
        return False

    def _calc_digito(base: str, fator_inicial: int) -> int:
        soma = sum(int(d) * (fator_inicial - i) for i, d in enumerate(base))
        resto = (soma * 10) % 11
        return 0 if resto == 10 else resto

    d1 = _calc_digito(cpf_num[:9], 10)
    d2 = _calc_digito(cpf_num[:10], 11)
    return cpf_num[-2:] == f"{d1}{d2}"
