import discord
from discord import app_commands
from discord.ext import commands

class SupportCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="support", description="Get the support server link.")
    async def support(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🛠️ Need Help?",
            description="Please join our support server:\n[Join Here](https://discord.gg/MTSRd8BvMP)",
            color=discord.Color.blurple()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(SupportCog(bot))



