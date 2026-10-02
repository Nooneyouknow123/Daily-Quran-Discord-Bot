import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
from datetime import datetime

# ----------------------------------------------------

OWNER_ID = 1274667778300706866

# ----------------------------------------------------

def console_log(message):
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {message}")

def log_error(error_message):
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - ERROR: {error_message}")

# ----------------------------------------------------

class ShoutCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="shout",
        description="Developer only command."
    )
    @app_commands.describe(
        message="The message you want to send."
    )
    async def shout(self, interaction: discord.Interaction, message: str):

        # me: Only I can use this command
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message(
                "❌ Developer only. You cannot use this command.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            conn = sqlite3.connect('quran_bot.db')
            c = conn.cursor()

            c.execute(
                'SELECT server_id, channel_id FROM server_settings WHERE channel_id IS NOT NULL'
            )

            servers = c.fetchall()
            conn.close()

            if not servers:
                await interaction.followup.send(
                    "❌ No configured servers were found.",
                    ephemeral=True
                )
                return

            sent_count = 0
            failed_count = 0

            for server_id, channel_id in servers:
                channel = self.bot.get_channel(channel_id)

                if not channel:
                    failed_count += 1
                    log_error(
                        f"Shout failed: Channel {channel_id} not found "
                        f"for server {server_id}"
                    )
                    continue

                try:
                    await channel.send(message)
                    sent_count += 1

                except discord.Forbidden:
                    failed_count += 1
                    log_error(
                        f"Shout failed: Missing permissions in server "
                        f"{server_id}, channel {channel_id}"
                    )

                except Exception as e:
                    failed_count += 1
                    log_error(
                        f"Shout failed in server {server_id}: {str(e)}"
                    )

            console_log(
                f"Shout sent to {sent_count} servers. "
                f"Failed: {failed_count}"
            )

            result = f"✅ Shout sent to {sent_count} server(s)."

            if failed_count > 0:
                result += f"\n⚠️ Failed: {failed_count}"

            await interaction.followup.send(
                result,
                ephemeral=True
            )

        except Exception as e:
            log_error(f"Shout command error: {str(e)}")

            await interaction.followup.send(
                "❌ An error occurred while sending the shout.",
                ephemeral=True
            )

# ----------------------------------------------------

async def setup(bot):
    await bot.add_cog(ShoutCog(bot))

# ----------------------------------------------------