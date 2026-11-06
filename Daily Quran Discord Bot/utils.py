# ----------------------------------------------------
# Common helpers used by main.py and all the cogs.
# This isn't a cog, main.py only loads files starting with "cog_".
# ----------------------------------------------------

import logging
import sqlite3
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

DB_PATH = 'quran_bot.db'

# Keep log files from getting too large by rotating them when needed.
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUPS = 3

# ----------------------------------------------------
# Logging
# ----------------------------------------------------

def _make_file_logger(name, filename):
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = RotatingFileHandler(
            filename,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUPS,
            encoding='utf-8'
        )
        handler.setFormatter(logging.Formatter('%(message)s'))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False

    return logger


_console_file = _make_file_logger('quranbot.console', 'console.txt')
_error_file = _make_file_logger('quranbot.errors', 'errors.txt')


def _stamp():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def console_log(message):
    """Print the message in the console and save it to console.txt."""
    line = f"{_stamp()} - {message}"

    try:
        print(line)
    except Exception:
        pass

    try:
        _console_file.info(line)
    except Exception:
        pass


def log_error(error_message, interaction=None, track=True):
    """Print the error and save it to errors.txt.

    Errors are also sent to the tracker for the dev panel.
    Pass the interaction when available so the command, server and user
    IDs can be saved. Use track=False to skip error tracking.
    """
    line = f"{_stamp()} - {error_message}"

    try:
        print(f"{_stamp()} - ERROR: {error_message}")
    except Exception:
        pass

    try:
        _error_file.info(line)
    except Exception:
        pass

    if track:
        try:
            import tracker  # Keep this import here to avoid circular imports.
            tracker.record_error(error_message, interaction=interaction)
        except Exception:
            pass


# ----------------------------------------------------
# Time
# ----------------------------------------------------

def utcnow():
    """Get the current UTC time without timezone info, as used by the database."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ----------------------------------------------------
# Database
# ----------------------------------------------------

def db_connect():
    """Connect to the bot database with a timeout to avoid database lock errors."""
    return sqlite3.connect(DB_PATH, timeout=30)


def init_db():
    """Create the required tables and add role_id if an older database is missing it."""
    conn = None

    try:
        conn = db_connect()
        c = conn.cursor()

        c.execute('''
            CREATE TABLE IF NOT EXISTS server_settings (
                server_id INTEGER PRIMARY KEY,
                channel_id INTEGER,
                time_interval REAL,
                current_verse TEXT,
                next_send_utc TIMESTAMP,
                last_sent_utc TIMESTAMP,
                role_id INTEGER
            )
        ''')

        # Keep track of which errors the server owner has already been notified about.
        # This stops the bot from sending the same notice repeatedly.
        c.execute('''
            CREATE TABLE IF NOT EXISTS owner_notices (
                server_id INTEGER,
                error_type TEXT,
                notified_utc TIMESTAMP,
                PRIMARY KEY (server_id, error_type)
            )
        ''')

        c.execute("PRAGMA table_info(server_settings)")
        columns = [row[1] for row in c.fetchall()]

        if "role_id" not in columns:
            c.execute("ALTER TABLE server_settings ADD COLUMN role_id INTEGER")
            console_log("Added role_id column to server_settings")

        conn.commit()
        return True

    except Exception as e:
        log_error(f"Database setup error: {e}")
        return False

    finally:
        if conn:
            conn.close()


def claim_owner_notice(server_id, error_type):
    """Save an owner notice so the same problem isn't reported twice.
    Returns True if this is the first notice, otherwise False."""
    conn = None

    try:
        conn = db_connect()
        c = conn.cursor()

        c.execute(
            '''
            INSERT OR IGNORE INTO owner_notices
                (server_id, error_type, notified_utc)
            VALUES (?, ?, ?)
            ''',
            (
                server_id,
                error_type,
                utcnow().strftime('%Y-%m-%d %H:%M:%S')
            )
        )

        conn.commit()
        return c.rowcount == 1

    except Exception as e:
        log_error(f"Owner notice database error: {e}")
        return False

    finally:
        if conn:
            conn.close()


def clear_owner_notices(server_id):
    """Clear the saved notices for a server owner."""
    conn = None

    try:
        conn = db_connect()
        conn.execute(
            'DELETE FROM owner_notices WHERE server_id = ?',
            (server_id,)
        )
        conn.commit()

    except Exception as e:
        log_error(f"Owner notice cleanup error: {e}")

    finally:
        if conn:
            conn.close()


# ----------------------------------------------------
# Permissions
# ----------------------------------------------------

def is_admin(interaction):
    """Check if the user has Administrator permissions in the server."""
    user = interaction.user
    perms = getattr(user, 'guild_permissions', None)
    return bool(perms and perms.administrator)


def bot_can_post(bot, channel):
    """Check if the bot can view the channel, send messages and embed links."""
    bot_member = channel.guild.get_member(bot.user.id)

    if not bot_member:
        return False

    permissions = channel.permissions_for(bot_member)

    return bool(
        permissions.view_channel
        and permissions.send_messages
        and permissions.embed_links
    )


# ----------------------------------------------------
# Uptime
# ----------------------------------------------------

def format_uptime(started_utc):
    """Format uptime like '2d 3h 14m 5s'."""
    total = max(0, int((utcnow() - started_utc).total_seconds()))

    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, seconds = divmod(rest, 60)

    parts = []

    if days:
        parts.append(f"{days}d")
    if days or hours:
        parts.append(f"{hours}h")
    if days or hours or minutes:
        parts.append(f"{minutes}m")

    parts.append(f"{seconds}s")

    return " ".join(parts)


# ----------------------------------------------------
# Time intervals (30m, 2h, etc.)
# ----------------------------------------------------

def parse_interval(time_str):
    """Convert an interval like '30m' or '2h' into hours."""
    import re

    if not time_str or not time_str.strip():
        raise ValueError("Please provide a time interval.")

    time_str = time_str.lower().strip().replace(' ', '')

    match = re.match(r'^(\d+)([mh])$', time_str)

    if not match:
        raise ValueError(
            "Invalid format. Use something like: 30m, 2h, 90m."
        )

    number, unit = match.groups()
    number = int(number)

    if unit == 'h':
        hours = number
    else:
        hours = number / 60.0

    if hours < (5 / 60):
        raise ValueError("Time interval must be at least 5 minutes.")

    if hours > 168:
        raise ValueError("Time interval cannot be more than 1 week.")

    return hours


def format_interval_hours(hours):
    """Convert hours into readable text, like '24.0 hours' or '30 minutes'."""
    if hours >= 1:
        return f"{hours:.1f} hour{'s' if hours != 1 else ''}"

    minutes = hours * 60
    return f"{minutes:.0f} minute{'s' if minutes != 1 else ''}"
