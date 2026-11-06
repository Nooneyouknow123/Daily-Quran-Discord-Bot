import asyncio
import time
from datetime import timezone, datetime, timedelta

import discord
from discord.ext import commands, tasks

import tracker
from utils import (
    console_log,
    log_error,
    db_connect,
    utcnow,
    format_uptime,
    parse_interval,
    format_interval_hours,
    bot_can_post,
    clear_owner_notices
)

# ====================================================
#  SETTINGS 
# ====================================================

DEV_GUILD_ID = 1567608193683693738           # the server where the dev panel lives
DEV_CHANNEL_ID = 1567608279167803435         # the channel the live panel is posted in
DEV_ALERT_CHANNEL_ID = 1567608279167803435    # optional: separate channel for error alerts
                               

DEV_USER_IDS = {1274667778300706866}   # only these users can use the panel

PANEL_REFRESH_SECONDS = 60     # how often the panel message is updated
ALERT_CHECK_SECONDS = 10       # how often new errors are checked for alerts

#  Verses sent BEFORE the panel started counting (the panel adds this to
#  its own running total). Leave 0 to count from today.
TOTAL_VERSES_BASELINE = 0

# ====================================================

STATUS_ICON = {'new': '🆕', 'read': '✅', 'minor': '🟡', 'serious': '🔴'}
STATUS_LABEL = {
    'new': 'New - awaiting your review',
    'read': 'Marked read',
    'minor': 'Approved as non-serious',
    'serious': 'Marked serious'
}
STATUS_COLOR = {
    'new': 0xE74C3C,
    'read': 0x95A5A6,
    'minor': 0xF1C40F,
    'serious': 0x992D22
}


def clip(text, limit):
    text = str(text)
    return text if len(text) <= limit else text[:limit - 1] + "…"


def unix(ts_string):
    """'YYYY-MM-DD HH:MM:SS' (UTC) -> unix seconds."""
    try:
        dt = datetime.strptime(ts_string, tracker.TS).replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return None


def rel(ts_string):
    stamp = unix(ts_string) if ts_string else None
    return f"<t:{stamp}:R>" if stamp else "never"


def release(view):
    """Buttons are answered by the cog's on_interaction handler (so they keep
    working after a restart), so the view object itself is not needed."""
    try:
        view.stop()
    except Exception:
        pass

    return view


def to_int(text):
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------
#  Modals (pop-up forms)
# ----------------------------------------------------

class _BaseModal(discord.ui.Modal):
    async def on_error(self, interaction, error):
        log_error(f"Dev panel modal error: {error}", interaction=interaction)

        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ Something went wrong in the dev panel.",
                    ephemeral=True
                )
        except Exception:
            pass


class ServerIdModal(_BaseModal):
    def __init__(self, cog, title, action):
        super().__init__(title=title)
        self.cog = cog
        self.action = action

        self.server_id = discord.ui.TextInput(
            label="Server ID",
            placeholder="e.g. 123456789012345678",
            required=True,
            max_length=25
        )
        self.add_item(self.server_id)

    async def on_submit(self, interaction):
        await self.cog.handle_server_action(
            interaction, self.action, self.server_id.value
        )


class ErrorIdModal(_BaseModal):
    def __init__(self, cog):
        super().__init__(title="Error details")
        self.cog = cog

        self.error_id = discord.ui.TextInput(
            label="Error number (the # in the panel)",
            placeholder="e.g. 12",
            required=True,
            max_length=10
        )
        self.add_item(self.error_id)

    async def on_submit(self, interaction):
        await self.cog.show_error_details(interaction, self.error_id.value)


class ConfigModal(_BaseModal):
    def __init__(self, cog):
        super().__init__(title="Configure a server")
        self.cog = cog

        self.server_id = discord.ui.TextInput(
            label="Server ID", required=True, max_length=25
        )
        self.channel_id = discord.ui.TextInput(
            label="Channel ID (blank = keep current)",
            required=False, max_length=25
        )
        self.interval = discord.ui.TextInput(
            label="Interval e.g. 30m / 2h (blank = keep)",
            required=False, max_length=10
        )
        self.role_id = discord.ui.TextInput(
            label="Ping role ID (blank = keep, 0 = none)",
            required=False, max_length=25
        )
        self.verse = discord.ui.TextInput(
            label="Current verse e.g. 2|255 (blank = keep)",
            required=False, max_length=10
        )

        for item in (self.server_id, self.channel_id, self.interval,
                     self.role_id, self.verse):
            self.add_item(item)

    async def on_submit(self, interaction):
        await self.cog.apply_config(
            interaction,
            self.server_id.value,
            self.channel_id.value,
            self.interval.value,
            self.role_id.value,
            self.verse.value
        )


# ----------------------------------------------------
#  The cog
# ----------------------------------------------------

class DevPanelCog(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self._last_problem_log = {}

        tracker.ensure_tables()

        self.alert_loop.change_interval(seconds=ALERT_CHECK_SECONDS)
        self.panel_loop.change_interval(seconds=PANEL_REFRESH_SECONDS)

        self.alert_loop.start()
        self.panel_loop.start()

        if not DEV_CHANNEL_ID:
            console_log(
                "Dev panel is idle: set DEV_CHANNEL_ID (and DEV_GUILD_ID) "
                "at the top of cog_DevPanel.py. Errors are still tracked."
            )

    def cog_unload(self):
        self.alert_loop.cancel()
        self.panel_loop.cancel()

    # ------------------------------------------------
    #  Helpers
    # ------------------------------------------------

    def _throttled_log(self, key, message, seconds=1800):
        """Log a recurring dev-panel problem at most once per 30 minutes."""
        now = time.monotonic()

        if now - self._last_problem_log.get(key, -seconds) >= seconds:
            self._last_problem_log[key] = now
            log_error(message)

    def get_panel_channel(self):
        if not DEV_CHANNEL_ID:
            return None

        channel = self.bot.get_channel(DEV_CHANNEL_ID)

        if channel and DEV_GUILD_ID and channel.guild.id != DEV_GUILD_ID:
            self._throttled_log(
                'guild-mismatch',
                "Dev panel: DEV_CHANNEL_ID is not in DEV_GUILD_ID"
            )
            return None

        return channel

    def get_alert_channel(self):
        if DEV_ALERT_CHANNEL_ID:
            return self.bot.get_channel(DEV_ALERT_CHANNEL_ID)

        return self.get_panel_channel()

    def is_dev(self, interaction):
        return interaction.user.id in DEV_USER_IDS

    # ------------------------------------------------
    #  Embeds
    # ------------------------------------------------

    def error_embed(self, err):
        icon = STATUS_ICON.get(err['status'], '❔')

        where = err['source'] or 'system'

        if err['command']:
            where = f"command /{err['command']}"

        embed = discord.Embed(
            title=f"{icon} Error #{err['id']} - {where}",
            description=f"```{clip(err['message'], 900)}```",
            color=STATUS_COLOR.get(err['status'], 0x95A5A6)
        )

        status_text = STATUS_LABEL.get(err['status'], err['status'])

        if err['status'] != 'new' and err.get('reviewed_by'):
            status_text += f" by <@{err['reviewed_by']}> {rel(err['reviewed_utc'])}"

        embed.add_field(name="Status", value=status_text, inline=False)

        embed.add_field(
            name=f"Error #{err['id']} generated",
            value=(
                f"**24 hours:** {err['count_24h']}\n"
                f"**Last week:** {err['count_7d']}\n"
                f"**All time:** {err['count_all']}"
            ),
            inline=True
        )

        embed.add_field(
            name="Seen",
            value=(
                f"First: {rel(err['first_seen'])}\n"
                f"Last: {rel(err['last_seen'])}"
            ),
            inline=True
        )

        context = []

        if err.get('last_server_id'):
            guild = self.bot.get_guild(err['last_server_id'])
            context.append(
                f"Server: {guild.name if guild else 'unknown'} "
                f"(`{err['last_server_id']}`)"
            )

        if err.get('last_user_id'):
            context.append(f"User: <@{err['last_user_id']}>")

        if context:
            embed.add_field(
                name="Latest context", value="\n".join(context), inline=False
            )

        if err.get('top_servers'):
            lines = []

            for server_id, count in err['top_servers']:
                guild = self.bot.get_guild(server_id)
                lines.append(
                    f"{clip(guild.name if guild else 'unknown', 30)} "
                    f"(`{server_id}`) - {count}x"
                )

            embed.add_field(
                name="Most affected servers (7 days)",
                value="\n".join(lines),
                inline=False
            )

        if err['status'] == 'new':
            embed.set_footer(
                text="Mark it to stop alerts - repeats are still logged"
            )
        else:
            embed.set_footer(
                text="Repeats of this error are logged silently (no new alerts)"
            )

        return embed

    def error_view(self, err):
        view = discord.ui.View(timeout=None)
        current = err['status']

        buttons = (
            ('read', "Mark read", '✅', discord.ButtonStyle.success),
            ('minor', "Non-serious", '🟡', discord.ButtonStyle.secondary),
            ('serious', "Serious", '🔴', discord.ButtonStyle.danger),
        )

        for status, label, emoji, style in buttons:
            view.add_item(discord.ui.Button(
                label=label,
                emoji=emoji,
                style=style,
                custom_id=f"dev:err:{status}:{err['id']}",
                disabled=(current == status)
            ))

        return view

    def panel_view(self):
        view = discord.ui.View(timeout=None)

        layout = (
            ("Refresh", '🔄', 'dev:refresh', discord.ButtonStyle.secondary, 0),
            ("Errors", '🧾', 'dev:errors', discord.ButtonStyle.secondary, 0),
            ("Error details", '🔎', 'dev:errdetail', discord.ButtonStyle.secondary, 0),
            ("Servers", '📋', 'dev:servers', discord.ButtonStyle.secondary, 0),
            ("Inspect server", '🛠️', 'dev:inspect', discord.ButtonStyle.primary, 1),
            ("Configure server", '⚙️', 'dev:config', discord.ButtonStyle.primary, 1),
            ("Send verse now", '📤', 'dev:sendnow', discord.ButtonStyle.primary, 1),
            ("Remove setup", '🗑️', 'dev:remove', discord.ButtonStyle.danger, 1),
        )

        for label, emoji, custom_id, style, row in layout:
            view.add_item(discord.ui.Button(
                label=label, emoji=emoji, style=style,
                custom_id=custom_id, row=row
            ))

        return view

    async def build_panel_embeds(self):
        data = await asyncio.to_thread(tracker.collect_stats)
        total_errors, unique_errors, pending = await asyncio.to_thread(
            tracker.count_errors_24h
        )
        errors = await asyncio.to_thread(tracker.list_errors, 8, True)

        guilds = list(self.bot.guilds)
        guild_ids = {g.id for g in guilds}
        setup_ids = data.get('setup_ids', set())

        not_setup = [g for g in guilds if g.id not in setup_ids]
        orphaned = [s for s in setup_ids if s not in guild_ids]
        members = sum((g.member_count or 0) for g in guilds)

        scheduler = self.bot.get_cog('SchedulerCog')
        failing = len(getattr(scheduler, 'retry_state', {}) or {})

        latency = self.bot.latency
        latency_text = (
            f"{latency * 1000:.0f} ms"
            if latency == latency and latency != float('inf') else "n/a"
        )

        started = getattr(self.bot, 'start_time', None)
        uptime = format_uptime(started) if started else "n/a"

        serious = any(e['status'] == 'serious' for e in errors)
        color = 0xE74C3C if (pending or serious) else 0x2ECC71

        overview = discord.Embed(
            title="🛰️ Daily Quran Bot - Dev Panel",
            color=color,
            timestamp=datetime.now()
        )

        overview.add_field(
            name="🌐 Servers",
            value=(
                f"**{len(guilds)}** total\n"
                f"✅ {len(guilds) - len(not_setup)} set up\n"
                f"⬜ {len(not_setup)} not set up\n"
                f"👥 {members:,} members"
            ),
            inline=True
        )

        overview.add_field(
            name="📖 Verses sent",
            value=(
                f"Last 24h: **{data.get('verses_24h', 0):,}**\n"
                f"Total: **{TOTAL_VERSES_BASELINE + data.get('verses_total', 0):,}**\n"
                f"Due in next hour: {data.get('due_next_hour', 0)}"
            ),
            inline=True
        )

        durations = data.get('top_intervals') or []
        overview.add_field(
            name="⏱️ Most used durations",
            value="\n".join(
                f"{format_interval_hours(hours)} - {count} server{'s' if count != 1 else ''}"
                for hours, count in durations
            ) or "No setups yet",
            inline=True
        )

        overview.add_field(
            name="🩺 Health",
            value=(
                f"Failing servers: **{failing}**\n"
                f"Orphaned setups: {len(orphaned)}\n"
                f"Latency: {latency_text}\n"
                f"Uptime: {uptime}"
            ),
            inline=True
        )

        top = data.get('top_commands') or []
        overview.add_field(
            name="🕹️ Commands",
            value=(
                f"Last 24h: **{data.get('commands_24h', 0):,}**\n"
                f"Total: {data.get('commands_total', 0):,}\n"
                + (", ".join(f"/{name} ({n})" for name, n in top) or "-")
            ),
            inline=True
        )

        overview.add_field(
            name="📈 Growth & mail",
            value=(
                f"24h: +{data.get('joins_24h', 0)} joined / "
                f"-{data.get('leaves_24h', 0)} left\n"
                f"Owner DMs: {data.get('owner_dms_24h', 0)} (24h) / "
                f"{data.get('owner_dms_total', 0)} total\n"
                f"Database: {data.get('db_size', 0) / 1024 / 1024:.1f} MB"
            ),
            inline=True
        )

        overview.set_footer(
            text=f"Auto-updates every {PANEL_REFRESH_SECONDS}s • Last update"
        )

        error_embed = discord.Embed(
            title="🧯 Errors - last 24 hours",
            color=color
        )

        if total_errors == 0:
            summary = "✅ **No errors in the last 24 hours.**"
        else:
            summary = (
                f"**{total_errors:,}** error{'s' if total_errors != 1 else ''} "
                f"• **{unique_errors}** unique"
            )

        if pending:
            summary += f" • 🆕 **{pending}** awaiting your review"

        lines = []

        for err in errors:
            name = f"/{err['command']}" if err['command'] else (err['source'] or 'system')
            lines.append(
                f"{STATUS_ICON.get(err['status'], '❔')} **#{err['id']}** "
                f"×{err['count_24h']} • {name}\n"
                f"└ {clip(err['message'].replace(chr(10), ' '), 90)}"
            )

        if lines:
            summary += "\n\n" + "\n".join(lines)

        if unique_errors > len(errors):
            summary += f"\n… and {unique_errors - len(errors)} more (press 🧾 Errors)"

        error_embed.description = clip(summary, 4000)

        return [overview, error_embed]

    async def errors_embed(self):
        errors = await asyncio.to_thread(tracker.list_errors, 15, False)

        embed = discord.Embed(title="🧾 All unique errors", color=0x3498DB)

        if not errors:
            embed.description = "No errors have been recorded yet. ✅"
            return embed

        lines = []

        for err in errors:
            name = f"/{err['command']}" if err['command'] else (err['source'] or 'system')
            lines.append(
                f"{STATUS_ICON.get(err['status'], '❔')} **#{err['id']}** {name}\n"
                f"24h **{err['count_24h']}** • week **{err['count_7d']}** • "
                f"all time **{err['count_all']}**\n"
                f"└ {clip(err['message'].replace(chr(10), ' '), 80)}"
            )

        embed.description = clip("\n".join(lines), 4000)
        embed.set_footer(text="🆕 new  ✅ read  🟡 non-serious  🔴 serious • 🔎 Error details for the full text")

        return embed

    def servers_embed(self):
        embed = discord.Embed(title="📋 Servers", color=0x3498DB)

        conn = db_connect()

        try:
            setup_ids = {
                r[0] for r in conn.execute('SELECT server_id FROM server_settings').fetchall()
            }
        finally:
            conn.close()

        guilds = list(self.bot.guilds)
        guild_ids = {g.id for g in guilds}

        not_setup = sorted(
            (g for g in guilds if g.id not in setup_ids),
            key=lambda g: g.member_count or 0,
            reverse=True
        )

        lines = [
            f"{clip(g.name, 30)} (`{g.id}`) - {g.member_count or '?'} members"
            for g in not_setup[:15]
        ]

        embed.add_field(
            name=f"⬜ Not set up ({len(not_setup)})",
            value=clip("\n".join(lines) or "Everyone is set up 🎉", 1000),
            inline=False
        )

        scheduler = self.bot.get_cog('SchedulerCog')
        retry = getattr(scheduler, 'retry_state', {}) or {}

        failing = []

        for server_id, (count, _) in list(retry.items())[:10]:
            guild = self.bot.get_guild(server_id)
            failing.append(
                f"{clip(guild.name if guild else 'unknown', 30)} "
                f"(`{server_id}`) - {count} failed"
            )

        embed.add_field(
            name=f"🔁 Failing right now ({len(retry)})",
            value=clip("\n".join(failing) or "None ✅", 1000),
            inline=False
        )

        orphaned = [s for s in setup_ids if s not in guild_ids]

        embed.add_field(
            name=f"👻 Orphaned setups - bot is no longer in the server ({len(orphaned)})",
            value=clip(", ".join(f"`{s}`" for s in orphaned[:15]) or "None ✅", 1000),
            inline=False
        )

        return embed

    def inspect_embed(self, server_id):
        guild = self.bot.get_guild(server_id)

        conn = db_connect()

        try:
            row = conn.execute(
                '''SELECT channel_id, time_interval, current_verse,
                          next_send_utc, last_sent_utc, role_id
                   FROM server_settings WHERE server_id = ?''',
                (server_id,)
            ).fetchone()

            notices = [
                r[0] for r in conn.execute(
                    'SELECT error_type FROM owner_notices WHERE server_id = ?',
                    (server_id,)
                ).fetchall()
            ]

        finally:
            conn.close()

        embed = discord.Embed(
            title=f"🛠️ {guild.name if guild else 'Unknown server'}",
            description=f"ID `{server_id}`",
            color=0x3498DB
        )

        if guild:
            embed.add_field(
                name="Server",
                value=(
                    f"Members: {guild.member_count or '?'}\n"
                    f"Owner: <@{guild.owner_id}> (`{guild.owner_id}`)"
                ),
                inline=False
            )
        else:
            embed.add_field(
                name="Server",
                value="⚠️ The bot is **not** in this server.",
                inline=False
            )

        if not row:
            embed.add_field(
                name="Setup", value="❌ Not set up (no settings saved).", inline=False
            )
        else:
            channel_id, interval, verse, next_send, last_sent, role_id = row
            channel = self.bot.get_channel(channel_id)

            if channel:
                member = channel.guild.get_member(self.bot.user.id)
                perms = channel.permissions_for(member) if member else None

                def tick(flag):
                    return "✅" if flag else "❌"

                perm_text = (
                    f"{tick(perms.view_channel)} View  "
                    f"{tick(perms.send_messages)} Send  "
                    f"{tick(perms.embed_links)} Embed"
                    if perms else "unknown"
                )

                channel_text = f"{channel.mention} (`{channel_id}`)\n{perm_text}"
            else:
                channel_text = f"❌ Channel `{channel_id}` not found"

            embed.add_field(name="📁 Channel", value=channel_text, inline=False)

            embed.add_field(
                name="⚙️ Settings",
                value=(
                    f"Interval: {format_interval_hours(interval)}\n"
                    f"Current verse: {verse}\n"
                    f"Ping role: {f'<@&{role_id}>' if role_id else 'none'}"
                ),
                inline=True
            )

            embed.add_field(
                name="🕒 Schedule (UTC)",
                value=f"Last sent: {last_sent or 'never'}\nNext send: {next_send}",
                inline=True
            )

        scheduler = self.bot.get_cog('SchedulerCog')
        state = (getattr(scheduler, 'retry_state', {}) or {}).get(server_id)

        embed.add_field(
            name="🔁 Scheduler",
            value=(f"⚠️ {state[0]} consecutive failed attempts" if state else "No failures ✅"),
            inline=True
        )

        embed.add_field(
            name="✉️ Owner already told about",
            value=", ".join(notices) or "nothing",
            inline=True
        )

        return embed

    # ------------------------------------------------
    #  Panel + alerts
    # ------------------------------------------------

    async def update_panel(self):
        channel = self.get_panel_channel()

        if channel is None:
            return False

        embeds = await self.build_panel_embeds()
        view = self.panel_view()

        message = None
        message_id = to_int(tracker.get_state('panel_message_id'))

        if message_id:
            try:
                message = await channel.fetch_message(message_id)
            except discord.NotFound:
                message = None

        if message is not None:
            await message.edit(embeds=embeds, view=view)
        else:
            message = await channel.send(embeds=embeds, view=view)
            tracker.set_state('panel_message_id', message.id)

            try:
                await message.pin()
            except Exception:
                pass

        release(view)
        return True

    async def send_pending_alerts(self):
        channel = self.get_alert_channel()

        if channel is None:
            return

        for error_id in await asyncio.to_thread(tracker.pending_alerts, 5):
            err = await asyncio.to_thread(tracker.get_error, error_id)

            if not err:
                continue

            ping = f"<@{min(DEV_USER_IDS)}>" if DEV_USER_IDS else None

            view = self.error_view(err)

            message = await channel.send(
                content=f"🚨 New error {ping}" if ping else "🚨 New error",
                embed=self.error_embed(err),
                view=view,
                allowed_mentions=discord.AllowedMentions(users=True)
            )

            release(view)

            tracker.set_alert_message(error_id, channel.id, message.id)

    @tasks.loop(seconds=10)
    async def alert_loop(self):
        try:
            await self.send_pending_alerts()
        except Exception as e:
            self._throttled_log('alerts', f"Dev panel alert error: {e}", 900)

    @tasks.loop(seconds=60)
    async def panel_loop(self):
        try:
            await self.update_panel()

            #  Housekeeping once in a while
            if int(time.time() // PANEL_REFRESH_SECONDS) % 60 == 0:
                await asyncio.to_thread(tracker.prune)

        except Exception as e:
            self._throttled_log('panel', f"Dev panel update error: {e}", 1800)

    @alert_loop.before_loop
    async def before_alert_loop(self):
        await self.bot.wait_until_ready()

    @panel_loop.before_loop
    async def before_panel_loop(self):
        await self.bot.wait_until_ready()

    # ------------------------------------------------
    #  Statistics listeners
    # ------------------------------------------------

    @commands.Cog.listener()
    async def on_app_command_completion(self, interaction, command):
        tracker.record_command(
            getattr(command, 'name', 'unknown'),
            getattr(interaction, 'guild_id', None),
            interaction.user.id
        )

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        tracker.record_guild_event(guild.id, 'join')

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        tracker.record_guild_event(guild.id, 'leave')

    # ------------------------------------------------
    #  Button handling
    # ------------------------------------------------

    async def reply(self, interaction, **kwargs):
        kwargs.setdefault('ephemeral', True)

        if interaction.response.is_done():
            await interaction.followup.send(**kwargs)
        else:
            await interaction.response.send_message(**kwargs)

    @commands.Cog.listener()
    async def on_interaction(self, interaction):
        try:
            if interaction.type != discord.InteractionType.component:
                return

            custom_id = (interaction.data or {}).get('custom_id', '')

            if not custom_id.startswith('dev:'):
                return

            if not self.is_dev(interaction):
                await interaction.response.send_message(
                    "❌ Developer only.", ephemeral=True
                )
                return

            parts = custom_id.split(':')
            action = parts[1]

            if action == 'refresh':
                await interaction.response.defer()
                await self.update_panel()

            elif action == 'errors':
                await interaction.response.send_message(
                    embed=await self.errors_embed(), ephemeral=True
                )

            elif action == 'errdetail':
                await interaction.response.send_modal(ErrorIdModal(self))

            elif action == 'servers':
                await interaction.response.send_message(
                    embed=self.servers_embed(), ephemeral=True
                )

            elif action == 'inspect':
                await interaction.response.send_modal(
                    ServerIdModal(self, "Inspect a server", 'inspect')
                )

            elif action == 'sendnow':
                await interaction.response.send_modal(
                    ServerIdModal(self, "Send a verse now", 'sendnow')
                )

            elif action == 'remove':
                await interaction.response.send_modal(
                    ServerIdModal(self, "Remove a server's setup", 'remove')
                )

            elif action == 'config':
                await interaction.response.send_modal(ConfigModal(self))

            elif action == 'err':
                await self.handle_error_button(interaction, parts[2], to_int(parts[3]))

            elif action == 'rm':
                await self.handle_remove_confirm(interaction, parts[2], to_int(parts[3]) if len(parts) > 3 else None)

        except Exception as e:
            log_error(f"Dev panel interaction error: {e}", interaction=interaction)

            try:
                await self.reply(interaction, content="❌ Something went wrong in the dev panel.")
            except Exception:
                pass

    async def handle_error_button(self, interaction, status, error_id):
        if not tracker.set_error_status(error_id, status, interaction.user.id):
            await interaction.response.send_message(
                "❌ That error no longer exists.", ephemeral=True
            )
            return

        tracker.log_dev_action(
            interaction.user.id, f"error_{status}", None, f"error #{error_id}"
        )

        err = await asyncio.to_thread(tracker.get_error, error_id)

        view = self.error_view(err)

        await interaction.response.edit_message(
            content=None,
            embed=self.error_embed(err),
            view=view
        )

        release(view)

        #  Keep the panel's "awaiting review" count in step
        try:
            await self.update_panel()
        except Exception:
            pass

    async def show_error_details(self, interaction, raw_id):
        error_id = to_int(raw_id)
        err = await asyncio.to_thread(tracker.get_error, error_id) if error_id else None

        if not err:
            await interaction.response.send_message(
                "❌ No error with that number.", ephemeral=True
            )
            return

        view = self.error_view(err)

        await interaction.response.send_message(
            embed=self.error_embed(err),
            view=view,
            ephemeral=True
        )

        release(view)

    # ------------------------------------------------
    #  Server control actions
    # ------------------------------------------------

    async def handle_server_action(self, interaction, action, raw_server_id):
        server_id = to_int(raw_server_id)

        if not server_id:
            await interaction.response.send_message(
                "❌ That is not a valid server ID.", ephemeral=True
            )
            return

        if action == 'inspect':
            await interaction.response.send_message(
                embed=self.inspect_embed(server_id), ephemeral=True
            )

        elif action == 'sendnow':
            await self.send_now(interaction, server_id)

        elif action == 'remove':
            await self.ask_remove(interaction, server_id)

    async def send_now(self, interaction, server_id):
        verse_cog = self.bot.get_cog('VerseCog')

        if not verse_cog:
            await interaction.response.send_message(
                "❌ VerseCog is not loaded.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        #  Works exactly like the first verse of /setup: the verse is sent,
        #  progress moves on, and the next send is one interval from now.
        #  The owner is not DMed about problems caused by a dev test.
        success = await verse_cog.send_verse_to_server(
            server_id, scheduled_time=utcnow(), notify=False
        )

        tracker.log_dev_action(
            interaction.user.id, 'send_verse_now', server_id,
            'success' if success else 'failed'
        )

        console_log(f"Dev {interaction.user} sent a verse now to server {server_id}: {success}")

        if success:
            await interaction.followup.send(
                "✅ Verse sent. Progress advanced and the next send was "
                "rescheduled one interval from now.",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                "❌ The verse could not be sent (not set up, channel missing, "
                "or missing permissions). Use **Inspect server** for details.",
                ephemeral=True
            )

    async def ask_remove(self, interaction, server_id):
        view = discord.ui.View(timeout=120)

        view.add_item(discord.ui.Button(
            label="Yes, remove setup", emoji='🗑️',
            style=discord.ButtonStyle.danger,
            custom_id=f"dev:rm:yes:{server_id}"
        ))
        view.add_item(discord.ui.Button(
            label="Cancel", style=discord.ButtonStyle.secondary,
            custom_id="dev:rm:no:0"
        ))

        guild = self.bot.get_guild(server_id)

        await interaction.response.send_message(
            f"⚠️ Remove the bot setup for **{guild.name if guild else server_id}** "
            f"(`{server_id}`)? Their verse progress and settings are deleted.",
            view=view,
            ephemeral=True
        )

        release(view)

    async def handle_remove_confirm(self, interaction, answer, server_id):
        if answer != 'yes' or not server_id:
            await interaction.response.edit_message(
                content="✅ Cancelled. Nothing was changed.", view=None
            )
            return

        conn = db_connect()

        try:
            cursor = conn.execute(
                'DELETE FROM server_settings WHERE server_id = ?', (server_id,)
            )
            conn.commit()
            removed = cursor.rowcount
        finally:
            conn.close()

        clear_owner_notices(server_id)

        tracker.log_dev_action(
            interaction.user.id, 'remove_setup', server_id,
            'removed' if removed else 'nothing to remove'
        )

        console_log(f"Dev {interaction.user} removed setup of server {server_id}")

        await interaction.response.edit_message(
            content=(
                f"✅ Setup removed for `{server_id}`."
                if removed else f"ℹ️ `{server_id}` had no setup."
            ),
            view=None
        )

        try:
            await self.update_panel()
        except Exception:
            pass

    async def apply_config(self, interaction, raw_server, raw_channel, raw_interval, raw_role, raw_verse):
        server_id = to_int(raw_server)
        guild = self.bot.get_guild(server_id) if server_id else None

        if not guild:
            await interaction.response.send_message(
                "❌ The bot is not in a server with that ID.", ephemeral=True
            )
            return

        verse_cog = self.bot.get_cog('VerseCog')
        warnings = []
        changes = {}

        #  --- validate every field that was filled in ---
        try:
            if raw_channel.strip():
                channel_id = to_int(raw_channel)
                channel = guild.get_channel(channel_id) if channel_id else None

                if not isinstance(channel, discord.TextChannel):
                    raise ValueError("That channel ID is not a text channel in that server.")

                if not bot_can_post(self.bot, channel):
                    warnings.append(
                        f"⚠️ I lack View/Send/Embed permission in {channel.mention} - saved anyway."
                    )

                changes['channel_id'] = channel.id

            if raw_interval.strip():
                changes['time_interval'] = parse_interval(raw_interval)

            if raw_role.strip():
                if raw_role.strip().lower() in ('0', 'none', 'clear', '-'):
                    changes['role_id'] = None
                else:
                    role_id = to_int(raw_role)
                    role = guild.get_role(role_id) if role_id else None

                    if not role:
                        raise ValueError("That role ID does not exist in that server.")

                    if role.is_default() or role.managed:
                        raise ValueError("That role cannot be used (@everyone / managed).")

                    changes['role_id'] = role.id

            if raw_verse.strip():
                reference = raw_verse.strip().replace(':', '|')

                if not verse_cog or reference not in verse_cog.verse_index:
                    raise ValueError("That verse does not exist. Use the form `surah|verse`, e.g. `2|255`.")

                changes['current_verse'] = reference

        except ValueError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
            return

        if not changes:
            await interaction.response.send_message(
                "ℹ️ Nothing to change - fill in at least one field.", ephemeral=True
            )
            return

        #  --- save to the database, like any normal setup ---
        conn = db_connect()

        try:
            existing = conn.execute(
                'SELECT 1 FROM server_settings WHERE server_id = ?', (server_id,)
            ).fetchone()

            if existing:
                columns = ', '.join(f"{name} = ?" for name in changes)

                conn.execute(
                    f'UPDATE server_settings SET {columns} WHERE server_id = ?',
                    (*changes.values(), server_id)
                )
                created = False

            else:
                if 'channel_id' not in changes or 'time_interval' not in changes:
                    await interaction.response.send_message(
                        "❌ This server is not set up yet - a **channel** and an "
                        "**interval** are both required to create its setup.",
                        ephemeral=True
                    )
                    return

                next_send = utcnow() + timedelta(hours=changes['time_interval'])

                conn.execute(
                    '''INSERT INTO server_settings
                           (server_id, channel_id, time_interval, current_verse,
                            next_send_utc, last_sent_utc, role_id)
                       VALUES (?, ?, ?, ?, ?, NULL, ?)''',
                    (
                        server_id,
                        changes['channel_id'],
                        changes['time_interval'],
                        changes.get('current_verse', '1|1'),
                        next_send.strftime('%Y-%m-%d %H:%M:%S'),
                        changes.get('role_id')
                    )
                )
                created = True

            conn.commit()

        finally:
            conn.close()

        summary = ", ".join(f"{k}={v}" for k, v in changes.items())

        tracker.log_dev_action(
            interaction.user.id,
            'create_setup' if created else 'update_setup',
            server_id, summary
        )

        console_log(
            f"Dev {interaction.user} {'created' if created else 'updated'} "
            f"setup of server {server_id}: {summary}"
        )

        embed = self.inspect_embed(server_id)
        embed.title = f"{'✅ Setup created' if created else '✅ Settings updated'} - {guild.name}"

        if warnings:
            embed.add_field(name="Warnings", value="\n".join(warnings), inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

        try:
            await self.update_panel()
        except Exception:
            pass


async def setup(bot):
    await bot.add_cog(DevPanelCog(bot))
