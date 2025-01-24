import os
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
bot = commands.Bot(command_prefix="/", intents=intents)
tree = bot.tree

# Dictionary to store job assignments
job_data = defaultdict(lambda: {"Main": [], "Sub": []})
player_jobs = {}

@bot.event
async def on_ready():
    try:
        await bot.tree.sync()  # 🔹 Forces global sync of all commands
        print(f'✅ Logged in as {bot.user}')
        print("✅ All slash commands have been registered globally.")
        print(f"Available commands: {[cmd.name for cmd in bot.tree.get_commands()]}")

        for guild in bot.guilds:
            print(f"🛠 Synced commands in {guild.name} (ID: {guild.id})")

        bot.loop.create_task(keep_alive())  # 🔹 Prevents bot from going idle
        bot.loop.create_task(keep_koyeb_alive())  # 🔹 Keeps the bot alive on Koyeb

    except Exception as e:
        print(f"❌ Command sync failed: {e}")

# ✅ Keep-Alive Function (Prevents Idle Disconnections)
async def keep_alive():
    """Sends periodic updates to Discord to prevent idle disconnections."""
    while True:
        await asyncio.sleep(1800)  # Every 30 minutes
        try:
            await bot.change_presence(activity=discord.Game(name="Managing Jobs"))
            print("🟢 Keep-alive message sent to Discord.")
        except Exception as e:
            print(f"⚠️ Keep-alive failed: {e}")

# ✅ Prevent Koyeb from Stopping Instance
async def keep_koyeb_alive():
    """Periodically pings the bot's own web server to prevent Koyeb from stopping the instance."""
    while True:
        await asyncio.sleep(600)  # Every 10 minutes
        try:
            requests.get("http://127.0.0.1:8000")
            print("🔄 Koyeb keep-alive ping sent.")
        except requests.exceptions.RequestException as e:
            print(f"⚠️ Failed to ping Koyeb server: {e}")

@tree.command(name="lock", description="Locks job selection to prevent further submissions.")
async def lock(interaction: discord.Interaction):
    global job_selection_locked

    if interaction.user.id not in ALLOWED_USERS:
        await interaction.response.send_message("❌ You don’t have permission to lock job selection.", ephemeral=True)
        return

    job_selection_locked = True
    await interaction.response.send_message("🔒 **Job selection has been locked! No further submissions are allowed.**")

@tree.command(name="unlock", description="Unlocks job selection to allow submissions again.")
async def unlock(interaction: discord.Interaction):
    global job_selection_locked

    if interaction.user.id not in ALLOWED_USERS:
        await interaction.response.send_message("❌ You don’t have permission to unlock job selection.", ephemeral=True)
        return

    job_selection_locked = False
    await interaction.response.send_message("🔓 **Job selection has been unlocked! Players can now submit jobs again.**", ephemeral=True)
    await interaction.channel.send("@everyone 🔓 **Job selection is now open!** Use `/setjob` to submit your loot preferences for Main and Sub.")

@tree.command(name="showjobs", description="Shows all job selections.")
async def showjobs(interaction: discord.Interaction):
    if interaction.user.id not in ALLOWED_USERS:
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

    if interaction.user.id not in ALLOWED_USERS:
        await interaction.response.send_message("❌ You don’t have permission to use this command.", ephemeral=True)
        return

    job_data = defaultdict(lambda: {"Main": [], "Sub": []})
    player_jobs = {}

    await interaction.response.send_message("🔄 **All job selections have been reset.**")

# ✅ Flask Web Server for Koyeb Health Check
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running!"

def run_web_server():
    serve(app, host="0.0.0.0", port=8000)

# Run the Flask web server in a separate thread
web_thread = threading.Thread(target=run_web_server, daemon=True)
web_thread.start()

# ✅ Start the bot
bot.run(TOKEN, reconnect=True)
