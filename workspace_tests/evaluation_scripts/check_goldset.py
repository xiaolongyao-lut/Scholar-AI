import json
with open("gateb_goldset.jsonl", "r", encoding="utf-8") as f:
    for i, line in enumerate(f, 1):
        r = json.loads(line)
        if r.get("no_gold"):
            rels = [q["relevance"] for q in r.get("qrels", [])]
            nonzero = [rv for rv in rels if rv > 0]
            print(f"line {i} {r['query_id']:12s}  no_gold=True  rels={rels}  nonzero={nonzero}")
