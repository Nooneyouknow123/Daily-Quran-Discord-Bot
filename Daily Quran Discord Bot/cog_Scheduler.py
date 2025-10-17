import discord
from discord.ext import commands, tasks
import sqlite3
import asyncio
from datetime import datetime, timedelta
import os
# ----------------------------------------------------
def console_log(message):
    with open('console.txt', 'a', encoding='utf-8') as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {message}\n")

def log_error(error_message):
    with open('errors.txt', 'a', encoding='utf-8') as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {error_message}\n")

class SchedulerCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.verse_check.start()
        console_log("Scheduler started - UTC-based system")

    def cog_unload(self):
        self.verse_check.cancel()
        console_log("Scheduler stopped")

    @tasks.loop(minutes=1)
    async def verse_check(self):
        try:
            current_utc = datetime.utcnow()
            conn = sqlite3.connect('quran_bot.db')
            c = conn.cursor()
            
            # Find servers where current UTC time >= next_send_utc
            c.execute('''SELECT server_id, channel_id, time_interval, current_verse, next_send_utc 
                        FROM server_settings 
                        WHERE next_send_utc <= ?''', (current_utc.strftime('%Y-%m-%d %H:%M:%S'),))
            
            servers = c.fetchall()
            
            sent_count = 0
            
            for server_id, channel_id, time_interval, current_verse, next_send_utc in servers:
                sent_count += 1
                verse_cog = self.bot.get_cog('VerseCog')
                if verse_cog:
                    # Check if this send is significantly late (for recovery notice)
                    scheduled_time = datetime.strptime(next_send_utc, '%Y-%m-%d %H:%M:%S')
                    time_late = current_utc - scheduled_time
                    interval_duration = timedelta(hours=time_interval)
                    
                    # Show recovery notice if we're more than 2 intervals late
                    was_down = time_late > (interval_duration * 2)
                    missed_count = int(time_late.total_seconds() / interval_duration.total_seconds()) if was_down else 0
                    
                    await verse_cog.send_verse_to_server(
                        server_id, 
                        was_down=was_down, 
                        missed_count=missed_count
                    )
                    console_log(f"UTC-based send to server {server_id} - scheduled: {next_send_utc}, current: {current_utc.strftime('%H:%M:%S')}")
            
            conn.close()
            
            if sent_count > 0:
                console_log(f"Scheduler: Sent {sent_count} verses at UTC {current_utc.strftime('%H:%M:%S')}")
                
        except Exception as e:
            error_msg = f"Scheduler error: {str(e)}"
            log_error(error_msg)

    @verse_check.before_loop
    async def before_verse_check(self):
        await self.bot.wait_until_ready()
        console_log("UTC Scheduler is now active")

async def setup(bot):
    await bot.add_cog(SchedulerCog(bot))

# ----------------------------------------------------


