import discord
from discord.ext import commands
from datetime import datetime, timedelta

from utils import console_log, log_error, db_connect, utcnow, claim_owner_notice
import tracker

# ----------------------------------------------------

class VerseCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.verses = []
        self.verse_index = {}
        self.load_verses()

        console_log(
            f"Loaded {len(self.verses)} verses from quran.txt"
        )

    def load_verses(self):
        verses = []
        index = {}

        try:
            with open('quran.txt', 'r', encoding='utf-8') as file:
                for line in file:
                    line = line.strip()

                    #  Skip blank lines and the "#" license/header comments
                    if not line or line.startswith('#'):
                        continue

                    parts = line.split('|', 2)

                    if len(parts) >= 3:
                        #  Lookup table: "surah|verse" -> position in list
                        index.setdefault(
                            f"{parts[0]}|{parts[1]}",
                            len(verses)
                        )

                    verses.append(line)

        except FileNotFoundError:
            error_msg = "quran.txt file not found!"
            console_log(error_msg)
            log_error(error_msg)
            verses, index = [], {}

        except Exception as e:
            error_msg = f"Error loading quran.txt: {e}"
            console_log(error_msg)
            log_error(error_msg)
            verses, index = [], {}

        self.verses = verses
        self.verse_index = index
        return verses

    def find_verse_index(self, current_verse):
        """Position of a "surah|verse" reference in the verse list,
        or None if it does not exist."""
        position = self.verse_index.get(current_verse)

        if position is not None:
            return position

        #  Fallback for unusual stored values (old behaviour)
        for i, verse in enumerate(self.verses):
            if verse.startswith(current_verse):
                return i

        return None

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
            position = self.find_verse_index(current_verse)

            if position is None:
                return "1|1"

            next_verse = self.verses[(position + 1) % len(self.verses)]

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
            color=0xB8860B,
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

    #  What the server owner is told for each type of problem
    OWNER_NOTICES = {
        'channel_missing': (
            "The verse channel no longer exists",
            "The channel I send Quran verses to was deleted or I can no "
            "longer see it.",
            "Use `/changechannel` (or `/setup`) in your server to pick a "
            "new channel. Your verse progress will be kept."
        ),
        'no_view_channel': (
            "I can't see the verse channel",
            "I'm missing the **View Channel** permission in the channel "
            "where verses are sent.",
            "Give me **View Channel** in that channel, or pick another "
            "channel with `/changechannel`."
        ),
        'no_send_messages': (
            "I can't send messages in the verse channel",
            "I'm missing the **Send Messages** permission in the channel "
            "where verses are sent.",
            "Give me **Send Messages** in that channel, or pick another "
            "channel with `/changechannel`."
        ),
        'no_embed_links': (
            "I can't embed links in the verse channel",
            "I'm missing the **Embed Links** permission in the channel "
            "where verses are sent.",
            "Give me **Embed Links** in that channel, or pick another "
            "channel with `/changechannel`."
        ),
        'send_forbidden': (
            "Discord blocked my message",
            "Discord refused to let me post in the verse channel "
            "(a permission or channel setting is blocking me).",
            "Check my permissions and the channel's settings, or pick "
            "another channel with `/changechannel`."
        ),
        'http_error': (
            "I couldn't post the verse",
            "Discord returned an error when I tried to post in the verse "
            "channel.",
            "Check my permissions in that channel, or pick another "
            "channel with `/changechannel`."
        ),
    }

    async def notify_owner(self, server_id, error_type, channel_id=None):
        """DM the server owner about a problem. Each owner is told only
        ONCE per type of problem per server. Never raises."""
        try:
            guild = self.bot.get_guild(server_id)

            if not guild:
                return

            notice = self.OWNER_NOTICES.get(error_type)

            if not notice:
                return

            #  Only the first caller gets True - everyone else stops here
            if not claim_owner_notice(server_id, error_type):
                return

            title, problem, fix = notice

            embed = discord.Embed(
                title=f"⚠️ Daily Quran Bot - {title}",
                description=f"There is a problem in **{guild.name}**.",
                color=0xE74C3C,
                timestamp=datetime.now()
            )

            embed.add_field(
                name="❓ What's wrong",
                value=problem,
                inline=False
            )

            if channel_id:
                embed.add_field(
                    name="📁 Channel",
                    value=f"<#{channel_id}>",
                    inline=False
                )

            embed.add_field(
                name="🛠️ How to fix it",
                value=fix,
                inline=False
            )

            embed.add_field(
                name="🔗 Need help?",
                value="[Join our support server](https://discord.gg/MTSRd8BvMP)",
                inline=False
            )

            embed.set_footer(
                text="Verses are paused until this is fixed • "
                     "You will only get this message once for this problem"
            )

            owner = guild.owner

            if not owner and guild.owner_id:
                owner = await self.bot.fetch_user(guild.owner_id)

            if not owner:
                log_error(f"Owner of server {server_id} not found")
                return

            await owner.send(embed=embed)

            console_log(
                f"Owner of server {server_id} notified: {error_type}"
            )

        except Exception as e:
            #  Closed DMs etc. - never retried, never breaks the scheduler
            log_error(
                f"Could not DM owner of server {server_id} "
                f"({error_type}): {e}"
            )

    async def send_verse_to_server(
        self,
        server_id,
        scheduled_time,
        was_down=False,
        missed_count=0,
        notify=True
    ):
        conn = None
        channel_id = None

        try:
            conn = db_connect()
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

                if notify:
                    await self.notify_owner(
                        server_id, 'channel_missing', channel_id
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

                if notify:
                    await self.notify_owner(
                        server_id, 'no_view_channel', channel_id
                    )

                return False

            if not permissions.send_messages:
                log_error(
                    f"Missing Send Messages permission in "
                    f"server {server_id}, channel {channel_id}"
                )

                if notify:
                    await self.notify_owner(
                        server_id, 'no_send_messages', channel_id
                    )

                return False

            if not permissions.embed_links:
                log_error(
                    f"Missing Embed Links permission in "
                    f"server {server_id}, channel {channel_id}"
                )

                if notify:
                    await self.notify_owner(
                        server_id, 'no_embed_links', channel_id
                    )

                return False

            #  Find the full verse text
            position = self.find_verse_index(current_verse)
            full_verse_text = (
                self.verses[position] if position is not None else None
            )

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
            current_utc = utcnow()

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

            #  Statistics for the dev panel (never affects sending)
            tracker.record_verse_sent(server_id)

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

            if notify:
                await self.notify_owner(
                    server_id, 'send_forbidden', channel_id
                )

            return False

        except discord.NotFound:
            log_error(
                f"Discord says the channel no longer exists "
                f"in server {server_id}"
            )

            if notify:
                await self.notify_owner(
                    server_id, 'channel_missing', channel_id
                )

            return False

        except discord.HTTPException as e:
            log_error(
                f"Discord HTTP error in server {server_id}: {e}"
            )

            #  5xx errors are Discord's own hiccups, not the owner's problem
            if notify and getattr(e, 'status', 0) < 500:
                await self.notify_owner(
                    server_id, 'http_error', channel_id
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
