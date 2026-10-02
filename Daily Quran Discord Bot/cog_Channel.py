import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import re
from datetime import datetime, timedelta

# ----------------------------------------------------

def console_log(message):
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {message}")

def log_error(error_message):
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - ERROR: {error_message}")

# ----------------------------------------------------

class ChannelCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.setup_db()

    def setup_db(self):
        conn = None

        try:
            conn = sqlite3.connect('quran_bot.db')
            c = conn.cursor()

            c.execute('''
                CREATE TABLE IF NOT EXISTS server_settings (
                    server_id INTEGER PRIMARY KEY,
                    channel_id INTEGER,
                    time_interval REAL,
                    current_verse TEXT,
                    next_send_utc TIMESTAMP,
                    last_sent_utc TIMESTAMP,
                    role_id INTEGER
                )
            ''')

            #  Add role_id to old databases
            c.execute("PRAGMA table_info(server_settings)")
            columns = [row[1] for row in c.fetchall()]

            if "role_id" not in columns:
                c.execute(
                    "ALTER TABLE server_settings ADD COLUMN role_id INTEGER"
                )
                console_log("Added role_id column to server_settings")

            conn.commit()
            console_log("Database setup completed")

        except Exception as e:
            log_error(f"Database setup error: {e}")

        finally:
            if conn:
                conn.close()

    async def is_admin(self, interaction):
        return interaction.user.guild_permissions.administrator

    async def check_bot_permissions(self, channel):
        bot_member = channel.guild.get_member(self.bot.user.id)

        if not bot_member:
            return False

        permissions = channel.permissions_for(bot_member)

        return (
            permissions.view_channel
            and permissions.send_messages
            and permissions.embed_links
        )

    def parse_time_input(self, time_str):
        if not time_str or not time_str.strip():
            raise ValueError("Please provide a time interval.")

        time_str = time_str.lower().strip().replace(' ', '')

        match = re.match(r'^(\d+)([mh])$', time_str)

        if not match:
            raise ValueError(
                "Invalid format. Use something like: 30m, 2h, 90m."
            )

        number, unit = match.groups()
        number = int(number)

        if unit == 'h':
            hours = number
        else:
            hours = number / 60.0

        if hours < (5 / 60):
            raise ValueError("Time interval must be at least 5 minutes.")

        if hours > 168:
            raise ValueError("Time interval cannot be more than 1 week.")

        return hours

    def calculate_next_send_utc(self, interval_hours):
        return datetime.utcnow() + timedelta(hours=interval_hours)

    def format_interval(self, hours):
        if hours >= 1:
            return f"{hours:.1f} hour{'s' if hours != 1 else ''}"

        minutes = hours * 60
        return f"{minutes:.0f} minute{'s' if minutes != 1 else ''}"

    @app_commands.command(
        name="setup",
        description="Set up Quran verses channel and interval"
    )
    @app_commands.describe(
        channel="Select channel for Quran verses",
        interval="Time interval (e.g. 30m, 2h, 90m)",
        role="Role to ping with each Quran verse"
    )
    async def setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        interval: str,
        role: discord.Role = None
    ):
        if not await self.is_admin(interaction):
            await interaction.response.send_message(
                "❌ You need **Administrator** permissions to use this command.",
                ephemeral=True
            )
            return

        if not await self.check_bot_permissions(channel):
            await interaction.response.send_message(
                f"❌ I don't have the required permissions in {channel.mention}.\n\n"
                "**Required:** View Channel, Send Messages, Embed Links",
                ephemeral=True
            )
            return

        #  Validate the selected role
        if role:
            if role.is_default():
                await interaction.response.send_message(
                    "❌ You cannot select the @everyone role.",
                    ephemeral=True
                )
                return

            if role.managed:
                await interaction.response.send_message(
                    "❌ You cannot use a managed/integration role.",
                    ephemeral=True
                )
                return

        try:
            hours = self.parse_time_input(interval)

            conn = sqlite3.connect('quran_bot.db')
            c = conn.cursor()

            #  Check if this server already has a setup
            c.execute(
                '''
                SELECT current_verse, next_send_utc, last_sent_utc
                FROM server_settings
                WHERE server_id = ?
                ''',
                (interaction.guild.id,)
            )

            existing = c.fetchone()

            if existing:
                #  Update settings without resetting progress or schedule
                c.execute(
                    '''
                    UPDATE server_settings
                    SET channel_id = ?,
                        time_interval = ?,
                        role_id = ?
                    WHERE server_id = ?
                    ''',
                    (
                        channel.id,
                        hours,
                        role.id if role else None,
                        interaction.guild.id
                    )
                )

                conn.commit()
                conn.close()

                role_display = role.mention if role else "No role ping"
                time_display = self.format_interval(hours)

                await interaction.response.send_message(
                    f"✅ Quran settings updated.\n"
                    f"**Channel:** {channel.mention}\n"
                    f"**Interval:** {time_display}\n"
                    f"**Ping role:** {role_display}\n\n"
                    f"Your verse progress and existing schedule were preserved.",
                    ephemeral=True
                )

                return

            #  Create the first setup
            next_send_utc = self.calculate_next_send_utc(hours)

            c.execute(
                '''
                INSERT INTO server_settings (
                    server_id,
                    channel_id,
                    time_interval,
                    current_verse,
                    next_send_utc,
                    last_sent_utc,
                    role_id
                )
                VALUES (?, ?, ?, ?, ?, NULL, ?)
                ''',
                (
                    interaction.guild.id,
                    channel.id,
                    hours,
                    "1|1",
                    next_send_utc.strftime('%Y-%m-%d %H:%M:%S'),
                    role.id if role else None
                )
            )

            conn.commit()
            conn.close()

            role_display = role.mention if role else "No role ping"
            time_display = self.format_interval(hours)

            await interaction.response.send_message(
                f"✅ Quran verses will be sent to {channel.mention} "
                f"every {time_display}.\n"
                f"**Ping role:** {role_display}\n\n"
                f"**First verse sent!** 📖",
                ephemeral=True
            )

            #  Send the first verse immediately
            verse_cog = self.bot.get_cog('VerseCog')

            if verse_cog:
                success = await verse_cog.send_verse_to_server(
                    interaction.guild.id,
                    scheduled_time=datetime.utcnow()
                )

                #  Remove the setup if the first send completely failed
                if not success:
                    conn = sqlite3.connect('quran_bot.db')
                    c = conn.cursor()

                    c.execute(
                        '''
                        DELETE FROM server_settings
                        WHERE server_id = ?
                        ''',
                        (interaction.guild.id,)
                    )

                    conn.commit()
                    conn.close()

                    log_error(
                        f"Initial verse failed for server "
                        f"{interaction.guild.id}; setup rolled back"
                    )

            else:
                log_error(
                    "VerseCog not found when trying to send first verse"
                )

        except ValueError as e:
            await interaction.response.send_message(
                f"❌ {str(e)}\n\n"
                "**Examples:** 30m, 2h, 90m\n"
                "**Minimum:** 5 minutes",
                ephemeral=True
            )

        except Exception as e:
            log_error(f"Setup command error: {e}")

            try:
                await interaction.response.send_message(
                    "❌ An error occurred during setup. Please try again.",
                    ephemeral=True
                )
            except discord.InteractionResponded:
                pass

# ----------------------------------------------------

async def setup(bot):
    await bot.add_cog(ChannelCog(bot))

# ----------------------------------------------------