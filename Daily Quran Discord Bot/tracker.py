# ----------------------------------------------------
# Stats and error tracking storage for the dev panel.
# This isn't a cog, main.py only loads files starting with "cog_".
#
# Uses the same quran_bot.db as the rest of the bot.
# Errors here shouldn't affect the bot. If tracking fails,
# the bot should still keep running normally.
# ----------------------------------------------------

import os
import re
from datetime import timedelta

import utils
from utils import db_connect, utcnow, DB_PATH

TS = '%Y-%m-%d %H:%M:%S'

# Delete raw events older than this. All-time totals are stored separately,
# so deleting old events won't affect the overall counts.
EVENT_RETENTION_DAYS = 14

STATUSES = ('new', 'read', 'minor', 'serious')

_ready = False


def _ts(dt):
    return dt.strftime(TS)


def _quiet_error(message):
    """Log tracker errors to the files without triggering tracking again."""
    try:
        utils.log_error(message, track=False)
    except Exception:
        pass

# ----------------------------------------------------
# Database tables
# ----------------------------------------------------

def ensure_tables():
    global _ready

    if _ready:
        return

    conn = db_connect()

    try:
        c = conn.cursor()

        c.execute('''
            CREATE TABLE IF NOT EXISTS error_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signature TEXT UNIQUE,
                message TEXT,
                source TEXT,
                command TEXT,
                status TEXT DEFAULT 'new',
                count_total INTEGER DEFAULT 0,
                first_seen TEXT,
                last_seen TEXT,
                last_server_id INTEGER,
                last_user_id INTEGER,
                alert_channel_id INTEGER,
                alert_message_id INTEGER,
                reviewed_by INTEGER,
                reviewed_utc TEXT
            )
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS error_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                error_id INTEGER,
                occurred_utc TEXT,
                server_id INTEGER,
                user_id INTEGER
            )
        ''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_error_events_err ON error_events (error_id, occurred_utc)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_error_events_time ON error_events (occurred_utc)')

        c.execute('''
            CREATE TABLE IF NOT EXISTS verse_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id INTEGER,
                sent_utc TEXT
            )
        ''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_verse_events_time ON verse_events (sent_utc)')

        c.execute('''
            CREATE TABLE IF NOT EXISTS command_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                command TEXT,
                server_id INTEGER,
                user_id INTEGER,
                used_utc TEXT
            )
        ''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_command_events_time ON command_events (used_utc)')

        c.execute('''
            CREATE TABLE IF NOT EXISTS guild_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                event TEXT,
                event_utc TEXT
            )
        ''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_guild_events_time ON guild_events (event_utc)')

        c.execute('''
            CREATE TABLE IF NOT EXISTS bot_state (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS dev_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action_utc TEXT,
                user_id INTEGER,
                action TEXT,
                server_id INTEGER,
                details TEXT
            )
        ''')

        conn.commit()
        _ready = True

    finally:
        conn.close()


def _run(fn, default=None):
    """Run a database operation and return the default if something fails."""
    try:
        ensure_tables()
        conn = db_connect()

        try:
            result = fn(conn.cursor())
            conn.commit()
            return result

        finally:
            conn.close()

    except Exception as e:
        _quiet_error(f"Tracker database error: {e}")
        return default

# ----------------------------------------------------
# State storage (panel message ID, running totals, etc.)
# ----------------------------------------------------

def get_state(key, default=None):
    def op(c):
        row = c.execute('SELECT value FROM bot_state WHERE key = ?', (key,)).fetchone()
        return row[0] if row else default
    return _run(op, default)


def set_state(key, value):
    def op(c):
        c.execute(
            '''INSERT INTO bot_state (key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value''',
            (key, str(value))
        )
    _run(op)


def _incr(c, key, amount=1):
    c.execute(
        '''INSERT INTO bot_state (key, value) VALUES (?, ?)
           ON CONFLICT(key) DO UPDATE SET value = CAST(value AS INTEGER) + ?''',
        (key, str(amount), amount)
    )

# ----------------------------------------------------
# Error tracking
# ----------------------------------------------------

def normalize(message):
    """Normalize error messages so similar errors get grouped together.
    IDs and changing numbers are replaced, but Discord error codes and HTTP
    status codes are kept so different errors don't get mixed up."""
    text = re.sub(r'0x[0-9a-fA-F]+', 'ADDR', str(message))

    def swap(match):
        token = match.group(0)

        if token.startswith('error code') or not token.isdigit():
            return token

        return 'N'

    text = re.sub(r'error code: \d+|\b[45]\d\d\b(?= [A-Z])|\d+', swap, text)
    text = re.sub(r'\s+', ' ', text).strip()

    return text[:300]


def infer_source(message):
    """Detect whether an error came from a command or the system."""
    match = re.search(r'Slash command error in (\w+)', message)

    if match:
        return 'command', match.group(1).lower()

    match = re.match(r'\s*([A-Za-z][\w ]*?) command\b', message)

    if match:
        return 'command', match.group(1).strip().lower().replace(' ', '_')

    return 'system', None


def context_from_interaction(interaction):
    """Get the command, server ID and user ID from an interaction."""
    if interaction is None:
        return None, None, None

    command = getattr(interaction, 'command', None)
    user = getattr(interaction, 'user', None)

    return (
        getattr(command, 'name', None),
        getattr(interaction, 'guild_id', None) or getattr(getattr(interaction, 'guild', None), 'id', None),
        getattr(user, 'id', None)
    )


def record_error(message, source=None, command=None, server_id=None, user_id=None, interaction=None):
    """Save an error occurrence and return its ID."""
    message = str(message)

    ctx_command, ctx_server, ctx_user = context_from_interaction(interaction)
    command = command or ctx_command
    server_id = server_id or ctx_server
    user_id = user_id or ctx_user

    if server_id is None:
        match = re.search(r'server (\d{15,20})', message)

        if match:
            server_id = int(match.group(1))

    inferred_source, inferred_command = infer_source(message)

    if command:
        source = source or 'command'
    else:
        source = source or inferred_source
        command = inferred_command

    signature = normalize(message)
    now = _ts(utcnow())

    def op(c):
        c.execute(
            '''INSERT OR IGNORE INTO error_log
                   (signature, message, source, command, status, count_total,
                    first_seen, last_seen, last_server_id, last_user_id)
               VALUES (?, ?, ?, ?, 'new', 0, ?, ?, ?, ?)''',
            (signature, message[:500], source, command, now, now, server_id, user_id)
        )

        c.execute(
            '''UPDATE error_log
               SET count_total = count_total + 1,
                   last_seen = ?,
                   last_server_id = COALESCE(?, last_server_id),
                   last_user_id = COALESCE(?, last_user_id)
               WHERE signature = ?''',
            (now, server_id, user_id, signature)
        )

        error_id = c.execute(
            'SELECT id FROM error_log WHERE signature = ?', (signature,)
        ).fetchone()[0]

        c.execute(
            '''INSERT INTO error_events (error_id, occurred_utc, server_id, user_id)
               VALUES (?, ?, ?, ?)''',
            (error_id, now, server_id, user_id)
        )

        return error_id

    return _run(op)


_ERROR_COLUMNS = (
    'id', 'message', 'source', 'command', 'status', 'count_total',
    'first_seen', 'last_seen', 'last_server_id', 'last_user_id',
    'alert_channel_id', 'alert_message_id', 'reviewed_by', 'reviewed_utc'
)


def _counts(c, error_id):
    now = utcnow()

    row = c.execute(
        '''SELECT COALESCE(SUM(occurred_utc >= ?), 0),
                  COALESCE(SUM(occurred_utc >= ?), 0)
           FROM error_events WHERE error_id = ?''',
        (_ts(now - timedelta(hours=24)), _ts(now - timedelta(days=7)), error_id)
    ).fetchone()

    return int(row[0]), int(row[1])


def get_error(error_id):
    """Get error details along with its 24h, 7d and all-time counts."""
    def op(c):
        row = c.execute(
            f"SELECT {', '.join(_ERROR_COLUMNS)} FROM error_log WHERE id = ?",
            (error_id,)
        ).fetchone()

        if not row:
            return None

        err = dict(zip(_ERROR_COLUMNS, row))
        err['count_24h'], err['count_7d'] = _counts(c, error_id)
        err['count_all'] = err['count_total']

        now = utcnow()

        err['top_servers'] = c.execute(
            '''SELECT server_id, COUNT(*) FROM error_events
               WHERE error_id = ? AND server_id IS NOT NULL AND occurred_utc >= ?
               GROUP BY server_id ORDER BY COUNT(*) DESC LIMIT 5''',
            (error_id, _ts(now - timedelta(days=7)))
        ).fetchall()

        return err

    return _run(op)


def list_errors(limit=20, active_only=False):
    """Get unique errors, showing new ones and frequently occurring ones first."""
    def op(c):
        now = utcnow()
        since_24h = _ts(now - timedelta(hours=24))
        since_7d = _ts(now - timedelta(days=7))

        rows = c.execute(
            f'''SELECT e.id, e.message, e.source, e.command, e.status,
                       e.count_total, e.last_seen,
                       COALESCE(SUM(ev.occurred_utc >= ?), 0) AS c24,
                       COALESCE(SUM(ev.occurred_utc >= ?), 0) AS c7
                FROM error_log e
                LEFT JOIN error_events ev ON ev.error_id = e.id
                GROUP BY e.id
                {'HAVING c24 > 0' if active_only else ''}
                ORDER BY (e.status = 'new') DESC, c24 DESC, e.last_seen DESC
                LIMIT ?''',
            (since_24h, since_7d, limit)
        ).fetchall()

        keys = ('id', 'message', 'source', 'command', 'status', 'count_all',
                'last_seen', 'count_24h', 'count_7d')

        return [dict(zip(keys, r)) for r in rows]

    return _run(op, [])


def set_error_status(error_id, status, user_id=None):
    if status not in STATUSES:
        return False

    def op(c):
        c.execute(
            '''UPDATE error_log SET status = ?, reviewed_by = ?, reviewed_utc = ?
               WHERE id = ?''',
            (status, user_id, _ts(utcnow()), error_id)
        )
        return c.rowcount == 1

    return _run(op, False)


def pending_alerts(limit=5):
    """Get new errors that haven't been sent to the developer yet."""
    def op(c):
        rows = c.execute(
            '''SELECT id FROM error_log
               WHERE status = 'new' AND alert_message_id IS NULL
               ORDER BY first_seen LIMIT ?''',
            (limit,)
        ).fetchall()

        return [r[0] for r in rows]

    return _run(op, [])


def set_alert_message(error_id, channel_id, message_id):
    def op(c):
        c.execute(
            '''UPDATE error_log SET alert_channel_id = ?, alert_message_id = ?
               WHERE id = ?''',
            (channel_id, message_id, error_id)
        )

    _run(op)


def count_errors_24h():
    """Get total occurrences, unique errors and errors awaiting review."""
    def op(c):
        since = _ts(utcnow() - timedelta(hours=24))

        total, unique = c.execute(
            'SELECT COUNT(*), COUNT(DISTINCT error_id) FROM error_events WHERE occurred_utc >= ?',
            (since,)
        ).fetchone()

        pending = c.execute(
            "SELECT COUNT(*) FROM error_log WHERE status = 'new'"
        ).fetchone()[0]

        return total, unique, pending

    return _run(op, (0, 0, 0))

# ----------------------------------------------------
# Verse, command and server tracking
# ----------------------------------------------------

def record_verse_sent(server_id):
    def op(c):
        c.execute(
            'INSERT INTO verse_events (server_id, sent_utc) VALUES (?, ?)',
            (server_id, _ts(utcnow()))
        )
        _incr(c, 'total_verses_sent')

    _run(op)


def record_command(command, server_id=None, user_id=None):
    def op(c):
        c.execute(
            '''INSERT INTO command_events (command, server_id, user_id, used_utc)
               VALUES (?, ?, ?, ?)''',
            (command, server_id, user_id, _ts(utcnow()))
        )
        _incr(c, 'total_commands')

    _run(op)


def record_guild_event(guild_id, event):
    def op(c):
        c.execute(
            'INSERT INTO guild_events (guild_id, event, event_utc) VALUES (?, ?, ?)',
            (guild_id, event, _ts(utcnow()))
        )

    _run(op)


def log_dev_action(user_id, action, server_id=None, details=None):
    """Keep a record of actions performed through the dev panel."""
    def op(c):
        c.execute(
            '''INSERT INTO dev_actions (action_utc, user_id, action, server_id, details)
               VALUES (?, ?, ?, ?, ?)''',
            (_ts(utcnow()), user_id, action, server_id, (details or '')[:500])
        )

    _run(op)


def prune():
    """Remove old event records without affecting the all-time totals."""
    cutoff = _ts(utcnow() - timedelta(days=EVENT_RETENTION_DAYS))

    def op(c):
        for table, column in (
            ('error_events', 'occurred_utc'),
            ('verse_events', 'sent_utc'),
            ('command_events', 'used_utc'),
            ('guild_events', 'event_utc'),
        ):
            c.execute(f'DELETE FROM {table} WHERE {column} < ?', (cutoff,))

    _run(op)


def collect_stats():
    """Collect all the stats needed by the dev panel."""
    def op(c):
        now = utcnow()
        since = _ts(now - timedelta(hours=24))
        hour_ahead = _ts(now + timedelta(hours=1))

        stats = {}

        stats['verses_24h'] = c.execute(
            'SELECT COUNT(*) FROM verse_events WHERE sent_utc >= ?', (since,)
        ).fetchone()[0]

        row = c.execute("SELECT value FROM bot_state WHERE key = 'total_verses_sent'").fetchone()
        stats['verses_total'] = int(row[0]) if row else 0

        stats['commands_24h'] = c.execute(
            'SELECT COUNT(*) FROM command_events WHERE used_utc >= ?', (since,)
        ).fetchone()[0]

        row = c.execute("SELECT value FROM bot_state WHERE key = 'total_commands'").fetchone()
        stats['commands_total'] = int(row[0]) if row else 0

        stats['top_commands'] = c.execute(
            '''SELECT command, COUNT(*) FROM command_events WHERE used_utc >= ?
               GROUP BY command ORDER BY COUNT(*) DESC LIMIT 3''',
            (since,)
        ).fetchall()

        stats['joins_24h'] = c.execute(
            "SELECT COUNT(*) FROM guild_events WHERE event = 'join' AND event_utc >= ?", (since,)
        ).fetchone()[0]

        stats['leaves_24h'] = c.execute(
            "SELECT COUNT(*) FROM guild_events WHERE event = 'leave' AND event_utc >= ?", (since,)
        ).fetchone()[0]

        stats['setup_ids'] = {
            r[0] for r in c.execute('SELECT server_id FROM server_settings').fetchall()
        }

        stats['top_intervals'] = c.execute(
            '''SELECT time_interval, COUNT(*) FROM server_settings
               GROUP BY time_interval ORDER BY COUNT(*) DESC, time_interval LIMIT 5'''
        ).fetchall()

        stats['due_next_hour'] = c.execute(
            'SELECT COUNT(*) FROM server_settings WHERE next_send_utc <= ?', (hour_ahead,)
        ).fetchone()[0]

        stats['owner_dms_24h'] = c.execute(
            'SELECT COUNT(*) FROM owner_notices WHERE notified_utc >= ?', (since,)
        ).fetchone()[0]

        stats['owner_dms_total'] = c.execute(
            'SELECT COUNT(*) FROM owner_notices'
        ).fetchone()[0]

        return stats

    stats = _run(op, {}) or {}

    try:
        stats['db_size'] = os.path.getsize(DB_PATH)
    except OSError:
        stats['db_size'] = 0

    return stats
