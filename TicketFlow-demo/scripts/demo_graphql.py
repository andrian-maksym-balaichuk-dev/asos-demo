"""Demo C fallback: rovnaká GraphQL query, naivný resolver vs. DataLoader, SKUTOČNÝ počet SQL.
Použitie: python3 scripts/demo_graphql.py --seats 100 --compare"""
import argparse
import json

from _client import BOLD, RESET, line, post, title

p = argparse.ArgumentParser()
p.add_argument("--seats", type=int, default=100)
p.add_argument("--compare", action="store_true")
a = p.parse_args()
q = f'{{ event(id: "42") {{ seats(limit: {a.seats}) {{ id price {{ amount currency }} }} }} }}'
print("Query:", q)
out = {}
for mode, path in (("naivne", "/graphql/naive"), ("batching", "/graphql")):
    if not a.compare and mode == "naivne":
        continue
    j = post(path, {"query": q}).json
    out[mode] = j
    sql = j["extensions"]["sql"]
    title(f"{mode}: {sql['count']} SQL dotazov · {j['extensions']['durationMs']} ms (orientačné lokálne meranie)")
    if j.get("errors"):
        print("  chyba:", j["errors"][0]["message"])
    for i, s in enumerate(sql["statements"][:3], 1):
        print(f"  {i:3d}. {s['sql'][:140]}")
    if sql["count"] > 3:
        print(f"       … a ďalších {sql['count'] - 3}")
if a.compare and "naivne" in out:
    same = json.dumps(out["naivne"]["data"], sort_keys=True) == json.dumps(out["batching"]["data"], sort_keys=True)
    n, b = out["naivne"]["extensions"]["sql"]["count"], out["batching"]["extensions"]["sql"]["count"]
    title("Porovnanie")
    line(same, f"rovnaký JSON ({len(out['batching']['data']['event']['seats'])} sedadiel)")
    print(f"  {BOLD}{n} vs {b} skutočných SQL dotazov{RESET} (zdroj: {out['batching']['extensions']['sql']['source']})")
