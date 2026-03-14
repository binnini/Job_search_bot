"""
구독 시스템 통합 테스트
- 구독 CRUD
- 조건별 매칭 로직 (_match)
- get_new_recruits 조회
결과는 test_subscription_results.txt 에 출력됩니다.
"""
from dotenv import load_dotenv
load_dotenv(override=True)

from db.io import (
    save_subscription, get_subscription, delete_subscription,
    get_all_subscriptions, get_new_recruits, SubscriptionOut
)
from discord_bot.notifier import _match, _format_recruit

TEST_SUBSCRIPTIONS = [
    # (설명, discord_user_id, 조건)
    ("백엔드 서울 정규직 신입",  "test_001", dict(keyword="백엔드", region="서울", form=1, max_experience=0)),
    ("파이썬 개발자",            "test_002", dict(keyword="파이썬")),
    ("연봉 5000 이상",           "test_003", dict(min_annual_salary=5000)),
    ("인턴 공고",                "test_004", dict(form=3)),
    ("경기 정규직",              "test_005", dict(region="경기", form=1)),
    ("조건 없음 (전체 매칭)",    "test_006", dict()),
    ("절대 매칭 안 되는 조건",   "test_007", dict(keyword="백엔드", min_annual_salary=99999)),
]


def run_tests(output_path="test_subscription_results.txt"):
    lines = []
    header = "=" * 60 + "\n  구독 시스템 테스트 결과\n" + "=" * 60
    lines.append(header)

    # ── 1. CRUD 테스트 ────────────────────────────────────────
    lines.append("\n[CRUD 테스트]")

    for desc, uid, cond in TEST_SUBSCRIPTIONS:
        save_subscription(discord_user_id=uid, **cond)
    lines.append(f"  구독 저장: {len(TEST_SUBSCRIPTIONS)}건 완료")

    all_subs = get_all_subscriptions()
    test_subs = [s for s in all_subs if s.discord_user_id.startswith("test_")]
    lines.append(f"  전체 조회: {len(test_subs)}건 확인")

    sub = get_subscription("test_001")
    lines.append(f"  단건 조회: {sub}")

    delete_subscription("test_007")
    after = get_subscription("test_007")
    lines.append(f"  삭제 확인: test_007 → {after if after else '삭제됨 ✓'}")

    # ── 2. 신규 공고 조회 ────────────────────────────────────
    lines.append("\n[신규 공고 조회]")
    new_recruits = get_new_recruits(hours=24)
    lines.append(f"  최근 24시간 신규 공고: {len(new_recruits)}건")
    if new_recruits:
        lines.append(f"  샘플: {new_recruits[0].announcement_name} @ {new_recruits[0].company_name}")

    # ── 3. 매칭 테스트 ──────────────────────────────────────
    lines.append("\n[매칭 테스트]")

    if not new_recruits:
        lines.append("  신규 공고 없어 매칭 테스트 생략")
    else:
        active_subs = [s for s in get_all_subscriptions() if s.discord_user_id.startswith("test_")]
        for sub in active_subs:
            matched = [r for r in new_recruits if _match(r, sub)]
            cond_str = ", ".join(f"{k}={v}" for k, v in {
                "keyword": sub.keyword, "region": sub.region,
                "form": sub.form, "max_exp": sub.max_experience,
                "min_salary": sub.min_annual_salary,
            }.items() if v is not None)
            lines.append(f"\n  구독 [{sub.discord_user_id}] {cond_str or '(조건 없음)'}")
            lines.append(f"  → 매칭 공고: {len(matched)}건")
            for i, r in enumerate(matched[:3], start=1):
                lines.append(f"    {i}. {r.announcement_name} @ {r.company_name}")

    # ── 4. 정리 ─────────────────────────────────────────────
    for _, uid, _ in TEST_SUBSCRIPTIONS:
        delete_subscription(uid)
    lines.append("\n[테스트 구독 정리 완료]")

    output = "\n".join(lines)
    print(output)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output)
    print(f"\n✅ 결과 저장 완료: {output_path}")


if __name__ == "__main__":
    run_tests()
