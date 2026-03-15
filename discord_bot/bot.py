import discord
import os
import logging
from discord.ext import tasks
from dotenv import load_dotenv
from discord_bot.llm import sql_search, extract_filters
from discord_bot.notifier import notify_subscribers
from discord_bot.views import SubscriptionView, _describe_profile
from db.base import ensure_tables
from db.io import (
    save_subscription, delete_subscription, delete_all_subscriptions,
    get_subscriptions, get_user_profile, MAX_SUBSCRIPTIONS_PER_USER,
)
from db.JobPreprocessor import JobPreprocessor

load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

intents = discord.Intents.all()
client = discord.Client(intents=intents)



@client.event
async def on_ready():
    ensure_tables()
    if not notify_task.is_running():
        notify_task.start()
    logging.info(f"봇 준비 완료: {client.user.name}")
    print(f'We have logged in as {client.user.name}')


@tasks.loop(hours=24)
async def notify_task():
    logging.info("정기 알림 태스크 실행")
    await notify_subscribers(client)


@notify_task.before_loop
async def before_notify_task():
    await client.wait_until_ready()


@client.event
async def on_message(message):
    if message.author == client.user:
        return

    content = message.content.strip()
    if not content:
        return

    # ── !도움 ──────────────────────────────────────────────
    if content.startswith("!도움"):
        await message.channel.send(
            "**📖 사용 가능한 명령어**\n\n"
            "`!구독` — 필터(지역/고용형태/경력/연봉) + 키워드 등록\n"
            "　　　　필터는 공통 적용, 키워드는 각각 별도 구독으로 관리\n"
            "`!내구독` — 공통 필터 + 키워드 구독 목록 확인\n"
            "`!구독해제 <번호>` — 특정 키워드 구독 해제 (번호는 `!내구독` 참고)\n"
            "`!구독해제 전체` — 모든 키워드 구독 해제\n"
            "`!알림테스트` — 지금 즉시 알림 조건 확인 및 DM 발송\n"
            "`!인사이트` — 현재 채용 시장 현황 (인기 스택, 지역 분포, 평균 연봉)\n\n"
            "**🔍 공고 검색**\n"
            "명령어 없이 자연어로 입력하면 공고를 검색합니다.\n"
            "예) `백엔드 서울 정규직 신입`, `카카오 공고`, `연봉 5000만원 이상`"
        )
        return

    # ── !인사이트 ──────────────────────────────────────────
    if content.startswith("!인사이트"):
        await message.channel.send("📊 채용 시장 분석 중...")
        try:
            from db.analytics import get_market_snapshot, get_salary_by_tags
            snap = get_market_snapshot()

            # 인기 태그 TOP 5 기준 연봉 조회
            top_kws = [t["name"] for t in snap["top_tags"][:5]]
            salary_data = get_salary_by_tags(top_kws)
            salary_map = {s["keyword"]: s["avg_salary"] for s in salary_data}

            lines = [f"**📊 채용 시장 현황 ({snap['date']})**\n"]

            lines.append(f"**유효 공고** {snap['total_valid_jobs']:,}건  |  **오늘 신규** {snap['new_jobs_today']:,}건  |  **전체 평균연봉** {snap['avg_salary']:,}만원\n")

            lines.append("**🔥 인기 기술 스택 TOP 10**")
            for i, t in enumerate(snap["top_tags"], 1):
                sal = f"  _(평균 {salary_map[t['name']]:,}만원)_" if t["name"] in salary_map else ""
                lines.append(f"`{i:>2}.` {t['name']}  **{t['count']:,}건**{sal}")

            lines.append("\n**📍 지역별 공고 분포**")
            for r in snap["region_dist"]:
                lines.append(f"· {r['region']}  {r['count']:,}건")

            lines.append("\n**🎓 경력별 분포**")
            for e in snap["experience_dist"]:
                lines.append(f"· {e['label']}  {e['count']:,}건")

            msg = "\n".join(lines)
            if len(msg) > 1900:
                for chunk in [msg[i:i+1900] for i in range(0, len(msg), 1900)]:
                    await message.channel.send(chunk)
            else:
                await message.channel.send(msg)
        except Exception as e:
            await message.channel.send(f"❌ 인사이트 조회 실패: {str(e)}")
        return

    # ── !알림테스트 ────────────────────────────────────────
    if content.startswith("!알림테스트"):
        await message.channel.send("🔍 알림 조건을 확인 중입니다...")
        try:
            await notify_subscribers(client, skip_dedup=True)
            await message.channel.send("✅ 알림 테스트 완료. 조건에 맞는 공고가 있으면 DM을 확인하세요.")
        except Exception as e:
            await message.channel.send(f"❌ 알림 테스트 실패: {str(e)}")
        return

    # ── !구독해제 ──────────────────────────────────────────
    if content.startswith("!구독해제"):
        arg = content[len("!구독해제"):].strip()
        uid = str(message.author.id)

        if arg == "전체":
            count = delete_all_subscriptions(uid)
            await message.channel.send(
                f"✅ 구독 {count}개를 모두 해제했습니다." if count else "구독 중인 조건이 없습니다."
            )
        elif arg.isdigit():
            ok = delete_subscription(uid, int(arg))
            await message.channel.send(
                f"✅ {arg}번 구독을 해제했습니다." if ok else f"{arg}번 구독을 찾을 수 없습니다. `!내구독`으로 목록을 확인하세요."
            )
        else:
            await message.channel.send("사용법: `!구독해제 1` (번호) 또는 `!구독해제 전체`")
        return

    # ── !내구독 ────────────────────────────────────────────
    if content.startswith("!내구독"):
        uid = str(message.author.id)
        profile = get_user_profile(uid)
        subs = get_subscriptions(uid)

        lines = ["**📋 내 구독 현황**\n"]
        lines.append("**[공통 필터]**")
        lines.append(_describe_profile(profile))
        lines.append(f"\n**[키워드 구독]** ({len(subs)}/{MAX_SUBSCRIPTIONS_PER_USER}개)")
        if subs:
            for i, sub in enumerate(subs, start=1):
                lines.append(f"[{i}] {sub.keyword or '(키워드 없음)'}")
        else:
            lines.append("등록된 키워드가 없습니다. `!구독`으로 등록하세요.")
        await message.channel.send("\n".join(lines))
        return

    # ── !구독 ──────────────────────────────────────────────
    if content.startswith("!구독"):
        view = SubscriptionView(discord_user_id=str(message.author.id))
        await message.channel.send(
            f"📋 구독 조건을 선택해주세요. ({MAX_SUBSCRIPTIONS_PER_USER}개까지 등록 가능)\n"
            "원하지 않는 항목은 **상관없음**으로 두세요.",
            view=view,
        )
        return

    # ── 일반 검색 쿼리 ────────────────────────────────────
    await message.channel.send("잠시만 기다려 주세요...")
    try:
        response = sql_search(content, limit=5)
        if len(response) > 1900:
            chunks = [response[i:i + 1900] for i in range(0, len(response), 1900)]
            for chunk in chunks:
                await message.channel.send(chunk)
        else:
            await message.channel.send(response)
    except Exception as e:
        await message.channel.send(f"오류 발생: {str(e)}")


client.run(TOKEN)
