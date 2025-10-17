import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
from datetime import datetime, timedelta
# ----------------------------------------------------
def console_log(message):
    with open('console.txt', 'a', encoding='utf-8') as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {message}\n")

def log_error(error_message):
    with open('errors.txt', 'a', encoding='utf-8') as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {error_message}\n")

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
                  "• **Interval**: Choose how often (e.g., `30m`, `2h`, `24h`)\n\n"
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
            value="• `Administrator` permission to use `/setup` command\n"
                  "• `Send Messages` permission in target channel\n"
                  "• `Embed Links` permission for beautiful verse display",
            inline=False
        )
        
        embed.add_field(
            name="🔧 **Step 4: Bot Recovery**",
            value="• If bot goes offline, it will send missed verses when back online\n"
                  "• Maintains your original schedule automatically\n",
            inline=False
        )
        
        
        embed.add_field(
            name="❓ **Need Help?**",
            value="• Check bot permissions in the channel\n"
                  "• Ensure you're using the correct command format\n"
                  "• Make sure the target channel is accessible\n"
                  "• Contact marty_fabio_ if issues persist",
            inline=False
        )
        
        embed.set_footer(text="Daily Quran Bot • May Allah bless your server with His remembrance")

        try:
            await interaction.response.send_message(embed=embed, ephemeral=True)
            console_log(f"Guide command used by {interaction.user} in {interaction.guild.name}")
        except Exception as e:
            error_msg = f"Guide command error: {str(e)}"
            log_error(error_msg)
            try:
                await interaction.response.send_message("❌ Failed to send guide. Please try again.", ephemeral=True)
            except:
                pass

    @app_commands.command(name="stats", description="Check bot statistics and server settings")
    async def stats(self, interaction: discord.Interaction):
        """Check server settings and bot stats"""
        
        try:
            conn = sqlite3.connect('quran_bot.db')
            c = conn.cursor()
            
            # Get server settings with new UTC fields
            c.execute('SELECT channel_id, time_interval, current_verse, next_send_utc, last_sent_utc FROM server_settings WHERE server_id = ?', (interaction.guild.id,))
            result = c.fetchone()
            
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
            embed.add_field(
                name="🤖 Bot Info", 
                value=f"Servers: {len(self.bot.guilds)}\nUptime: Online", 
                inline=False
            )
            
            # Add UTC time for reference
            current_utc = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            embed.add_field(
                name="🌐 Current UTC Time",
                value=current_utc,
                inline=False
            )
            
            conn.close()
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            console_log(f"Stats command used by {interaction.user} in {interaction.guild.name}")
            
        except Exception as e:
            error_msg = f"Stats command error: {str(e)}"
            log_error(error_msg)
            try:
                await interaction.response.send_message("❌ Failed to get statistics. Please try again.", ephemeral=True)
            except:
                pass

async def setup(bot):
    await bot.add_cog(GuideCog(bot))
# ----------------------------------------------------