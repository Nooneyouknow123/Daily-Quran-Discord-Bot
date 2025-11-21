import discord
from discord.ext import commands
import sqlite3
import os
from datetime import datetime, timedelta
from log import log
# ----------------------------------------------------

class VerseCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.verses = self.load_verses()
        log(f"Loaded {len(self.verses)} verses from quran.txt")

    def load_verses(self):
        verses = []
        try:
            with open('quran.txt', 'r', encoding='utf-8') as file:
                for line in file:
                    if line.strip():
                        verses.append(line.strip())
            return verses
        except FileNotFoundError:
            log("ERROR: quran.txt file not found!")
            return []
        except Exception as e:
            log(f"ERROR: Failed to load quran.txt: {str(e)}")
            return []

    def parse_verse(self, verse_line):
        """Parse verse line like '1|1|In the Name of Allah...'"""
        try:
            parts = verse_line.split('|', 2)
            if len(parts) >= 3:
                surah = parts[0]
                verse = parts[1]
                text = parts[2]
                return surah, verse, text
            return "1", "1", verse_line
        except:
            return "1", "1", verse_line

    def get_next_verse(self, current_verse):
        if not self.verses:
            return "1|1"
        
        try:
            for i, verse in enumerate(self.verses):
                if verse.startswith(current_verse):
                    next_index = (i + 1) % len(self.verses)
                    next_verse = self.verses[next_index]
                    # Return just the verse reference (e.g., "1|2")
                    return next_verse.split('|')[0] + '|' + next_verse.split('|')[1]
            return "1|1"
        except:
            return "1|1"
# ----------------------------------------------------
    def create_embed(self, verse_line, was_down=False, missed_count=0):
        surah, verse, text = self.parse_verse(verse_line)
        
        embed = discord.Embed(
            title=f"📖 Quran Verse - Surah {surah}, Verse {verse}",
            description=text,
            color=0x2ecc71,
            timestamp=datetime.now()
        )
        
        if was_down and missed_count > 0:
            if missed_count == 1:
                notice = "Bot was temporarily offline. Back on schedule now!"
            else:
                notice = f"Bot was offline due to some issues. Resuming regular schedule."
            
            embed.add_field(name="📝 Note", value=notice, inline=False)
        
        embed.set_footer(text="Daily Quran • May Allah bless you with this reminder")
        return embed

    async def send_verse_to_server(self, server_id, was_down=False, missed_count=0):
        try:
            conn = sqlite3.connect('quran_bot.db')
            c = conn.cursor()
            
            c.execute('SELECT channel_id, current_verse, time_interval FROM server_settings WHERE server_id = ?', (server_id,))
            result = c.fetchone()
            
            if not result:
                conn.close()
                return
            
            channel_id, current_verse, time_interval = result
            channel = self.bot.get_channel(channel_id)
            
            if not channel:
                conn.close()
                return
            
            # Check bot permissions
            bot_member = channel.guild.get_member(self.bot.user.id)
            if not bot_member or not channel.permissions_for(bot_member).send_messages:
                log(f"ERROR: Missing permissions in server {server_id}, channel {channel_id}")
                conn.close()
                return
            
            # Find the full verse text
            full_verse_text = None
            for verse in self.verses:
                if verse.startswith(current_verse):
                    full_verse_text = verse
                    break
            
            if full_verse_text:
                embed = self.create_embed(full_verse_text, was_down, missed_count)
                await channel.send(embed=embed)
                
                # Update to next verse AND schedule next send in UTC
                next_verse = self.get_next_verse(current_verse)
                next_send_utc = datetime.utcnow() + timedelta(hours=time_interval)
                
                c.execute(
                    '''UPDATE server_settings 
                       SET current_verse = ?, last_sent_utc = datetime('now'), next_send_utc = ?
                       WHERE server_id = ?''',
                    (next_verse, next_send_utc.strftime('%Y-%m-%d %H:%M:%S'), server_id)
                )
                conn.commit()
                
                log(f"Sent verse {current_verse} to server {server_id}, next UTC: {next_send_utc.strftime('%Y-%m-%d %H:%M:%S')}")
            else:
                log(f"ERROR: Verse not found: {current_verse} for server {server_id}")
            
            conn.close()
            
        except discord.errors.Forbidden:
            log(f"ERROR: Missing permissions in server {server_id}")
        except Exception as e:
            log(f"ERROR: Failed to send verse to server {server_id}: {str(e)}")

async def setup(bot):
    await bot.add_cog(VerseCog(bot))
# ----------------------------------------------------