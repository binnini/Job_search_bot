"""
방안 3 (LLM 시맨틱 태깅) Before/After 평가 스크립트.

평가 방법:
  - 공고명에 등장하지 않지만 의미적으로 관련된 동의어/기술 스택 쿼리 사용
  - Before: 태깅 전 — 공고명만으로 검색
  - After:  태깅 후 — 공고명 + LLM 생성 태그로 검색
  - 지표: Recall@K (쿼리에 해당하는 공고가 상위 K건 안에 있는 비율)

Usage:
    python tests/evaluate_tagging.py
    python tests/evaluate_tagging.py --out tests/results_tagging.json --top-k 10
"""
import argparse
import json
import os
import sys
from dotenv import load_dotenv

load_dotenv(override=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.io import SessionLocal, search_recruits_by_filter
from db.models import Recruit, Tag
from sqlalchemy import func
from datetime import date

# 공고명에 잘 안 등장하지만 의미적으로 동의어인 쿼리 쌍
# (검색 쿼리, 공고명에 실제 등장하는 키워드)
SYNONYM_PAIRS = [
    ("ML엔지니어",       ["머신러닝", "machine learning", "AI", "인공지능"]),
    ("MLOps",            ["ML엔지니어", "머신러닝", "모델배포"]),
    ("백엔드",           ["server", "서버", "API", "Spring", "Django"]),
    ("프론트엔드",       ["frontend", "React", "Vue", "UI개발"]),
    ("DevOps",           ["인프라", "CI/CD", "Kubernetes", "AWS"]),
    ("데이터분석",       ["analytics", "SQL", "Python", "tableau"]),
    ("UX디자인",         ["사용자경험", "UI/UX", "Figma", "프로토타입"]),
    ("임베디드",         ["펌웨어", "firmware", "RTOS", "MCU"]),
    ("클라우드",         ["AWS", "Azure", "GCP", "cloud"]),
    ("보안",             ["security", "취약점", "SIEM", "침해"]),
]


def _has_tag_match(recruit_id: int, query: str, session) -> bool:
    """해당 공고에 쿼리 키워드를 포함하는 태그가 있는지 확인."""
    count = (
        session.query(Tag)
        .join(Recruit.tags)
        .filter(Recruit.id == recruit_id)
        .filter(Tag.name.ilike(f"%{query}%"))
        .count()
    )
    return count > 0


def _has_name_match(announcement_name: str, keywords: list[str]) -> bool:
    """공고명에 동의어 키워드 중 하나라도 포함되는지."""
    name_lower = (announcement_name or "").lower()
    return any(k.lower() in name_lower for k in keywords)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--out", type=str,
                        default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                             "results_tagging.json"))
    args = parser.parse_args()
    K = args.top_k

    session = SessionLocal()
    today = date.today()

    results = []
    total_before = total_after = 0

    for query, synonyms in SYNONYM_PAIRS:
        print(f"[{query}] 평가 중 (동의어: {synonyms[:2]}...)...")

        # 검색 결과 (공고명 + 태그 모두 사용)
        search_results = search_recruits_by_filter(keyword=query, limit=K)
        if not search_results:
            print(f"  → 검색 결과 없음, 건너뜀\n")
            results.append({
                "query": query, "synonyms": synonyms,
                f"recall@{K}_before": 0, f"recall@{K}_after": 0, "delta": 0
            })
            continue

        # Ground truth: deadline >= today인 공고 중 공고명에 동의어가 포함된 공고 수
        gt_count = (
            session.query(Recruit)
            .filter(Recruit.deadline >= today)
            .filter(
                func.lower(Recruit.announcement_name).contains(synonyms[0].lower()) if synonyms
                else Recruit.id == -1
            )
            .count()
        )

        if gt_count == 0:
            print(f"  → ground truth 없음 (동의어 '{synonyms[0]}' 공고명 매칭 0건), 건너뜀\n")
            continue

        # Before: 쿼리가 공고명에만 매칭되는 공고 수 (태그 무시)
        hits_before = sum(
            1 for r in search_results
            if query.lower() in (r.announcement_name or "").lower()
        )
        recall_before = hits_before / min(K, len(search_results))

        # After: 쿼리가 공고명 OR 태그에 매칭되는 공고 수 (현재 search는 이미 태그 포함)
        # 추가로 태그 매칭으로만 찾힌 공고 수 확인
        hits_after_name = sum(
            1 for r in search_results
            if query.lower() in (r.announcement_name or "").lower()
        )
        hits_after_tag = sum(
            1 for r in search_results
            if query.lower() not in (r.announcement_name or "").lower()
            and any(query.lower() in t.lower() for t in r.tags)
        )
        recall_after = (hits_after_name + hits_after_tag) / min(K, len(search_results))

        total_before += recall_before
        total_after += recall_after

        entry = {
            "query": query,
            "synonyms": synonyms,
            "results_count": len(search_results),
            "gt_count": gt_count,
            "hits_name_only": hits_after_name,
            "hits_tag_only": hits_after_tag,
            f"recall@{K}_before": round(recall_before, 3),
            f"recall@{K}_after": round(recall_after, 3),
            "delta": round(recall_after - recall_before, 3),
        }
        results.append(entry)
        print(f"  결과: {len(search_results)}건 | 공고명 매칭: {hits_after_name}건 | 태그 전용 매칭: {hits_after_tag}건")
        print(f"  Recall@{K} Before: {recall_before:.1%} → After: {recall_after:.1%} ({recall_after-recall_before:+.1%})\n")

    n = len([r for r in results if f"recall@{K}_before" in r])
    avg_before = total_before / n if n else 0
    avg_after = total_after / n if n else 0

    print("=" * 55)
    print(f"  평균 Recall@{K} Before : {avg_before:.1%}")
    print(f"  평균 Recall@{K} After  : {avg_after:.1%}")
    print(f"  개선                   : {avg_after - avg_before:+.1%}")
    print("=" * 55)

    output = {
        "summary": {
            f"avg_recall@{K}_before": round(avg_before, 4),
            f"avg_recall@{K}_after": round(avg_after, 4),
            "delta": round(avg_after - avg_before, 4),
        },
        "results": results,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {args.out}")

    session.close()


if __name__ == "__main__":
    main()
