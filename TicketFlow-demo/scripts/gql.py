"""Spusti ľubovoľnú GraphQL query a ukáž výsledok + skutočný počet SQL dotazov.

Použitie:
  python3 scripts/gql.py '{ event(id: "42") { seats(limit: 3) { id price { amount } } } }'
  python3 scripts/gql.py --naive '{ event(id: "42") { seats(limit: 3) { id price { amount } } } }'
  python3 scripts/gql.py --admin '{ event(id: "42") { seats(limit: 1) { price { internalCost } } } }'
  python3 scripts/gql.py --sql '...'      # vypíše aj všetky SQL príkazy
"""
import argparse
import json

from _client import BOLD, RESET, post

p = argparse.ArgumentParser()
p.add_argument("query")
p.add_argument("--naive", action="store_true", help="naivné resolvery (N+1)")
p.add_argument("--admin", action="store_true", help="pošli X-Demo-Role: admin")
p.add_argument("--sql", action="store_true", help="vypíš všetky SQL príkazy")
a = p.parse_args()

r = post("/graphql/naive" if a.naive else "/graphql", {"query": a.query},
         headers={"X-Demo-Role": "admin"} if a.admin else None).json
ext = r["extensions"]
out = {k: r[k] for k in ("data", "errors") if r.get(k) is not None}
text = json.dumps(out, indent=1, ensure_ascii=False)
print(text if len(text) < 1500 else text[:1500] + "\n… (skrátené)")
print(f"\n{BOLD}{ext['sql']['count']} SQL{RESET} · režim {ext['resolverMode']} · {ext['durationMs']} ms (orientačne)")
if a.sql:
    for i, s in enumerate(ext["sql"]["statements"], 1):
        print(f"{i:4d}. {s['sql'][:160]}  {s['params']}")
