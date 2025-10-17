import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import re
import os
from datetime import datetime, timedelta
# ----------------------------------------------------
def console_log(message):
    with open('console.txt', 'a', encoding='utf-8') as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {message}\n")

def log_error(error_message):
    with open('errors.txt', 'a', encoding='utf-8') as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {error_message}\n")

class ChannelCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.setup_db()

    def setup_db(self):
        try:
            conn = sqlite3.connect('quran_bot.db')
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS server_settings
                        (server_id INTEGER PRIMARY KEY,
                         channel_id INTEGER,
                         time_interval REAL,
                         current_verse TEXT,
                         next_send_utc TIMESTAMP,
                         last_sent_utc TIMESTAMP)''')
            conn.commit()
            conn.close()
            console_log("Database setup completed")
        except Exception as e:
            error_msg = f"Database setup error: {str(e)}"
            console_log(error_msg)
            log_error(error_msg)

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

    def parse_time_input(self, time_str: str) -> float:
        """Convert time string to hours"""
        if not time_str or not time_str.strip():
            raise ValueError("Please provide a time interval")
        
        time_str = time_str.lower().strip().replace(' ', '')
        
        match = re.match(r'^(\d+)([mh])$', time_str)
        if not match:
            raise ValueError("Invalid format. Use: 30m, 2h, 90m, etc.")
        
        number, unit = match.groups()
        number = int(number)
        
        if unit == 'h':
            hours = number
        else:  # unit == 'm'
            hours = number / 60.0
        
        if hours < (5/60):  # 5 minutes minimum
            raise ValueError("Time interval must be at least 5 minutes")
        if hours > 168:  # 1 week maximum
            raise ValueError("Time interval cannot be more than 1 week")
        
        return hours

    def calculate_next_send_utc(self, interval_hours):
        """Calculate next send time in UTC based on interval"""
        now_utc = datetime.utcnow()
        
        # If setting up for first time, send immediately
        # Then schedule next send based on interval
        next_send = now_utc + timedelta(hours=interval_hours)
        
        return next_send

    @app_commands.command(name="setup", description="Set up Quran verses channel and interval")
    @app_commands.describe(
        channel="Select channel for Quran verses", 
        interval="Time interval (e.g., 30m, 2h, 90m)"
    )
    async def setup(self, interaction: discord.Interaction, channel: discord.TextChannel, interval: str):
        if not await self.is_admin(interaction):
            try:
                await interaction.response.send_message(
                    "❌ You need **Administrator** permissions to use this command.",
                    ephemeral=True
                )
            except:
                pass
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
            hours = self.parse_time_input(interval)
            next_send_utc = self.calculate_next_send_utc(hours)
            
            conn = sqlite3.connect('quran_bot.db')
            c = conn.cursor()
            
            # Get or set current verse
            c.execute('SELECT current_verse FROM server_settings WHERE server_id = ?', (interaction.guild.id,))
            result = c.fetchone()
            current_verse = result[0] if result else "1|1"
            
            # Store settings with UTC times
            c.execute('''INSERT OR REPLACE INTO server_settings 
                        (server_id, channel_id, time_interval, current_verse, next_send_utc, last_sent_utc)
                        VALUES (?, ?, ?, ?, ?, datetime('now'))''',
                     (interaction.guild.id, channel.id, hours, current_verse, next_send_utc.strftime('%Y-%m-%d %H:%M:%S')))
            
            conn.commit()
            conn.close()
            
            # Format display
            if hours >= 1:
                time_display = f"{hours:.1f} hour{'s' if hours > 1 else ''}"
            else:
                minutes = hours * 60
                time_display = f"{minutes:.0f} minute{'s' if minutes > 1 else ''}"
            
            # Show next send time in user-friendly format
            next_send_local = next_send_utc.strftime('%Y-%m-%d %H:%M UTC')
            
            try:
                await interaction.response.send_message(
                    f"✅ Quran verses will be sent to {channel.mention} every {time_display}\n"
                    f"**Next verse:** {next_send_local}\n\n"
                    "**First verse sent!** 📖",
                    ephemeral=True
                )
            except discord.errors.NotFound:
                try:
                    await interaction.channel.send(
                        f"✅ {interaction.user.mention} Quran verses setup completed for {channel.mention}"
                    )
                except:
                    pass
            
            # Send first verse immediately
            verse_cog = self.bot.get_cog('VerseCog')
            if verse_cog:
                await verse_cog.send_verse_to_server(interaction.guild.id)
            else:
                log_error("VerseCog not found when trying to send first verse")
                    
        except ValueError as e:
            try:
                await interaction.response.send_message(
                    f"❌ {str(e)}\n\n**Examples:** 30m, 2h, 90m\n**Minimum:** 5 minutes",
                    ephemeral=True
                )
            except:
                pass
        except Exception as e:
            error_msg = f"Setup command error: {str(e)}"
            log_error(error_msg)
            try:
                await interaction.response.send_message(
                    "❌ An error occurred during setup. Please try again.",
                    ephemeral=True
                )
            except:
                pass

async def setup(bot):
    await bot.add_cog(ChannelCog(bot))

# ----------------------------------------------------