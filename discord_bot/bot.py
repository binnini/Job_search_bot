import discord
import os
import logging
from discord.ext import tasks
from dotenv import load_dotenv
from discord_bot.llm import sql_search, extract_filters
from discord_bot.notifier import notify_subscribers
from db.base import ensure_tables
from db.io import save_subscription, delete_subscription, get_subscription
from db.JobPreprocessor import JobPreprocessor

load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

intents = discord.Intents.all()
client = discord.Client(command_prefix='!', intents=intents)


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

    # ── !구독 ──────────────────────────────────────────────
    if content.startswith("!구독해제"):
        deleted = delete_subscription(str(message.author.id))
        if deleted:
            await message.channel.send("✅ 구독이 해제되었습니다.")
        else:
            await message.channel.send("구독 중인 조건이 없습니다.")
        return

    if content.startswith("!내구독"):
        sub = get_subscription(str(message.author.id))
        if sub:
            await message.channel.send(f"📋 현재 구독 조건:\n{_describe_subscription(sub)}")
        else:
            await message.channel.send("구독 중인 조건이 없습니다. `!구독 <조건>`으로 등록하세요.")
        return

    if content.startswith("!구독"):
        condition = content[len("!구독"):].strip()
        if not condition:
            await message.channel.send(
                "구독 조건을 입력해 주세요.\n예) `!구독 백엔드 서울 정규직 신입`"
            )
            return

        filters = extract_filters(condition)
        form_code = JobPreprocessor.parse_form(filters.get('form') or '')

        save_subscription(
            discord_user_id=str(message.author.id),
            keyword=filters.get('keyword'),
            region=filters.get('region'),
            form=form_code,
            max_experience=filters.get('max_experience'),
            min_annual_salary=filters.get('min_annual_salary'),
        )

        sub = get_subscription(str(message.author.id))
        await message.channel.send(
            f"✅ 구독이 등록되었습니다!\n{_describe_subscription(sub)}\n"
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
