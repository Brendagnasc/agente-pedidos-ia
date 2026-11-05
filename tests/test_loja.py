import pytest

from agente_pedidos.loja import Loja


@pytest.fixture
def loja():
    return Loja.carregar()


def test_busca_por_culinaria_ignora_acento_e_maiuscula(loja):
    resultado = loja.buscar_restaurantes(culinaria="SAUDAVEL")
    assert [r["id"] for r in resultado["restaurantes"]] == ["r4"]


def test_busca_por_restricao_so_traz_quem_tem_opcao(loja):
    resultado = loja.buscar_restaurantes(restricao="vegano")
    ids = {r["id"] for r in resultado["restaurantes"]}
    assert ids == {"r1", "r2", "r3", "r4"}
    sem_gluten = loja.buscar_restaurantes(culinaria="japonesa", restricao="sem glúten")
    assert sem_gluten["restaurantes"][0]["itens_compativeis"] == 1


def test_restricao_desconhecida_vira_erro(loja):
    assert "erro" in loja.buscar_restaurantes(restricao="keto")


def test_cardapio_filtrado(loja):
    itens = loja.ver_cardapio("r1", restricao="vegano")["itens"]
    assert {i["id"] for i in itens} == {"r1-04", "r1-05", "r1-06"}


def test_adicionar_soma_quantidades_do_mesmo_item(loja):
    loja.adicionar_item("r1-01")
    carrinho = loja.adicionar_item("r1-01", quantidade=2)
    assert carrinho["itens"][0]["quantidade"] == 3
    assert carrinho["total_itens"] == pytest.approx(164.7)


def test_carrinho_nao_mistura_restaurantes(loja):
    loja.adicionar_item("r1-01")
    resposta = loja.adicionar_item("r2-01")
    assert "erro" in resposta and "Forno da Praça" in resposta["erro"]


def test_item_inexistente(loja):
    assert "erro" in loja.adicionar_item("r9-99")


def test_remover_parcial_e_total(loja):
    loja.adicionar_item("r2-04", quantidade=3)
    assert loja.remover_item("r2-04", quantidade=1)["itens"][0]["quantidade"] == 2
    vazio = loja.remover_item("r2-04")
    assert vazio["itens"] == [] and vazio["restaurante"] is None


def test_frete_depende_da_distancia(loja):
    loja.adicionar_item("r1-01")
    perto = loja.calcular_frete("Centro")["frete"]
    longe = loja.calcular_frete("saramenha")["frete"]
    assert perto < longe


def test_frete_gratis_acima_do_limite(loja):
    loja.adicionar_item("r1-03", quantidade=3)
    assert loja.calcular_frete("Barra")["frete"] == 0.0


def test_bairro_nao_atendido(loja):
    loja.adicionar_item("r1-01")
    assert "erro" in loja.calcular_frete("Copacabana")


def test_finalizar_respeita_pedido_minimo(loja):
    loja.adicionar_item("r3-05")
    resposta = loja.finalizar_pedido("Barra", "pix")
    assert "erro" in resposta and "Pedido mínimo" in resposta["erro"]


def test_finalizar_pedido_valido(loja):
    loja.adicionar_item("r2-02", quantidade=2)
    resposta = loja.finalizar_pedido("Pilar", "cartão")
    pedido = resposta["pedido"]
    assert resposta["status"] == "confirmado"
    assert pedido["forma_pagamento"] == "cartao"
    assert pedido["total"] == pytest.approx(pedido["total_itens"] + pedido["frete"])
    assert "erro" in loja.adicionar_item("r2-01")


def test_executar_valida_nome_e_argumentos(loja):
    assert "erro" in loja.executar("apagar_tudo", {})
    assert "erro" in loja.executar("adicionar_item", {"produto": "r1-01"})
    assert loja.executar("adicionar_item", {"item_id": "r1-05", "quantidade": 2.0})["total_itens"] == 13.0
