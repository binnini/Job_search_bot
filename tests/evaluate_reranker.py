"""
방안 2 (알림 재순위) Before/After 평가 스크립트.

평가 방법:
  - 방안 1 확장 매칭으로 후보 공고를 뽑은 뒤
  - Before: ID 역순 상위 10건에서 원본 키워드 AND 매칭 비율 (Precision@10)
  - After:  rerank 후 상위 10건에서 원본 키워드 AND 매칭 비율 (Precision@10)
  - 원본 AND 매칭 = 실제 관련 공고의 ground truth

Usage:
    python tests/evaluate_reranker.py
    python tests/evaluate_reranker.py --out tests/results_reranker.json --top-k 10
"""
import argparse
import json
import os
import sys
from dotenv import load_dotenv

load_dotenv(override=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.io import get_new_recruits, RecruitOut
from discord_bot.keyword_expander import expand_keyword
from discord_bot.reranker import rerank

TEST_KEYWORDS = [
    "백엔드", "프론트엔드", "데이터엔지니어",
    "ML엔지니어", "DevOps", "게임개발",
    "UX디자인", "영상편집", "품질관리", "영업",
]


def _match_original(recruit: RecruitOut, keyword: str) -> bool:
    all_text = (recruit.announcement_name or '') + ' ' + ' '.join(recruit.tags)
    return all(token.lower() in all_text.lower() for token in keyword.split())


def _match_expanded(recruit: RecruitOut, expanded: list[str]) -> bool:
    all_text = (recruit.announcement_name or '') + ' ' + ' '.join(recruit.tags)
    all_text_lower = all_text.lower()
    return any(k.lower() in all_text_lower for k in expanded)


def precision_at_k(recruits: list[RecruitOut], keyword: str, k: int) -> float:
    top_k = recruits[:k]
    hits = sum(1 for r in top_k if _match_original(r, keyword))
    return hits / k if k else 0.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--out", type=str,
                        default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                             "results_reranker.json"))
    args = parser.parse_args()
    K = args.top_k

    print("공고 로딩 중...")
    recruits = get_new_recruits(hours=24 * 365)
    print(f"{len(recruits)}건 로드\n")

    results = []
    total_before = total_after = 0

    for keyword in TEST_KEYWORDS:
        print(f"[{keyword}] 확장 + 재순위 평가 중...")
        expanded = expand_keyword(keyword)

        # 후보 공고 (확장 매칭)
        candidates = [r for r in recruits if _match_expanded(r, expanded)]
        if not candidates:
            print(f"  → 매칭 공고 없음, 건너뜀\n")
            continue

        # Before: ID 역순 (현재 방식)
        before_list = sorted(candidates, key=lambda r: r.id, reverse=True)
        p_before = precision_at_k(before_list, keyword, K)

        # After: rerank
        after_list = rerank(keyword, candidates[:50])  # 상위 50건만 재순위
        p_after = precision_at_k(after_list, keyword, K)

        total_before += p_before
        total_after += p_after

        entry = {
            "keyword": keyword,
            "expanded": expanded,
            "candidates": len(candidates),
            f"precision@{K}_before": round(p_before, 3),
            f"precision@{K}_after": round(p_after, 3),
            "delta": round(p_after - p_before, 3),
        }
        results.append(entry)
        print(f"  후보: {len(candidates)}건 | P@{K} Before: {p_before:.1%} → After: {p_after:.1%} ({p_after-p_before:+.1%})\n")

    n = len(results)
    avg_before = total_before / n if n else 0
    avg_after = total_after / n if n else 0

    print("=" * 55)
    print(f"  평균 Precision@{K} Before : {avg_before:.1%}")
    print(f"  평균 Precision@{K} After  : {avg_after:.1%}")
    print(f"  개선                      : {avg_after - avg_before:+.1%}")
    print("=" * 55)

    output = {
        "summary": {
            f"avg_precision@{K}_before": round(avg_before, 4),
            f"avg_precision@{K}_after": round(avg_after, 4),
            "delta": round(avg_after - avg_before, 4),
        },
        "results": results,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {args.out}")


if __name__ == "__main__":
    main()
