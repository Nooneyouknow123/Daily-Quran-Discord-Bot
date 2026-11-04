import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime

from utils import console_log, log_error, db_connect, utcnow, format_uptime

# ----------------------------------------------------

def guild_name(interaction: discord.Interaction) -> str:
    """Server name for logs ('DM' when the command is used outside a server)."""
    return interaction.guild.name if interaction.guild else "DM"


class GuideCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="guide", description="Learn how to set up and use the Daily Quran Bot")
    async def guide(self, interaction: discord.Interaction):
        """Sends a setup guide for the bot"""

        embed = discord.Embed(
            title="📖 Daily Quran Bot - Setup Guide",
            description="Welcome! Follow these steps to set up automated Quran verses in your server.",
            color=0x3498db
        )

        # Setup Steps
        embed.add_field(
            name="🛠️ **Step 1: Set Up Channel & Schedule**",
            value="Use `/setup` command to configure:\n"
                  "• **Channel**: Select where verses will be sent\n"
                  "• **Interval**: Choose how often (e.g., `30m`, `2h`, `24h`)\n"
                  "• **Role** *(optional)*: A role to ping with each verse\n\n"
                  "**Example:** `/setup channel:#quran-verses interval:24h`",
            inline=False
        )

        embed.add_field(
            name="⏰ **Step 2: How It Works**",
            value="• Bot sends Quran verses automatically at your chosen interval\n"
                  "• Progresses through the Quran sequentially\n"
                  "• Restarts from beginning after completion\n"
                  "• First verse is sent immediately after setup",
            inline=False
        )

        embed.add_field(
            name="⚙️ **Step 3: Permissions Required**",
            value="• `Administrator` permission to use `/setup`, `/changechannel` and `/reset`\n"
                  "• `View Channel` and `Send Messages` permission in target channel\n"
                  "• `Embed Links` permission for beautiful verse display",
            inline=False
        )

        embed.add_field(
            name="🧰 **Other Commands**",
            value="• `/changechannel` - Move verses to another channel, keeping your progress\n"
                  "• `/stats` - See your current settings and schedule\n"
                  "• `/random_verse` - Get a random verse (admins can post it for everyone)\n"
                  "• `/reset` - Clear all settings for this server and start over",
            inline=False
        )

        embed.add_field(
            name="🔧 **Step 4: Bot Recovery**",
            value="• If the bot goes offline, it sends the next verse when it is back online "
                  "(with a short note) and continues on your original schedule\n"
                  "• Verses missed while it was offline are skipped, not sent all at once\n",
            inline=False
        )


        embed.add_field(
            name="❓ **Need Help?**",
            value="• Check bot permissions in the channel\n"
                  "• Ensure you're using the correct command format\n"
                  "• Make sure the target channel is accessible\n"
                  "• /support to get the link of our support server",
            inline=False
        )

        embed.set_footer(text="Daily Quran Bot • May Allah bless your server with His remembrance")

        try:
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            error_msg = f"Guide command error: {str(e)}"
            log_error(error_msg, interaction=interaction)

            #  Only try to answer again if Discord has not already
            #  received a response for this interaction.
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ Failed to send guide. Please try again.", ephemeral=True)
            except Exception:
                pass
            return

        #  Logging happens after the guide was sent, and can never
        #  cause an error message to be sent on top of it.
        try:
            console_log(f"Guide command used by {interaction.user} in {guild_name(interaction)}")
        except Exception as e:
            log_error(f"Guide command logging error: {str(e)}", interaction=interaction)

    @app_commands.command(name="stats", description="Check bot statistics and server settings")
    @app_commands.guild_only()
    async def stats(self, interaction: discord.Interaction):
        """Check server settings and bot stats"""

        conn = None

        try:
            conn = db_connect()
            c = conn.cursor()

            # Get server settings with new UTC fields
            c.execute('SELECT channel_id, time_interval, current_verse, next_send_utc, last_sent_utc FROM server_settings WHERE server_id = ?', (interaction.guild.id,))
            result = c.fetchone()

            conn.close()
            conn = None

            embed = discord.Embed(title="📊 Bot Statistics", color=0x9b59b6)

            if result:
                channel_id, time_interval, current_verse, next_send_utc, last_sent_utc = result
                channel = self.bot.get_channel(channel_id)

                embed.add_field(name="🔄 Status", value="✅ Active", inline=True)
                embed.add_field(name="📁 Channel", value=channel.mention if channel else "Not Found", inline=True)

                # Format interval display
                if time_interval >= 1:
                    interval_display = f"{time_interval:.1f} hours"
                else:
                    minutes = time_interval * 60
                    interval_display = f"{minutes:.0f} minutes"

                embed.add_field(name="⏰ Interval", value=interval_display, inline=True)
                embed.add_field(name="📖 Current Verse", value=current_verse, inline=True)
                embed.add_field(name="🕒 Last Sent (UTC)", value=last_sent_utc or "Never", inline=True)

                if next_send_utc:
                    # Convert UTC to readable format
                    next_send_dt = datetime.strptime(next_send_utc, '%Y-%m-%d %H:%M:%S')
                    embed.add_field(name="⏱️ Next Send (UTC)", value=next_send_dt.strftime("%Y-%m-%d %H:%M"), inline=True)
            else:
                embed.add_field(name="🔄 Status", value="❌ Not Setup", inline=True)
                embed.description = "Use `/setup` to configure the bot for this server"

            # Bot stats
            started = getattr(self.bot, 'start_time', None)
            uptime = format_uptime(started) if started else "Unknown"

            embed.add_field(
                name="🤖 Bot Info",
                value=f"Servers: {len(self.bot.guilds)}\nUptime: {uptime}",
                inline=False
            )

            # Add UTC time for reference
            current_utc = utcnow().strftime("%Y-%m-%d %H:%M:%S")
            embed.add_field(
                name="🌐 Current UTC Time",
                value=current_utc,
                inline=False
            )

            await interaction.response.send_message(embed=embed, ephemeral=True)
            console_log(f"Stats command used by {interaction.user} in {guild_name(interaction)}")

        except Exception as e:
            error_msg = f"Stats command error: {str(e)}"
            log_error(error_msg, interaction=interaction)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ Failed to get statistics. Please try again.", ephemeral=True)
            except Exception:
                pass

        finally:
            if conn:
                conn.close()

async def setup(bot):
    await bot.add_cog(GuideCog(bot))
# ----------------------------------------------------
