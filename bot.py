import asyncio
import html
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update
from telegram.constants import ChatType, ParseMode
from telegram.error import BadRequest, Forbidden, RetryAfter
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DB_FILE = os.getenv("DB_FILE", "bot.db")
BROADCAST_DELAY = float(os.getenv("BROADCAST_DELAY", "0.05"))
USER_COOLDOWN = float(os.getenv("USER_COOLDOWN", "1.0"))
USERS_PAGE_SIZE = int(os.getenv("USERS_PAGE_SIZE", "20"))
PORT = int(os.getenv("PORT", "10000"))

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("telegram-bot")

db_lock = asyncio.Lock()
cooldowns: dict[int, float] = {}


# --------------------------------------------------------------------------
# Dummy HTTP server (Render Web Service requires an open port to stay alive)
# --------------------------------------------------------------------------

class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is running.")

    def log_message(self, format, *args):
        pass  # silencio: huwag i-spam ang logs ng bawat health check hit


def start_health_server() -> None:
    server = HTTPServer(("0.0.0.0", PORT), _HealthHandler)
    log.info("Health check server listening on port %s", PORT)
    server.serve_forever()




# --------------------------------------------------------------------------
# Database helpers
# --------------------------------------------------------------------------

def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            banned INTEGER NOT NULL DEFAULT 0,
            message_count INTEGER NOT NULL DEFAULT 0
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS message_map (
            admin_message_id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_users_banned ON users(banned)")
    conn.commit()
    conn.close()


async def register_user(user) -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with db_lock:
        conn = connect_db()
        conn.execute("""
            INSERT INTO users(user_id, username, full_name, first_seen, last_seen, banned)
            VALUES (?, ?, ?, ?, ?, 0)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                full_name=excluded.full_name,
                last_seen=excluded.last_seen
        """, (user.id, user.username, user.full_name, now))
        conn.commit()
        conn.close()


async def bump_message_count(user_id: int) -> None:
    async with db_lock:
        conn = connect_db()
        conn.execute(
            "UPDATE users SET message_count = message_count + 1 WHERE user_id=?",
            (user_id,),
        )
        conn.commit()
        conn.close()


async def is_banned(user_id: int) -> bool:
    async with db_lock:
        conn = connect_db()
        row = conn.execute(
            "SELECT banned FROM users WHERE user_id=?", (user_id,)
        ).fetchone()
        conn.close()
    return bool(row and row[0])


async def map_admin_message(admin_message_id: int, user_id: int) -> None:
    async with db_lock:
        conn = connect_db()
        conn.execute(
            "INSERT OR REPLACE INTO message_map(admin_message_id,user_id) VALUES (?,?)",
            (admin_message_id, user_id),
        )
        conn.commit()
        conn.close()


async def mapped_user(admin_message_id: int) -> int | None:
    async with db_lock:
        conn = connect_db()
        row = conn.execute(
            "SELECT user_id FROM message_map WHERE admin_message_id=?",
            (admin_message_id,),
        ).fetchone()
        conn.close()
    return row[0] if row else None


async def all_users() -> list[int]:
    async with db_lock:
        conn = connect_db()
        rows = conn.execute(
            "SELECT user_id FROM users WHERE banned=0"
        ).fetchall()
        conn.close()
    return [r[0] for r in rows]


async def list_users_page(offset: int, limit: int):
    async with db_lock:
        conn = connect_db()
        rows = conn.execute(
            """SELECT user_id, username, full_name, banned, message_count
               FROM users ORDER BY last_seen DESC LIMIT ? OFFSET ?""",
            (limit, offset),
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        conn.close()
    return rows, total


async def set_banned(user_id: int, value: bool) -> None:
    async with db_lock:
        conn = connect_db()
        conn.execute(
            "INSERT INTO users(user_id,username,full_name,first_seen,last_seen,banned) "
            "VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET banned=excluded.banned",
            (
                user_id, None, None,
                datetime.now(timezone.utc).isoformat(),
                datetime.now(timezone.utc).isoformat(),
                int(value),
            ),
        )
        conn.commit()
        conn.close()


async def user_stats():
    async with db_lock:
        conn = connect_db()
        total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        active = conn.execute("SELECT COUNT(*) FROM users WHERE banned=0").fetchone()[0]
        banned = conn.execute("SELECT COUNT(*) FROM users WHERE banned=1").fetchone()[0]
        messages = conn.execute("SELECT COALESCE(SUM(message_count),0) FROM users").fetchone()[0]
        conn.close()
    return total, active, banned, messages


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def admin_only(update: Update) -> bool:
    return bool(
        update.effective_user
        and update.effective_user.id == ADMIN_ID
        and update.effective_chat
        and update.effective_chat.type == ChatType.PRIVATE
    )


def greeting_name(user) -> str:
    if user.full_name:
        return user.full_name
    if user.username:
        return f"@{user.username}"
    return "Pre"


# --------------------------------------------------------------------------
# User-facing handlers
# --------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user:
        return
    await register_user(update.effective_user)
    name = html.escape(greeting_name(update.effective_user))
    await update.message.reply_text(
        f"👋 <b>Penge kiss, {name}!</b>\n\n"
        "Ipadala mo lang ang mensahe, larawan, video, o file mo dito "
        "at direktang mararating ito ng admin. Sasagutin ka rin dito.\n\n"
        "Gamitin ang /help kung kailangan mo ng tulong.",
        parse_mode=ParseMode.HTML,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user:
        await register_user(update.effective_user)
    await update.message.reply_text(
        "ℹ️ Puwede kang magpadala ng kahit anong klase ng file dito — "
        "text, larawan, video, .apk, .txt, .so, .zip, o kahit anong extension — "
        "at direkta itong ipapasa sa admin.\n\n"
        "Antabayanan mo lang ang balik-tugon dito rin sa chat na ito."
    )


async def receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user = update.effective_user
    if not message or not user or user.id == ADMIN_ID:
        return

    await register_user(user)
    if await is_banned(user.id):
        return

    now = time.monotonic()
    previous = cooldowns.get(user.id, 0)
    if now - previous < USER_COOLDOWN:
        return
    cooldowns[user.id] = now

    await bump_message_count(user.id)

    username = f"@{user.username}" if user.username else "Walang username"
    file_line = ""
    doc = message.document
    if doc:
        size_kb = (doc.file_size or 0) / 1024
        size_text = f"{size_kb / 1024:.2f} MB" if size_kb >= 1024 else f"{size_kb:.1f} KB"
        file_name = doc.file_name or "(walang pangalan)"
        file_line = (
            f"📎 File: {html.escape(file_name)}\n"
            f"📦 Laki: {size_text}\n"
        )

    info = await context.bot.send_message(
        ADMIN_ID,
        "📩 <b>BAGONG MENSAHE</b>\n\n"
        f"👤 Pangalan: {html.escape(user.full_name)}\n"
        f"🔹 Username: {html.escape(username)}\n"
        f"🆔 User ID: <code>{user.id}</code>\n"
        f"💬 Chat ID: <code>{update.effective_chat.id}</code>\n"
        f"{file_line}",
        parse_mode=ParseMode.HTML,
    )
    await map_admin_message(info.message_id, user.id)

    try:
        forwarded = await message.forward(ADMIN_ID)
        await map_admin_message(forwarded.message_id, user.id)
    except Exception:
        log.exception("Could not forward message from %s", user.id)

    await message.reply_text("✅ Naipadala na sa admin. Salamat!")


# --------------------------------------------------------------------------
# Admin handlers
# --------------------------------------------------------------------------

async def admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update) or not update.message.reply_to_message:
        return

    target = await mapped_user(update.message.reply_to_message.message_id)
    if not target:
        await update.message.reply_text(
            "❌ Hindi mahanap kung sino ang dapat sagutin. "
            "I-reply lang ang orihinal na forwarded na mensahe."
        )
        return

    try:
        await context.bot.copy_message(
            chat_id=target,
            from_chat_id=ADMIN_ID,
            message_id=update.message.message_id,
        )
        await update.message.reply_text("✅ Naipadala ang sagot.")
    except Forbidden:
        await update.message.reply_text(
            "❌ Hindi naabot ang user (posibleng na-block ka na niya)."
        )
    except BadRequest as e:
        await update.message.reply_text(f"❌ Hindi napadala: {html.escape(str(e))}")
    except Exception:
        log.exception("Admin reply failed")
        await update.message.reply_text("❌ May naganap na error sa pagpapadala.")


async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update):
        return

    page = 0
    if context.args:
        try:
            page = max(0, int(context.args[0]) - 1)
        except ValueError:
            pass

    offset = page * USERS_PAGE_SIZE
    rows, total = await list_users_page(offset, USERS_PAGE_SIZE)

    if not rows:
        await update.message.reply_text("Wala pang user na naitala.")
        return

    lines = [f"👥 <b>Users</b> (page {page + 1}, total {total})\n"]
    for user_id, username, full_name, banned, msg_count in rows:
        tag = f"@{username}" if username else "—"
        name = full_name or "—"
        status = "🚫" if banned else "✅"
        lines.append(
            f"{status} <code>{user_id}</code> · {html.escape(name)} ({html.escape(tag)}) · {msg_count} msg"
        )

    max_page = (total - 1) // USERS_PAGE_SIZE
    if page < max_page:
        lines.append(f"\nGamitin ang /users {page + 2} para sa susunod na page.")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update):
        return
    total, active, banned, messages = await user_stats()
    await update.message.reply_text(
        "📊 <b>BOT STATS</b>\n\n"
        f"Users: <b>{total}</b>\n"
        f"Puwedeng padalhan ng broadcast: <b>{active}</b>\n"
        f"Banned: <b>{banned}</b>\n"
        f"Kabuuang mensaheng natanggap: <b>{messages}</b>",
        parse_mode=ParseMode.HTML,
    )


async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update):
        return
    if not context.args:
        await update.message.reply_text("Paggamit: /ban USER_ID")
        return
    try:
        user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Paggamit: /ban USER_ID")
        return

    if user_id == ADMIN_ID:
        await update.message.reply_text("❌ Hindi mo puwedeng i-ban ang sarili mo.")
        return

    await set_banned(user_id, True)
    await update.message.reply_text(f"🚫 Na-ban: <code>{user_id}</code>", parse_mode=ParseMode.HTML)


async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update):
        return
    if not context.args:
        await update.message.reply_text("Paggamit: /unban USER_ID")
        return
    try:
        user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Paggamit: /unban USER_ID")
        return

    await set_banned(user_id, False)
    await update.message.reply_text(f"✅ Na-unban: <code>{user_id}</code>", parse_mode=ParseMode.HTML)


async def broadcast_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update):
        return
    if not context.args:
        await update.message.reply_text(
            "Paggamit: /broadcast mensahe mo dito\n"
            "Para sa media: ipadala muna ito dito, tapos i-reply ito ng /broadcast"
        )
        return

    text = " ".join(context.args)
    await _run_broadcast(update, context, sender=lambda uid: context.bot.send_message(uid, text))


async def broadcast_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update) or not update.message.reply_to_message:
        return

    source = update.message.reply_to_message
    await _run_broadcast(
        update,
        context,
        sender=lambda uid: context.bot.copy_message(
            chat_id=uid, from_chat_id=ADMIN_ID, message_id=source.message_id
        ),
    )


async def _run_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE, *, sender):
    users = await all_users()
    status = await update.message.reply_text(
        f"📢 Bino-broadcast sa {len(users)} users..."
    )

    success = failed = 0
    for user_id in users:
        try:
            await sender(user_id)
            success += 1
            await asyncio.sleep(BROADCAST_DELAY)
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after + 0.5)
            try:
                await sender(user_id)
                success += 1
            except Exception:
                failed += 1
        except (Forbidden, BadRequest):
            failed += 1
        except Exception:
            failed += 1
            log.exception("Broadcast failed for %s", user_id)

    await status.edit_text(
        "📢 <b>TAPOS NA ANG BROADCAST</b>\n\n"
        f"✅ Naipadala: {success}\n"
        f"❌ Hindi naipadala: {failed}",
        parse_mode=ParseMode.HTML,
    )


async def admin_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update):
        return
    await update.message.reply_text(
        "🛠 <b>ADMIN COMMANDS</b>\n\n"
        "/users [page] - listahan ng users\n"
        "/stats - istatistika ng bot\n"
        "/broadcast TEXT - text broadcast\n"
        "/ban USER_ID - i-ban ang user\n"
        "/unban USER_ID - alisin ang ban\n\n"
        "💬 I-reply ang isang forwarded na mensahe ng user para sagutin siya.\n"
        "📢 Ipadala ang media dito, tapos i-reply ito ng /broadcast para i-broadcast.",
        parse_mode=ParseMode.HTML,
    )


# --------------------------------------------------------------------------
# Error handling & startup
# --------------------------------------------------------------------------

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    if isinstance(context.error, RetryAfter):
        log.warning("Telegram rate limit: retry after %s seconds", context.error.retry_after)
    else:
        log.exception("Unhandled error", exc_info=context.error)


async def post_init(application: Application):
    me = await application.bot.get_me()
    log.info("Logged in as @%s", me.username)
    if ADMIN_ID:
        try:
            await application.bot.send_message(ADMIN_ID, "🟢 Online na ang bot.")
        except Exception:
            log.warning("Could not notify admin on startup (has the admin started the bot yet?)")


def main():
    if not BOT_TOKEN:
        raise RuntimeError("Kulang ang BOT_TOKEN environment variable.")
    if not ADMIN_ID:
        raise RuntimeError("Kulang o mali ang ADMIN_ID environment variable.")

    init_db()

    threading.Thread(target=start_health_server, daemon=True).start()

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))

    app.add_handler(CommandHandler("users", users_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("ban", ban_command))
    app.add_handler(CommandHandler("unban", unban_command))
    app.add_handler(CommandHandler("admin", admin_help))

    # /broadcast as a command, including media broadcast when replying.
    app.add_handler(
        MessageHandler(
            filters.Chat(ADMIN_ID) & filters.REPLY & filters.COMMAND,
            broadcast_media,
        ),
        group=0,
    )
    app.add_handler(CommandHandler("broadcast", broadcast_text, filters=filters.Chat(ADMIN_ID)))

    # Admin replies to forwarded user messages.
    app.add_handler(
        MessageHandler(
            filters.Chat(ADMIN_ID) & filters.REPLY & ~filters.COMMAND,
            admin_reply,
        ),
        group=1,
    )

    # All non-command user content.
    app.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND & ~filters.Chat(ADMIN_ID),
            receive,
        ),
        group=2,
    )

    app.add_error_handler(error_handler)

    log.info("Bot polling started.")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
    )


if __name__ == "__main__":
    main()
