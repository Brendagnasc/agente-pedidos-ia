"""Testa o loop do agente com um cliente falso, sem chamar a API."""

from types import SimpleNamespace

import pytest
from google.genai import errors, types

from agente_pedidos.agente import AgentePedidos
from agente_pedidos.loja import Loja


def _resposta_com_chamadas(*chamadas):
    partes = [types.Part(function_call=types.FunctionCall(name=n, args=a)) for n, a in chamadas]
    conteudo = types.Content(role="model", parts=partes)
    return SimpleNamespace(
        candidates=[SimpleNamespace(content=conteudo)],
        function_calls=[types.FunctionCall(name=n, args=a) for n, a in chamadas],
        text=None,
    )


def _resposta_texto(texto):
    conteudo = types.Content(role="model", parts=[types.Part(text=texto)])
    return SimpleNamespace(candidates=[SimpleNamespace(content=conteudo)], function_calls=None, text=texto)


class ClienteFalso:
    """Devolve respostas roteirizadas e guarda o que recebeu."""

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.recebido = []
        self.models = self

    def generate_content(self, model, contents, config):
        self.recebido.append(list(contents))
        return self.respostas.pop(0)


def test_executa_ferramentas_e_devolve_texto_final():
    cliente = ClienteFalso([
        _resposta_com_chamadas(("ver_cardapio", {"restaurante_id": "r1", "restricao": "vegano"})),
        _resposta_com_chamadas(("adicionar_item", {"item_id": "r1-04", "quantidade": 1})),
        _resposta_texto("Adicionei a Pizza Vegana ao carrinho."),
    ])
    agente = AgentePedidos(loja=Loja.carregar(), cliente=cliente, modelo="falso")

    resposta = agente.enviar("Quero uma pizza vegana do Forno da Praça")

    assert resposta == "Adicionei a Pizza Vegana ao carrinho."
    assert [c.nome for c in agente.chamadas] == ["ver_cardapio", "adicionar_item"]
    assert agente.loja.ver_carrinho()["itens"][0]["id"] == "r1-04"
    ultima_ida = cliente.recebido[-1][-1]
    assert ultima_ida.parts[0].function_response.name == "adicionar_item"


def test_erro_da_ferramenta_volta_para_o_modelo():
    cliente = ClienteFalso([
        _resposta_com_chamadas(("adicionar_item", {"item_id": "nao-existe"})),
        _resposta_texto("Esse item não existe."),
    ])
    agente = AgentePedidos(loja=Loja.carregar(), cliente=cliente, modelo="falso")

    agente.enviar("Adiciona o item X")

    resposta_ferramenta = cliente.recebido[-1][-1].parts[0].function_response.response
    assert "erro" in resposta_ferramenta


class ClienteSobrecarregado(ClienteFalso):
    """Falha com 503 para os modelos da lista `indisponiveis`."""

    def __init__(self, respostas, indisponiveis):
        super().__init__(respostas)
        self.indisponiveis = set(indisponiveis)
        self.modelos_chamados = []

    def generate_content(self, model, contents, config):
        self.modelos_chamados.append(model)
        if model in self.indisponiveis:
            raise errors.ServerError(503, {"error": {"code": 503, "message": "alta demanda", "status": "UNAVAILABLE"}})
        return super().generate_content(model, contents, config)


def test_tenta_de_novo_e_usa_modelo_reserva():
    cliente = ClienteSobrecarregado([_resposta_texto("Oi!")], indisponiveis={"principal"})
    agente = AgentePedidos(loja=Loja.carregar(), cliente=cliente, modelo="principal",
                           reservas=("reserva",), espera_inicial=0)

    assert agente.enviar("oi") == "Oi!"
    assert cliente.modelos_chamados == ["principal"] * 3 + ["reserva"]
    assert agente.modelo_usado == "reserva"


def test_erro_definitivo_nao_e_mascarado():
    class ClienteChaveInvalida(ClienteFalso):
        def generate_content(self, model, contents, config):
            raise errors.ClientError(400, {"error": {"code": 400, "message": "API key not valid", "status": "INVALID_ARGUMENT"}})

    agente = AgentePedidos(loja=Loja.carregar(), cliente=ClienteChaveInvalida([]), modelo="principal",
                           espera_inicial=0)
    with pytest.raises(errors.ClientError):
        agente.enviar("oi")


def test_para_depois_do_limite_de_passos():
    cliente = ClienteFalso([_resposta_com_chamadas(("ver_carrinho", {}))] * 20)
    agente = AgentePedidos(loja=Loja.carregar(), cliente=cliente, modelo="falso")

    resposta = agente.enviar("oi")

    assert "Desculpe" in resposta
    assert len(cliente.recebido) == 8
