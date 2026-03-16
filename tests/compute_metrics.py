"""
my_judgments.json + candidates.json → NDCG@K, P@K, Hit@K per mode
"""
import json
import math
from collections import defaultdict

CANDIDATES = "tests/candidates_v5.json"
JUDGMENTS  = "tests/my_judgments_v5.json"
KS         = [5, 10]


def dcg(rels, k):
    return sum(r / math.log2(i + 2) for i, r in enumerate(rels[:k]))


def ndcg(ranked_ids, rel_map, k):
    rels = [rel_map.get(str(rid), rel_map.get(rid, 0)) for rid in ranked_ids[:k]]
    ideal = sorted(rel_map.values(), reverse=True)
    d = dcg(rels, k)
    i = dcg(ideal, k)
    return d / i if i > 0 else 0.0


def precision_at_k(ranked_ids, rel_map, k, threshold=1):
    rels = [rel_map.get(str(rid), rel_map.get(rid, 0)) for rid in ranked_ids[:k]]
    return sum(1 for r in rels if r >= threshold) / k


def hit_at_k(ranked_ids, rel_map, k, threshold=2):
    rels = [rel_map.get(str(rid), rel_map.get(rid, 0)) for rid in ranked_ids[:k]]
    return 1.0 if any(r >= threshold for r in rels) else 0.0


def main():
    with open(CANDIDATES, encoding="utf-8") as f:
        candidates = json.load(f)
    with open(JUDGMENTS, encoding="utf-8") as f:
        judgments = json.load(f)

    modes = ["baseline", "+tags", "+expanded", "+adaptive"]
    # metrics[mode][metric_name] = list of per-query scores
    metrics = {m: defaultdict(list) for m in modes}

    for query_data in candidates:
        qid = query_data["id"]
        qtype = query_data["type"]
        rel_map = judgments.get(qid, {})
        if not rel_map:
            continue

        # Convert keys to int for lookup
        rel_map_int = {int(k): v for k, v in rel_map.items()}

        for mode in modes:
            ranked = [r["id"] for r in query_data["modes"].get(mode, [])]
            if not ranked:
                continue

            for k in KS:
                metrics[mode][f"ndcg@{k}"].append(ndcg(ranked, rel_map_int, k))
                metrics[mode][f"p@{k}"].append(precision_at_k(ranked, rel_map_int, k, threshold=1))
                metrics[mode][f"hit@{k}"].append(hit_at_k(ranked, rel_map_int, k, threshold=2))

    # Also compute per type
    modes_all = ["baseline", "+tags", "+expanded", "+adaptive"]
    type_data = {m: {t: defaultdict(list) for t in "ABCD"} for m in modes_all}
    for query_data in candidates:
        qid = query_data["id"]
        qtype = query_data["type"]
        rel_map = judgments.get(qid, {})
        if not rel_map:
            continue
        rel_map_int = {int(k): v for k, v in rel_map.items()}

        for mode in modes_all:
            ranked = [r["id"] for r in query_data["modes"].get(mode, [])]
            if not ranked:
                continue
            for k in KS:
                type_data[mode][qtype][f"ndcg@{k}"].append(ndcg(ranked, rel_map_int, k))
                type_data[mode][qtype][f"p@{k}"].append(precision_at_k(ranked, rel_map_int, k))

    print("=" * 80)
    print("OVERALL METRICS")
    print("=" * 80)
    header = f"{'Metric':<15}" + "".join(f"{m:>16}" for m in modes) + f"  {'vs baseline':>12}"
    print(header)
    print("-" * 95)
    for k in KS:
        for metric in [f"ndcg@{k}", f"p@{k}", f"hit@{k}"]:
            vals = []
            for mode in modes:
                lst = metrics[mode].get(metric, [])
                avg = sum(lst) / len(lst) if lst else 0.0
                vals.append(avg)
            delta = vals[-1] - vals[0]
            sign = "+" if delta >= 0 else ""
            row = f"{metric:<15}" + "".join(f"{v:>16.4f}" for v in vals) + f"  {sign}{delta:.4f}"
            print(row)
        print()

    print("=" * 80)
    print("BY QUERY TYPE  (NDCG@10)")
    print("=" * 80)
    type_header = f"{'Type':<8}" + "".join(f"{m:>16}" for m in modes) + f"  {'vs baseline':>12}"
    print(type_header)
    print("-" * 80)
    for t in "ABCD":
        vals = []
        for mode in modes:
            lst = type_data[mode][t].get("ndcg@10", [])
            avg = sum(lst) / len(lst) if lst else 0.0
            vals.append(avg)
        delta = vals[-1] - vals[0]
        sign = "+" if delta >= 0 else ""
        row = f"Type {t:<3}" + "".join(f"{v:>16.4f}" for v in vals) + f"  {sign}{delta:.4f}"
        print(row)

    print()
    print("=" * 80)
    print("PER-QUERY NDCG@10 DETAIL")
    print("=" * 80)
    print(f"{'QID':<6} {'Type':<6}" + "".join(f"{m:>16}" for m in modes) + f"  {'vs baseline':>12}")
    print("-" * 80)
    for query_data in candidates:
        qid = query_data["id"]
        qtype = query_data["type"]
        rel_map = judgments.get(qid, {})
        if not rel_map:
            print(f"{qid:<6} {qtype:<6}  (no judgments)")
            continue
        rel_map_int = {int(k): v for k, v in rel_map.items()}
        row_vals = []
        for mode in modes:
            ranked = [r["id"] for r in query_data["modes"].get(mode, [])]
            v = ndcg(ranked, rel_map_int, 10) if ranked else 0.0
            row_vals.append(v)
        delta = row_vals[-1] - row_vals[0]
        sign = "+" if delta >= 0 else ""
        print(f"{qid:<6} {qtype:<6}" + "".join(f"{v:>16.4f}" for v in row_vals) + f"  {sign}{delta:.4f}")


if __name__ == "__main__":
    main()
