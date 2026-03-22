"""
testset.json 기반으로 현재 검색 성능을 측정한다.

지표:
  Hit@K      - 상위 K개 결과 안에 정답 공고가 포함된 비율
  MRR        - Mean Reciprocal Rank (정답이 몇 번째에 나오는지 역수 평균)
  Zero-rate  - 결과가 0건인 쿼리 비율

Usage:
    python tests/evaluate.py                        # testset.json 기준
    python tests/evaluate.py --testset tests/testset_small.json
    python tests/evaluate.py --k 5 --k 10           # 여러 K 값
    python tests/evaluate.py --out results_before.json
"""
import argparse
import json
import os
import sys
import time

from dotenv import load_dotenv
load_dotenv(override=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from discord_bot.llm import extract_filters
from db.io import search_recruits_by_filter
from db.JobPreprocessor import JobPreprocessor

DEFAULT_TESTSET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "testset.json")


def search(query: str, limit: int):
    filters = extract_filters(query)
    form_code = JobPreprocessor.parse_form(filters.get("form") or "")
    return search_recruits_by_filter(
        keyword=filters.get("keyword"),
        min_deadline=filters.get("min_deadline"),
        min_annual_salary=filters.get("min_annual_salary"),
        company_name=filters.get("company_name"),
        max_experience=filters.get("max_experience"),
        form=form_code,
        region=filters.get("region"),
        limit=limit,
    )


def evaluate(testset, k_values):
    max_k = max(k_values)
    results = []

    for entry in testset:
        query = entry["query"]
        correct_id = entry["recruit_id"]

        t0 = time.perf_counter()
        recruits = search(query, limit=max_k)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        returned_ids = [r.id for r in recruits]
        rank = None
        for i, rid in enumerate(returned_ids, 1):
            if rid == correct_id:
                rank = i
                break

        results.append({
            "id": entry["id"],
            "recruit_id": correct_id,
            "query": query,
            "returned_ids": returned_ids,
            "rank": rank,
            "zero_result": len(returned_ids) == 0,
            "elapsed_ms": round(elapsed_ms, 1),
        })

    # 지표 계산
    n = len(results)
    metrics = {"n": n, "k_values": k_values}

    for k in k_values:
        hits = sum(1 for r in results if r["rank"] is not None and r["rank"] <= k)
        metrics[f"hit@{k}"] = round(hits / n, 4)

    rr_sum = sum(1 / r["rank"] for r in results if r["rank"] is not None)
    metrics["mrr"] = round(rr_sum / n, 4)

    zero_count = sum(1 for r in results if r["zero_result"])
    metrics["zero_result_rate"] = round(zero_count / n, 4)

    return metrics, results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--testset", type=str, default=DEFAULT_TESTSET)
    parser.add_argument("--k", type=int, action="append", default=None)
    parser.add_argument("--out", type=str, default=None, help="결과 JSON 저장 경로")
    args = parser.parse_args()

    k_values = sorted(set(args.k)) if args.k else [5, 10]

    with open(args.testset, encoding="utf-8") as f:
        testset = json.load(f)

    print(f"테스트셋 {len(testset)}개 로드 → 평가 시작 (K={k_values})\n")

    metrics, results = evaluate(testset, k_values)

    # 출력
    print("=" * 50)
    print("  검색 품질 평가 결과")
    print("=" * 50)
    for k in k_values:
        print(f"  Hit@{k:<3}          : {metrics[f'hit@{k}']:.1%}")
    print(f"  MRR              : {metrics['mrr']:.4f}")
    print(f"  Zero-result rate : {metrics['zero_result_rate']:.1%}  ({int(metrics['zero_result_rate'] * metrics['n'])}/{metrics['n']}건)")
    print("=" * 50)

    # 실패 케이스 출력
    misses = [r for r in results if r["rank"] is None]
    if misses:
        print(f"\n미검색 케이스 ({len(misses)}개):")
        for r in misses[:10]:
            zero = " [결과없음]" if r["zero_result"] else ""
            print(f"  [{r['id']:03d}] {r['query']!r}{zero}")
        if len(misses) > 10:
            print(f"  ... 외 {len(misses) - 10}개")

    if args.out:
        output = {"metrics": metrics, "results": results}
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"\n결과 저장: {args.out}")


if __name__ == "__main__":
    main()
