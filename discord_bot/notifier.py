import logging
from collections import defaultdict
from db.io import (
    get_all_subscriptions, get_all_user_profiles, get_new_recruits,
    SubscriptionOut, ProfileOut, RecruitOut,
    get_notified_recruit_ids, save_notification_log,
)
from db.JobPreprocessor import JobPreprocessor


def _match(recruit: RecruitOut, keyword: str, profile: ProfileOut) -> bool:
    """공고가 (키워드 + 프로필 필터) 조건에 부합하는지 검사."""
    if keyword:
        tokens = keyword.split()
        all_text = (recruit.announcement_name or '') + ' ' + ' '.join(recruit.tags)
        if not all(token.lower() in all_text.lower() for token in tokens):
            return False

    if profile:
        if profile.region and recruit.region_name and profile.region not in recruit.region_name:
            return False

        if profile.form is not None and recruit.form != profile.form:
            return False

        if profile.max_experience is not None and recruit.experience is not None:
            if recruit.experience > profile.max_experience:
                return False

        if profile.min_annual_salary is not None and recruit.annual_salary is not None:
            if recruit.annual_salary < profile.min_annual_salary:
                return False

    return True


def _format_recruit(i: int, r: RecruitOut) -> str:
    return (
        f"📌 [{i}] {r.announcement_name} @ {r.company_name}\n"
        f"- 경력: {JobPreprocessor.stringify_experience(r.experience)}\n"
        f"- 형태: {JobPreprocessor.stringify_form(r.form)}\n"
        f"- 연봉: {JobPreprocessor.stringify_salary(r.annual_salary)}\n"
        f"- 마감일: {JobPreprocessor.stringify_deadline(r.deadline)}\n"
        f"🔗 {r.link}"
    )


async def notify_subscribers(client):
    """신규 공고를 조회하고 구독 조건에 맞는 사용자에게 DM을 발송."""
    new_recruits = get_new_recruits(hours=24)
    if not new_recruits:
        logging.info("신규 공고 없음 — 알림 생략")
        return

    subscriptions = get_all_subscriptions()
    profiles = get_all_user_profiles()  # {discord_user_id: ProfileOut}
    logging.info(f"알림 처리 시작: 신규 공고 {len(new_recruits)}건, 구독 {len(subscriptions)}개")

    # 사용자별로 키워드를 묶어서 처리 (사용자당 1회 DM)
    user_keywords: dict = defaultdict(list)
    for sub in subscriptions:
        user_keywords[sub.discord_user_id].append(sub.keyword)

    for discord_user_id, keywords in user_keywords.items():
        profile = profiles.get(discord_user_id)

        # 모든 키워드 매칭 결과를 합산 (중복 제거)
        seen_ids: set = set()
        matched: list = []
        for keyword in keywords:
            for r in new_recruits:
                if r.id not in seen_ids and _match(r, keyword, profile):
                    seen_ids.add(r.id)
                    matched.append(r)

        if not matched:
            continue

        # 이미 알림 발송한 공고 제외
        already_notified = get_notified_recruit_ids(discord_user_id)
        to_notify = [r for r in matched if r.id not in already_notified]

        if not to_notify:
            logging.info(f"user={discord_user_id}: 매칭 {len(matched)}건 모두 이미 발송됨, 생략")
            continue

        try:
            user = await client.fetch_user(int(discord_user_id))
            lines = [f"🔔 관심 조건에 맞는 신규 공고 {len(to_notify)}건이 등록되었습니다!\n"]
            for i, r in enumerate(to_notify[:10], start=1):
                lines.append(_format_recruit(i, r))
            msg = "\n\n".join(lines)

            if len(msg) > 1900:
                chunks = [msg[i:i + 1900] for i in range(0, len(msg), 1900)]
                for chunk in chunks:
                    await user.send(chunk)
            else:
                await user.send(msg)

            # 발송 성공 후 이력 저장
            save_notification_log(discord_user_id, [r.id for r in to_notify])
            logging.info(f"알림 전송 완료 → user={discord_user_id}, {len(to_notify)}건 (중복 제외 {len(matched) - len(to_notify)}건)")
        except Exception as e:
            logging.warning(f"알림 전송 실패 (user={discord_user_id}): {e}")
