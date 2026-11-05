"""Roda os casos de evals/casos.json contra o modelo real e mostra a taxa de acerto.

Uso: python evals/rodar_evals.py [--caso ID] [--pausa SEGUNDOS]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from agente_pedidos.agente import AgentePedidos  # noqa: E402
from agente_pedidos.loja import Loja  # noqa: E402


def verificar(esperado: dict, loja: Loja) -> list[str]:
    """Devolve a lista de falhas (vazia = caso aprovado)."""
    falhas = []
    itens = {i.item_id: i.quantidade for i in loja.carrinho}
    pedido = loja.pedido_finalizado
    if pedido:
        itens = {i["id"]: i["quantidade"] for i in pedido["itens"]}

    if "carrinho" in esperado and itens != esperado["carrinho"]:
        falhas.append(f"carrinho {itens} != {esperado['carrinho']}")
    if esperado.get("carrinho_nao_vazio") and not itens:
        falhas.append("carrinho vazio")
    if esperado.get("carrinho_vazio") and itens:
        falhas.append(f"carrinho deveria estar vazio: {itens}")
    if "todos_com_tag" in esperado:
        tag = esperado["todos_com_tag"]
        for item_id in itens:
            _, item = loja._item(item_id)
            if tag not in item["tags"]:
                falhas.append(f"{item_id} não é {tag}")
    if "finalizado" in esperado and bool(pedido) != esperado["finalizado"]:
        falhas.append(f"finalizado={bool(pedido)}, esperado {esperado['finalizado']}")
    if "total" in esperado and (not pedido or abs(pedido["total"] - esperado["total"]) > 0.01):
        falhas.append(f"total {pedido and pedido['total']} != {esperado['total']}")
    if "pagamento" in esperado and (not pedido or pedido["forma_pagamento"] != esperado["pagamento"]):
        falhas.append(f"pagamento {pedido and pedido['forma_pagamento']} != {esperado['pagamento']}")
    return falhas


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--caso", help="roda só o caso com este id")
    parser.add_argument("--pausa", type=float, default=4.0, help="segundos entre casos (cota gratuita)")
    args = parser.parse_args()

    load_dotenv(RAIZ / ".env")
    casos = json.loads((RAIZ / "evals" / "casos.json").read_text(encoding="utf-8"))
    if args.caso:
        casos = [c for c in casos if c["id"] == args.caso]

    resultados = []
    for numero, caso in enumerate(casos):
        if numero:
            time.sleep(args.pausa)
        agente = AgentePedidos()
        inicio = time.perf_counter()
        try:
            for mensagem in caso["mensagens"]:
                agente.enviar(mensagem)
            falhas = verificar(caso["esperado"], agente.loja)
        except Exception as erro:  # erro de API conta como falha do caso
            falhas = [f"exceção: {erro}"]
        segundos = time.perf_counter() - inicio
        resultados.append({
            "id": caso["id"],
            "aprovado": not falhas,
            "falhas": falhas,
            "segundos": round(segundos, 1),
            "modelo_usado": agente.modelo_usado,
            "ferramentas": [c.nome for c in agente.chamadas],
        })
        marca = "OK  " if not falhas else "FALHOU"
        print(f"{marca} {caso['id']:<30} {segundos:5.1f}s  {'; '.join(falhas)}")

    aprovados = sum(r["aprovado"] for r in resultados)
    print(f"\n{aprovados}/{len(resultados)} casos aprovados ({agente.modelo})")

    pasta = RAIZ / "evals" / "resultados"
    pasta.mkdir(exist_ok=True)
    arquivo = pasta / f"{datetime.now():%Y%m%d-%H%M%S}.json"
    arquivo.write_text(json.dumps({"modelo": agente.modelo, "resultados": resultados},
                                  ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Resultados salvos em {arquivo.relative_to(RAIZ)}")
    return 0 if aprovados == len(resultados) else 1


if __name__ == "__main__":
    raise SystemExit(main())
