# ----------------------------------------------------
import discord
from discord.ext import commands
import os
import sys
from datetime import datetime
import asyncio
from log import log
# ----------------------------------------------------

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    log("python-dotenv not installed, using system environment variables")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)

# ----------------------------------------------------

# Run when bot login
@bot.event
async def on_ready():
    log(f'{bot.user} has logged in!')
    log(f'Bot ID: {bot.user.id}')
    log(f'Connected to {len(bot.guilds)} servers')

    # Load cogs first
    await load_cogs()
    
    # Wait a moment for commands to register
    await asyncio.sleep(1)
    
    # Set status
    activity = discord.Activity(
        type=discord.ActivityType.listening,
        name="/help to setup | 1 command setup"
    )
    await bot.change_presence(activity=activity)

    # Sync commands AFTER loading cogs and giving time for registration
    try:
        synced = await bot.tree.sync()
        log(f'Synced {len(synced)} slash command(s)')
        # Debug: List what commands were synced
        for cmd in synced:
            log(f" - {cmd.name}")
    except Exception as e:
        log(f"ERROR: Failed to sync commands: {e}")

# ----------------------------------------------------

# Log when joining or leaving a server -- All goes in file console.txt
@bot.event
async def on_guild_join(guild):
    log(f'Joined new server: {guild.name} (ID: {guild.id})')

@bot.event
async def on_guild_remove(guild):
    log(f'Left server: {guild.name} (ID: {guild.id})')

async def load_cogs():
    for filename in os.listdir("./cogs"):
        if filename.endswith(".py"):
            try:
                await bot.load_extension(f"commands.{filename[:-3]}")
                log(f"Loaded {filename[:-3]}")
            except Exception as e:
                log(f"ERROR: Failed to log cog {filename[:-3]}")

# ----------------------------------------------------

# Error handling
@bot.event
async def on_app_command_error(interaction, error):
    log(f"Slash command error in {interaction.command.name}: {str(error)}")
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "❌ An error occurred. Please try again.",
                ephemeral=True
            )
    except:
        pass

# ----------------------------------------------------

# Run the bot
if __name__ == "__main__":
    token = os.getenv('TOKEN')
    if not token:
        log("ERROR: TOKEN not found in environment variables")
        sys.exit(1)
    
    log("Starting Daily Quran Bot...")
    try:
        bot.run(token)
    except Exception as e:
        log(f"ERROR: Bot failed to start: {str(e)}")

# ----------------------------------------------------