
import discord
from discord.ext import commands
from datetime import datetime, timedelta

from utils import console_log, log_error, db_connect, utcnow, claim_owner_notice
from languages import (
    get_verse,
    get_language_name,
    get_language_lines
)
import tracker

# ----------------------------------------------------

class VerseCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.verses = []
        self.verse_index = {}
        self.load_verses()

        console_log(
            f"Loaded {len(self.verses)} verses from quranlanguages/quran.txt"
        )

    def load_verses(self):
        verses = []
        index = {}

        try:
            verses = get_language_lines("en")

            for position, line in enumerate(verses):
                parts = line.split('|', 2)

                if len(parts) >= 3:
                    reference = f"{parts[0]}|{parts[1]}"
                    index.setdefault(reference, position)

        except Exception as e:
            error_msg = f"Error loading English verses: {e}"
            console_log(error_msg)
            log_error(error_msg)
            verses, index = [], {}

        self.verses = verses
        self.verse_index = index
        return verses

    def find_verse_index(self, current_verse):
        """Find the position of a verse reference in the English list."""
        position = self.verse_index.get(current_verse)

        if position is not None:
            return position

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
            parts = next_verse.split('|', 2)

            if len(parts) >= 2:
                return f"{parts[0]}|{parts[1]}"

            return "1|1"

        except Exception:
            return "1|1"

    def create_embeds(
        self,
        verse_line,
        was_down=False,
        missed_count=0,
        translation_language="en"
    ):
        surah, verse, _ = self.parse_verse(verse_line)
        reference = f"{surah}|{verse}"

        # Always show Arabic, regardless of the selected translation.
        arabic_line = get_verse("ar", reference)

        if arabic_line:
            _, _, arabic_text = self.parse_verse(arabic_line)
        else:
            arabic_text = "Arabic translation unavailable."

        # Use English if an invalid language code is supplied.
        translated_line = get_verse(translation_language, reference)

        if not translated_line:
            translation_language = "en"
            translated_line = get_verse("en", reference)

        _, _, translated_text = self.parse_verse(translated_line)
        language_name = get_language_name(translation_language)

        title = f"📖 Quran Verse - Surah {surah}, Verse {verse}"

        def create_new_embed():
            return discord.Embed(
                title=title,
                color=0xB8860B,
                timestamp=datetime.now()
            )

        embeds = [create_new_embed()]

        # Add text fields without exceeding Discord's embed limits.
        def add_text_fields(name, text):
            if not text:
                text = "\u200b"

            chunks = [
                text[i:i + 1024]
                for i in range(0, len(text), 1024)
            ]

            for i, chunk in enumerate(chunks):
                embed = embeds[-1]
                field_name = name if i == 0 else "\u200b"

                if (
                    len(embed.fields) >= 25
                    or len(embed) + len(field_name) + len(chunk) > 6000
                ):
                    embed = create_new_embed()
                    embeds.append(embed)
                    field_name = name

                embed.add_field(
                    name=field_name,
                    value=chunk,
                    inline=False
                )

        add_text_fields("Arabic", arabic_text)

        # Don't show Arabic twice if Arabic is the selected language.
        if translation_language != "ar":
            add_text_fields(
                f"Translation • {language_name}",
                translated_text
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

            add_text_fields("📝 Note", notice)

        add_text_fields(
            "🔗 Support Server",
            "[Join our support server](https://discord.gg/MTSRd8BvMP)"
        )

        footer_text = (
            f"Translation: {language_name} • "
            "Daily Quran • May Allah bless you with this reminder"
        )

        # Keep the footer within the 6,000-character limit too.
        if len(embeds[-1]) + len(footer_text) > 6000:
            embeds.append(create_new_embed())

        embeds[-1].set_footer(text=footer_text)

        return embeds

    # What the server owner is told for each type of problem
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
            "I'm missing **Embed Links** permission in the channel "
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
            "Discord returned an error when I tried to post the verse.",
            "Check my permissions in that channel, or pick another "
            "channel with `/changechannel`."
        ),
    }

    async def notify_owner(self, server_id, error_type, channel_id=None):
        """DM the server owner about a problem. Each owner is told only
        once per type of problem per server. Never raises."""
        try:
            guild = self.bot.get_guild(server_id)

            if not guild:
                return

            notice = self.OWNER_NOTICES.get(error_type)

            if not notice:
                return

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
                    role_id,
                    translation_language
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
                role_id,
                translation_language
            ) = result

            if not translation_language:
                translation_language = "en"

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

            # Check bot permissions
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

            # Find the full verse text and its reference.
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

            # Find the configured role
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

            embeds = self.create_embeds(
                full_verse_text,
                was_down=was_down,
                missed_count=missed_count,
                translation_language=translation_language
            )

            content = role.mention if role else None

            # Send each embed as a separate message.
            for i, embed in enumerate(embeds):
                await channel.send(
                    content=content if i == 0 else None,
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions(
                        roles=True
                    )
                )

            # Only update progress after Discord accepted all messages.
            next_verse = self.get_next_verse(current_verse)

            interval_duration = timedelta(hours=time_interval)
            next_send_utc = scheduled_time + interval_duration

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
                    next_send_utc.strftime('%Y-%m-%d %H:%M:%S'),
                    server_id
                )
            )

            conn.commit()

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

