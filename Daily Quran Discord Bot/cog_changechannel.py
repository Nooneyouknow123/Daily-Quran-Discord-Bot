import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime

from utils import console_log, log_error, db_connect, is_admin, bot_can_post

# ----------------------------------------------------

class ChangeChannelCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def is_admin(self, interaction: discord.Interaction) -> bool:
        return is_admin(interaction)

    async def check_bot_permissions(self, channel: discord.TextChannel) -> bool:
        return bot_can_post(self.bot, channel)

    @app_commands.command(name="changechannel", description="Change the channel for Quran verses without resetting progress")
    @app_commands.guild_only()
    @app_commands.describe(channel="Select new channel for Quran verses")
    async def changechannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Change the channel while keeping verse progress and settings"""

        if not await self.is_admin(interaction):
            try:
                await interaction.response.send_message(
                    "❌ You need **Administrator** permissions to use this command.",
                    ephemeral=True
                )
            except Exception:
                pass
            return

        # Check if bot is already setup in this server
        conn = None

        try:
            conn = db_connect()
            c = conn.cursor()
            c.execute('SELECT channel_id, time_interval, current_verse FROM server_settings WHERE server_id = ?', (interaction.guild.id,))
            result = c.fetchone()

            if not result:
                await interaction.response.send_message(
                    "❌ Bot is not setup in this server. Use `/setup` first.",
                    ephemeral=True
                )
                return

            old_channel_id, time_interval, current_verse = result

        except Exception as e:
            error_msg = f"Changechannel database error: {str(e)}"
            log_error(error_msg, interaction=interaction)
            try:
                await interaction.response.send_message(
                    "❌ Failed to check bot settings. Please try again.",
                    ephemeral=True
                )
            except Exception:
                pass
            return

        finally:
            if conn:
                conn.close()

        if not await self.check_bot_permissions(channel):
            try:
                await interaction.response.send_message(
                    f"❌ I don't have permission to send messages in {channel.mention}.\n\n"
                    "**Required permissions:** Send Messages, Embed Links, View Channel",
                    ephemeral=True
                )
            except Exception:
                pass
            return

        conn = None

        try:
            conn = db_connect()
            c = conn.cursor()

            # Update only the channel ID, keep everything else
            c.execute('''UPDATE server_settings
                        SET channel_id = ?
                        WHERE server_id = ?''',
                     (channel.id, interaction.guild.id))

            conn.commit()
            conn.close()
            conn = None

            # Get old channel name for message
            old_channel = self.bot.get_channel(old_channel_id)
            old_channel_name = old_channel.mention if old_channel else f"Channel #{old_channel_id}"

            # Format time interval for display
            if time_interval >= 1:
                interval_display = f"{time_interval:.1f} hours"
            else:
                minutes = time_interval * 60
                interval_display = f"{minutes:.0f} minutes"

            embed = discord.Embed(
                title="✅ Channel Changed Successfully",
                color=0x00ff00,
                timestamp=datetime.now()
            )

            embed.add_field(
                name="📁 Channel Updated",
                value=f"**From:** {old_channel_name}\n**To:** {channel.mention}",
                inline=False
            )

            embed.add_field(
                name="📊 Settings Preserved",
                value=f"• **Interval:** {interval_display}\n• **Current Verse:** {current_verse}\n• **Progress:** Unchanged",
                inline=False
            )

            embed.add_field(
                name="⏰ Next Verse",
                value=f"Next Quran verse will be sent to {channel.mention} according to your schedule.",
                inline=False
            )

            embed.set_footer(text="Channel changed • Progress preserved")

            await interaction.response.send_message(embed=embed, ephemeral=True)
            console_log(f"Channel changed by {interaction.user} in {interaction.guild.name}: {old_channel_id} → {channel.id}")

        except Exception as e:
            error_msg = f"Changechannel command error: {str(e)}"
            log_error(error_msg, interaction=interaction)
            try:
                await interaction.response.send_message(
                    "❌ Failed to change channel. Please try again.",
                    ephemeral=True
                )
            except Exception:
                pass

        finally:
            if conn:
                conn.close()

async def setup(bot):
    await bot.add_cog(ChangeChannelCog(bot))
# ----------------------------------------------------
