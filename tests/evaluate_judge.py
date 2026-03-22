"""
LLM-as-Judge 평가 스크립트.

judge_queries.json의 수동 작성 쿼리를 기반으로:
  1. 4가지 검색 모드에서 후보 공고 수집 및 풀링
  2. Claude로 (쿼리, 공고) 관련도 판단 — 태그 정보 제외 (0~3점)
  3. NDCG@K, Precision@K 지표 계산 및 모드별 비교

검색 모드:
  baseline    : 태그 검색 없음 + 재순위 없음
  +tags       : 태그 검색 있음 + 재순위 없음
  +rerank     : 태그 검색 없음 + 재순위 있음
  +tags+rerank: 태그 검색 있음 + 재순위 있음

Usage:
    python tests/evaluate_judge.py
    python tests/evaluate_judge.py --dry-run
    python tests/evaluate_judge.py --no-rerank          # 재순위 없이 태깅만 (빠름)
    python tests/evaluate_judge.py --judge-model claude-opus-4-6
    python tests/evaluate_judge.py --out tests/results_judge.json
    python tests/evaluate_judge.py --resume             # 중단된 평가 재개

비용 안내 (--dry-run으로 사전 확인 권장):
  claude-haiku-4-5  (기본값): ~$0.5~1.0 / 전체 43쿼리
  claude-sonnet-4-6          : ~$1.5~3.0
  claude-opus-4-6            : ~$5~10
"""
import argparse
import json
import math
import os
import sys
import time

from dotenv import load_dotenv
load_dotenv(override=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import anthropic
from discord_bot.llm import extract_filters
from db.io import search_recruits_by_filter, RecruitOut, get_employment_type_name
from db.JobPreprocessor import JobPreprocessor
from discord_bot.reranker import rerank

# ──────────────────────────────────────────────────────────────────────────────
# 상수
# ──────────────────────────────────────────────────────────────────────────────
JUDGE_QUERIES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "judge_queries.json")
DEFAULT_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results_judge.json")
DEFAULT_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "judge_cache.json")
MODES = ["baseline", "+tags", "+rerank", "+tags+rerank"]
TOP_K_PER_MODE = 10   # 모드별 후보 수집 상한
RERANK_POOL = 50      # 재순위에 넘길 최대 후보 수

# LLM 판단 기준 — 모든 호출에 동일하게 사용되므로 prompt caching 효과를 최대화
JUDGE_SYSTEM = [
    {
        "type": "text",
        "text": (
            "당신은 채용 검색 시스템의 결과 관련도를 평가하는 전문가입니다.\n\n"
            "[점수 기준]\n"
            "3 = 매우 관련 (직무·지역·조건이 검색 의도에 정확히 부합)\n"
            "2 = 관련있음 (직무는 맞고 주요 조건 대부분 충족)\n"
            "1 = 약간 관련 (같은 분야지만 직무나 조건이 다소 불일치)\n"
            "0 = 무관련 (직무·분야·조건이 검색 의도와 맞지 않음)\n\n"
            "[규칙]\n"
            "- 공고명·회사명·지역·고용형태·경력·연봉만으로 판단하세요.\n"
            "- 태그 정보는 제공되지 않습니다. 오직 제시된 텍스트만 사용하세요.\n"
            "- 숫자 하나만 출력하세요 (0, 1, 2, 3 중 하나). 다른 설명 없이."
        ),
        "cache_control": {"type": "ephemeral"},   # 매 호출마다 시스템 프롬프트 재전송 비용 절감
    }
]


# ──────────────────────────────────────────────────────────────────────────────
# 유틸
# ──────────────────────────────────────────────────────────────────────────────
def _job_text(r: RecruitOut) -> str:
    salary = JobPreprocessor.stringify_salary(r.annual_salary)
    experience = JobPreprocessor.stringify_experience(r.experience)
    form = get_employment_type_name(r.form) or "기타"
    return (
        f"공고명: {r.announcement_name}\n"
        f"회사명: {r.company_name}\n"
        f"지역: {r.region_name or '미상'}\n"
        f"고용형태: {form}\n"
        f"경력: {experience}\n"
        f"연봉: {salary}"
    )


def _parse_score(text: str) -> int:
    """LLM 응답에서 0~3 숫자 추출. 실패 시 0 반환."""
    for ch in text.strip():
        if ch in "0123":
            return int(ch)
    return 0


def _dcg(rels: list[float], k: int) -> float:
    return sum(r / math.log2(i + 2) for i, r in enumerate(rels[:k]))


def ndcg_at_k(ranked_ids: list[int], relevance_map: dict[int, int], k: int) -> float:
    rels = [relevance_map.get(rid, 0) for rid in ranked_ids[:k]]
    ideal = sorted(relevance_map.values(), reverse=True)
    dcg = _dcg(rels, k)
    idcg = _dcg(ideal, k)
    return dcg / idcg if idcg > 0 else 0.0


def precision_at_k(ranked_ids: list[int], relevance_map: dict[int, int], k: int, threshold: int = 2) -> float:
    hits = sum(1 for rid in ranked_ids[:k] if relevance_map.get(rid, 0) >= threshold)
    return hits / k if k else 0.0


# ──────────────────────────────────────────────────────────────────────────────
# 검색
# ──────────────────────────────────────────────────────────────────────────────
def _search(filters: dict, use_tags: bool, limit: int) -> list[RecruitOut]:
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
        use_tags=use_tags,
    )


def collect_mode_results(query: str, skip_rerank: bool) -> dict[str, list[RecruitOut]]:
    """쿼리에 대해 각 모드의 검색 결과를 반환."""
    filters = extract_filters(query)
    keyword = filters.get("keyword") or query

    results_no_tags = _search(filters, use_tags=False, limit=TOP_K_PER_MODE)
    results_tags = _search(filters, use_tags=True, limit=TOP_K_PER_MODE)

    mode_results = {
        "baseline": results_no_tags,
        "+tags": results_tags,
    }

    if not skip_rerank:
        mode_results["+rerank"] = rerank(keyword, results_no_tags[:RERANK_POOL])[:TOP_K_PER_MODE]
        mode_results["+tags+rerank"] = rerank(keyword, results_tags[:RERANK_POOL])[:TOP_K_PER_MODE]

    return mode_results


def pool_candidates(mode_results: dict[str, list[RecruitOut]]) -> list[RecruitOut]:
    """모드별 결과에서 중복 제거하여 후보 풀 반환."""
    seen, pool = set(), []
    for results in mode_results.values():
        for r in results:
            if r.id not in seen:
                seen.add(r.id)
                pool.append(r)
    return pool


# ──────────────────────────────────────────────────────────────────────────────
# LLM 판단
# ──────────────────────────────────────────────────────────────────────────────
def judge_relevance(client: anthropic.Anthropic, query: str, recruit: RecruitOut, model: str) -> int:
    """Claude로 (쿼리, 공고) 쌍의 관련도를 0~3점으로 판단."""
    response = client.messages.create(
        model=model,
        max_tokens=10,
        system=JUDGE_SYSTEM,
        messages=[{
            "role": "user",
            "content": f"검색어: \"{query}\"\n\n{_job_text(recruit)}\n\n점수:"
        }],
    )
    text = response.content[0].text if response.content else "0"
    return _parse_score(text)


def judge_query(
    client: anthropic.Anthropic,
    query: str,
    candidates: list[RecruitOut],
    cache: dict,
    model: str,
) -> dict[int, int]:
    """후보 공고들에 대한 관련도 판단. 캐시 활용."""
    relevance_map = {}
    for r in candidates:
        cache_key = f"{query}||{r.id}"
        if cache_key in cache:
            relevance_map[r.id] = cache[cache_key]
        else:
            score = judge_relevance(client, query, r, model)
            cache[cache_key] = score
            relevance_map[r.id] = score
            time.sleep(0.1)   # rate limit 여유
    return relevance_map


# ──────────────────────────────────────────────────────────────────────────────
# 지표 계산
# ──────────────────────────────────────────────────────────────────────────────
def compute_query_metrics(
    mode_results: dict[str, list[RecruitOut]],
    relevance_map: dict[int, int],
    k_values: list[int],
) -> dict:
    """쿼리 하나에 대한 모드별 지표 계산."""
    metrics = {}
    active_modes = list(mode_results.keys())
    for mode in active_modes:
        ranked_ids = [r.id for r in mode_results[mode]]
        m = {}
        for k in k_values:
            m[f"ndcg@{k}"] = round(ndcg_at_k(ranked_ids, relevance_map, k), 4)
            m[f"p@{k}"] = round(precision_at_k(ranked_ids, relevance_map, k), 4)
        metrics[mode] = m
    return metrics


# ──────────────────────────────────────────────────────────────────────────────
# 출력
# ──────────────────────────────────────────────────────────────────────────────
def print_summary(aggregated: dict, k_values: list[int], active_modes: list[str]):
    print()
    print("=" * 70)
    print("  LLM-as-Judge 컴포넌트 기여도 (NDCG·Precision 기준)")
    print("=" * 70)
    col = 14
    header = f"{'지표':<22}" + "".join(f"{m:>{col}}" for m in active_modes)
    print(header)
    print("-" * 70)

    for k in k_values:
        for metric_key in [f"ndcg@{k}", f"p@{k}"]:
            label = f"NDCG@{k}" if "ndcg" in metric_key else f"Precision@{k}(≥2)"
            row = f"{label:<22}"
            for mode in active_modes:
                val = aggregated[mode].get(metric_key, 0)
                row += f"{val:.4f}".rjust(col)
            print(row)

    print("=" * 70)

    # 기여도 요약
    ref = "baseline"
    last_k = k_values[-1]
    if ref in aggregated:
        print()
        for mode in active_modes:
            if mode == ref:
                continue
            delta_ndcg = aggregated[mode].get(f"ndcg@{last_k}", 0) - aggregated[ref].get(f"ndcg@{last_k}", 0)
            delta_p = aggregated[mode].get(f"p@{last_k}", 0) - aggregated[ref].get(f"p@{last_k}", 0)
            print(f"  {mode:<16} vs baseline │ NDCG@{last_k}: {delta_ndcg:+.4f}  P@{last_k}: {delta_p:+.4f}")
    print()


# ──────────────────────────────────────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--queries", type=str, default=JUDGE_QUERIES_PATH)
    parser.add_argument("--k", type=int, action="append", default=None)
    parser.add_argument("--out", type=str, default=DEFAULT_OUT)
    parser.add_argument("--judge-model", type=str, default="claude-haiku-4-5",
                        help="판단에 사용할 Claude 모델 (기본: haiku-4-5, 저비용)\n"
                             "정확도 우선: claude-opus-4-6")
    parser.add_argument("--no-rerank", action="store_true", help="재순위 없이 태깅 효과만 측정")
    parser.add_argument("--dry-run", action="store_true", help="API 호출 없이 예상 호출 수만 출력")
    parser.add_argument("--resume", action="store_true", help="judge_cache.json 기반으로 중단된 평가 재개")
    parser.add_argument("--cache", type=str, default=DEFAULT_CACHE, help="판단 캐시 파일 경로")
    parser.add_argument("--type-filter", type=str, default=None,
                        help="특정 유형만 실행 (예: A, B, C, D)")
    args = parser.parse_args()

    k_values = sorted(set(args.k)) if args.k else [5, 10]
    active_modes = (["baseline", "+tags"] if args.no_rerank else MODES)

    with open(args.queries, encoding="utf-8") as f:
        queries = json.load(f)

    if args.type_filter:
        queries = [q for q in queries if q["type"] == args.type_filter.upper()]

    # 캐시 로드
    cache = {}
    if args.resume and os.path.exists(args.cache):
        with open(args.cache, encoding="utf-8") as f:
            cache = json.load(f)
        print(f"캐시 로드: {len(cache)}건\n")

    # Dry-run: 예상 API 호출 수 계산
    if args.dry_run:
        print("=== Dry-run: 예상 API 호출 수 ===")
        total_new = 0
        for q in queries:
            mode_results = collect_mode_results(q["query"], args.no_rerank)
            candidates = pool_candidates(mode_results)
            new_calls = sum(1 for r in candidates if f"{q['query']}||{r.id}" not in cache)
            total_new += new_calls
            print(f"  [{q['id']}] 후보: {len(candidates)}건 / 신규 판단: {new_calls}건")
        print(f"\n총 신규 판단 호출: {total_new}건")
        print(f"예상 비용 (haiku-4-5 기준): ${total_new * 400 / 1_000_000:.2f}")
        print(f"예상 비용 (opus-4-6 기준):  ${total_new * 400 * 5 / 1_000_000:.2f}")
        return

    client = anthropic.Anthropic()

    all_results = []
    aggregated = {m: {} for m in active_modes}

    for idx, q in enumerate(queries, 1):
        qid, qtype, query = q["id"], q["type"], q["query"]
        print(f"[{idx:02d}/{len(queries)}] [{qid}({qtype})] {query!r}")

        # 검색
        mode_results = collect_mode_results(query, args.no_rerank)
        mode_results = {m: v for m, v in mode_results.items() if m in active_modes}
        candidates = pool_candidates(mode_results)
        print(f"  후보 풀: {len(candidates)}건 (모드별 최대 {TOP_K_PER_MODE}건 합산)")

        # 판단
        relevance_map = judge_query(client, query, candidates, cache, args.judge_model)
        score_dist = {s: sum(1 for v in relevance_map.values() if v == s) for s in range(4)}
        print(f"  관련도 분포: {score_dist}")

        # 캐시 저장 (매 쿼리마다)
        with open(args.cache, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)

        # 지표 계산
        query_metrics = compute_query_metrics(mode_results, relevance_map, k_values)

        # 집계
        for mode, m in query_metrics.items():
            for key, val in m.items():
                aggregated[mode][key] = aggregated[mode].get(key, 0.0) + val

        # 결과 기록
        all_results.append({
            "id": qid,
            "type": qtype,
            "query": query,
            "pool_size": len(candidates),
            "relevance_map": {str(k): v for k, v in relevance_map.items()},
            "mode_ranked_ids": {m: [r.id for r in mode_results[m]] for m in active_modes},
            "metrics": query_metrics,
        })

        # 진행 상황 출력
        for mode in active_modes:
            vals = " | ".join(
                f"NDCG@{k}={query_metrics[mode].get(f'ndcg@{k}', 0):.3f}" for k in k_values
            )
            print(f"  {mode:<16}: {vals}")
        print()

    # 평균 계산
    n = len(queries)
    for mode in active_modes:
        for key in aggregated[mode]:
            aggregated[mode][key] = round(aggregated[mode][key] / n, 4)

    print_summary(aggregated, k_values, active_modes)

    # 유형별 요약
    types = sorted(set(q["type"] for q in queries))
    if len(types) > 1:
        print("── 쿼리 유형별 NDCG@10 ──")
        last_k = k_values[-1]
        type_labels = {"A": "키워드 직접형", "B": "시맨틱형", "C": "모호형", "D": "엣지케이스"}
        for t in types:
            t_results = [r for r in all_results if r["type"] == t]
            for mode in active_modes:
                vals = [r["metrics"][mode].get(f"ndcg@{last_k}", 0) for r in t_results if mode in r["metrics"]]
                avg = sum(vals) / len(vals) if vals else 0
                print(f"  [{t}] {type_labels.get(t, t):<12} {mode:<16}: {avg:.4f}")
        print()

    # 저장
    output = {
        "config": {
            "judge_model": args.judge_model,
            "k_values": k_values,
            "top_k_per_mode": TOP_K_PER_MODE,
            "active_modes": active_modes,
            "n_queries": len(queries),
        },
        "summary": aggregated,
        "per_query": all_results,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"결과 저장: {args.out}")
    print(f"판단 캐시: {args.cache}  ({len(cache)}건)")


if __name__ == "__main__":
    main()
