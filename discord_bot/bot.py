import discord
import os
import logging
from discord.ext import tasks
from dotenv import load_dotenv
from discord_bot.llm import sql_search, extract_filters
from discord_bot.notifier import notify_subscribers
from db.base import ensure_tables
from db.io import (
    save_subscription, delete_subscription, delete_all_subscriptions,
    get_subscriptions, MAX_SUBSCRIPTIONS_PER_USER,
)
from db.JobPreprocessor import JobPreprocessor

load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

intents = discord.Intents.all()
client = discord.Client(intents=intents)


def _describe_subscription(sub) -> str:
    """구독 조건을 사람이 읽기 좋은 문자열로 변환."""
    parts = []
    if sub.keyword:
        parts.append(f"키워드: {sub.keyword}")
    if sub.region:
        parts.append(f"지역: {sub.region}")
    if sub.form is not None:
        parts.append(f"고용형태: {JobPreprocessor.stringify_form(sub.form)}")
    if sub.max_experience is not None:
        parts.append(f"최대경력: {JobPreprocessor.stringify_experience(sub.max_experience)}")
    if sub.min_annual_salary is not None:
        parts.append(f"최소연봉: {JobPreprocessor.stringify_salary(sub.min_annual_salary)}")
    return ", ".join(parts) if parts else "(조건 없음)"


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

    # ── !알림테스트 ────────────────────────────────────────
    if content.startswith("!알림테스트"):
        await message.channel.send("🔍 알림 조건을 확인 중입니다...")
        try:
            await notify_subscribers(client)
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
        subs = get_subscriptions(str(message.author.id))
        if not subs:
            await message.channel.send("구독 중인 조건이 없습니다. `!구독 <조건>`으로 등록하세요.")
        else:
            lines = [f"📋 내 구독 목록 ({len(subs)}/{MAX_SUBSCRIPTIONS_PER_USER}개)\n"]
            for i, sub in enumerate(subs, start=1):
                lines.append(f"[{i}] {_describe_subscription(sub)}")
            await message.channel.send("\n".join(lines))
        return

    # ── !구독 ──────────────────────────────────────────────
    if content.startswith("!구독"):
        condition = content[len("!구독"):].strip()
        if not condition:
            await message.channel.send(
                "구독 조건을 입력해 주세요.\n예) `!구독 백엔드 서울 정규직 신입`"
            )
            return

        filters = extract_filters(condition)
        form_code = JobPreprocessor.parse_form(filters.get('form') or '')

        ok, err = save_subscription(
            discord_user_id=str(message.author.id),
            keyword=filters.get('keyword'),
            region=filters.get('region'),
            form=form_code,
            max_experience=filters.get('max_experience'),
            min_annual_salary=filters.get('min_annual_salary'),
        )
        if not ok:
            await message.channel.send(f"❌ {err}")
            return

        subs = get_subscriptions(str(message.author.id))
        new_sub = subs[-1]
        await message.channel.send(
            f"✅ 구독이 등록되었습니다! ({len(subs)}/{MAX_SUBSCRIPTIONS_PER_USER}개)\n"
            f"{_describe_subscription(new_sub)}\n"
            f"조건에 맞는 신규 공고가 올라오면 DM으로 알려드립니다."
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
