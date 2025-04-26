import os
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
GUILD_ID = os.getenv('GUILD_ID')

intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    try:
        synced = await bot.tree.sync()
        print(f'Synced {len(synced)} commands')
    except Exception as e:
        print(e)

async def load_cogs():
    for cog in ['cogs.queue', 'cogs.verify']:
        try:
            await bot.load_extension(cog)
        except Exception as e:
            print(f'Failed to load {cog}: {e}')

if __name__ == '__main__':
    import asyncio
    async def main():
        await load_cogs()
        await bot.start(TOKEN)
    asyncio.run(main())
