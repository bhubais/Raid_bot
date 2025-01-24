import os
import time
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
import pandas as pd
from collections import defaultdict
from tabulate import tabulate  # For formatted table output
from flask import Flask
import threading
from waitress import serve  # Production server for Flask
import requests  # Required for Koyeb keep-alive

# Load Discord Token from Environment Variables
TOKEN = os.getenv("TOKEN")

if not TOKEN:
    raise ValueError("ERROR: TOKEN environment variable is missing. Please set it in Koyeb.")

# List of Allowed Users (Who Can Use /lock, /unlock, /showjobs, and /resetjobs)
ALLOWED_USERS = {
    248504544407846914,  # Watahero
    1098370060327862495,
    262282716731408385,
    256843911945781279
}

# Valid FFXI Jobs (up to Chains of Promathia)
VALID_JOBS = [
    "WAR", "MNK", "WHM", "BLM", "RDM", "THF", "PLD", "DRK",
    "BST", "BRD", "RNG", "SAM", "NIN", "DRG", "SMN"
]

# Job Selection Lock State (STARTS LOCKED)
job_selection_locked = True  

# Bot Setup
intents = discord.Intents.default()
intents.presences = True  # Required for keep-alive updates
intents.guilds = True
intents.messages = True
bot = commands.Bot(command_prefix="/", intents=intents)  # AutoShardedBot for better WebSocket handling
tree = bot.tree  # Use bot.tree instead of app_commands.CommandTree(bot)

# Dictionary to store job assignments
job_data = defaultdict(lambda: {"Main": [], "Sub": []})
player_jobs = {}

@bot.event
async def on_ready():
    await bot.tree.sync()  # 🔹 Ensures all slash commands are registered globally
    print(f'✅ Logged in as {bot.user}')
    print("Bot is now running in your Discord server!")

    # Start keep-alive background tasks
    bot.loop.create_task(keep_alive())
    bot.loop.create_task(keep_koyeb_alive())

    # Confirm successful command sync
    for guild in bot.guilds:
        print(f"🛠 Synced commands in {guild.name} (ID: {guild.id})")

# Function to check if a user is allowed to use admin commands
def is_allowed_user(interaction: discord.Interaction) -> bool:
    return interaction.user.id in ALLOWED_USERS

# Function to create job selection dropdown
class JobDropdown(discord.ui.Select):
    def __init__(self, placeholder, custom_id, parent_view):
        self.parent_view = parent_view  # Link parent view
        options = [discord.SelectOption(label=job, value=job) for job in VALID_JOBS]
        super().__init__(placeholder=placeholder, options=options, custom_id=custom_id)

    async def callback(self, interaction: discord.Interaction):
        if self.custom_id == "main_job":
            self.parent_view.main_job = self.values[0]
        elif self.custom_id == "sub_job":
            self.parent_view.sub_job = self.values[0]
        await interaction.response.defer()  # Prevents "Interaction Failed"

class JobSelectionView(discord.ui.View):
    def __init__(self, ctx):
        super().__init__(timeout=30)
        self.ctx = ctx
        self.main_job = None
        self.sub_job = None
        self.add_item(JobDropdown("Select Main Job", "main_job", self))  # Pass parent view
        self.add_item(JobDropdown("Select Sub Job", "sub_job", self))  # Pass parent view

    @discord.ui.button(label="Confirm Selection", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.main_job and self.sub_job:
            player = interaction.user.display_name  # Removes numbers from username

            # Remove previous job entries if updating
            if player in player_jobs:
                prev_main, prev_sub = player_jobs[player]
                job_data[prev_main]["Main"].remove(player)
                if prev_sub:
                    job_data[prev_sub]["Sub"].remove(player)

            # Add new jobs
            job_data[self.main_job]["Main"].append(player)
            job_data[self.sub_job]["Sub"].append(player)

            player_jobs[player] = (self.main_job, self.sub_job)

            await interaction.response.send_message(
                f"✅ {player}, your main job is **{self.main_job}** and sub job is **{self.sub_job}**.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message("❌ Please select both Main and Sub jobs.", ephemeral=True)

@tree.command(name="setjob", description="Select your Main and Sub job.")
async def setjob(interaction: discord.Interaction):
    global job_selection_locked

    if job_selection_locked:
        await interaction.response.send_message("🔒 **Job selection is currently locked. Please wait until it is unlocked.**", ephemeral=True)
        return

    view = JobSelectionView(interaction)
    player = interaction.user.display_name  # Removes numbers from username
    await interaction.response.send_message(f"🛠 **{player}, select your Main and Sub job:**", view=view, ephemeral=True)

@tree.command(name="lock", description="Locks job selection to prevent further submissions.")
async def lock(interaction: discord.Interaction):
    global job_selection_locked

    if not is_allowed_user(interaction):
        await interaction.response.send_message("❌ You don’t have permission to lock job selection.", ephemeral=True)
        return

    job_selection_locked = True
    await interaction.response.send_message("🔒 **Job selection has been locked! No further submissions are allowed.**")

@tree.command(name="unlock", description="Unlocks job selection to allow submissions again.")
async def unlock(interaction: discord.Interaction):
    global job_selection_locked

    if not is_allowed_user(interaction):
        await interaction.response.send_message("❌ You don’t have permission to unlock job selection.", ephemeral=True)
        return

    job_selection_locked = False

    # Immediate response to the user
    await interaction.response.send_message("🔓 **Job selection has been unlocked! Players can now submit jobs again.**", ephemeral=True)

    # Announcement for everyone
    await interaction.channel.send("@everyone 🔓 **Job selection is now open!** Use `/setjob` to submit your loot preferences for Main and Sub.")

@tree.command(name="showjobs", description="Shows all job selections.")
async def showjobs(interaction: discord.Interaction):
    if not is_allowed_user(interaction):
        await interaction.response.send_message("❌ You don’t have permission to use this command.", ephemeral=True)
        return

    table = []
    for job, data in job_data.items():
        table.append([job, ", ".join(data["Main"]) or "None", ", ".join(data["Sub"]) or "None"])

    job_table = tabulate(table, headers=["Job", "Main", "Sub"], tablefmt="grid") if table else "No job selections have been made yet."
    await interaction.response.send_message(f"```\n{job_table}\n```")

@tree.command(name="resetjobs", description="Resets all job selections.")
async def resetjobs(interaction: discord.Interaction):
    global job_data, player_jobs

    if not is_allowed_user(interaction):
        await interaction.response.send_message("❌ You don’t have permission to use this command.", ephemeral=True)
        return

    job_data = defaultdict(lambda: {"Main": [], "Sub": []})
    player_jobs = {}

    await interaction.response.send_message("🔄 **All job selections have been reset.**")

# Keep bot alive
bot.run(TOKEN, reconnect=True)
