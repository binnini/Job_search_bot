"""
구독 시스템 통합 테스트
- 구독 CRUD (keyword 전용)
- 프로필 저장/조회
- 조건별 매칭 로직 (_match)
- get_new_recruits 조회
결과는 test_subscription_results.txt 에 출력됩니다.
"""
from dotenv import load_dotenv
load_dotenv(override=True)

import os
from db.io import (
    save_subscription, get_subscriptions, delete_subscription, delete_all_subscriptions,
    get_all_subscriptions, get_new_recruits, SubscriptionOut,
    save_user_profile, get_user_profile, ProfileOut,
)
from discord_bot.notifier import _match, format_recruit

TEST_USERS = [
    # (discord_user_id, keyword, profile_kwargs)
    ("test_001", "백엔드",   dict(region="서울", form=1, max_experience=0)),
    ("test_002", "파이썬",   dict()),
    ("test_003", None,       dict(min_annual_salary=5000)),
    ("test_004", None,       dict(form=3)),
    ("test_005", None,       dict(region="경기", form=1)),
    ("test_006", None,       dict()),
    ("test_007", "백엔드",   dict(min_annual_salary=99999)),
]


def run_tests(output_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_subscription_results.txt")):
    lines = []
    header = "=" * 60 + "\n  구독 시스템 테스트 결과\n" + "=" * 60
    lines.append(header)

    # ── 1. CRUD 테스트 ────────────────────────────────────────
    lines.append("\n[CRUD 테스트]")

    for uid, keyword, profile_kwargs in TEST_USERS:
        save_subscription(discord_user_id=uid, keyword=keyword)
        if profile_kwargs:
            save_user_profile(discord_user_id=uid, **profile_kwargs)
    lines.append(f"  구독 저장: {len(TEST_USERS)}건 완료")

    all_subs = get_all_subscriptions()
    test_subs = [s for s in all_subs if s.discord_user_id.startswith("test_")]
    lines.append(f"  전체 조회: {len(test_subs)}건 확인")

    subs_001 = get_subscriptions("test_001")
    lines.append(f"  단건 조회 (test_001): {subs_001}")

    delete_subscription("test_007", index=1)
    after = get_subscriptions("test_007")
    lines.append(f"  삭제 확인: test_007 → {'삭제됨 ✓' if not after else after}")

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
            profile = get_user_profile(sub.discord_user_id)
            matched = [r for r in new_recruits if _match(r, sub.keyword, profile)]
            cond_parts = []
            if sub.keyword:
                cond_parts.append(f"keyword={sub.keyword}")
            if profile:
                for k in ("region", "form", "max_experience", "min_annual_salary"):
                    v = getattr(profile, k)
                    if v is not None:
                        cond_parts.append(f"{k}={v}")
            cond_str = ", ".join(cond_parts) or "(조건 없음)"
            lines.append(f"\n  구독 [{sub.discord_user_id}] {cond_str}")
            lines.append(f"  → 매칭 공고: {len(matched)}건")
            for i, r in enumerate(matched[:3], start=1):
                lines.append(f"    {i}. {r.announcement_name} @ {r.company_name}")

    # ── 4. 정리 ─────────────────────────────────────────────
    for uid, _, _ in TEST_USERS:
        delete_all_subscriptions(uid)
    lines.append("\n[테스트 구독 정리 완료]")

    output = "\n".join(lines)
    print(output)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output)
    print(f"\n✅ 결과 저장 완료: {output_path}")


if __name__ == "__main__":
    run_tests()
