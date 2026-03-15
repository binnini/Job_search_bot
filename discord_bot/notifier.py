import logging
from collections import defaultdict
from db.io import (
    get_all_subscriptions, get_all_user_profiles, get_new_recruits,
    SubscriptionOut, ProfileOut, RecruitOut,
    get_notified_recruit_ids, save_notification_log,
)
from db.JobPreprocessor import JobPreprocessor


def _match(recruit: RecruitOut, keyword: str, profile: ProfileOut,
           expanded_keywords: list[str] = None) -> bool:
    """공고가 (키워드 + 프로필 필터) 조건에 부합하는지 검사.

    expanded_keywords: 방안1 키워드 확장 시 전달. 하나라도 매칭되면 통과 (OR 매칭).
    미전달 시 원본 keyword AND 매칭 (기존 방식).
    """
    if keyword:
        all_text = (recruit.announcement_name or '') + ' ' + ' '.join(recruit.tags)
        all_text_lower = all_text.lower()

        if expanded_keywords:
            # OR 매칭: 확장 키워드 중 하나라도 포함되면 통과
            if not any(k.lower() in all_text_lower for k in expanded_keywords):
                return False
        else:
            # AND 매칭: 원본 키워드의 모든 토큰 포함 (기존 방식)
            tokens = keyword.split()
            if not all(token.lower() in all_text_lower for token in tokens):
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


def format_recruit(i: int, r: RecruitOut, include_education: bool = False) -> str:
    lines = [
        f"📌 [{i}] {r.announcement_name} @ {r.company_name}",
        f"- 경력: {JobPreprocessor.stringify_experience(r.experience) or '무관'}",
    ]
    if include_education:
        lines.append(f"- 학력: {JobPreprocessor.stringify_education(r.education) or '무관'}")
    lines += [
        f"- 형태: {JobPreprocessor.stringify_form(r.form) or '정보 없음'}",
        f"- 연봉: {JobPreprocessor.stringify_salary(r.annual_salary) or '협의'}",
        f"- 마감일: {JobPreprocessor.stringify_deadline(r.deadline)}",
        f"🔗 {r.link}",
    ]
    return "\n".join(lines)


async def notify_subscribers(client, skip_dedup: bool = False):
    """신규 공고를 조회하고 구독 조건에 맞는 사용자에게 DM을 발송.

    skip_dedup=True: 발송 이력 무시 (테스트용). 이력 저장도 하지 않음.
    """
    new_recruits = get_new_recruits(hours=24)
    if not new_recruits:
        logging.info("신규 공고 없음 — 알림 생략")
        return

    subscriptions = get_all_subscriptions()
    profiles = get_all_user_profiles()
    logging.info(f"알림 처리 시작: 신규 공고 {len(new_recruits)}건, 구독 {len(subscriptions)}개")

    from discord_bot.keyword_expander import expand_keyword

    user_keywords: dict = defaultdict(list)
    for sub in subscriptions:
        user_keywords[sub.discord_user_id].append(sub.keyword)

    # 키워드 확장 (중복 제거 후 1회만 호출)
    all_keywords = list({kw for kws in user_keywords.values() for kw in kws if kw})
    expanded_map = {kw: expand_keyword(kw) for kw in all_keywords}
    logging.info(f"키워드 확장 완료: {len(expanded_map)}개")

    for discord_user_id, keywords in user_keywords.items():
        profile = profiles.get(discord_user_id)

        seen_ids: set = set()
        matched: list = []
        for keyword in keywords:
            expanded = expanded_map.get(keyword)
            for r in new_recruits:
                if r.id not in seen_ids and _match(r, keyword, profile, expanded_keywords=expanded):
                    seen_ids.add(r.id)
                    matched.append(r)

        if not matched:
            continue

        if skip_dedup:
            to_notify = matched
        else:
            already_notified = get_notified_recruit_ids(discord_user_id)
            to_notify = [r for r in matched if r.id not in already_notified]
            if not to_notify:
                logging.info(f"user={discord_user_id}: 매칭 {len(matched)}건 모두 이미 발송됨, 생략")
                continue

        # 방안 2: 발송 전 키워드별 관련도 재순위
        if len(keywords) == 1:
            from discord_bot.reranker import rerank
            to_notify = rerank(keywords[0], to_notify)
        elif len(keywords) > 1:
            from discord_bot.reranker import rerank
            # 다중 키워드: 가장 구독자가 많이 쓴 첫 번째 키워드 기준으로 재순위
            to_notify = rerank(keywords[0], to_notify)

        try:
            user = await client.fetch_user(int(discord_user_id))
            header = "🔍 [테스트] " if skip_dedup else "🔔 "
            lines = [f"{header}관심 조건에 맞는 공고 {len(to_notify)}건\n"]
            for i, r in enumerate(to_notify[:10], start=1):
                lines.append(format_recruit(i, r))
            msg = "\n\n".join(lines)

            if len(msg) > 1900:
                chunks = [msg[i:i + 1900] for i in range(0, len(msg), 1900)]
                for chunk in chunks:
                    await user.send(chunk)
            else:
                await user.send(msg)

            if not skip_dedup:
                save_notification_log(discord_user_id, [r.id for r in to_notify])
                logging.info(f"알림 전송 완료 → user={discord_user_id}, {len(to_notify)}건")
            else:
                logging.info(f"알림 테스트 전송 완료 → user={discord_user_id}, {len(to_notify)}건 (이력 저장 안함)")
        except Exception as e:
            logging.warning(f"알림 전송 실패 (user={discord_user_id}): {e}")
