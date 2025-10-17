# ----------------------------------------------------

import discord
from discord.ext import commands
import os
import sys
from datetime import datetime
import asyncio
# ----------------------------------------------------

def console_log(message):
    with open('console.txt', 'a', encoding='utf-8') as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {message}\n")

def log_error(error_message):
    """Log errors to errors.txt"""
    with open('errors.txt', 'a', encoding='utf-8') as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {error_message}\n")

# ----------------------------------------------------

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    console_log("python-dotenv not installed, using system environment variables")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)

# ----------------------------------------------------

# Run when bot login
@bot.event
async def on_ready():
    console_log(f'{bot.user} has logged in!')
    console_log(f'Bot ID: {bot.user.id}')
    console_log(f'Connected to {len(bot.guilds)} servers')

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
        console_log(f'Synced {len(synced)} slash command(s)')
        # Debug: List what commands were synced
        for cmd in synced:
            console_log(f" - {cmd.name}")
    except Exception as e:
        error_msg = f"Failed to sync commands: {e}"
        console_log(error_msg)
        log_error(error_msg)

# ----------------------------------------------------

# Log when joining or leaving a server -- All goes in file console.txt
@bot.event
async def on_guild_join(guild):
    console_log(f'Joined new server: {guild.name} (ID: {guild.id})')

@bot.event
async def on_guild_remove(guild):
    console_log(f'Left server: {guild.name} (ID: {guild.id})')

async def load_cogs():
    cog_files = [f for f in os.listdir('.') if f.endswith('.py') and f.startswith('cog_')]
    console_log(f"Found {len(cog_files)} cog files: {cog_files}")
    
    for filename in cog_files:
        try:
            cog_name = filename[:-3]  # Remove .py extension
            await bot.load_extension(cog_name)
            console_log(f'✅ Loaded cog: {filename}')
        except Exception as e:
            error_msg = f"❌ Failed to load cog {filename}: {str(e)}"
            console_log(error_msg)
            log_error(error_msg)

# ----------------------------------------------------

# Error handling
@bot.event
async def on_app_command_error(interaction, error):
    error_msg = f"Slash command error in {interaction.command.name}: {str(error)}"
    log_error(error_msg)
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
        console_log("ERROR: TOKEN not found in environment variables")
        log_error("TOKEN not found in environment variables")
        sys.exit(1)
    
    console_log("Starting Daily Quran Bot...")
    try:
        bot.run(token)
    except Exception as e:
        error_msg = f"Bot failed to start: {str(e)}"
        console_log(error_msg)
        log_error(error_msg)

# ----------------------------------------------------