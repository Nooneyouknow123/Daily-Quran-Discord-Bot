import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta

from utils import console_log, log_error, db_connect, utcnow

# ----------------------------------------------------

#  When a server's send keeps failing (deleted channel, missing permissions,
#  ...) the scheduler waits longer and longer before trying it again instead
#  of retrying (and logging an error) every single minute.
#  Minutes to wait after the 1st, 2nd, 3rd... consecutive failure.
RETRY_BACKOFF_MINUTES = [1, 2, 5, 15, 30, 60]


class SchedulerCog(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

        #  server_id -> [consecutive_failures, retry_not_before_utc]
        self.retry_state = {}

        self.verse_check.start()

        console_log("Scheduler started - UTC-based system")

    def cog_unload(self):
        self.verse_check.cancel()

        console_log("Scheduler stopped")

    def record_failure(self, server_id, current_utc):
        failures = self.retry_state.get(server_id, [0, None])[0] + 1

        wait = RETRY_BACKOFF_MINUTES[
            min(failures, len(RETRY_BACKOFF_MINUTES)) - 1
        ]

        self.retry_state[server_id] = [
            failures,
            current_utc + timedelta(minutes=wait)
        ]

    def record_success(self, server_id):
        state = self.retry_state.pop(server_id, None)

        if state and state[0] > 1:
            console_log(
                f"Server {server_id} recovered after "
                f"{state[0]} failed attempts"
            )

    @tasks.loop(minutes=1)
    async def verse_check(self):

        conn = None

        try:
            current_utc = utcnow()

            conn = db_connect()
            c = conn.cursor()

            c.execute(
                '''
                SELECT
                    server_id,
                    channel_id,
                    time_interval,
                    current_verse,
                    next_send_utc
                FROM server_settings
                WHERE next_send_utc <= ?
                ''',
                (
                    current_utc.strftime('%Y-%m-%d %H:%M:%S'),
                )
            )

            servers = c.fetchall()

            conn.close()
            conn = None

            sent_count = 0

            #  Forget backoff data for servers that no longer exist
            due_ids = {row[0] for row in servers}

            for stale_id in list(self.retry_state):
                if stale_id not in due_ids:
                    self.retry_state.pop(stale_id, None)

            for (
                server_id,
                channel_id,
                time_interval,
                current_verse,
                next_send_utc
            ) in servers:

                try:
                    verse_cog = self.bot.get_cog('VerseCog')

                    if not verse_cog:
                        continue

                    #  Still waiting after a recent failure
                    state = self.retry_state.get(server_id)

                    if state and state[1] and current_utc < state[1]:
                        continue

                    scheduled_time = datetime.strptime(
                        next_send_utc,
                        '%Y-%m-%d %H:%M:%S'
                    )

                    interval_duration = timedelta(
                        hours=time_interval
                    )

                    time_late = current_utc - scheduled_time

                    # Number of complete intervals that have passed
                    missed_count = max(
                        0,
                        int(
                            time_late.total_seconds()
                            // interval_duration.total_seconds()
                        )
                    )

                    # Any overdue scheduled time means the bot
                    # is recovering from a missed send.
                    was_down = time_late.total_seconds() > 600

                    sent = await verse_cog.send_verse_to_server(
                        server_id,
                        scheduled_time=scheduled_time,
                        was_down=was_down,
                        missed_count=missed_count
                    )

                    if sent:
                        sent_count += 1
                        self.record_success(server_id)

                        console_log(
                            f"UTC send to server {server_id} - "
                            f"scheduled: {next_send_utc}, "
                            f"current: {current_utc.strftime('%Y-%m-%d %H:%M:%S')}, "
                            f"late: {time_late}, "
                            f"missed: {missed_count}"
                        )

                    else:
                        self.record_failure(server_id, current_utc)

                except Exception as e:
                    #  One broken server must never stop the others
                    self.record_failure(server_id, current_utc)

                    log_error(
                        f"Scheduler error for server {server_id}: {str(e)}"
                    )

            if sent_count > 0:
                console_log(
                    f"Scheduler: Sent {sent_count} verses at "
                    f"UTC {current_utc.strftime('%H:%M:%S')}"
                )

        except Exception as e:

            error_msg = f"Scheduler error: {str(e)}"

            log_error(error_msg)

        finally:
            if conn:
                conn.close()

    @verse_check.before_loop
    async def before_verse_check(self):

        await self.bot.wait_until_ready()

        console_log("UTC Scheduler is now active")


async def setup(bot):
    await bot.add_cog(SchedulerCog(bot))

# ----------------------------------------------------
