
import random

import discord
from discord.ext import commands
from discord import app_commands

from utils import console_log, log_error, is_admin
from languages import LANGUAGES

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


class RandomVerseCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="random_verse",
        description="Get a random Quran verse"
    )
    @app_commands.describe(
        language="Choose the translation language",
        public="Post it in this channel for everyone to see (admins only)"
    )
    @app_commands.autocomplete(language=language_autocomplete)
    async def random_verse(
        self,
        interaction: discord.Interaction,
        language: str,
        public: bool = False
    ):
        """Get a random verse without affecting scheduled progress."""

        try:
            if public and not is_admin(interaction):
                await interaction.response.send_message(
                    "❌ Only **Administrators** can post a random verse for "
                    "everyone. Use the command without `public` to see one "
                    "privately.",
                    ephemeral=True
                )
                return

            if language not in LANGUAGES:
                await interaction.response.send_message(
                    "❌ Invalid language. Please select a language from the list.",
                    ephemeral=True
                )
                return

            verse_cog = self.bot.get_cog('VerseCog')

            if not verse_cog or not verse_cog.verses:
                await interaction.response.send_message(
                    "❌ Verses are not available right now. "
                    "Please try again later.",
                    ephemeral=True
                )
                return

            verse_line = random.choice(verse_cog.verses)

            embeds = verse_cog.create_embeds(
                verse_line,
                translation_language=language
            )

            embeds[0].title = f"🎲 Random Verse - {embeds[0].title}"

            await interaction.response.send_message(
                embeds=embeds,
                ephemeral=not public
            )

            where = interaction.guild.name if interaction.guild else "DM"

            console_log(
                f"Random verse ({'public' if public else 'private'}) "
                f"used by {interaction.user} in {where} "
                f"with language {language}"
            )

        except Exception as e:
            log_error(
                f"Random verse command error: {str(e)}",
                interaction=interaction
            )

            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ Failed to get a random verse. Please try again.",
                        ephemeral=True
                    )
            except Exception:
                pass


# ----------------------------------------------------

async def setup(bot):
    await bot.add_cog(RandomVerseCog(bot))

# ----------------------------------------------------


