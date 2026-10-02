import discord
from discord.ext import commands
import sqlite3
from datetime import datetime, timedelta

# ----------------------------------------------------

def console_log(message):
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {message}")

def log_error(error_message):
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - ERROR: {error_message}")

# ----------------------------------------------------

class VerseCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.verses = self.load_verses()

        console_log(
            f"Loaded {len(self.verses)} verses from quran.txt"
        )

    def load_verses(self):
        verses = []

        try:
            with open('quran.txt', 'r', encoding='utf-8') as file:
                for line in file:
                    if line.strip():
                        verses.append(line.strip())

            return verses

        except FileNotFoundError:
            error_msg = "quran.txt file not found!"
            console_log(error_msg)
            log_error(error_msg)
            return []

        except Exception as e:
            error_msg = f"Error loading quran.txt: {e}"
            console_log(error_msg)
            log_error(error_msg)
            return []

    def parse_verse(self, verse_line):
        try:
            parts = verse_line.split('|', 2)

            if len(parts) >= 3:
                return parts[0], parts[1], parts[2]

            return "1", "1", verse_line

        except Exception:
            return "1", "1", verse_line

    def get_next_verse(self, current_verse):
        if not self.verses:
            return "1|1"

        try:
            for i, verse in enumerate(self.verses):
                if verse.startswith(current_verse):
                    next_index = (i + 1) % len(self.verses)
                    next_verse = self.verses[next_index]

                    #  Return only the next verse reference
                    parts = next_verse.split('|', 2)

                    if len(parts) >= 2:
                        return f"{parts[0]}|{parts[1]}"

            return "1|1"

        except Exception:
            return "1|1"

    def create_embed(
        self,
        verse_line,
        was_down=False,
        missed_count=0
    ):
        surah, verse, text = self.parse_verse(verse_line)

        embed = discord.Embed(
            title=f"📖 Quran Verse - Surah {surah}, Verse {verse}",
            description=text,
            color=0x2ecc71,
            timestamp=datetime.now()
        )

        if was_down:
            if missed_count <= 1:
                notice = (
                    "Bot was temporarily offline. "
                    "Back on schedule now!"
                )
            else:
                notice = (
                    "Bot was offline due to some issues. "
                    "Resuming regular schedule."
                )

            embed.add_field(
                name="📝 Note",
                value=notice,
                inline=False
            )

        embed.add_field(
            name="🔗 Support Server",
            value="[Join our support server](https://discord.gg/MTSRd8BvMP)",
            inline=False
        )

        embed.set_footer(
            text="Daily Quran • May Allah bless you with this reminder"
        )

        return embed

    async def send_verse_to_server(
        self,
        server_id,
        scheduled_time,
        was_down=False,
        missed_count=0
    ):
        conn = None

        try:
            conn = sqlite3.connect('quran_bot.db')
            c = conn.cursor()

            c.execute(
                '''
                SELECT
                    channel_id,
                    current_verse,
                    time_interval,
                    role_id
                FROM server_settings
                WHERE server_id = ?
                ''',
                (server_id,)
            )

            result = c.fetchone()

            if not result:
                return False

            (
                channel_id,
                current_verse,
                time_interval,
                role_id
            ) = result

            channel = self.bot.get_channel(channel_id)

            if not channel:
                log_error(
                    f"Channel {channel_id} not found "
                    f"for server {server_id}"
                )
                return False

            #  Check bot permissions
            bot_member = channel.guild.get_member(self.bot.user.id)

            if not bot_member:
                log_error(
                    f"Bot member not found in server {server_id}"
                )
                return False

            permissions = channel.permissions_for(bot_member)

            if not permissions.view_channel:
                log_error(
                    f"Missing View Channel permission in "
                    f"server {server_id}, channel {channel_id}"
                )
                return False

            if not permissions.send_messages:
                log_error(
                    f"Missing Send Messages permission in "
                    f"server {server_id}, channel {channel_id}"
                )
                return False

            if not permissions.embed_links:
                log_error(
                    f"Missing Embed Links permission in "
                    f"server {server_id}, channel {channel_id}"
                )
                return False

            #  Find the full verse text
            full_verse_text = None

            for verse in self.verses:
                if verse.startswith(current_verse):
                    full_verse_text = verse
                    break

            if not full_verse_text:
                log_error(
                    f"Verse {current_verse} not found "
                    f"for server {server_id}"
                )
                return False

            #  Find the configured role
            role = None

            if role_id:
                role = channel.guild.get_role(role_id)

                if not role:
                    log_error(
                        f"Configured role {role_id} no longer exists "
                        f"in server {server_id}. Clearing it."
                    )

                    c.execute(
                        '''
                        UPDATE server_settings
                        SET role_id = NULL
                        WHERE server_id = ?
                        ''',
                        (server_id,)
                    )

                    conn.commit()

                elif role.is_default() or role.managed:
                    log_error(
                        f"Configured role {role_id} is invalid "
                        f"in server {server_id}. Clearing it."
                    )

                    c.execute(
                        '''
                        UPDATE server_settings
                        SET role_id = NULL
                        WHERE server_id = ?
                        ''',
                        (server_id,)
                    )

                    conn.commit()

                    role = None

            embed = self.create_embed(
                full_verse_text,
                was_down,
                missed_count
            )

            #  Mention the configured role
            content = role.mention if role else None

            #  Send the verse first
            await channel.send(
                content=content,
                embed=embed,
                allowed_mentions=discord.AllowedMentions(
                    roles=True
                )
            )

            #  Only update progress after Discord accepted the message
            next_verse = self.get_next_verse(current_verse)

            interval_duration = timedelta(hours=time_interval)

            #  Keep the schedule based on the original scheduled time
            next_send_utc = scheduled_time + interval_duration

            #  Skip old schedule points until we reach the future
            current_utc = datetime.utcnow()

            while next_send_utc <= current_utc:
                next_send_utc += interval_duration

            c.execute(
                '''
                UPDATE server_settings
                SET current_verse = ?,
                    last_sent_utc = datetime('now'),
                    next_send_utc = ?
                WHERE server_id = ?
                ''',
                (
                    next_verse,
                    next_send_utc.strftime(
                        '%Y-%m-%d %H:%M:%S'
                    ),
                    server_id
                )
            )

            conn.commit()

            console_log(
                f"Sent verse {current_verse} to server {server_id}. "
                f"Next UTC: "
                f"{next_send_utc.strftime('%Y-%m-%d %H:%M:%S')}"
            )

            return True

        except discord.Forbidden:
            log_error(
                f"Discord denied message send in server {server_id}"
            )
            return False

        except discord.HTTPException as e:
            log_error(
                f"Discord HTTP error in server {server_id}: {e}"
            )
            return False

        except Exception as e:
            log_error(
                f"Error sending verse to server {server_id}: {e}"
            )
            return False

        finally:
            if conn:
                conn.close()

# ----------------------------------------------------

async def setup(bot):
    await bot.add_cog(VerseCog(bot))

# ----------------------------------------------------