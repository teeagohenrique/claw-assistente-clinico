import unittest

from core.config import calcular_idade, limpar_digitos
from core.nomenclatura import (
    ACERVO,
    CONSULTA_PONTUAL,
    ESPACO_DECIMO_PASSO_COMPLETO,
    PACIENTE_CONTINUIDADE,
    PROGRAMA_CONTINUIDADE_COMPLETO,
)
from routers.webhook import rotear_mensagem_paciente
from services.diario_service import analisar_urgencia_clinica


class TestCLAWMultiagente(unittest.TestCase):
    def test_01_limpar_digitos(self):
        self.assertEqual(limpar_digitos("123.456.789-00"), "12345678900")
        self.assertEqual(limpar_digitos("(11) 98765-4321"), "11987654321")
        self.assertEqual(limpar_digitos("sem digitos"), "")

    def test_02_analisar_urgencia_clinica(self):
        # Casos com gatilhos de urgência
        self.assertTrue(analisar_urgencia_clinica("estou desesperado e pensando em suicidio"))
        self.assertTrue(analisar_urgencia_clinica("quero acabar com a minha vida"))
        self.assertTrue(analisar_urgencia_clinica("não aguento mais viver"))

        # Casos seguros de rotina reflexiva
        self.assertFalse(analisar_urgencia_clinica("hoje foi um dia produtivo, consegui caminhar"))
        self.assertFalse(analisar_urgencia_clinica("senti um pouco de ansiedade, mas respirei fundo"))

    def test_03_fluxo_boas_vindas(self):
        resposta = rotear_mensagem_paciente("5511900000001", "olá", "João Silva")
        self.assertIn("João", resposta)
        self.assertIn(CONSULTA_PONTUAL, resposta)
        self.assertIn(PROGRAMA_CONTINUIDADE_COMPLETO, resposta)

    def test_04_fluxo_conhecer_programa(self):
        resposta = rotear_mensagem_paciente("5511900000002", "3", "João Silva")
        self.assertIn(PROGRAMA_CONTINUIDADE_COMPLETO, resposta)
        self.assertIn("Consulta Clínica Incluída", resposta)
        self.assertIn(ESPACO_DECIMO_PASSO_COMPLETO, resposta)
        self.assertIn(ACERVO, resposta)

    def test_05_fluxo_opcao_1_agendamento(self):
        resposta = rotear_mensagem_paciente("5511900000003", "1", "João Silva")
        self.assertIn(CONSULTA_PONTUAL, resposta)
        self.assertIn("quartas e quintas-feiras", resposta)

    def test_06_comando_universal_menu(self):
        resposta = rotear_mensagem_paciente("5511900000004", "menu", "João Silva")
        self.assertIn("menu principal", resposta)
        self.assertIn("1️⃣", resposta)
        self.assertIn(PACIENTE_CONTINUIDADE, resposta)

    def test_07_nomenclatura_sem_palavra_plano(self):
        textos = [
            PROGRAMA_CONTINUIDADE_COMPLETO,
            PACIENTE_CONTINUIDADE,
            ESPACO_DECIMO_PASSO_COMPLETO,
            ACERVO,
        ]
        for texto in textos:
            self.assertNotIn("plano", texto.lower())

    def test_08_calcular_idade(self):
        self.assertIsInstance(calcular_idade("1990-01-01"), int)


if __name__ == "__main__":
    unittest.main()
