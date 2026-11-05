"""Chat no terminal: python -m agente_pedidos [--debug]"""

from __future__ import annotations

import argparse
import json
import os
import sys

from dotenv import load_dotenv

from .agente import AgentePedidos


def main() -> int:
    parser = argparse.ArgumentParser(description="Converse com o agente de pedidos.")
    parser.add_argument("--debug", action="store_true", help="mostra as ferramentas chamadas")
    args = parser.parse_args()

    load_dotenv()
    if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        print("Defina GEMINI_API_KEY no arquivo .env (veja .env.example).", file=sys.stderr)
        return 1

    agente = AgentePedidos()
    print(f"Agente de pedidos ({agente.modelo}). Digite 'sair' para encerrar.\n")
    while True:
        try:
            mensagem = input("você> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if mensagem.lower() in {"sair", "exit", "quit"}:
            return 0
        if not mensagem:
            continue
        inicio = len(agente.chamadas)
        resposta = agente.enviar(mensagem)
        if args.debug:
            if agente.modelo_usado and agente.modelo_usado != agente.modelo:
                print(f"  [modelo reserva] {agente.modelo_usado}")
            for chamada in agente.chamadas[inicio:]:
                argumentos = json.dumps(chamada.argumentos, ensure_ascii=False)
                print(f"  [ferramenta] {chamada.nome}({argumentos})")
        print(f"agente> {resposta}\n")
        if agente.loja.pedido_finalizado:
            print("Pedido confirmado. Até a próxima!")
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
