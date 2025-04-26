import discord
from discord.ext import commands
from discord import app_commands, Interaction, ui
import os
from dotenv import load_dotenv
from . import db as queuedb
import time

load_dotenv()
VERIFY_CHANNEL_ID = int(os.getenv('VERIFY_CHANNEL_ID', 0))
QUEUE_ACCESS_ROLE_ID = int(os.getenv('QUEUE_ACCESS_ROLE_ID', 0))
WAITLIST_ROLE_ID = int(os.getenv('WAITLIST_ROLE_ID', 0))
TEST_INTERVAL_DAYS = int(os.getenv('TEST_INTERVAL_DAYS', 3))

class VerifyModal(ui.Modal, title="Join Waitlist"):
    region = ui.TextInput(label="Region (NA/EU)", placeholder="NA or EU", required=True, max_length=4)
    ign = ui.TextInput(label="IGN (In-Game Name)", placeholder="Your Minecraft IGN", required=True, max_length=32)

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: Interaction):
        region = self.region.value.upper()
        ign = self.ign.value
        await self.cog.handle_verification(interaction, region, ign)

class VerifyView(ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @ui.button(label='Join Waitlist', style=discord.ButtonStyle.green, custom_id='join_waitlist_btn')
    async def join_waitlist(self, interaction: Interaction, button: ui.Button):
        await interaction.response.send_modal(VerifyModal(self.cog))

class VerifyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        channel = self.bot.get_channel(VERIFY_CHANNEL_ID)
        if channel:
            async for msg in channel.history(limit=10):
                if msg.author == self.bot.user:
                    return
            embed = discord.Embed(
                title="Welcome to the Aurora Waitlist!",
                description="Click the button below and fill out the form to access the queue.",
                color=discord.Color.gold()
            )
            await channel.send(embed=embed, view=VerifyView(self))

    async def handle_verification(self, interaction: Interaction, region, ign):
        user_info = await queuedb.get_user_info_by_ign(ign)
        now = int(time.time())
        if user_info and user_info.get('last_test_timestamp'):
            last = user_info['last_test_timestamp']
            if last and now - last < TEST_INTERVAL_DAYS * 86400:
                remaining = (last + TEST_INTERVAL_DAYS * 86400 - now) // 86400 + 1
                await interaction.response.send_message(f"You are on cooldown. You must wait {remaining} more day(s) before verifying again.", ephemeral=True)
                return
        queue_role = interaction.guild.get_role(QUEUE_ACCESS_ROLE_ID) if 'QUEUE_ACCESS_ROLE_ID' in globals() else None
        waitlist_role = interaction.guild.get_role(WAITLIST_ROLE_ID)
        if queue_role:
            await interaction.user.add_roles(queue_role, reason="Verified for queue access")
        if waitlist_role:
            await interaction.user.add_roles(waitlist_role, reason="Verified for waitlist")
        await queuedb.save_user_info(interaction.user.id, ign, region)
        await interaction.response.send_message(f"You have been verified and given access to the queue! Region: {region}, IGN: {ign}", ephemeral=True)

    @app_commands.command(name="verifyembed", description="(Admin) Post the verify embed in the verify channel.")
    @app_commands.checks.has_permissions(administrator=True)
    async def verifyembed(self, interaction: Interaction):
        channel = self.bot.get_channel(VERIFY_CHANNEL_ID)
        if not channel:
            await interaction.response.send_message("Verify channel not found.", ephemeral=True)
            return
        embed = discord.Embed(
            title="Welcome to the Aurora Waitlist!",
            description="Click the button below and fill out the form to access the queue.",
            color=discord.Color.gold()
        )
        await channel.send(embed=embed, view=VerifyView(self))
        await interaction.response.send_message("Verify embed posted!", ephemeral=True)

async def setup(bot):
    await bot.add_cog(VerifyCog(bot))