"""
judge_queries.json의 각 쿼리에 대해 4가지 모드로 검색 후
후보 공고를 수집하여 candidates.json으로 저장.

Usage:
    python tests/collect_candidates.py
    python tests/collect_candidates.py --no-rerank
"""
import argparse
import json
import os
import sys
from dotenv import load_dotenv

load_dotenv(override=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from discord_bot.llm import extract_filters
from db.io import search_recruits_by_filter, RecruitOut
from db.JobPreprocessor import JobPreprocessor
from discord_bot.reranker import rerank
from discord_bot.keyword_expander import expand_keyword

JUDGE_QUERIES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "judge_queries.json")
DEFAULT_OUT   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "candidates.json")
TOP_K = 10
RERANK_POOL = 50
ADAPTIVE_THRESHOLD = 3  # AND 결과 이 미만이면 LLM 확장 fallback


def _search(filters, use_tags, limit):
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


def _to_dict(r: RecruitOut):
    return {
        "id": r.id,
        "announcement_name": r.announcement_name,
        "company_name": r.company_name,
        "region": r.region_name or "미상",
        "form": JobPreprocessor.stringify_form(r.form),
        "experience": JobPreprocessor.stringify_experience(r.experience),
        "salary": JobPreprocessor.stringify_salary(r.annual_salary),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-rerank", action="store_true")
    parser.add_argument("--out", default=DEFAULT_OUT)
    args = parser.parse_args()

    with open(JUDGE_QUERIES, encoding="utf-8") as f:
        queries = json.load(f)

    output = []
    total_candidates = 0

    for q in queries:
        qid, query = q["id"], q["query"]
        print(f"[{qid}] {query!r}", end=" ... ", flush=True)

        filters = extract_filters(query)
        keyword = filters.get("keyword") or query
        form_code = JobPreprocessor.parse_form(filters.get("form") or "")

        no_tags = _search(filters, use_tags=False, limit=TOP_K)
        with_tags = _search(filters, use_tags=True, limit=TOP_K)

        # +expanded: LLM 쿼리 확장 키워드로 제목·태그 OR 매칭 (항상 확장)
        expanded_kws = expand_keyword(keyword) if keyword else None
        with_expanded = search_recruits_by_filter(
            keyword=keyword,
            min_deadline=filters.get("min_deadline"),
            min_annual_salary=filters.get("min_annual_salary"),
            company_name=filters.get("company_name"),
            max_experience=filters.get("max_experience"),
            form=form_code,
            region=filters.get("region"),
            limit=TOP_K,
            expanded_keywords=expanded_kws,
        )

        # +adaptive: AND 결과 부족할 때만 LLM 확장 OR 매칭으로 fallback
        if len(no_tags) < ADAPTIVE_THRESHOLD and expanded_kws:
            with_adaptive = with_expanded
        else:
            with_adaptive = no_tags

        modes = {
            "baseline":  [_to_dict(r) for r in no_tags],
            "+tags":     [_to_dict(r) for r in with_tags],
            "+expanded": [_to_dict(r) for r in with_expanded],
            "+adaptive": [_to_dict(r) for r in with_adaptive],
        }

        if not args.no_rerank:
            modes["+rerank"]          = [_to_dict(r) for r in rerank(keyword, no_tags[:RERANK_POOL])[:TOP_K]]
            modes["+tags+rerank"]     = [_to_dict(r) for r in rerank(keyword, with_tags[:RERANK_POOL])[:TOP_K]]
            modes["+expanded+rerank"] = [_to_dict(r) for r in rerank(keyword, with_expanded[:RERANK_POOL])[:TOP_K]]

        # 후보 풀 (중복 제거)
        seen, pool = set(), []
        for results in modes.values():
            for r in results:
                if r["id"] not in seen:
                    seen.add(r["id"])
                    pool.append(r)

        total_candidates += len(pool)
        print(f"후보 {len(pool)}건")

        output.append({
            "id": qid,
            "type": q["type"],
            "query": query,
            "modes": modes,
            "pool": pool,
        })

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n완료: {len(queries)}쿼리 / 총 후보 {total_candidates}건")
    print(f"저장: {args.out}")


if __name__ == "__main__":
    main()
