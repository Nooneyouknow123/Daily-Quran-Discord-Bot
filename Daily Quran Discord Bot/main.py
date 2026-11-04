# ----------------------------------------------------

import discord
from discord.ext import commands
import os
import sys

import tracker
from utils import console_log, log_error, init_db, utcnow

# ----------------------------------------------------

#  Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    console_log("python-dotenv not installed, using system environment variables")

intents = discord.Intents.default()
intents.message_content = False

activity = discord.Activity(
    type=discord.ActivityType.listening,
    name="/support for help! | Daily Quran Bot"
)

bot = commands.Bot(
    command_prefix='!',
    intents=intents,
    activity=activity
)

#  Used by /stats to show the real uptime
bot.start_time = utcnow()

# ----------------------------------------------------

async def load_cogs():
    cog_files = sorted(
        f for f in os.listdir('.')
        if f.endswith('.py') and f.startswith('cog_')
    )

    console_log(f"Found {len(cog_files)} cog files: {cog_files}")

    for filename in cog_files:
        try:
            cog_name = filename[:-3]
            await bot.load_extension(cog_name)
            console_log(f'Loaded cog: {filename}')

        except Exception as e:
            error_msg = f"Failed to load cog {filename}: {str(e)}"
            log_error(error_msg)


#  setup_hook runs exactly ONCE per start (on_ready can fire again after
#  every reconnect, which used to try to re-load all the cogs).
@bot.event
async def setup_hook():
    #  Make sure the database exists before any cog needs it
    init_db()
    tracker.ensure_tables()

    #  Load cogs first
    await load_cogs()

    #  Sync commands after loading cogs
    try:
        synced = await bot.tree.sync()
        console_log(f'Synced {len(synced)} slash command(s)')

        for cmd in synced:
            console_log(f" - {cmd.name}")

    except Exception as e:
        error_msg = f"Failed to sync commands: {e}"
        log_error(error_msg)

# ----------------------------------------------------

#  Run when bot login
@bot.event
async def on_ready():
    console_log(f'{bot.user} has logged in!')
    console_log(f'Bot ID: {bot.user.id}')
    console_log(f'Connected to {len(bot.guilds)} servers')

#  Log when joining or leaving a server
@bot.event
async def on_guild_join(guild):
    console_log(f'Joined new server: {guild.name} (ID: {guild.id})')

@bot.event
async def on_guild_remove(guild):
    console_log(f'Left server: {guild.name} (ID: {guild.id})')

# ----------------------------------------------------

#  Error handling
#  (discord.py routes slash command errors to the command tree, so the
#  handler has to be registered there to actually be called.)
@bot.tree.error
async def on_app_command_error(interaction, error):
    command_name = interaction.command.name if interaction.command else "unknown"
    original = getattr(error, 'original', error)
    error_msg = (
        f"Slash command error in {command_name}: "
        f"{type(original).__name__}: {str(original)}"
    )
    log_error(error_msg, interaction=interaction)

    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "❌ An error occurred. Please try again.",
                ephemeral=True
            )
    except Exception:
        pass

# ----------------------------------------------------

#  Run the bot
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
        log_error(error_msg)

# ----------------------------------------------------
