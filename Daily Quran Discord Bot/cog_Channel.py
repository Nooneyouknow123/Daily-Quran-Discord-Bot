import discord
from discord.ext import commands
from discord import app_commands
from datetime import timedelta

from utils import (
    console_log,
    log_error,
    db_connect,
    init_db,
    utcnow,
    is_admin,
    bot_can_post,
    parse_interval
)

from languages import LANGUAGES, get_language_name

# ----------------------------------------------------

async def language_autocomplete(interaction, current: str):
    current = current.lower()

    choices = []

    for code, details in LANGUAGES.items():
        name = details["name"]

        if current in code.lower() or current in name.lower():
            choices.append(
                app_commands.Choice(
                    name=f"{name} ({code})",
                    value=code
                )
            )

    return choices[:25]


class ChannelCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        init_db()

    async def is_admin(self, interaction):
        return is_admin(interaction)

    async def check_bot_permissions(self, channel):
        return bot_can_post(self.bot, channel)

    def parse_time_input(self, time_str):
        return parse_interval(time_str)

    def calculate_next_send_utc(self, interval_hours):
        return utcnow() + timedelta(hours=interval_hours)

    def format_interval(self, hours):
        if hours >= 1:
            return f"{hours:.1f} hour{'s' if hours != 1 else ''}"

        minutes = hours * 60
        return f"{minutes:.0f} minute{'s' if minutes != 1 else ''}"

    @app_commands.command(
        name="setup",
        description="Set up Quran verses channel and interval"
    )
    @app_commands.guild_only()
    @app_commands.describe(
        channel="Select channel for Quran verses",
        interval="Time interval (e.g. 30m, 2h, 90m)",
        role="Role to ping with each Quran verse",
        language="Translation language for this server"
    )
    @app_commands.autocomplete(language=language_autocomplete)
    async def setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        interval: str,
        role: discord.Role = None,
        language: str = None
    ):
        if not await self.is_admin(interaction):
            await interaction.response.send_message(
                "❌ You need **Administrator** permissions to use this command.",
                ephemeral=True
            )
            return

        if language is not None and language not in LANGUAGES:
            await interaction.response.send_message(
                "❌ Invalid language. Please select a language from the list.",
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

        # Validate the selected role
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

        # Validate the interval
        try:
            hours = self.parse_time_input(interval)

        except ValueError as e:
            await interaction.response.send_message(
                f"❌ {str(e)}\n\n"
                "**Examples:** 30m, 2h, 90m\n"
                "**Minimum:** 5 minutes",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        conn = None

        try:
            conn = db_connect()
            c = conn.cursor()

            # Check if this server already has a setup
            c.execute(
                '''
                SELECT
                    current_verse,
                    next_send_utc,
                    last_sent_utc,
                    translation_language
                FROM server_settings
                WHERE server_id = ?
                ''',
                (interaction.guild.id,)
            )

            existing = c.fetchone()

            if existing:
                # Keep the current language if none was selected.
                selected_language = language or existing[3] or "en"

                c.execute(
                    '''
                    UPDATE server_settings
                    SET channel_id = ?,
                        time_interval = ?,
                        role_id = ?,
                        translation_language = ?
                    WHERE server_id = ?
                    ''',
                    (
                        channel.id,
                        hours,
                        role.id if role else None,
                        selected_language,
                        interaction.guild.id
                    )
                )

                conn.commit()
                conn.close()
                conn = None

                role_display = role.mention if role else "No role ping"
                time_display = self.format_interval(hours)
                language_display = get_language_name(selected_language)

                await interaction.followup.send(
                    f"✅ Quran settings updated.\n"
                    f"**Channel:** {channel.mention}\n"
                    f"**Interval:** {time_display}\n"
                    f"**Ping role:** {role_display}\n"
                    f"**Translation:** {language_display}\n\n"
                    f"Your verse progress and existing schedule were preserved.",
                    ephemeral=True
                )

                return

            # Create the first setup
            selected_language = language or "en"
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
                    role_id,
                    translation_language
                )
                VALUES (?, ?, ?, ?, ?, NULL, ?, ?)
                ''',
                (
                    interaction.guild.id,
                    channel.id,
                    hours,
                    "1|1",
                    next_send_utc.strftime('%Y-%m-%d %H:%M:%S'),
                    role.id if role else None,
                    selected_language
                )
            )

            conn.commit()
            conn.close()
            conn = None

            role_display = role.mention if role else "No role ping"
            time_display = self.format_interval(hours)
            language_display = get_language_name(selected_language)

            # Send the first verse immediately
            verse_cog = self.bot.get_cog('VerseCog')

            if not verse_cog:
                log_error(
                    "VerseCog not found when trying to send first verse"
                )

                await interaction.followup.send(
                    f"✅ Quran verses will be sent to {channel.mention} "
                    f"every {time_display}.\n"
                    f"**Ping role:** {role_display}\n"
                    f"**Translation:** {language_display}",
                    ephemeral=True
                )

                return

            success = await verse_cog.send_verse_to_server(
                interaction.guild.id,
                scheduled_time=utcnow(),
                notify=False
            )

            if success:
                await interaction.followup.send(
                    f"✅ Quran verses will be sent to {channel.mention} "
                    f"every {time_display}.\n"
                    f"**Ping role:** {role_display}\n"
                    f"**Translation:** {language_display}\n\n"
                    f"**First verse sent!** 📖",
                    ephemeral=True
                )

            else:
                # Remove the setup if the first send completely failed.
                conn = db_connect()
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
                conn = None

                log_error(
                    f"Initial verse failed for server "
                    f"{interaction.guild.id}; setup rolled back"
                )

                await interaction.followup.send(
                    f"❌ I couldn't send the first verse to {channel.mention}, "
                    f"so the setup was **not saved**.\n\n"
                    "**Please check that I have:** View Channel, "
                    "Send Messages and Embed Links in that channel, "
                    "then run `/setup` again.",
                    ephemeral=True
                )

        except Exception as e:
            log_error(
                f"Setup command error: {e}",
                interaction=interaction
            )

            try:
                await interaction.followup.send(
                    "❌ An error occurred during setup. Please try again.",
                    ephemeral=True
                )
            except Exception:
                pass

        finally:
            if conn:
                conn.close()


# ----------------------------------------------------

async def setup(bot):
    await bot.add_cog(ChannelCog(bot))

# ----------------------------------------------------
