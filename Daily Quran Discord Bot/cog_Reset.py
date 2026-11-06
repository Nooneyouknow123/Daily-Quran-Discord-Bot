import discord
from discord.ext import commands
from discord import app_commands

from utils import console_log, log_error, db_connect, is_admin, clear_owner_notices
# ----------------------------------------------------

class ResetCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def is_admin(self, interaction: discord.Interaction) -> bool:
        return is_admin(interaction)

    @app_commands.command(name="reset", description="Completely reset bot settings for this server")
    @app_commands.guild_only()
    async def reset(self, interaction: discord.Interaction):
        """Reset bot to fresh state - removes channel, resets verses, clears settings"""
        
        if not await self.is_admin(interaction):
            try:
                await interaction.response.send_message(
                    "❌ You need **Administrator** permissions to use this command.",
                    ephemeral=True
                )
            except:
                pass
            return

        # Create confirmation embed
        embed = discord.Embed(
            title="🔄 Bot Reset",
            description="**This will completely reset all bot settings for this server!**",
            color=0xff9900
        )
        
        embed.add_field(
            name="⚠️ What will be reset:",
            value="• Channel assignment ❌\n"
                  "• Verse progress (back to 1:1) 📖\n"
                  "• Schedule settings ❌\n"
                  "• All server settings 🗑️",
            inline=False
        )
        
        embed.add_field(
            name="✅ What happens after:",
            value="• You'll need to use `/setup` again\n"
                  "• Bot will start from Surah 1, Verse 1\n"
                  "• No data retained from previous setup",
            inline=False
        )
        
        embed.set_footer(text="This action cannot be undone!")

        # Create confirmation buttons
        class ResetConfirm(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=60.0)
                self.value = None

            @discord.ui.button(label='Confirm Reset', style=discord.ButtonStyle.danger, emoji='⚠️')
            async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
                self.value = True
                self.stop()
                
                # Perform the reset
                try:
                    conn = db_connect()
                    c = conn.cursor()
                    
                    # Delete server settings
                    c.execute('DELETE FROM server_settings WHERE server_id = ?', (interaction.guild.id,))
                    conn.commit()
                    conn.close()

                    # A fresh start also means fresh owner notices
                    clear_owner_notices(interaction.guild.id)
                    
                    # Success embed
                    success_embed = discord.Embed(
                        title="✅ Bot Reset Complete",
                        description="All settings have been cleared for this server.",
                        color=0x00ff00
                    )
                    
                    success_embed.add_field(
                        name="Next Steps:",
                        value="Use `/setup` to configure the bot again with a new channel and schedule.",
                        inline=False
                    )
                    
                    await interaction.response.edit_message(embed=success_embed, view=None)
                    console_log(f"Bot reset by {interaction.user} in {interaction.guild.name} (ID: {interaction.guild.id})")
                    
                except Exception as e:
                    error_msg = f"Reset command database error: {str(e)}"
                    log_error(error_msg, interaction=interaction)
                    await interaction.response.edit_message(
                        content="❌ Failed to reset bot settings. Please try again.",
                        embed=None,
                        view=None
                    )

            @discord.ui.button(label='Cancel', style=discord.ButtonStyle.secondary, emoji='❌')
            async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
                self.value = False
                self.stop()
                await interaction.response.edit_message(
                    content="✅ Reset cancelled. No changes were made.",
                    embed=None,
                    view=None
                )

        view = ResetConfirm()
        
        try:
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        except Exception as e:
            error_msg = f"Reset command error: {str(e)}"
            log_error(error_msg, interaction=interaction)
            try:
                await interaction.response.send_message(
                    "❌ Failed to start reset process. Please try again.",
                    ephemeral=True
                )
            except:
                pass

async def setup(bot):
    await bot.add_cog(ResetCog(bot))
# ----------------------------------------------------

