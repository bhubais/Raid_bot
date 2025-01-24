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
bot = commands.AutoShardedBot(command_prefix="/", intents=intents)  # AutoShardedBot for better WebSocket handling
tree = bot.tree  # Use bot.tree instead of app_commands.CommandTree(bot)

# Dictionary to store job assignments
job_data = defaultdict(lambda: {"Main": [], "Sub": []})
player_jobs = {}

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f'✅ Logged in as {bot.user}')
    print("Bot is now running in your Discord server!")

    # Start keep-alive background tasks
    bot.loop.create_task(keep_alive())
    bot.loop.create_task(keep_koyeb_alive())

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

    # Send the announcement mentioning everyone
    await interaction.channel.send("@everyone 🔓 **Job selection is now open!** Use `/setjob` to submit your loot preferences for Main and Sub.")

    # Respond only to the user who executed the command
    await interaction.response.send_message("🔓 **Job selection has been unlocked! Players can now submit jobs again.**", ephemeral=True)

# ✅ Flask Web Server Using Waitress to Satisfy Koyeb Health Checks
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running!"

def run_web_server():
    serve(app, host="0.0.0.0", port=8000)  # Use waitress instead of Flask's dev server

# Run the Flask web server in a separate thread
web_thread = threading.Thread(target=run_web_server, daemon=True)
web_thread.start()

# ✅ Keep-Alive Task to Prevent WebSocket Disconnects
async def keep_alive():
    """Sends periodic updates to Discord to prevent idle disconnections."""
    while True:
        await asyncio.sleep(1800)  # Every 30 minutes
        try:
            await bot.change_presence(activity=discord.Game(name="Managing Jobs"))
        except Exception as e:
            print(f"⚠️ Keep-alive failed: {e}")

# ✅ Prevent Koyeb from Stopping Instance
async def keep_koyeb_alive():
    """Periodically pings the bot's own web server to prevent Koyeb from stopping the instance."""
    while True:
        await asyncio.sleep(600)  # Every 10 minutes
        try:
            requests.get("http://127.0.0.1:8000")
        except requests.exceptions.RequestException as e:
            print(f"⚠️ Failed to ping Koyeb server: {e}")

# ✅ Improved Auto-Reconnect Handling
bot.run(TOKEN, reconnect=True)
