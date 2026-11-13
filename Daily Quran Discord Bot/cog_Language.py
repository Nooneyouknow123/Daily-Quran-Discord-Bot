import discord
from discord.ext import commands
from discord import app_commands

from utils import db_connect, is_admin, log_error, console_log
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


class LanguageCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="language",
        description="Change the Quran translation for this server"
    )
    @app_commands.guild_only()
    @app_commands.describe(
        language="Select the translation language"
    )
    @app_commands.autocomplete(language=language_autocomplete)
    async def language(
        self,
        interaction: discord.Interaction,
        language: str
    ):
        if not is_admin(interaction):
            await interaction.response.send_message(
                "❌ You need **Administrator** permissions to use this command.",
                ephemeral=True
            )
            return

        if language not in LANGUAGES:
            await interaction.response.send_message(
                "❌ Invalid language. Please select a language from the list.",
                ephemeral=True
            )
            return

        conn = None

        try:
            conn = db_connect()
            c = conn.cursor()

            c.execute(
                '''
                SELECT translation_language
                FROM server_settings
                WHERE server_id = ?
                ''',
                (interaction.guild.id,)
            )

            existing = c.fetchone()

            if not existing:
                await interaction.response.send_message(
                    "❌ This server hasn't been set up yet. "
                    "Run `/setup` first.",
                    ephemeral=True
                )
                return

            c.execute(
                '''
                UPDATE server_settings
                SET translation_language = ?
                WHERE server_id = ?
                ''',
                (language, interaction.guild.id)
            )

            conn.commit()

            language_name = get_language_name(language)

            console_log(
                f"Server {interaction.guild.id} changed translation "
                f"to {language} ({language_name})"
            )

            await interaction.response.send_message(
                f"✅ Translation language changed to **{language_name}**.\n\n"
                f"The next scheduled verse will use this translation. "
                f"Your verse progress and schedule have not been changed.",
                ephemeral=True
            )

        except Exception as e:
            log_error(
                f"Language command error: {e}",
                interaction=interaction
            )

            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ An error occurred while changing the language.",
                        ephemeral=True
                    )
            except Exception:
                pass

        finally:
            if conn:
                conn.close()


# ----------------------------------------------------

async def setup(bot):
    await bot.add_cog(LanguageCog(bot))

# ----------------------------------------------------