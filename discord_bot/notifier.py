import logging
from db.io import (
    get_all_subscriptions, get_new_recruits, SubscriptionOut, RecruitOut,
    get_notified_recruit_ids, save_notification_log,
)
from db.JobPreprocessor import JobPreprocessor


def _match(recruit: RecruitOut, sub: SubscriptionOut) -> bool:
    """공고가 구독 조건에 부합하는지 검사."""
    if sub.keyword:
        tokens = sub.keyword.split()
        all_text = (recruit.announcement_name or '') + ' ' + ' '.join(recruit.tags)
        if not all(token.lower() in all_text.lower() for token in tokens):
            return False

    if sub.region and recruit.region_name and sub.region not in recruit.region_name:
        return False

    if sub.form is not None and recruit.form != sub.form:
        return False

    if sub.max_experience is not None and recruit.experience is not None:
        if recruit.experience > sub.max_experience:
            return False

    if sub.min_annual_salary is not None and recruit.annual_salary is not None:
        if recruit.annual_salary < sub.min_annual_salary:
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
    logging.info(f"알림 처리 시작: 신규 공고 {len(new_recruits)}건, 구독자 {len(subscriptions)}명")

    for sub in subscriptions:
        matched = [r for r in new_recruits if _match(r, sub)]
        if not matched:
            continue

        # 이미 알림 발송한 공고 제외
        already_notified = get_notified_recruit_ids(sub.discord_user_id)
        to_notify = [r for r in matched if r.id not in already_notified]

        if not to_notify:
            logging.info(f"user={sub.discord_user_id}: 매칭 {len(matched)}건 모두 이미 발송됨, 생략")
            continue

        try:
            user = await client.fetch_user(int(sub.discord_user_id))
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
            save_notification_log(sub.discord_user_id, [r.id for r in to_notify])
            logging.info(f"알림 전송 완료 → user={sub.discord_user_id}, {len(to_notify)}건 (중복 제외 {len(matched) - len(to_notify)}건)")
        except Exception as e:
            logging.warning(f"알림 전송 실패 (user={sub.discord_user_id}): {e}")
