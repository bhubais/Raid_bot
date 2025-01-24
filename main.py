import os
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from collections import defaultdict
from tabulate import tabulate
from flask import Flask
import threading
from waitress import serve
import requests

TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise ValueError("ERROR: TOKEN environment variable is missing. Please set it in Koyeb.")

ALLOWED_USERS = {
    248504544407846914,  # Watahero
    546328217217400842,
    1098370060327862495,
    262282716731408385,
    256843911945781279
}

VALID_JOBS = [
    "WAR", "MNK", "WHM", "BLM", "RDM", "THF", "PLD", "DRK",
    "BST", "BRD", "RNG", "SAM", "NIN", "DRG", "SMN"
]

job_selection_locked = True  
intents = discord.Intents.default()
intents.presences = True
intents.guilds = True
intents.messages = True
bot = commands.Bot(command_prefix="/", intents=intents)
tree = bot.tree
job_data = defaultdict(lambda: {"Main": [], "Sub": []})
player_jobs = {}

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

@tree.command(name="setjob", description="Select your Main and Sub job.")
async def setjob(interaction: discord.Interaction):
    global job_selection_locked

    if job_selection_locked:
        await interaction.response.send_message("🔒 **Job selection is currently locked. Please wait until it is unlocked.**", ephemeral=True)
        return

    class JobDropdown(discord.ui.Select):
        def __init__(self, placeholder, custom_id, parent_view):
            self.parent_view = parent_view
            options = [discord.SelectOption(label=job, value=job) for job in VALID_JOBS]
            super().__init__(placeholder=placeholder, options=options, custom_id=custom_id)

        async def callback(self, interaction: discord.Interaction):
            if self.custom_id == "main_job":
                self.parent_view.main_job = self.values[0]
            elif self.custom_id == "sub_job":
                self.parent_view.sub_job = self.values[0]
            await interaction.response.defer()

    class JobSelectionView(discord.ui.View):
        def __init__(self, ctx):
            super().__init__(timeout=30)
            self.ctx = ctx
            self.main_job = None
            self.sub_job = None
            self.add_item(JobDropdown("Select Main Job", "main_job", self))
            self.add_item(JobDropdown("Select Sub Job", "sub_job", self))

        @discord.ui.button(label="Confirm Selection", style=discord.ButtonStyle.green)
        async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
            if self.main_job and self.sub_job:
                player = interaction.user.display_name  

                if player in player_jobs:
                    prev_main, prev_sub = player_jobs[player]
                    job_data[prev_main]["Main"].remove(player)
                    if prev_sub:
                        job_data[prev_sub]["Sub"].remove(player)

                job_data[self.main_job]["Main"].append(player)
                job_data[self.sub_job]["Sub"].append(player)

                player_jobs[player] = (self.main_job, self.sub_job)

                await interaction.response.send_message(
                    f"✅ {player}, your main job is **{self.main_job}** and sub job is **{self.sub_job}**.",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message("❌ Please select both Main and Sub jobs.", ephemeral=True)

    view = JobSelectionView(interaction)
    player = interaction.user.display_name  
    await interaction.response.send_message(f"🛠 **{player}, select your Main and Sub job:**", view=view, ephemeral=True)

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

@bot.event
async def on_ready():
    try:
        await bot.tree.sync()  
        print(f'✅ Logged in as {bot.user}')
        print("✅ All slash commands have been registered globally.")

        registered_commands = {cmd.name for cmd in bot.tree.get_commands()}
        print(f"🛠 Available Commands: {registered_commands}")

        missing_commands = {"setjob", "lock", "unlock", "showjobs", "resetjobs"} - registered_commands
        if missing_commands:
            print(f"⚠️ Missing commands: {missing_commands}. Registering them now...")
            if "setjob" in missing_commands:
                bot.tree.add_command(setjob)
            if "lock" in missing_commands:
                bot.tree.add_command(lock)
            if "unlock" in missing_commands:
                bot.tree.add_command(unlock)
            if "showjobs" in missing_commands:
                bot.tree.add_command(showjobs)
            if "resetjobs" in missing_commands:
                bot.tree.add_command(resetjobs)

            await bot.tree.sync()  

        for guild in bot.guilds:
            print(f"🔄 Synced commands in {guild.name} (ID: {guild.id})")

    except Exception as e:
        print(f"❌ Command sync failed: {e}")

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running!"

def run_web_server():
    serve(app, host="0.0.0.0", port=8000)

web_thread = threading.Thread(target=run_web_server, daemon=True)
web_thread.start()

bot.run(TOKEN, reconnect=True)
