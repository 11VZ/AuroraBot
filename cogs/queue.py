import discord
from discord.ext import commands
from discord import app_commands, Interaction, ui
import os
from dotenv import load_dotenv
import asyncio
from . import db as queuedb
from .verify import TEST_INTERVAL_DAYS
import time

load_dotenv()
QUEUE_CHANNEL_ID = int(os.getenv('QUEUE_CHANNEL_ID', 0))
TIER_ANNOUNCE_CHANNEL_ID = int(os.getenv('TIER_ANNOUNCE_CHANNEL_ID', 0))
TESTER_ROLE_ID = int(os.getenv('TESTER_ROLE_ID', 0))
WAITLIST_ROLE_ID = int(os.getenv('WAITLIST_ROLE_ID', 0))
QUEUE_MAX = 20
TIERS = ['LT5', 'HT5', 'LT4', 'HT4', 'LT3', 'HT3', 'LT2', 'HT2', 'LT1', 'HT1']
TIER_ROLE_IDS = {
    'LT5': 0,  #Add role ids where 0 goes
    'HT5': 0,
    'LT4': 0,
    'HT4': 0,
    'LT3': 0,
    'HT3': 0,
    'LT2': 0,
    'HT2': 0,
    'LT1': 0,
    'HT1': 0
}

class QueueView(ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @ui.button(label='Join Queue', style=discord.ButtonStyle.green, custom_id='join_queue_btn')
    async def join_queue(self, interaction: Interaction, button: ui.Button):
        await self.cog.handle_join_queue(interaction)

class QueueCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queue_open = False
        self.queue = []
        self.active_testers = set()
        self.current_ticket = None
        self.current_testee = None
        self.previous_tier = None
        self.last_testee = None
        self.queue_message = None

    async def cog_load(self):
        await queuedb.init_db()
        state = await queuedb.load_queue_state()
        if state:
            self.queue_open = state['queue_open']
            self.current_testee = state['current_testee']
            self.previous_tier = state['previous_tier']
            self.queue_message = None
            self.queue = await queuedb.load_queue_members()
            self.active_testers = set(await queuedb.load_active_testers())
            if state['queue_message_id'] and state['queue_channel_id']:
                channel = self.bot.get_channel(state['queue_channel_id'])
                if channel:
                    try:
                        self.queue_message = await channel.fetch_message(state['queue_message_id'])
                    except Exception:
                        self.queue_message = None
            await self.update_queue_message()
        else:
            await queuedb.save_queue_state(self.queue_open, None, QUEUE_CHANNEL_ID, self.current_testee, self.previous_tier)
            await queuedb.save_queue_members(self.queue)
            await queuedb.save_active_testers(list(self.active_testers))

    async def update_queue_message(self):
        channel = self.bot.get_channel(QUEUE_CHANNEL_ID)
        if not channel:
            return
        embed = discord.Embed(
            title=f"Aurora Queue ({len(self.queue)}/{QUEUE_MAX})",
            color=discord.Color.blue()
        )
        if self.queue:
            embed.add_field(
                name="Queue",
                value="\n".join([f"{i+1}. <@{user_id}>" for i, user_id in enumerate(self.queue)]),
                inline=False
            )
        else:
            embed.add_field(name="Queue", value="No one in queue.", inline=False)
        if self.active_testers:
            tester_mentions = [f"<@{tid}>" for tid in self.active_testers]
            embed.add_field(name="Active Testers", value=", ".join(tester_mentions), inline=False)
        else:
            embed.add_field(name="Active Testers", value="None", inline=False)
        embed.set_footer(text="Use /leave to leave the queue.")
        if not self.queue_message:
            self.queue_message = await channel.send(embed=embed, view=QueueView(self))
        else:
            await self.queue_message.edit(embed=embed, view=QueueView(self))
        await queuedb.save_queue_state(
            self.queue_open,
            self.queue_message.id if self.queue_message else None,
            QUEUE_CHANNEL_ID,
            self.current_testee,
            self.previous_tier
        )
        await queuedb.save_queue_members(self.queue)
        await queuedb.save_active_testers(list(self.active_testers))

    @app_commands.command(name='start', description='Open the queue for people to join')
    @app_commands.checks.has_role(TESTER_ROLE_ID)
    async def start(self, interaction: Interaction):
        if self.queue_open:
            await interaction.response.send_message('Queue is already open.', ephemeral=True)
            return
        self.queue_open = True
        self.active_testers.add(interaction.user.id)
        await self.update_queue_message()
        await interaction.response.send_message('Queue opened!', ephemeral=True)

    @app_commands.command(name='leave', description='Leave the queue')
    async def leave(self, interaction: Interaction):
        user_id = interaction.user.id
        if user_id in self.queue:
            self.queue.remove(user_id)
            await self.update_queue_message()
            await interaction.response.send_message('You have left the queue.', ephemeral=True)
        else:
            await interaction.response.send_message('You are not in the queue.', ephemeral=True)

    @app_commands.command(name='stop', description='Close the queue (Tester only)')
    @app_commands.checks.has_role(TESTER_ROLE_ID)
    async def stop(self, interaction: Interaction):
        if not self.queue_open:
            await interaction.response.send_message('Queue is already closed.', ephemeral=True)
            return
        self.active_testers.discard(interaction.user.id)
        if not self.active_testers:
            self.queue_open = False
            self.queue.clear()
            await self.close_ticket()
            await self.update_queue_message()
            await interaction.response.send_message('Queue closed and cleared (no more active testers).', ephemeral=True)
        else:
            await self.update_queue_message()
            await interaction.response.send_message('You are no longer an active tester. Queue remains open for others.', ephemeral=True)

    @app_commands.command(name='next', description='Move to next in queue and open a ticket')
    @app_commands.describe(tier='Tier for the previous testee')
    @app_commands.checks.has_role(TESTER_ROLE_ID)
    async def next(self, interaction: Interaction, tier: str):
        await self.assign_tier_and_advance(interaction, tier, advance=True)

    @app_commands.command(name='skip', description='Skip current testee')
    @app_commands.checks.has_role(TESTER_ROLE_ID)
    async def skip(self, interaction: Interaction):
        await self.close_ticket()
        await self.advance_queue(interaction)
        await interaction.response.send_message('Skipped to next in queue.', ephemeral=True)

    @app_commands.command(name='close', description='Close ticket and assign tier')
    @app_commands.describe(tier='Tier for the testee')
    @app_commands.checks.has_role(TESTER_ROLE_ID)
    async def close(self, interaction: Interaction, tier: str):
        await self.assign_tier_and_advance(interaction, tier, advance=False)

    @app_commands.command(name='queue', description='Show the current queue')
    async def queue_cmd(self, interaction: Interaction):
        embed = discord.Embed(
            title=f"Aurora Queue ({len(self.queue)}/{QUEUE_MAX})",
            color=discord.Color.blue()
        )
        if self.queue:
            embed.add_field(
                name="Queue",
                value="\n".join([f"{i+1}. <@{user_id}>" for i, user_id in enumerate(self.queue)]),
                inline=False
            )
        else:
            embed.add_field(name="Queue", value="No one in queue.", inline=False)
        if self.active_testers:
            tester_mentions = [f"<@{tid}>" for tid in self.active_testers]
            embed.add_field(name="Active Testers", value=", ".join(tester_mentions), inline=False)
        else:
            embed.add_field(name="Active Testers", value="None", inline=False)
        embed.set_footer(text="Use /leave to leave the queue.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name='ticket', description='Show the current ticket channel (Tester only)')
    @app_commands.checks.has_role(TESTER_ROLE_ID)
    async def ticket(self, interaction: Interaction):
        if self.current_ticket:
            await interaction.response.send_message(f'Current ticket: {self.current_ticket.mention}', ephemeral=True)
        else:
            await interaction.response.send_message('No ticket is currently open.', ephemeral=True)

    async def handle_join_queue(self, interaction: Interaction):
        user_id = interaction.user.id
        user_info = await queuedb.get_user_info(user_id)
        now = int(time.time())
        if user_info and user_info.get('last_test_timestamp'):
            last = user_info['last_test_timestamp']
            if last and now - last < TEST_INTERVAL_DAYS * 86400:
                remaining = (last + TEST_INTERVAL_DAYS * 86400 - now) // 86400 + 1
                await interaction.response.send_message(f"You must wait {remaining} more day(s) before you can be tested again.", ephemeral=True)
                return
        if not self.queue_open:
            await interaction.response.send_message('Queue is not open.', ephemeral=True)
            return
        if user_id in self.queue:
            await interaction.response.send_message('You are already in the queue.', ephemeral=True)
            return
        if len(self.queue) >= QUEUE_MAX:
            await interaction.response.send_message('Queue is full.', ephemeral=True)
            return
        self.queue.append(user_id)
        await self.update_queue_message()
        await interaction.response.send_message('You have joined the queue.', ephemeral=True)

    async def assign_tier_and_advance(self, interaction, tier, advance=True):
        if tier not in TIERS:
            await interaction.response.send_message(f'Invalid tier. Valid tiers: {", ".join(TIERS)}', ephemeral=True)
            return
        previous_tier = self.previous_tier if self.current_testee == getattr(self, 'last_testee', None) else None
        tester = interaction.user
        testee_id = self.current_testee
        if testee_id:
            channel = self.bot.get_channel(TIER_ANNOUNCE_CHANNEL_ID)
            if channel:
                embed = discord.Embed(
                    title="Test Result",
                    color=discord.Color.green()
                )
                embed.add_field(name="Tester", value=tester.mention, inline=True)
                embed.add_field(name="Testee", value=f"<@{testee_id}>", inline=True)
                embed.add_field(name="Previous Tier", value=previous_tier if previous_tier else "N/A", inline=True)
                embed.add_field(name="Achieved Tier", value=tier, inline=True)
                await channel.send(content=f'<@{testee_id}>', embed=embed)
            member = interaction.guild.get_member(testee_id)
            if member:
                for t, rid in TIER_ROLE_IDS.items():
                    if rid and discord.utils.get(member.roles, id=rid):
                        await member.remove_roles(discord.Object(id=rid), reason="Tier updated")
                role_id = TIER_ROLE_IDS.get(tier)
                if role_id:
                    await member.add_roles(discord.Object(id=role_id), reason=f"Assigned tier {tier}")
                waitlist_role = interaction.guild.get_role(WAITLIST_ROLE_ID)
                if waitlist_role and waitlist_role in member.roles:
                    await member.remove_roles(waitlist_role, reason="Completed test")
            await queuedb.set_last_test_timestamp(testee_id, int(time.time()))
        self.previous_tier = tier
        self.last_testee = testee_id
        await self.update_queue_message()
        await self.close_ticket()
        if advance:
            await self.advance_queue(interaction)
            await interaction.response.send_message(f'Tier {tier} assigned. Advanced to next.', ephemeral=True)
        else:
            await interaction.response.send_message(f'Tier {tier} assigned. Ticket closed.', ephemeral=True)

    async def advance_queue(self, interaction):
        if self.queue:
            self.current_testee = self.queue.pop(0)
            await self.update_queue_message()
            await self.open_ticket(interaction.user, self.current_testee)
        else:
            self.current_testee = None
            await self.update_queue_message()

    async def open_ticket(self, tester, testee_id):
        guild = tester.guild
        user_info = await queuedb.get_user_info(testee_id)
        ign = user_info['ign'] if user_info and 'ign' in user_info else f"user{testee_id}"
        ticket_name = f"{ign.lower()}-{tester.name.lower()}"
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            tester: discord.PermissionOverwrite(view_channel=True),
            guild.get_member(testee_id): discord.PermissionOverwrite(view_channel=True)
        }
        ticket_channel = await guild.create_text_channel(ticket_name, overwrites=overwrites)
        self.current_ticket = ticket_channel
        previous_tier = self.previous_tier if testee_id == getattr(self, 'last_testee', None) else None
        embed = discord.Embed(
            title=f"Test Session for {ign}",
            color=discord.Color.purple()
        )
        embed.add_field(name="IGN", value=ign, inline=True)
        embed.add_field(name="Last Tier", value=previous_tier if previous_tier else "N/A", inline=True)
        await ticket_channel.send(embed=embed)
        await ticket_channel.send(f"Test session for <@{testee_id}> with {tester.mention}")

    async def close_ticket(self):
        if self.current_ticket:
            await self.current_ticket.delete()
            self.current_ticket = None

async def setup(bot):
    cog = QueueCog(bot)
    await bot.add_cog(cog)
    await cog.cog_load()
