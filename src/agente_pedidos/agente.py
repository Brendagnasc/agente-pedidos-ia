"""Loop do agente: conversa com o Gemini e executa as ferramentas que ele pede."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

import httpx
from google import genai
from google.genai import errors, types

from .loja import Loja

MODELO_PADRAO = "gemini-3.8-flash"
MODELOS_RESERVA = ("gemini-3.6-flash", "gemini-3.5-flash-lite")
MAX_PASSOS = 8
TENTATIVAS_POR_MODELO = 3
ESPERA_INICIAL = 2.0  # segundos; dobra a cada nova tentativa
TEMPO_LIMITE_MS = 60_000  # sem limite, uma chamada pode ficar presa por minutos


def _temporario(erro: Exception) -> bool:
    """Sobrecarga (503), limite de cota (429) ou tempo esgotado: vale tentar de novo."""
    if isinstance(erro, httpx.TimeoutException):
        return True
    return isinstance(erro, errors.APIError) and erro.code in (429, 500, 503, 504)

INSTRUCOES = """\
Você é o assistente de pedidos de um app de delivery em Ouro Preto. Ajude o cliente
a escolher um restaurante, montar o carrinho e fechar o pedido.

Regras:
- Use sempre as ferramentas para consultar restaurantes, itens, preços e frete.
  Nunca invente itens, ids ou valores.
- Para adicionar um item, use o id exato que veio de ver_cardapio.
- Se o cliente citar uma restrição alimentar (vegano, vegetariano, sem glúten,
  sem lactose), filtre por ela e não ofereça itens incompatíveis.
- O carrinho só aceita um restaurante por vez. Se o cliente quiser trocar,
  confirme antes de esvaziar o carrinho.
- Antes de finalizar, mostre um resumo com itens, frete, total, bairro e forma de
  pagamento e peça confirmação. Só chame finalizar_pedido depois de um "sim" claro.
- Se faltar o bairro ou a forma de pagamento (pix, cartao ou dinheiro), pergunte.
- Se uma ferramenta devolver "erro", explique o problema ao cliente em uma frase
  e proponha uma saída.
- Responda em português do Brasil, de forma curta e direta, com valores em R$.
"""

_TEXTO = {"type": "STRING"}
_INTEIRO = {"type": "INTEGER"}
_RESTRICAO = {"type": "STRING", "description": "vegetariano, vegano, sem_gluten ou sem_lactose"}

DECLARACOES = [
    {
        "name": "buscar_restaurantes",
        "description": "Lista restaurantes. Filtra por culinária (pizza, mineira, japonesa, saudável) e/ou restrição alimentar.",
        "parameters": {"type": "OBJECT", "properties": {"culinaria": _TEXTO, "restricao": _RESTRICAO}},
    },
    {
        "name": "ver_cardapio",
        "description": "Mostra os itens de um restaurante com id, preço e tags. Pode filtrar por restrição alimentar.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"restaurante_id": _TEXTO, "restricao": _RESTRICAO},
            "required": ["restaurante_id"],
        },
    },
    {
        "name": "adicionar_item",
        "description": "Adiciona um item ao carrinho pelo id do cardápio.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "item_id": _TEXTO,
                "quantidade": _INTEIRO,
                "observacao": {"type": "STRING", "description": "Ex.: sem cebola"},
            },
            "required": ["item_id"],
        },
    },
    {
        "name": "remover_item",
        "description": "Remove um item do carrinho. quantidade=0 remove todas as unidades.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"item_id": _TEXTO, "quantidade": _INTEIRO},
            "required": ["item_id"],
        },
    },
    {"name": "esvaziar_carrinho", "description": "Remove todos os itens do carrinho."},
    {"name": "ver_carrinho", "description": "Mostra os itens do carrinho e o total sem frete."},
    {
        "name": "calcular_frete",
        "description": "Calcula o frete até o bairro de entrega.",
        "parameters": {"type": "OBJECT", "properties": {"bairro": _TEXTO}, "required": ["bairro"]},
    },
    {
        "name": "finalizar_pedido",
        "description": "Fecha o pedido. Só use depois de o cliente confirmar o resumo.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "bairro": _TEXTO,
                "forma_pagamento": {"type": "STRING", "description": "pix, cartao ou dinheiro"},
            },
            "required": ["bairro", "forma_pagamento"],
        },
    },
]


@dataclass
class ChamadaFerramenta:
    nome: str
    argumentos: dict
    resultado: dict


@dataclass
class AgentePedidos:
    loja: Loja = field(default_factory=Loja.carregar)
    cliente: genai.Client | None = None
    modelo: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", MODELO_PADRAO))
    reservas: tuple[str, ...] = MODELOS_RESERVA
    espera_inicial: float = ESPERA_INICIAL
    historico: list[types.Content] = field(default_factory=list)
    chamadas: list[ChamadaFerramenta] = field(default_factory=list)
    modelo_usado: str | None = None

    def __post_init__(self) -> None:
        if self.cliente is None:
            # Lê GEMINI_API_KEY do ambiente. As novas tentativas ficam a cargo de _gerar.
            self.cliente = genai.Client(http_options=types.HttpOptions(
                timeout=TEMPO_LIMITE_MS,
                retry_options=types.HttpRetryOptions(attempts=1),
            ))
        self.config = types.GenerateContentConfig(
            system_instruction=INSTRUCOES,
            tools=[types.Tool(function_declarations=DECLARACOES)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            temperature=0.2,
        )

    def _gerar(self):
        """Chama o modelo com novas tentativas e, se preciso, passa para os modelos reserva."""
        candidatos = [self.modelo, *[m for m in self.reservas if m != self.modelo]]
        ultimo_erro: Exception | None = None
        for modelo in candidatos:
            for tentativa in range(TENTATIVAS_POR_MODELO):
                try:
                    resposta = self.cliente.models.generate_content(
                        model=modelo, contents=self.historico, config=self.config
                    )
                    self.modelo_usado = modelo
                    return resposta
                except (errors.APIError, httpx.TimeoutException) as erro:
                    if not _temporario(erro):
                        raise
                    ultimo_erro = erro
                    if tentativa < TENTATIVAS_POR_MODELO - 1:
                        time.sleep(self.espera_inicial * 2**tentativa)
        raise ultimo_erro

    def enviar(self, mensagem: str) -> str:
        """Manda uma mensagem do cliente e devolve a resposta final do agente."""
        self.historico.append(types.Content(role="user", parts=[types.Part(text=mensagem)]))
        for _ in range(MAX_PASSOS):
            resposta = self._gerar()
            self.historico.append(resposta.candidates[0].content)
            pedidos = resposta.function_calls or []
            if not pedidos:
                return (resposta.text or "").strip()
            partes = []
            for pedido in pedidos:
                argumentos = dict(pedido.args or {})
                resultado = self.loja.executar(pedido.name, argumentos)
                self.chamadas.append(ChamadaFerramenta(pedido.name, argumentos, resultado))
                partes.append(types.Part.from_function_response(name=pedido.name, response=resultado))
            self.historico.append(types.Content(role="user", parts=partes))
        return "Desculpe, não consegui concluir agora. Pode repetir o pedido de outro jeito?"
