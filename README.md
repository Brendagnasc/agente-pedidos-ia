# Agente de pedidos com IA

Assistente de delivery que conversa com o cliente em português e monta o pedido chamando ferramentas: busca restaurantes, filtra o cardápio por restrição alimentar, gerencia o carrinho, calcula o frete e fecha o pedido só depois da confirmação. Usa **tool calling** da API do **Gemini** e tem uma suíte de **evals** que mede se o agente segue as regras.

Conversa real com `gemini-3.6-flash` (`python -m agente_pedidos --debug`):

```
você> Oi! Sou vegana, o que tem pra mim no Verde Vivo?
  [ferramenta] buscar_restaurantes({"restricao": "vegano"})
  [ferramenta] ver_cardapio({"restricao": "vegano", "restaurante_id": "r4"})
agente> No restaurante Verde Vivo, temos as seguintes opções veganas:
        - Bowl de quinoa com legumes – R$ 33,00
        - Wrap de grão-de-bico – R$ 27,00
        - Smoothie de frutas vermelhas – R$ 15,00

você> Quero o bowl de quinoa e um smoothie. Entrega no Centro, pago no pix
  [ferramenta] adicionar_item({"quantidade": 1, "item_id": "r4-01"})
  [ferramenta] adicionar_item({"item_id": "r4-04", "quantidade": 1})
  [ferramenta] calcular_frete({"bairro": "Centro"})
agente> Subtotal: R$ 48,00 · Frete (Centro): R$ 9,95 · Total: R$ 57,95 · Pagamento: Pix
        Posso confirmar e finalizar o pedido?

você> Sim, pode confirmar
  [ferramenta] finalizar_pedido({"forma_pagamento": "pix", "bairro": "Centro"})
agente> Seu pedido foi confirmado com sucesso!
```

## Arquitetura

```
cliente ──► AgentePedidos ──► Gemini (function calling)
                 │  ▲                │
                 │  └── resultado ◄──┘ pede ferramenta
                 ▼
               Loja  (regras de negócio puras, sem IA)
               ├── buscar_restaurantes / ver_cardapio
               ├── adicionar_item / remover_item / esvaziar_carrinho / ver_carrinho
               └── calcular_frete / finalizar_pedido
```

- **`loja.py`**: regras de negócio deterministas (um restaurante por carrinho, pedido mínimo, frete por distância, frete grátis acima de R$ 120). Erros voltam como `{"erro": ...}` para o modelo se corrigir em vez de quebrar.
- **`agente.py`**: loop de function calling feito à mão (sem o modo automático do SDK), para registrar cada chamada, limitar os passos e testar com um cliente falso. Erros temporários da API (429, 500, 503, 504 e tempo esgotado) disparam novas tentativas com espera exponencial e, se o modelo continuar indisponível, o agente passa para um modelo reserva (`gemini-3.8-flash` → `gemini-3.6-flash` → `gemini-3.5-flash-lite`).
- **`evals/`**: casos de conversa com verificações sobre o estado final (carrinho, restrições respeitadas, pedido fechado ou não).

## Como rodar

Requer Python 3.10+ e uma chave gratuita do [Google AI Studio](https://aistudio.google.com/apikey).

```bash
python -m venv .venv
.venv\Scripts\activate          # Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
copy .env.example .env          # Linux/macOS: cp .env.example .env  — depois cole sua chave
python -m agente_pedidos --debug
```

## Testes e evals

```bash
pytest                          # regras de negócio e loop do agente, sem chamar a API
python evals/rodar_evals.py     # casos reais contra o modelo
```

| Caso | O que verifica |
|---|---|
| `pedido_simples` | adiciona o item e a quantidade certos |
| `restricao_vegana` / `restricao_sem_gluten` | não coloca no carrinho itens incompatíveis |
| `nao_finaliza_sem_confirmacao` | mostra o resumo e espera o "sim" |
| `finaliza_apos_confirmacao` | fecha com o total certo (itens + frete) |
| `pedido_minimo` / `bairro_fora_da_area` | não fecha pedidos inválidos |
| `item_inexistente` | não inventa itens fora do cardápio |
| `troca_de_restaurante` | esvazia e troca o carrinho quando o cliente pede |

**Resultado (05/11/2026, `gemini-3.6-flash`):** 9 de 9 casos aprovados, de 8 s a 76 s por caso (a maior parte é latência da API na cota gratuita). Na primeira rodada, `restricao_vegana` falhou porque o pedido era ambíguo e o agente, corretamente, perguntou qual prato o cliente queria; o caso foi reescrito para testar a restrição, não a escolha.

## Próximos passos

- API HTTP com FastAPI e uma interface web simples
- Mais casos de eval, incluindo conversas longas e mensagens ambíguas
- Comparar modelos (custo, latência e taxa de acerto) na mesma suíte de evals

O cardápio em `data/cardapio.json` é fictício.
