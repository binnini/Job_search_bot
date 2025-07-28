import discord
import os
from dotenv import load_dotenv
from discord_bot.llm import recruit_filter, rag_search

load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

intents = discord.Intents.all()
client = discord.Client(command_prefix='!', intents=intents)

@client.event
async def on_ready():
  print(f'We have logged in as {client.user.name}')

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    query = message.content.strip()
    if not query:
        return

    await message.channel.send("잠시만 기다려 주세요...")

    try:
        response = rag_search(query,k=5)
        # 응답이 너무 길면 나눠서 전송
        if len(response) > 1900:
            chunks = [response[i:i+1900] for i in range(0, len(response), 1900)]
            for chunk in chunks:
                await message.channel.send(chunk)
        else:
            await message.channel.send(response)
    except Exception as e:
        await message.channel.send(f"오류 발생: {str(e)}")

# start the bot
client.run(TOKEN)