import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
from datetime import datetime
# ----------------------------------------------------
def console_log(message):
    with open('console.txt', 'a', encoding='utf-8') as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {message}\n")

def log_error(error_message):
    with open('errors.txt', 'a', encoding='utf-8') as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {error_message}\n")

class ChangeChannelCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def is_admin(self, interaction: discord.Interaction) -> bool:
        return interaction.user.guild_permissions.administrator

    async def check_bot_permissions(self, channel: discord.TextChannel) -> bool:
        bot_member = channel.guild.get_member(self.bot.user.id)
        if not bot_member:
            return False
        return all([
            channel.permissions_for(bot_member).send_messages,
            channel.permissions_for(bot_member).embed_links,
            channel.permissions_for(bot_member).view_channel
        ])

    @app_commands.command(name="changechannel", description="Change the channel for Quran verses without resetting progress")
    @app_commands.describe(channel="Select new channel for Quran verses")
    async def changechannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Change the channel while keeping verse progress and settings"""
        
        if not await self.is_admin(interaction):
            try:
                await interaction.response.send_message(
                    "❌ You need **Administrator** permissions to use this command.",
                    ephemeral=True
                )
            except:
                pass
            return

        # Check if bot is already setup in this server
        try:
            conn = sqlite3.connect('quran_bot.db')
            c = conn.cursor()
            c.execute('SELECT channel_id, time_interval, current_verse FROM server_settings WHERE server_id = ?', (interaction.guild.id,))
            result = c.fetchone()
            
            if not result:
                await interaction.response.send_message(
                    "❌ Bot is not setup in this server. Use `/setup` first.",
                    ephemeral=True
                )
                conn.close()
                return
                
            old_channel_id, time_interval, current_verse = result
            conn.close()
            
        except Exception as e:
            error_msg = f"Changechannel database error: {str(e)}"
            log_error(error_msg)
            await interaction.response.send_message(
                "❌ Failed to check bot settings. Please try again.",
                ephemeral=True
            )
            return

        if not await self.check_bot_permissions(channel):
            try:
                await interaction.response.send_message(
                    f"❌ I don't have permission to send messages in {channel.mention}.\n\n"
                    "**Required permissions:** Send Messages, Embed Links, View Channel",
                    ephemeral=True
                )
            except:
                pass
            return

        try:
            conn = sqlite3.connect('quran_bot.db')
            c = conn.cursor()
            
            # Update only the channel ID, keep everything else
            c.execute('''UPDATE server_settings 
                        SET channel_id = ?
                        WHERE server_id = ?''',
                     (channel.id, interaction.guild.id))
            
            conn.commit()
            conn.close()
            
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
            log_error(error_msg)
            try:
                await interaction.response.send_message(
                    "❌ Failed to change channel. Please try again.",
                    ephemeral=True
                )
            except:
                pass

async def setup(bot):
    await bot.add_cog(ChangeChannelCog(bot))
# ----------------------------------------------------