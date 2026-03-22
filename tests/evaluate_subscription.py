"""
방안 1 (구독 키워드 확장) Before/After 평가 스크립트.

지표:
  matched_before  - 원본 키워드 AND 매칭 건수
  matched_after   - 확장 키워드 OR 매칭 건수
  new_matches     - 확장으로 새로 추가된 공고 수
  expansion_ratio - matched_after / matched_before

Usage:
    python tests/evaluate_subscription.py
    python tests/evaluate_subscription.py --out tests/results_subscription.json
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

# 테스트 구독 키워드 30개
TEST_KEYWORDS = [
    # 개발
    "백엔드", "프론트엔드", "풀스택", "데이터엔지니어", "ML엔지니어",
    "DevOps", "안드로이드", "iOS", "게임개발", "보안",
    # 디자인
    "UX디자인", "그래픽디자인", "영상편집", "3D모델링",
    # 데이터
    "데이터분석", "데이터사이언스",
    # 기획/마케팅
    "서비스기획", "디지털마케팅", "콘텐츠마케팅", "SNS마케팅",
    # 경영지원
    "회계", "인사", "영업",
    # 의료/복지
    "간호사", "요양보호사",
    # 제조
    "품질관리", "생산관리",
    # 금융
    "금융", "보험영업",
    # 교육
    "강사",
]


def _match_original(recruit: RecruitOut, keyword: str) -> bool:
    """원본 AND 매칭."""
    all_text = (recruit.announcement_name or '') + ' ' + ' '.join(recruit.tags)
    return all(token.lower() in all_text.lower() for token in keyword.split())


def _match_expanded(recruit: RecruitOut, expanded: list[str]) -> bool:
    """확장 OR 매칭."""
    all_text = (recruit.announcement_name or '') + ' ' + ' '.join(recruit.tags)
    all_text_lower = all_text.lower()
    return any(k.lower() in all_text_lower for k in expanded)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=str,
                        default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                             "results_subscription.json"))
    args = parser.parse_args()

    print("신규 공고 로딩 중 (최근 24h)...")
    recruits = get_new_recruits(hours=24 * 365)  # 평가용: 1년치 신규 공고 활용
    print(f"{len(recruits)}건 로드 완료\n")

    results = []
    total_before = total_after = 0

    for keyword in TEST_KEYWORDS:
        print(f"[{keyword}] 확장 중...", end=" ", flush=True)
        expanded = expand_keyword(keyword)
        print(f"→ {', '.join(expanded[:5])}{'...' if len(expanded) > 5 else ''}")

        before_ids = {r.id for r in recruits if _match_original(r, keyword)}
        after_ids = {r.id for r in recruits if _match_expanded(r, expanded)}
        new_ids = after_ids - before_ids

        entry = {
            "keyword": keyword,
            "expanded": expanded,
            "matched_before": len(before_ids),
            "matched_after": len(after_ids),
            "new_matches": len(new_ids),
            "expansion_ratio": round(len(after_ids) / len(before_ids), 2) if before_ids else None,
        }
        results.append(entry)
        total_before += len(before_ids)
        total_after += len(after_ids)

        print(f"         Before: {len(before_ids)}건 → After: {len(after_ids)}건 (+{len(new_ids)}건)")

    # 요약
    print("\n" + "=" * 55)
    print("  구독 키워드 확장 Before/After 요약")
    print("=" * 55)
    print(f"  전체 매칭 Before : {total_before}건")
    print(f"  전체 매칭 After  : {total_after}건")
    print(f"  증가량           : +{total_after - total_before}건 ({(total_after/total_before - 1)*100:.1f}%)" if total_before else "")
    print("=" * 55)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"summary": {
            "total_before": total_before,
            "total_after": total_after,
        }, "results": results}, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {args.out}")


if __name__ == "__main__":
    main()
