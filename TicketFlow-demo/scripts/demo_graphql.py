"""Demo C (záloha z terminálu): rovnaká GraphQL query, naivný resolver vs. DataLoader, SKUTOČNÝ počet SQL.

Spustenie:  python3 scripts/demo_graphql.py --seats 100 --compare
"""
import argparse
import json

from _client import BOLD, RESET, line, post, title

ENDPOINTS = (("naivne", "/graphql/naive"), ("batching", "/graphql"))


def build_query(seat_count):
    return f'{{ event(id: "42") {{ seats(limit: {seat_count}) {{ id price {{ amount currency }} }} }} }}'


def run_and_print(mode, path, query):
    """Pošle query a vypíše počet SQL (meria server, nie skript) a prvé 3 dotazy."""
    response = post(path, {"query": query}).json
    sql = response["extensions"]["sql"]
    title(f"{mode}: {sql['count']} SQL dotazov · {response['extensions']['durationMs']} ms "
          "(orientačné lokálne meranie)")
    if response.get("errors"):
        print("  chyba:", response["errors"][0]["message"])
    for index, statement in enumerate(sql["statements"][:3], 1):
        print(f"  {index:3d}. {statement['sql'][:140]}")
    if sql["count"] > 3:
        print(f"       … a ďalších {sql['count'] - 3}")
    return response


def print_comparison(naive, batched):
    same_json = json.dumps(naive["data"], sort_keys=True) == json.dumps(batched["data"], sort_keys=True)
    naive_count = naive["extensions"]["sql"]["count"]
    batched_count = batched["extensions"]["sql"]["count"]
    title("Porovnanie")
    line(same_json, f"rovnaký JSON ({len(batched['data']['event']['seats'])} sedadiel)")
    print(f"  {BOLD}{naive_count} vs {batched_count} skutočných SQL dotazov{RESET} "
          f"(zdroj: {batched['extensions']['sql']['source']})")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seats", type=int, default=100)
    parser.add_argument("--compare", action="store_true")
    args = parser.parse_args()

    query = build_query(args.seats)
    print("Query:", query)

    # Bez --compare beží iba batching
    responses = {}
    for mode, path in ENDPOINTS:
        if not args.compare and mode == "naivne":
            continue
        responses[mode] = run_and_print(mode, path, query)

    if args.compare and "naivne" in responses:
        print_comparison(responses["naivne"], responses["batching"])


if __name__ == "__main__":
    main()
