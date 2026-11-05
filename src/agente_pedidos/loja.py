"""Regras de negócio do pedido: cardápio, carrinho, frete e finalização.

Cada método público é uma ferramenta que o agente pode chamar. Erros de uso
(item inexistente, restaurante diferente no carrinho etc.) voltam como
{"erro": "..."} em vez de exceção, para o modelo conseguir se corrigir.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

CARDAPIO_PADRAO = Path(__file__).resolve().parents[2] / "data" / "cardapio.json"

RESTRICOES = {"vegetariano", "vegano", "sem_gluten", "sem_lactose"}
FORMAS_PAGAMENTO = {"pix", "cartao", "dinheiro"}
CUSTO_POR_KM = 1.5
FRETE_GRATIS_A_PARTIR_DE = 120.0


def normalizar(texto: str) -> str:
    """Minúsculas, sem acentos e com "_" no lugar de espaços e hífens."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return sem_acento.strip().lower().replace(" ", "_").replace("-", "_")


@dataclass
class ItemCarrinho:
    item_id: str
    nome: str
    preco: float
    quantidade: int
    observacao: str = ""

    @property
    def subtotal(self) -> float:
        return round(self.preco * self.quantidade, 2)


@dataclass
class Loja:
    restaurantes: list[dict]
    bairros: dict[str, float]
    carrinho: list[ItemCarrinho] = field(default_factory=list)
    restaurante_do_carrinho: str | None = None
    pedido_finalizado: dict | None = None

    @classmethod
    def carregar(cls, caminho: Path | str = CARDAPIO_PADRAO) -> "Loja":
        dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
        return cls(restaurantes=dados["restaurantes"], bairros=dados["bairros"])

    # ---------- buscas auxiliares ----------

    def _restaurante(self, restaurante_id: str) -> dict | None:
        return next((r for r in self.restaurantes if r["id"] == restaurante_id), None)

    def _item(self, item_id: str) -> tuple[dict, dict] | tuple[None, None]:
        for restaurante in self.restaurantes:
            for item in restaurante["itens"]:
                if item["id"] == item_id:
                    return restaurante, item
        return None, None

    def _bairro(self, bairro: str) -> str | None:
        alvo = normalizar(bairro)
        return next((b for b in self.bairros if normalizar(b) == alvo), None)

    def _total_itens(self) -> float:
        return round(sum(i.subtotal for i in self.carrinho), 2)

    # ---------- ferramentas ----------

    def buscar_restaurantes(self, culinaria: str = "", restricao: str = "") -> dict:
        """Lista restaurantes, filtrando por culinária e/ou por restrição alimentar."""
        if restricao and normalizar(restricao) not in RESTRICOES:
            return {"erro": f"Restrição desconhecida. Use uma de: {sorted(RESTRICOES)}"}
        encontrados = []
        for r in self.restaurantes:
            if culinaria and normalizar(culinaria) not in normalizar(r["culinaria"]):
                continue
            opcoes = [i for i in r["itens"] if not restricao or normalizar(restricao) in i["tags"]]
            if restricao and not opcoes:
                continue
            encontrados.append({
                "id": r["id"],
                "nome": r["nome"],
                "culinaria": r["culinaria"],
                "bairro": r["bairro"],
                "pedido_minimo": r["pedido_minimo"],
                "itens_compativeis": len(opcoes),
            })
        return {"restaurantes": encontrados}

    def ver_cardapio(self, restaurante_id: str, restricao: str = "") -> dict:
        """Mostra os itens de um restaurante, opcionalmente só os compatíveis com uma restrição."""
        restaurante = self._restaurante(restaurante_id)
        if restaurante is None:
            return {"erro": f"Restaurante {restaurante_id!r} não existe."}
        if restricao and normalizar(restricao) not in RESTRICOES:
            return {"erro": f"Restrição desconhecida. Use uma de: {sorted(RESTRICOES)}"}
        itens = [
            {"id": i["id"], "nome": i["nome"], "categoria": i["categoria"], "preco": i["preco"], "tags": i["tags"]}
            for i in restaurante["itens"]
            if not restricao or normalizar(restricao) in i["tags"]
        ]
        return {"restaurante": restaurante["nome"], "itens": itens}

    def adicionar_item(self, item_id: str, quantidade: int = 1, observacao: str = "") -> dict:
        """Adiciona um item ao carrinho. O carrinho aceita itens de um único restaurante."""
        if self.pedido_finalizado:
            return {"erro": "O pedido já foi finalizado."}
        quantidade = int(quantidade)
        if quantidade < 1:
            return {"erro": "A quantidade precisa ser pelo menos 1."}
        restaurante, item = self._item(item_id)
        if item is None:
            return {"erro": f"Item {item_id!r} não existe. Consulte o cardápio para ver os ids."}
        if self.restaurante_do_carrinho and self.restaurante_do_carrinho != restaurante["id"]:
            atual = self._restaurante(self.restaurante_do_carrinho)["nome"]
            return {"erro": f"O carrinho já tem itens de {atual}. Esvazie o carrinho para pedir de outro restaurante."}
        self.restaurante_do_carrinho = restaurante["id"]
        existente = next((i for i in self.carrinho if i.item_id == item_id and i.observacao == observacao), None)
        if existente:
            existente.quantidade += quantidade
        else:
            self.carrinho.append(ItemCarrinho(item_id, item["nome"], item["preco"], quantidade, observacao))
        return self.ver_carrinho()

    def remover_item(self, item_id: str, quantidade: int = 0) -> dict:
        """Remove um item do carrinho. quantidade=0 remove todas as unidades."""
        quantidade = int(quantidade)
        alvo = next((i for i in self.carrinho if i.item_id == item_id), None)
        if alvo is None:
            return {"erro": f"O item {item_id!r} não está no carrinho."}
        if quantidade <= 0 or quantidade >= alvo.quantidade:
            self.carrinho.remove(alvo)
        else:
            alvo.quantidade -= quantidade
        if not self.carrinho:
            self.restaurante_do_carrinho = None
        return self.ver_carrinho()

    def esvaziar_carrinho(self) -> dict:
        """Remove todos os itens do carrinho."""
        self.carrinho.clear()
        self.restaurante_do_carrinho = None
        return self.ver_carrinho()

    def ver_carrinho(self) -> dict:
        """Mostra os itens do carrinho e o total dos itens (sem frete)."""
        restaurante = self._restaurante(self.restaurante_do_carrinho) if self.restaurante_do_carrinho else None
        return {
            "restaurante": restaurante["nome"] if restaurante else None,
            "itens": [
                {"id": i.item_id, "nome": i.nome, "quantidade": i.quantidade,
                 "preco_unitario": i.preco, "subtotal": i.subtotal, "observacao": i.observacao}
                for i in self.carrinho
            ],
            "total_itens": self._total_itens(),
        }

    def calcular_frete(self, bairro: str) -> dict:
        """Calcula o frete do restaurante do carrinho até o bairro de entrega."""
        if not self.restaurante_do_carrinho:
            return {"erro": "O carrinho está vazio; adicione itens antes de calcular o frete."}
        destino = self._bairro(bairro)
        if destino is None:
            return {"erro": f"Não entregamos em {bairro!r}. Bairros atendidos: {sorted(self.bairros)}"}
        restaurante = self._restaurante(self.restaurante_do_carrinho)
        distancia = abs(self.bairros[destino] - self.bairros[restaurante["bairro"]]) + 1.0
        if self._total_itens() >= FRETE_GRATIS_A_PARTIR_DE:
            frete = 0.0
        else:
            frete = round(restaurante["taxa_base"] + CUSTO_POR_KM * distancia, 2)
        return {"bairro": destino, "distancia_km": round(distancia, 1), "frete": frete,
                "frete_gratis_a_partir_de": FRETE_GRATIS_A_PARTIR_DE}

    def finalizar_pedido(self, bairro: str, forma_pagamento: str) -> dict:
        """Fecha o pedido. Só deve ser chamada depois de o cliente confirmar o resumo."""
        if self.pedido_finalizado:
            return {"erro": "O pedido já foi finalizado."}
        if not self.carrinho:
            return {"erro": "O carrinho está vazio."}
        pagamento = normalizar(forma_pagamento)
        if pagamento not in FORMAS_PAGAMENTO:
            return {"erro": f"Forma de pagamento inválida. Use uma de: {sorted(FORMAS_PAGAMENTO)}"}
        restaurante = self._restaurante(self.restaurante_do_carrinho)
        if self._total_itens() < restaurante["pedido_minimo"]:
            falta = round(restaurante["pedido_minimo"] - self._total_itens(), 2)
            return {"erro": f"Pedido mínimo de R$ {restaurante['pedido_minimo']:.2f}; faltam R$ {falta:.2f}."}
        frete = self.calcular_frete(bairro)
        if "erro" in frete:
            return frete
        self.pedido_finalizado = {
            **self.ver_carrinho(),
            "bairro": frete["bairro"],
            "frete": frete["frete"],
            "total": round(self._total_itens() + frete["frete"], 2),
            "forma_pagamento": pagamento,
        }
        return {"status": "confirmado", "pedido": self.pedido_finalizado}

    # ---------- despacho ----------

    FERRAMENTAS = (
        "buscar_restaurantes", "ver_cardapio", "adicionar_item", "remover_item",
        "esvaziar_carrinho", "ver_carrinho", "calcular_frete", "finalizar_pedido",
    )

    def executar(self, nome: str, argumentos: dict) -> dict:
        """Chama a ferramenta `nome` com os argumentos vindos do modelo."""
        if nome not in self.FERRAMENTAS:
            return {"erro": f"Ferramenta {nome!r} não existe."}
        try:
            return getattr(self, nome)(**argumentos)
        except TypeError as erro:
            return {"erro": f"Argumentos inválidos para {nome}: {erro}"}
