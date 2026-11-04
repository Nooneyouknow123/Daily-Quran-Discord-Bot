import random

import discord
from discord.ext import commands
from discord import app_commands

from utils import console_log, log_error, is_admin

# ----------------------------------------------------

class RandomVerseCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="random_verse",
        description="Get a random Quran verse"
    )
    @app_commands.describe(
        public="Post it in this channel for everyone to see (admins only)"
    )
    async def random_verse(
        self,
        interaction: discord.Interaction,
        public: bool = False
    ):
        """Get a random verse. It's private by default, but admins can
        choose to post it publicly. Doesn't affect scheduled verses
        or the bot's saved progress."""

        try:
            if public and not is_admin(interaction):
                await interaction.response.send_message(
                    "❌ Only **Administrators** can post a random verse for "
                    "everyone. Use the command without `public` to see one "
                    "privately.",
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

            embed = verse_cog.create_embed(verse_line)

            # Add a small label at the bottom of the embed.
            embed.set_footer(text="Random Verse")

            await interaction.response.send_message(
                embed=embed,
                ephemeral=not public
            )

            where = interaction.guild.name if interaction.guild else "DM"
            console_log(
                f"Random verse ({'public' if public else 'private'}) "
                f"used by {interaction.user} in {where}"
            )

        except Exception as e:
            log_error(f"Random verse command error: {str(e)}", interaction=interaction)

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
