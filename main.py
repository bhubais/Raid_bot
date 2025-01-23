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
from waitress import serve  # Replaces Flask's default server

# Load Discord Token from Environment Variables
TOKEN = os.getenv("TOKEN")

if not TOKEN:
    raise ValueError("ERROR: TOKEN environment variable is missing. Please set it in Koyeb.")

# List of Allowed Users (Who Can Use /showjobs and /resetjobs)
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

# Bot Setup
intents = discord.Intents.default()
intents.presences = True  # Required for keep-alive updates
bot = commands.AutoShardedBot(command_prefix="/", intents=intents)  # Use AutoShardedBot for better WebSocket handling
tree = bot.tree  # Use bot.tree instead of app_commands.CommandTree(bot)

# Dictionary to store job assignments
job_data = defaultdict(lambda: {"Main": [], "Sub": []})
player_jobs = {}

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f'✅ Logged in as {bot.user}')
    print("Bot is now running in your Discord server!")

    # Start keep-alive background task
    bot.loop.create_task(keep_alive())

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
    view = JobSelectionView(interaction)
    player = interaction.user.display_name  # Removes numbers from username
    await interaction.response.send_message(f"🛠 **{player}, select your Main and Sub job:**", view=view, ephemeral=True)

# Command: Show job summary with a formatted table (Restricted to Allowed Users)
@tree.command(name="showjobs", description="Show the job distribution table.")
async def showjobs(interaction: discord.Interaction):
    if not is_allowed_user(interaction):
        await interaction.response.send_message("❌ You don’t have permission to use this command.", ephemeral=True)
        return

    if not job_data:
        await interaction.response.send_message("❌ No jobs have been assigned yet.", ephemeral=True)
        return

    data = [(job, ", ".join([p.split("#")[0] for p in data["Main"]]), ", ".join([p.split("#")[0] for p in data["Sub"]])) for job, data in job_data.items()]
    
    df = pd.DataFrame(data, columns=["Job", "Main", "Sub"])
    table_str = tabulate(df, headers="keys", tablefmt="grid")

    await interaction.response.send_message(f"📊 **Job Distribution Table:**\n```{table_str}```")

# Command: Reset job data (Restricted to Allowed Users)
@tree.command(name="resetjobs", description="Reset all job assignments. (Allowed Users Only)")
async def resetjobs(interaction: discord.Interaction):
    if not is_allowed_user(interaction):
        await interaction.response.send_message("❌ You don’t have permission to reset the job list.", ephemeral=True)
        return

    job_data.clear()
    player_jobs.clear()
    await interaction.response.send_message("🔄 **Job list has been reset!** Players need to submit again.")

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

# ✅ Keep-Alive Task to Prevent WebSocket Disconnects (Reduced to 20 min)
async def keep_alive():
    """Sends periodic updates to Discord to prevent idle disconnections."""
    while True:
        await asyncio.sleep(1200)  # Reduced frequency to every 20 minutes
        print("🟢 Sending keep-alive message to Discord.")
        try:
            await bot.change_presence(activity=discord.Game(name="Managing Jobs"))
            print("✅ Keep-alive signal sent successfully.")
        except discord.HTTPException as e:
            print(f"⚠️ Keep-alive failed: {e}")
        except Exception as e:
            print(f"⚠️ Unexpected error in keep-alive: {e}")

# ✅ Improved Auto-Reconnect Handling
bot.run(TOKEN, reconnect=True)
