#!/usr/bin/env python3
"""
VotXify - Vote Giveaway Bot (improved edition)

Setup:
    pip install "python-telegram-bot>=22.6"
    export BOT_TOKEN="123456:ABC..."      # or put BOT_TOKEN=... inside a .env file next to this script
    (see .env.example for all variables, incl. OWNER_ID and OWNER_USERNAME)
    python vote.py
"""
import asyncio
import functools
import json
import logging
import os
import random
import shutil
import string
import sys
from datetime import datetime, timezone
from html import escape

from telegram import (
    BotCommand,
    BotCommandScopeChat,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Update,
)
from telegram.constants import ChatMemberStatus
from telegram.error import BadRequest, Forbidden, RetryAfter
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    TypeHandler,
    filters,
)
from telegram.request import HTTPXRequest


# ================= ENV / CONFIG ================= #
def _load_env_file(path=".env"):
    """Tiny .env loader (no extra dependency)."""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()

TOKEN = os.getenv("BOT_TOKEN", "")
BOT_USERNAME = os.getenv("BOT_USERNAME", "VotXify_bot")
OWNER_ID = int(os.getenv("OWNER_ID", "8254637769"))
BOT_NAME = os.getenv("BOT_NAME", "NURROSUL VOTE GIVEAWAY BOT")
OWNER_USERNAME = os.getenv("OWNER_USERNAME", "").lstrip("@").strip()   # used for the OWNER button
OWNER_BUTTON_TEXT = os.getenv("OWNER_BUTTON_TEXT", "OWNER")

# ---- behaviour switches ---- #
ALLOW_SELF_VOTE = False          # can a participant vote for their own entry?
SINGLE_VOTE_PER_GIVEAWAY = False # True = each person gets only ONE vote in the whole giveaway
LEADERBOARD_SIZE = 10            # rows shown in the leaderboard
EDIT_INTERVAL = 1.5              # seconds between channel edits (Telegram flood protection)
MEMBER_CACHE_TTL = 30            # seconds to cache a positive "is member" check
DATA_FILE = "bot_data.json"

# ---- force subscribe ---- #
# Users must join ALL these channels before they can use the bot. Owner can add/remove more with
# /addfsub, /removefsub, /fsublist (saved in the data file). This list is only the first-run default.
DEFAULT_FSUB = [
    {"ref": "@Tysonnn_Giveawayyy", "chat_id": None, "title": "Tysonnn Giveaway", "link": "https://t.me/Tysonnn_Giveawayyy"},
]
FSUB_GATE_VOTES = False  # True = people must also be in the fsub channels to press Vote buttons

# ================= PREMIUM EMOJIS ================= #
EMOJI_VOTE = "5267095979097610740"
EMOJI_JOIN = "6237668294896131350"
EMOJI_CANCEL = "6240245571626475799"
EMOJI_MAIN_MENU = "6240245571626475799"
EMOJI_BACK = "6217402478825049695"
EMOJI_CREATE = "5208891329626521299"
EMOJI_CONNECT = "5244710862953941180"
EMOJI_MANAGE = "6237621548472081271"
EMOJI_ADD_VOTES = "6240003971126139705"
EMOJI_REMOVE_VOTES = "6240003971126139705"
EMOJI_LEADERBOARD = "6240027791014765668"
EMOJI_END_GIVEAWAY = "6240085923397114865"
EMOJI_ADMIN = "6237595159329113605"
EMOJI_BROADCAST = "6237668294896131350"
EMOJI_STATS = "6239790794719370356"
EMOJI_SETTINGS = "6237621548472081271"
EMOJI_USERS = "6237867138997034625"
EMOJI_BACKUP = "6237900592497302202"
EMOJI_CLEAR = "6240152061598504832"
EMOJI_CHANNEL = "6237510794150419802"
EMOJI_NOTIFICATION = "6240073270423462835"
EMOJI_CONFIRM = "6239815031219820750"
EMOJI_REFRESH = "6240085923397114865"
EMOJI_WELCOME = "6332080283176672910"
EMOJI_FIRE = "6334449730734529256"
EMOJI_ARROW = "6332591195306334733"
EMOJI_CHART = "6332186798365612896"
EMOJI_HEART = "6237558987978447573"
EMOJI_ROCKET = "5188481279963715781"
EMOJI_CROWN = "6332246180583447893"
EMOJI_ERROR = "6334723470475139278"
EMOJI_ENDED = "6237572882197650867"
EMOJI_STAR = "6239815031219820750"
EMOJI_ID = "6237547619200014867"
EMOJI_GIFT = "6239894475229895983"
EMOJI_WINE = "6237510794150419802"
EMOJI_SMILE = "6237867138997034625"
EMOJI_LOVE = "6334437167955188087"
EMOJI_LIGHTNING = "6240073270423462835"
EMOJI_POINTER = "6237732706520668707"
EMOJI_ALERT = "6240152061598504832"
EMOJI_CLOWN = "6237900592497302202"
EMOJI_SEARCH = "6239790794719370356"
EMOJI_SPEAKER = "5217968773071401144"
EMOJI_LINK = "5289511602393984968"
EMOJI_CONFETTI = "6240085923397114865"
EMOJI_LOCATION = "6240101054566897479"
EMOJI_RIGHT = "6240295371772271503"
EMOJI_DIAMOND = "6240003971126139705"
EMOJI_CALENDAR = "6240027791014765668"
EMOJI_WINNER = "6332435498446888848"
EMOJI_MONEY_BAG = "6332246180583447893"
EMOJI_CELEBRATE = "6237621707385871360"
EMOJI_INBOX = "6237973405077871246"
EMOJI_LOCK = "6332490478323243268"
EMOJI_SHIELD = "6237595159329113605"

# ================= COLOR STYLES ================= #
BUTTON_STYLE_PRIMARY = "primary"
BUTTON_STYLE_SUCCESS = "success"
BUTTON_STYLE_DANGER = "danger"

# ================= LOGGING ================= #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("votxify")

NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
LINE = "━" * 18

# ================= IN-MEMORY STATE ================= #
giveaways: dict = {}
all_users: dict = {}
channel_history: dict = {}
banned: set = set()
fsub_channels: list = []

user_sessions: dict = {}
admin_sessions: dict = {}

_dirty = False
_member_cache: dict = {}
pending_buttons: dict = {}   # (giveaway_id, uid_str) -> True   (ordered queue of vote-button edits)
board_dirty: set = set()     # giveaway ids whose live board needs refreshing


# ================= HELPERS ================= #
def esc(value) -> str:
    return escape(str(value if value is not None else ""))


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now_utc().isoformat()


def parse_dt(value):
    try:
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def fmt_duration(seconds) -> str:
    seconds = int(max(seconds, 0))
    d, r = divmod(seconds, 86400)
    h, r = divmod(r, 3600)
    m, _ = divmod(r, 60)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m or not parts:
        parts.append(f"{m}m")
    return " ".join(parts[:2])


def time_left(g):
    """Seconds left, or None when the giveaway has no timer."""
    end = parse_dt(g.get("ends_at") or "")
    if not end:
        return None
    return (end - now_utc()).total_seconds()


def is_active(g) -> bool:
    if g.get("ended"):
        return False
    left = time_left(g)
    return left is None or left > 0


def is_owner(user_id) -> bool:
    return user_id == OWNER_ID


def owner_only(fn):
    @functools.wraps(fn)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user or not is_owner(update.effective_user.id):
            if update.message:
                await update.message.reply_text("❌ You are not the owner!")
            return
        return await fn(update, context)
    return wrapper


def can_manage(user_id, g) -> bool:
    return user_id == OWNER_ID or user_id == g.get("creator")


def premium_button(text, callback_data=None, url=None, emoji_id=None, style=None):
    if url:
        return InlineKeyboardButton(text=text, url=url, icon_custom_emoji_id=emoji_id, style=style)
    return InlineKeyboardButton(text=text, callback_data=callback_data, icon_custom_emoji_id=emoji_id, style=style)


def giveaway_link(gid) -> str:
    return f"https://t.me/{BOT_USERNAME}?start={gid}"


def post_link(g, message_id):
    """Deep link to a message inside the giveaway channel."""
    if not message_id:
        return None
    ident = g.get("channel", "")
    if ident.startswith("@"):
        return f"https://t.me/{ident[1:]}/{message_id}"
    cid = str(g.get("channel_id", ""))
    if cid.startswith("-100"):
        return f"https://t.me/c/{cid[4:]}/{message_id}"
    return None


# ================= STORAGE ================= #
def normalize_giveaway(g: dict) -> dict:
    """Make sure old / half-broken records have the new structure (all ids are str keys)."""
    g["users"] = {str(k): v for k, v in g.get("users", {}).items()}
    g["vote_counts"] = {str(k): int(v) for k, v in g.get("vote_counts", {}).items()}
    voted = {}
    for k, v in g.get("voted_users", {}).items():
        voted[str(k)] = sorted({int(x) for x in (v or [])})
    g["voted_users"] = voted
    g.setdefault("vote_msgs", {})
    g["vote_msgs"] = {str(k): v for k, v in g["vote_msgs"].items()}
    g.setdefault("ends_at", None)
    g.setdefault("board_msg_id", None)
    g.setdefault("ended", False)
    g.setdefault("log", [])
    for uid in g["users"]:
        g["vote_counts"].setdefault(uid, 0)
    return g


def load_data():
    giveaways.clear()
    all_users.clear()
    channel_history.clear()
    banned.clear()
    fsub_channels.clear()
    if not os.path.exists(DATA_FILE):
        fsub_channels.extend(json.loads(json.dumps(DEFAULT_FSUB)))
        return
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        for gid, g in data.get("giveaways", {}).items():
            giveaways[gid] = normalize_giveaway(g)
        all_users.update(data.get("all_users", {}))
        channel_history.update(data.get("channel_history", {}))
        banned.update(int(x) for x in data.get("banned", []))
        if "fsub" in data:
            fsub_channels.extend(data["fsub"])
        else:  # first run after upgrading -> seed with the default channel(s)
            fsub_channels.extend(json.loads(json.dumps(DEFAULT_FSUB)))
        logger.info("Loaded: %d giveaways, %d users", len(giveaways), len(all_users))
    except Exception as e:
        logger.error("Error loading data: %s", e)
        # keep the broken file so nothing is lost
        try:
            shutil.copy(DATA_FILE, f"{DATA_FILE}.corrupt-{int(now_utc().timestamp())}")
        except Exception:
            pass


def flush_data():
    """Atomic write: write to temp file, then replace. A crash can never corrupt the real file."""
    global _dirty
    try:
        payload = {
            "giveaways": giveaways,
            "all_users": all_users,
            "channel_history": channel_history,
            "banned": sorted(banned),
            "fsub": fsub_channels,
            "last_saved": now_iso(),
        }
        tmp = f"{DATA_FILE}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, DATA_FILE)
        _dirty = False
    except Exception as e:
        logger.error("Error saving data: %s", e)


def mark_dirty():
    """Cheap 'please save soon' - the background loop writes the file (no disk write per vote)."""
    global _dirty
    _dirty = True


def save_user(user_id, username, first_name, last_name=None, source=None):
    key = str(user_id)
    if key not in all_users:
        all_users[key] = {
            "user_id": user_id,
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
            "joined_at": now_iso(),
            "last_active": now_iso(),
            "source": source or "unknown",
            "total_votes_given": 0,
            "total_giveaways_joined": 0,
        }
    else:
        all_users[key]["last_active"] = now_iso()
        all_users[key]["first_name"] = first_name
        if username:
            all_users[key]["username"] = username
    mark_dirty()


def update_user_stats(user_id, action):
    u = all_users.get(str(user_id))
    if not u:
        return
    if action == "vote":
        u["total_votes_given"] = u.get("total_votes_given", 0) + 1
    elif action == "join":
        u["total_giveaways_joined"] = u.get("total_giveaways_joined", 0) + 1
    mark_dirty()


def update_channel_history(channel_identifier, channel_display, channel_id, user_id, user_name, action, giveaway_id=None):
    key = str(channel_identifier)
    if key not in channel_history:
        channel_history[key] = {
            "channel_identifier": channel_identifier,
            "channel_display": channel_display,
            "channel_id": channel_id,
            "type": "public" if str(channel_identifier).startswith("@") else "private",
            "total_giveaways": 0,
            "giveaways": [],
            "created_by": user_id,
            "created_by_name": user_name,
            "first_created": now_iso(),
        }
    ch = channel_history[key]
    if action == "create":
        ch["total_giveaways"] += 1
        ch["giveaways"].append({"giveaway_id": giveaway_id, "created_at": now_iso(), "status": "active"})
        ch["last_giveaway"] = now_iso()
    elif action == "end" and giveaway_id:
        for item in ch["giveaways"]:
            if item.get("giveaway_id") == giveaway_id:
                item["status"] = "ended"
                item["ended_at"] = now_iso()
                break
    mark_dirty()


# ================= TELEGRAM HELPERS ================= #
async def send_safe(bot, chat_id, text, **kwargs) -> bool:
    """Send a message; handles flood-wait once. Returns True on success."""
    kwargs.setdefault("parse_mode", "HTML")
    kwargs.setdefault("link_preview_options", NO_PREVIEW)
    for _ in range(2):
        try:
            await bot.send_message(chat_id=chat_id, text=text, **kwargs)
            return True
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
        except Forbidden:
            u = all_users.get(str(chat_id))
            if u is not None:
                u["blocked"] = True
            return False
        except Exception as e:
            logger.warning("send to %s failed: %s", chat_id, e)
            return False
    return False


async def safe_edit(query, text, keyboard=None):
    try:
        await query.edit_message_text(
            text=text,
            parse_mode="HTML",
            reply_markup=keyboard,
            link_preview_options=NO_PREVIEW,
        )
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            raise


async def notify_owner(context, title, message):
    await send_safe(context.bot, OWNER_ID, f"<b>{title}</b>\n\n{message}")


async def is_member(bot, channel_id, user_id, use_cache=True) -> bool:
    key = (channel_id, user_id)
    cached = _member_cache.get(key)
    if use_cache and cached and now_utc().timestamp() - cached < MEMBER_CACHE_TTL:
        return True
    try:
        m = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
        ok = m.status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
        if m.status == ChatMemberStatus.RESTRICTED and getattr(m, "is_member", False):
            ok = True
    except Exception as e:
        logger.warning("membership check failed: %s", e)
        return False
    if ok:
        _member_cache[key] = now_utc().timestamp()
    else:
        _member_cache.pop(key, None)
    return ok


async def get_channel_link(bot, g):
    ident = g.get("channel", "")
    if ident.startswith("@"):
        return f"https://t.me/{ident[1:]}"
    if g.get("invite_link"):
        return g["invite_link"]
    try:
        chat = await bot.get_chat(g["channel_id"])
        link = chat.invite_link
        if not link:
            link = await bot.export_chat_invite_link(g["channel_id"])
        g["invite_link"] = link
        mark_dirty()
        return link
    except Exception as e:
        logger.warning("could not get invite link: %s", e)
        return None


# ================= RANKING / LEADERBOARD ================= #
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


def ranking(g):
    """[(uid, votes, rank)] sorted by votes. Ties share the same rank (join order breaks display ties)."""
    rows = [(uid, g["vote_counts"].get(uid, 0)) for uid in g["users"]]
    rows.sort(key=lambda r: -r[1])
    out, prev_votes, prev_rank = [], None, 0
    for i, (uid, votes) in enumerate(rows, 1):
        rank = prev_rank if votes == prev_votes else i
        out.append((uid, votes, rank))
        prev_votes, prev_rank = votes, rank
    return out


def bar(ratio: float, width: int = 10) -> str:
    filled = max(0, min(width, round(ratio * width)))
    return "█" * filled + "░" * (width - filled)


def build_board(gid, g, viewer=None, limit=LEADERBOARD_SIZE) -> str:
    rows = ranking(g)
    total = sum(v for _, v, _ in rows)
    leader = rows[0][1] if rows else 0

    if g.get("ended"):
        status = "🔴 ENDED"
    else:
        left = time_left(g)
        status = "🟢 LIVE" + (f" • ⏳ {fmt_duration(left)} left" if left is not None else "")

    text = (
        f"<b><tg-emoji emoji-id='{EMOJI_LEADERBOARD}'>🏆</tg-emoji> LEADERBOARD</b>\n"
        f"<code>{LINE}</code>\n"
        f"<b>{status}</b>\n"
        f"📢 {esc(g.get('channel_display', g.get('channel')))}\n"
        f"👥 <b>{len(rows)}</b> players  •  🗳 <b>{total:,}</b> votes\n"
        f"<code>{LINE}</code>\n\n"
    )

    if not rows:
        text += "<i>Nobody has joined yet. Be the first! 🚀</i>\n"
    else:
        for uid, votes, rank in rows[:limit]:
            icon = MEDALS.get(rank, f"<b>{rank}.</b>")
            pct = (votes / total * 100) if total else 0
            ratio = (votes / leader) if leader else 0
            text += (
                f"{icon} <b>{esc(g['users'][uid])}</b>\n"
                f"      <code>{bar(ratio)}</code> <b>{votes:,}</b> votes • {pct:.0f}%\n"
            )
        if len(rows) > limit:
            text += f"\n<i>… and {len(rows) - limit} more players</i>\n"

    if viewer is not None and str(viewer) in g["users"]:
        for uid, votes, rank in rows:
            if uid == str(viewer):
                gap = ""
                if rank > 1 and leader > votes:
                    gap = f" • {leader - votes:,} behind 1st"
                text += f"\n<code>{LINE}</code>\n👤 <b>Your rank:</b> #{rank} • {votes:,} votes{gap}\n"
                break

    text += f"\n<i>🕒 Updated {now_utc().strftime('%H:%M:%S')} UTC</i>"
    return text


def build_winner_text(g) -> str:
    rows = [r for r in ranking(g) if r[2] <= 3]
    if not rows or rows[0][1] == 0:
        return "<i>No votes were cast - no winner this time.</i>"
    text = ""
    for uid, votes, rank in rows:
        text += f"{MEDALS[rank]} <b>{esc(g['users'][uid])}</b> — <b>{votes:,}</b> votes\n"
    firsts = [r for r in rows if r[2] == 1]
    if len(firsts) > 1:
        text += "\n🤝 <i>Tie for 1st place!</i>"
    return text


def rank_of(g, uid_str):
    for uid, votes, rank in ranking(g):
        if uid == uid_str:
            return rank, votes
    return None, 0


# ================= BACKGROUND WORKER ================= #
def queue_button_update(gid, uid_str):
    pending_buttons[(gid, uid_str)] = True
    board_dirty.add(gid)
    mark_dirty()


def vote_keyboard(gid, uid_str, votes):
    return InlineKeyboardMarkup([[
        premium_button(f"Vote - {votes}", callback_data=f"vote_{gid}_{uid_str}", emoji_id=EMOJI_VOTE, style=BUTTON_STYLE_SUCCESS)
    ]])


async def flush_one_button(bot) -> bool:
    if not pending_buttons:
        return False
    key = next(iter(pending_buttons))
    pending_buttons.pop(key, None)
    gid, uid = key
    g = giveaways.get(gid)
    if not g:
        return True
    msg_id = g["vote_msgs"].get(uid)
    if not msg_id:
        return True
    try:
        await bot.edit_message_reply_markup(
            chat_id=g["channel_id"],
            message_id=msg_id,
            reply_markup=vote_keyboard(gid, uid, g["vote_counts"].get(uid, 0)),
        )
    except RetryAfter as e:
        pending_buttons[key] = True
        await asyncio.sleep(e.retry_after + 1)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            logger.warning("button edit failed: %s", e)
    except Exception as e:
        logger.warning("button edit failed: %s", e)
    return True


async def refresh_board(bot, gid):
    g = giveaways.get(gid)
    if not g or not g.get("board_msg_id"):
        return
    kb = None
    if not g.get("ended"):
        kb = InlineKeyboardMarkup([[premium_button("JOIN & VOTE", url=giveaway_link(gid), emoji_id=EMOJI_JOIN, style=BUTTON_STYLE_SUCCESS)]])
    try:
        await bot.edit_message_text(
            chat_id=g["channel_id"],
            message_id=g["board_msg_id"],
            text=build_board(gid, g),
            parse_mode="HTML",
            reply_markup=kb,
            link_preview_options=NO_PREVIEW,
        )
    except RetryAfter as e:
        board_dirty.add(gid)
        await asyncio.sleep(e.retry_after + 1)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            logger.warning("board edit failed: %s", e)
    except Exception as e:
        logger.warning("board edit failed: %s", e)


async def finish_giveaway(bot, gid, auto=False):
    g = giveaways.get(gid)
    if not g or g.get("ended"):
        return None
    g["ended"] = True
    g["ended_at"] = now_iso()
    winner_text = build_winner_text(g)
    g["winners"] = [uid for uid, votes, rank in ranking(g) if rank == 1 and votes > 0]

    update_channel_history(
        g.get("channel"), g.get("channel_display"), g.get("channel_id"),
        g.get("creator"), g.get("creator_name", "Unknown"), "end", gid,
    )
    for key in [k for k in pending_buttons if k[0] == gid]:
        pending_buttons.pop(key, None)
    flush_data()

    total = sum(g["vote_counts"].values())
    await send_safe(
        bot, g["channel_id"],
        f"<b><tg-emoji emoji-id='{EMOJI_CELEBRATE}'>🎉</tg-emoji> GIVEAWAY ENDED!</b>\n"
        f"<code>{LINE}</code>\n"
        f"<b>🏆 WINNERS</b>\n\n{winner_text}\n\n"
        f"<code>{LINE}</code>\n"
        f"👥 {len(g['users'])} players • 🗳 {total:,} votes\n"
        f"<i>Thanks for playing! Stay tuned for the next one 🚀</i>",
    )
    await refresh_board(bot, gid)

    if auto:
        await send_safe(
            bot, g.get("creator"),
            f"<b>⏰ Your giveaway ended automatically</b>\n\n"
            f"📢 {esc(g.get('channel_display'))}\n\n{winner_text}",
        )
    return winner_text


async def maintenance_loop(app: Application):
    """One background loop: batched button edits, live boards, timers, periodic save."""
    last_expiry = last_save = 0.0
    while True:
        try:
            await asyncio.sleep(EDIT_INTERVAL)
            bot = app.bot
            now = now_utc().timestamp()

            if not await flush_one_button(bot) and board_dirty:
                await refresh_board(bot, board_dirty.pop())

            if now - last_expiry > 20:
                last_expiry = now
                for gid, g in list(giveaways.items()):
                    if not g.get("ended") and time_left(g) is not None and time_left(g) <= 0:
                        await finish_giveaway(bot, gid, auto=True)

            if _dirty and now - last_save > 3:
                last_save = now
                flush_data()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("maintenance loop error: %s", e)


# ================= KEYBOARDS / TEXTS ================= #
def owner_url() -> str:
    """t.me link to the owner: username if set, otherwise a direct tg://user link by ID."""
    if OWNER_USERNAME:
        return f"https://t.me/{OWNER_USERNAME}"
    return f"tg://user?id={OWNER_ID}"


def main_keyboard():
    return InlineKeyboardMarkup([
        [premium_button("CONNECT CHANNEL", url=f"https://t.me/{BOT_USERNAME}?startchannel=true&admin=post_messages", emoji_id=EMOJI_CONNECT, style=BUTTON_STYLE_SUCCESS)],
        [premium_button("CREATE", callback_data="create_giveaway", emoji_id=EMOJI_CREATE, style=BUTTON_STYLE_PRIMARY),
         premium_button("MANAGE", callback_data="my_giveaways", emoji_id=EMOJI_MANAGE, style=BUTTON_STYLE_PRIMARY)],
        [premium_button("HOW IT WORKS", callback_data="howto", emoji_id=EMOJI_SEARCH, style=BUTTON_STYLE_PRIMARY),
         premium_button("MY STATS", callback_data="stats_me", emoji_id=EMOJI_STATS, style=BUTTON_STYLE_PRIMARY)],
        [premium_button(OWNER_BUTTON_TEXT, url=owner_url(), emoji_id=EMOJI_ADMIN, style=BUTTON_STYLE_SUCCESS)],
    ])


def back_to_menu():
    return InlineKeyboardMarkup([[premium_button("MAIN MENU", callback_data="main_menu", emoji_id=EMOJI_MAIN_MENU, style=BUTTON_STYLE_PRIMARY)]])


def welcome_text(user) -> str:
    live = sum(1 for g in giveaways.values() if is_active(g))
    total_votes = sum(sum(g["vote_counts"].values()) for g in giveaways.values())
    return (
        f"<b><tg-emoji emoji-id='{EMOJI_WELCOME}'>👋</tg-emoji> Hey {esc(user.first_name or 'friend')}, welcome to {esc(BOT_NAME)}!</b>\n"
        f"<code>{LINE}</code>\n"
        f"Run <b>fair, fast &amp; exciting</b> vote giveaways right inside your Telegram channel.\n\n"
        f"<tg-emoji emoji-id='{EMOJI_FIRE}'>🔥</tg-emoji> <b>Real-time votes</b> — buttons update live\n"
        f"<tg-emoji emoji-id='{EMOJI_CHART}'>📈</tg-emoji> <b>Live leaderboard</b> — medals, bars &amp; ranks\n"
        f"<tg-emoji emoji-id='{EMOJI_SHIELD}'>🛡</tg-emoji> <b>Anti-cheat</b> — members only, no double voting\n"
        f"<tg-emoji emoji-id='{EMOJI_CALENDAR}'>⏳</tg-emoji> <b>Auto-end timer</b> — winners announced for you\n\n"
        f"<b>How it works</b>\n"
        f"1️⃣ Connect your channel (add me as admin)\n"
        f"2️⃣ Create a giveaway &amp; share the link\n"
        f"3️⃣ Members join, collect votes — top player wins 🏆\n"
        f"<code>{LINE}</code>\n"
        f"<i>🌍 {live} live now • 🗳 {total_votes:,} votes cast • 👥 {len(all_users):,} users</i>\n\n"
        f"<b><tg-emoji emoji-id='{EMOJI_ROCKET}'>🚀</tg-emoji> Tap CREATE to start your first giveaway!</b>"
    )


HOWTO_TEXT = (
    f"<b>📖 HOW IT WORKS</b>\n<code>{LINE}</code>\n\n"
    "<b>For channel owners</b>\n"
    "1️⃣ Add the bot to your channel as <b>admin</b> (post messages)\n"
    "2️⃣ Press <b>CREATE</b>, send your <code>@channel</code> or private channel ID\n"
    "3️⃣ Pick a duration (or no limit) and share the link\n"
    "4️⃣ Watch the live leaderboard, post it in your channel, end anytime\n\n"
    "<b>For participants</b>\n"
    "1️⃣ Open the giveaway link &amp; join the channel\n"
    "2️⃣ Press <b>JOIN GIVEAWAY</b> — your vote card appears in the channel\n"
    "3️⃣ Share your card, collect votes 🔥\n\n"
    "<b>Rules</b>\n"
    "• Only channel members can vote\n"
    "• No double voting, no self voting\n"
    "• Top voted player wins 🏆"
)


# ================= FORCE SUBSCRIBE ================= #
_fsub_warned: set = set()


async def warn_owner_once(bot, entry, reason):
    ref = str(entry.get("ref"))
    if ref in _fsub_warned:
        return
    _fsub_warned.add(ref)
    await send_safe(
        bot, OWNER_ID,
        f"⚠️ <b>Force-sub problem</b>\n\nChannel <code>{esc(ref)}</code> can't be checked ({esc(reason)}).\n"
        f"Make sure the bot is an <b>admin</b> there. Until then this channel is NOT enforced.",
    )


async def resolve_fsub(bot, entry) -> bool:
    if entry.get("chat_id"):
        return True
    ref = str(entry["ref"])
    try:
        chat = await bot.get_chat(ref if ref.startswith("@") else int(ref))
        entry["chat_id"] = chat.id
        entry["title"] = chat.title or entry.get("title") or ref
        mark_dirty()
        return True
    except Exception as e:
        logger.warning("fsub resolve failed for %s: %s", ref, e)
        await warn_owner_once(bot, entry, "channel not found")
        return False


async def fsub_joined(bot, entry, user_id, use_cache=True) -> bool:
    """True if joined. If the channel can't be checked we fail-open so a misconfig never locks everybody out."""
    if not await resolve_fsub(bot, entry):
        return True
    key = (entry["chat_id"], user_id)
    cached = _member_cache.get(key)
    if use_cache and cached and now_utc().timestamp() - cached < MEMBER_CACHE_TTL:
        return True
    try:
        m = await bot.get_chat_member(entry["chat_id"], user_id)
    except Exception as e:
        logger.warning("fsub check failed for %s: %s", entry.get("ref"), e)
        await warn_owner_once(bot, entry, "membership check failed")
        return True
    ok = m.status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
    if m.status == ChatMemberStatus.RESTRICTED and getattr(m, "is_member", False):
        ok = True
    if ok:
        _member_cache[key] = now_utc().timestamp()
    else:
        _member_cache.pop(key, None)
    return ok


async def fsub_missing(bot, user_id, use_cache=True):
    return [e for e in list(fsub_channels) if not await fsub_joined(bot, e, user_id, use_cache)]


async def fsub_prompt(bot, missing):
    rows = []
    names = ""
    for e in missing:
        link = e.get("link")
        if not link and e.get("chat_id"):
            try:
                link = await bot.export_chat_invite_link(e["chat_id"])
                e["link"] = link
                mark_dirty()
            except Exception:
                link = None
        title = esc(e.get("title") or e.get("ref"))
        names += f"• <b>{title}</b>\n"
        if link:
            rows.append([premium_button(f"JOIN {e.get('title') or e.get('ref')}", url=link, emoji_id=EMOJI_CHANNEL, style=BUTTON_STYLE_SUCCESS)])
    rows.append([premium_button("I'VE JOINED", callback_data="fsub_check", emoji_id=EMOJI_CONFIRM, style=BUTTON_STYLE_PRIMARY)])
    text = (
        f"<b><tg-emoji emoji-id='{EMOJI_LOCK}'>🔒</tg-emoji> JOIN REQUIRED</b>\n<code>{LINE}</code>\n"
        f"To use <b>{esc(BOT_NAME)}</b>, please join our channel{'s' if len(missing) > 1 else ''} first:\n\n"
        f"{names}\n"
        f"<i>After joining, tap <b>I'VE JOINED</b> to continue.</i>"
    )
    return text, InlineKeyboardMarkup(rows)


async def fsub_gate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Runs before every other handler (group -1). Blocks everything until the user joined the fsub channels."""
    user = update.effective_user
    if not user or not fsub_channels or is_owner(user.id):
        return
    query = update.callback_query
    if query:
        data = query.data or ""
        if data == "fsub_check":
            return
        if data.startswith("vote_") and not FSUB_GATE_VOTES:
            return
    elif update.message:
        if update.message.chat.type != "private":
            return
    else:
        return

    missing = await fsub_missing(context.bot, user.id)
    if not missing:
        return

    if query:
        in_private = bool(query.message and query.message.chat.type == "private")
        if in_private:
            await query.answer()
            text, kb = await fsub_prompt(context.bot, missing)
            await safe_edit(query, text, kb)
        else:
            await query.answer("🔒 Please join our channel first - open the bot and tap /start", show_alert=True)
    else:
        txt = update.message.text or ""
        if txt.startswith("/start ") and len(txt.split()) > 1:
            context.user_data["pending_start"] = txt.split()[1]  # remember the giveaway link
        text, kb = await fsub_prompt(context.bot, missing)
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb, link_preview_options=NO_PREVIEW)
    raise ApplicationHandlerStop


async def fsub_check_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    missing = await fsub_missing(context.bot, query.from_user.id, use_cache=False)
    if missing:
        await query.answer("❌ You haven't joined all channels yet!", show_alert=True)
        text, kb = await fsub_prompt(context.bot, missing)
        await safe_edit(query, text, kb)
        return
    await query.answer("✅ Verified! Welcome aboard.")
    pending = context.user_data.pop("pending_start", None)
    if pending:
        kb = InlineKeyboardMarkup([
            [premium_button("CONTINUE TO GIVEAWAY", url=giveaway_link(pending), emoji_id=EMOJI_ROCKET, style=BUTTON_STYLE_SUCCESS)],
            [premium_button("MAIN MENU", callback_data="main_menu", emoji_id=EMOJI_MAIN_MENU, style=BUTTON_STYLE_PRIMARY)],
        ])
        await safe_edit(query, "✅ <b>Verified!</b>\n\nTap below to open your giveaway 👇", kb)
    else:
        await safe_edit(query, welcome_text(query.from_user), main_keyboard())


def _fsub_arg(ref: str):
    return ref if ref.startswith("@") else int(ref)


@owner_only
async def addfsub_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Usage:\n<code>/addfsub @channel</code>\n<code>/addfsub -1001234567890 https://t.me/+inviteLink</code>\n\n"
            "The bot must be <b>admin</b> in that channel.", parse_mode="HTML")
        return
    ref = context.args[0]
    link = context.args[1] if len(context.args) > 1 else None
    try:
        chat = await context.bot.get_chat(_fsub_arg(ref))
    except Exception:
        await update.message.reply_text("❌ Channel not found. Check the @username / ID and add the bot as admin first.")
        return
    if any(e.get("chat_id") == chat.id or str(e.get("ref")).lower() == ref.lower() for e in fsub_channels):
        await update.message.reply_text("ℹ️ This channel is already in the force-sub list.")
        return
    try:
        me = await context.bot.get_chat_member(chat.id, context.bot.id)
        is_admin = me.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
    except Exception:
        is_admin = False
    if not is_admin:
        await update.message.reply_text("❌ Make the bot an <b>admin</b> in that channel first, then run the command again.", parse_mode="HTML")
        return
    if not link:
        if chat.username:
            link = f"https://t.me/{chat.username}"
        else:
            try:
                link = chat.invite_link or await context.bot.export_chat_invite_link(chat.id)
            except Exception:
                link = None
    fsub_channels.append({"ref": ref, "chat_id": chat.id, "title": chat.title or ref, "link": link})
    _fsub_warned.discard(ref)
    flush_data()
    await update.message.reply_text(f"✅ Added <b>{esc(chat.title or ref)}</b> to force-sub.\nTotal: <code>{len(fsub_channels)}</code>", parse_mode="HTML")


@owner_only
async def removefsub_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: <code>/removefsub NUMBER</code> (see /fsublist) or <code>/removefsub @channel</code>", parse_mode="HTML")
        return
    arg = context.args[0]
    target = None
    if arg.isdigit() and 1 <= int(arg) <= len(fsub_channels):
        target = fsub_channels[int(arg) - 1]
    else:
        for e in fsub_channels:
            if str(e.get("ref")).lower() == arg.lower() or str(e.get("chat_id")) == arg:
                target = e
                break
    if not target:
        await update.message.reply_text("❌ Not found. Check /fsublist.")
        return
    fsub_channels.remove(target)
    flush_data()
    await update.message.reply_text(f"🗑 Removed <b>{esc(target.get('title') or target.get('ref'))}</b>.\nRemaining: <code>{len(fsub_channels)}</code>", parse_mode="HTML")


@owner_only
async def fsublist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not fsub_channels:
        await update.message.reply_text("📭 Force-sub list is empty - everybody can use the bot.\nAdd one with /addfsub @channel")
        return
    text = "<b>🔒 FORCE-SUB CHANNELS</b>\n\n"
    for i, e in enumerate(fsub_channels, 1):
        status = "⚠️ not resolved"
        if await resolve_fsub(context.bot, e):
            try:
                me = await context.bot.get_chat_member(e["chat_id"], context.bot.id)
                status = "✅ active" if me.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER) else "⚠️ bot is not admin"
            except Exception:
                status = "⚠️ cannot check"
        text += f"<b>{i}.</b> {esc(e.get('title') or e.get('ref'))}\n   <code>{esc(e.get('ref'))}</code> • {status}\n"
    text += "\n<code>/addfsub</code> • <code>/removefsub &lt;number&gt;</code>"
    await update.message.reply_text(text, parse_mode="HTML")


# ================= START / MENU ================= #
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id in banned:
        await update.message.reply_text("🚫 You are banned from using this bot.")
        return
    save_user(user.id, user.username, user.first_name, user.last_name, source="/start")

    if context.args:
        await handle_giveaway_link(update, context, context.args[0])
        return

    await update.message.reply_text(
        welcome_text(user), parse_mode="HTML", reply_markup=main_keyboard(), link_preview_options=NO_PREVIEW
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HOWTO_TEXT, parse_mode="HTML", reply_markup=back_to_menu())


async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_sessions.pop(query.from_user.id, None)
    await safe_edit(query, welcome_text(query.from_user), main_keyboard())


async def howto_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await safe_edit(query, HOWTO_TEXT, back_to_menu())


async def my_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = str(query.from_user.id)
    u = all_users.get(uid, {})
    text = (
        f"<b><tg-emoji emoji-id='{EMOJI_STATS}'>📊</tg-emoji> MY STATS</b>\n<code>{LINE}</code>\n"
        f"🗳 Votes given: <b>{u.get('total_votes_given', 0)}</b>\n"
        f"🎁 Giveaways joined: <b>{u.get('total_giveaways_joined', 0)}</b>\n\n"
    )
    mine = [(gid, g) for gid, g in giveaways.items() if uid in g["users"]][-5:]
    if mine:
        text += "<b>Your recent entries</b>\n"
        for gid, g in reversed(mine):
            rank, votes = rank_of(g, uid)
            state = "🟢" if is_active(g) else "🔴"
            text += f"{state} {esc(g.get('channel_display'))} — #{rank} • {votes:,} votes\n"
    else:
        text += "<i>You haven't joined any giveaway yet.</i>"
    await safe_edit(query, text, back_to_menu())


# ================= GIVEAWAY LINK / JOIN ================= #
def join_prompt_text(g, headline="CHANNEL MEMBERSHIP REQUIRED", note="You need to join the channel first to participate!"):
    return (
        f"<tg-emoji emoji-id='{EMOJI_ALERT}'>⚠️</tg-emoji> <b>{headline}</b>\n\n"
        f"<tg-emoji emoji-id='{EMOJI_GIFT}'>🎁</tg-emoji> <b>Giveaway Host:</b> {esc(g.get('channel_display'))}\n\n"
        f"<i>{note}</i>\n\n"
        f"<b>Steps:</b>\n"
        f"1️⃣ Tap <b>JOIN CHANNEL</b>\n"
        f"2️⃣ Join the channel\n"
        f"3️⃣ Come back &amp; tap <b>TRY AGAIN</b>"
    )


async def join_prompt_keyboard(bot, gid, g):
    rows = []
    link = await get_channel_link(bot, g)
    if link:
        rows.append([premium_button("JOIN CHANNEL", url=link, emoji_id=EMOJI_CHANNEL, style=BUTTON_STYLE_SUCCESS)])
    rows.append([premium_button("TRY AGAIN", callback_data=f"retry_join_{gid}", emoji_id=EMOJI_REFRESH, style=BUTTON_STYLE_PRIMARY)])
    return InlineKeyboardMarkup(rows)


def ready_to_join_text(g, extra):
    left = time_left(g)
    timer = f"\n<tg-emoji emoji-id='{EMOJI_CALENDAR}'>⏳</tg-emoji> <b>Time left:</b> {fmt_duration(left)}" if left is not None else ""
    return (
        f"<tg-emoji emoji-id='{EMOJI_GIFT}'>🎁</tg-emoji> <b>EXCLUSIVE GIVEAWAY</b>\n<code>{LINE}</code>\n"
        f"<tg-emoji emoji-id='{EMOJI_WINE}'>🍷</tg-emoji> <b>Hosted By:</b> {esc(g.get('channel_display'))}\n"
        f"<tg-emoji emoji-id='{EMOJI_SMILE}'>😎</tg-emoji> <b>Participants:</b> {len(g['users'])}"
        f"{timer}\n\n"
        f"<tg-emoji emoji-id='{EMOJI_CONFIRM}'>✅</tg-emoji> <b>{extra}</b>"
    )


def join_keyboard(gid):
    return InlineKeyboardMarkup([
        [premium_button("JOIN GIVEAWAY", callback_data=f"join_{gid}", emoji_id=EMOJI_JOIN, style=BUTTON_STYLE_SUCCESS)],
        [premium_button("LEADERBOARD", callback_data=f"lb_{gid}", emoji_id=EMOJI_LEADERBOARD, style=BUTTON_STYLE_PRIMARY)],
    ])


async def handle_giveaway_link(update: Update, context: ContextTypes.DEFAULT_TYPE, gid: str):
    g = giveaways.get(gid)
    if not g:
        await update.message.reply_text(f"<tg-emoji emoji-id='{EMOJI_ERROR}'>❌</tg-emoji> <b>INVALID LINK</b>", parse_mode="HTML")
        return
    user_id = update.effective_user.id

    if not is_active(g):
        await update.message.reply_text(
            f"<tg-emoji emoji-id='{EMOJI_ENDED}'>❌</tg-emoji> <b>GIVEAWAY ENDED</b>\n\n{build_winner_text(g)}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[premium_button("LEADERBOARD", callback_data=f"lb_{gid}", emoji_id=EMOJI_LEADERBOARD, style=BUTTON_STYLE_PRIMARY)]]),
        )
        return

    uid = str(user_id)
    if uid in g["users"]:
        rank, votes = rank_of(g, uid)
        rows = [[premium_button("LEADERBOARD", callback_data=f"lb_{gid}", emoji_id=EMOJI_LEADERBOARD, style=BUTTON_STYLE_PRIMARY)]]
        link = post_link(g, g["vote_msgs"].get(uid))
        if link:
            rows.insert(0, [premium_button("MY VOTE CARD", url=link, emoji_id=EMOJI_VOTE, style=BUTTON_STYLE_SUCCESS)])
        await update.message.reply_text(
            f"<tg-emoji emoji-id='{EMOJI_STAR}'>🌟</tg-emoji> <b>ALREADY PARTICIPATING!</b>\n\n"
            f"🏅 Rank: <b>#{rank}</b>\n🗳 Votes: <b>{votes:,}</b>\n"
            f"<tg-emoji emoji-id='{EMOJI_ID}'>💌</tg-emoji> ID: <code>{user_id}</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return

    if await is_member(context.bot, g.get("channel_id"), user_id, use_cache=False):
        await update.message.reply_text(
            ready_to_join_text(g, "You are a member of the channel!"),
            parse_mode="HTML", reply_markup=join_keyboard(gid),
        )
    else:
        await update.message.reply_text(
            join_prompt_text(g), parse_mode="HTML",
            reply_markup=await join_prompt_keyboard(context.bot, gid, g),
        )


async def retry_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    gid = query.data.split("_")[2]
    g = giveaways.get(gid)
    if not g:
        await query.answer("Giveaway not found!", show_alert=True)
        return
    if not is_active(g):
        await query.answer("This giveaway has ended.", show_alert=True)
        return

    if await is_member(context.bot, g.get("channel_id"), query.from_user.id, use_cache=False):
        await query.answer("✅ Membership verified!")
        await safe_edit(query, ready_to_join_text(g, "Membership verified! You can now join."), join_keyboard(gid))
    else:
        await query.answer("❌ You haven't joined the channel yet!", show_alert=True)
        await safe_edit(
            query,
            join_prompt_text(g, "STILL NOT A MEMBER", "Please join the channel first!"),
            await join_prompt_keyboard(context.bot, gid, g),
        )


async def handle_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    gid = query.data.split("_")[1]
    user = query.from_user
    uid = str(user.id)

    g = giveaways.get(gid)
    if not g:
        await query.answer("Giveaway not found!", show_alert=True)
        return
    if user.id in banned:
        await query.answer("🚫 You are banned from this bot.", show_alert=True)
        return
    if not is_active(g):
        await query.answer("❌ This giveaway has already ended!", show_alert=True)
        return
    if uid in g["users"]:
        await query.answer("⚠️ Already joined!", show_alert=True)
        return

    if not await is_member(context.bot, g.get("channel_id"), user.id, use_cache=False):
        await query.answer("⚠️ Join the channel first!", show_alert=True)
        await safe_edit(query, join_prompt_text(g), await join_prompt_keyboard(context.bot, gid, g))
        return

    save_user(user.id, user.username, user.first_name, user.last_name, source="join")
    name = user.full_name or user.first_name or f"User {user.id}"

    # post the vote card first - only register the user if it really got posted
    try:
        sent = await context.bot.send_message(
            chat_id=g["channel_id"],
            text=(
                f"<tg-emoji emoji-id='{EMOJI_SMILE}'>😎</tg-emoji> <b>Name:</b> {esc(name)}\n"
                f"<tg-emoji emoji-id='{EMOJI_ID}'>💌</tg-emoji> <b>ID:</b> <code>{user.id}</code>"
            ),
            parse_mode="HTML",
            reply_markup=vote_keyboard(gid, uid, 0),
        )
    except Exception as e:
        logger.error("could not post vote card: %s", e)
        await query.answer("⚠️ Could not post your card in the channel. Tell the host to check bot permissions.", show_alert=True)
        return

    # re-check after the await (double click protection)
    if uid in g["users"]:
        await query.answer("⚠️ Already joined!", show_alert=True)
        return

    g["users"][uid] = name
    g["vote_counts"][uid] = 0
    g["voted_users"][uid] = []
    g["vote_msgs"][uid] = sent.message_id
    update_user_stats(user.id, "join")
    board_dirty.add(gid)
    mark_dirty()

    await query.answer("✅ Registration successful!", show_alert=True)

    rows = []
    link = post_link(g, sent.message_id)
    if link:
        rows.append([premium_button("MY VOTE CARD", url=link, emoji_id=EMOJI_VOTE, style=BUTTON_STYLE_SUCCESS)])
    rows.append([premium_button("LEADERBOARD", callback_data=f"lb_{gid}", emoji_id=EMOJI_LEADERBOARD, style=BUTTON_STYLE_PRIMARY)])
    await safe_edit(
        query,
        f"<b>✅ REGISTRATION SUCCESSFUL!</b>\n<code>{LINE}</code>\n"
        f"😎 {esc(name)}\n💌 <code>{user.id}</code>\n\n"
        f"📥 Your vote card is live in the channel.\n"
        f"🔥 <b>Share it with friends to collect votes!</b>",
        InlineKeyboardMarkup(rows),
    )


# ================= VOTING ================= #
async def handle_vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        _, gid, target = query.data.split("_")
    except ValueError:
        await query.answer()
        return
    voter = query.from_user

    g = giveaways.get(gid)
    if not g:
        await query.answer("❌ Giveaway not active!", show_alert=True)
        return
    if voter.id in banned:
        await query.answer("🚫 You are banned from voting.", show_alert=True)
        return
    if not is_active(g):
        await query.answer("❌ This giveaway has ended!", show_alert=True)
        return
    if target not in g["users"]:
        await query.answer("❌ Participant not found!", show_alert=True)
        return
    if str(voter.id) == target and not ALLOW_SELF_VOTE:
        await query.answer("🙅 You can't vote for yourself!", show_alert=True)
        return

    if not await is_member(context.bot, g["channel_id"], voter.id):
        await query.answer("⚠️ Only channel members can vote! Please join the channel first.", show_alert=True)
        return

    # all checks below run without awaiting -> no race between two quick taps
    voted = g["voted_users"].setdefault(target, [])
    if voter.id in voted:
        await query.answer("⚠️ You have already voted for this user!", show_alert=True)
        return
    if SINGLE_VOTE_PER_GIVEAWAY and any(voter.id in v for v in g["voted_users"].values()):
        await query.answer("⚠️ You already used your vote in this giveaway!", show_alert=True)
        return

    voted.append(voter.id)
    g["vote_counts"][target] = g["vote_counts"].get(target, 0) + 1
    new_votes = g["vote_counts"][target]

    save_user(voter.id, voter.username, voter.first_name, voter.last_name, source="vote")
    update_user_stats(voter.id, "vote")
    queue_button_update(gid, target)

    await query.answer(f"🎉 Vote recorded! {g['users'][target]} now has {new_votes:,} votes.")


# ================= CREATE GIVEAWAY ================= #
async def create_giveaway_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_sessions[query.from_user.id] = {"step": "waiting_channel"}
    await safe_edit(
        query,
        f"<b><tg-emoji emoji-id='{EMOJI_LIGHTNING}'>⚡</tg-emoji> CREATE GIVEAWAY</b>\n<code>{LINE}</code>\n\n"
        f"<i><tg-emoji emoji-id='{EMOJI_POINTER}'>👈</tg-emoji> Add me as <b>admin</b> in your channel, then send its info:</i>\n\n"
        f"<b>Public:</b> <code>@username</code>\n<b>Private:</b> <code>-1001234567890</code>",
        InlineKeyboardMarkup([[premium_button("CANCEL", callback_data="cancel_creation", emoji_id=EMOJI_CANCEL, style=BUTTON_STYLE_DANGER)]]),
    )


async def cancel_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_sessions.pop(query.from_user.id, None)
    await safe_edit(query, "✅ <b>Cancelled!</b>", main_keyboard())


async def process_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    session = user_sessions.get(user.id)
    if not session or session.get("step") != "waiting_channel":
        return

    channel_input = update.message.text.strip()
    loading = await update.message.reply_text(f"<tg-emoji emoji-id='{EMOJI_LIGHTNING}'>⚡</tg-emoji> <b>Verifying...</b>", parse_mode="HTML")

    async def fail(text):
        try:
            await loading.delete()
        except Exception:
            pass
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=back_to_menu())
        user_sessions.pop(user.id, None)

    try:
        if channel_input.startswith("@"):
            chat = await context.bot.get_chat(chat_id=channel_input)
            info = {"identifier": channel_input, "display": channel_input}
        else:
            chat = await context.bot.get_chat(chat_id=int(channel_input))
            info = {"identifier": str(channel_input), "display": chat.title or f"Channel {channel_input}"}
        info["chat_id"] = chat.id
    except Exception:
        await fail(f"<tg-emoji emoji-id='{EMOJI_ERROR}'>❌</tg-emoji> <b>Invalid channel!</b>\n\nCheck the @username / ID and make sure I'm added as admin.")
        return

    # only the channel's own admins may start a giveaway there
    try:
        creator_status = (await context.bot.get_chat_member(chat.id, user.id)).status
    except Exception:
        creator_status = None
    if user.id != OWNER_ID and creator_status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
        await fail("🔒 <b>Only admins of that channel can create a giveaway for it.</b>")
        return

    for gid, g in giveaways.items():
        if g.get("channel_id") == chat.id and is_active(g):
            await fail(
                f"<tg-emoji emoji-id='{EMOJI_ALERT}'>🚨</tg-emoji> <b>GIVEAWAY ALREADY ACTIVE!</b>\n\n"
                f"<b>Channel:</b> {esc(info['display'])}\n\n<b>Active link:</b>\n<code>{giveaway_link(gid)}</code>"
            )
            return

    try:
        test = await context.bot.send_message(chat_id=chat.id, text="✅ Bot connected!")
        await test.delete()
    except Exception:
        await fail(f"🤖 <b>Bot is not admin!</b>\n\nPlease add @{BOT_USERNAME} as an admin (with post permission) in the channel first.")
        return

    try:
        await loading.delete()
    except Exception:
        pass

    session.update({"step": "duration", "channel": info})
    keyboard = InlineKeyboardMarkup([
        [premium_button("NO LIMIT", callback_data="dur_0", emoji_id=EMOJI_ROCKET, style=BUTTON_STYLE_PRIMARY)],
        [premium_button("1 HOUR", callback_data="dur_1", style=BUTTON_STYLE_PRIMARY),
         premium_button("6 HOURS", callback_data="dur_6", style=BUTTON_STYLE_PRIMARY)],
        [premium_button("24 HOURS", callback_data="dur_24", style=BUTTON_STYLE_PRIMARY),
         premium_button("3 DAYS", callback_data="dur_72", style=BUTTON_STYLE_PRIMARY)],
        [premium_button("7 DAYS", callback_data="dur_168", style=BUTTON_STYLE_PRIMARY)],
        [premium_button("CANCEL", callback_data="cancel_creation", emoji_id=EMOJI_CANCEL, style=BUTTON_STYLE_DANGER)],
    ])
    await update.message.reply_text(
        f"<b><tg-emoji emoji-id='{EMOJI_CALENDAR}'>⏳</tg-emoji> CHOOSE DURATION</b>\n\n"
        f"📢 {esc(info['display'])}\n\n<i>The giveaway ends automatically and winners are announced.</i>",
        parse_mode="HTML", reply_markup=keyboard,
    )


async def handle_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    session = user_sessions.get(user.id)
    if not session or session.get("step") != "duration":
        await safe_edit(query, "⌛ Session expired. Please start again.", main_keyboard())
        return

    hours = int(query.data.split("_")[1])
    info = session["channel"]
    gid = "".join(random.choices(string.ascii_letters + string.digits, k=8))
    link = giveaway_link(gid)
    ends_at = None
    if hours:
        ends_at = datetime.fromtimestamp(now_utc().timestamp() + hours * 3600, timezone.utc).isoformat()

    giveaways[gid] = normalize_giveaway({
        "channel": info["identifier"], "channel_display": info["display"], "channel_id": info["chat_id"],
        "users": {}, "vote_counts": {}, "voted_users": {}, "vote_msgs": {},
        "creator": user.id, "creator_name": user.first_name, "ended": False,
        "created_at": now_iso(), "ends_at": ends_at,
    })
    update_channel_history(info["identifier"], info["display"], info["chat_id"], user.id, user.first_name, "create", gid)
    flush_data()
    user_sessions.pop(user.id, None)

    if user.id != OWNER_ID:
        await notify_owner(
            context, "🔔 NEW GIVEAWAY CREATED!",
            f"👤 {esc(user.first_name)}\n🆔 <code>{user.id}</code>\n📢 {esc(info['display'])}\n🔗 <code>{link}</code>",
        )

    duration_line = f"\n<b>⏳ Duration:</b> {fmt_duration(hours * 3600)}" if hours else ""
    await send_safe(
        context.bot, info["chat_id"],
        f"<b><tg-emoji emoji-id='{EMOJI_CONFETTI}'>🎉</tg-emoji> NEW GIVEAWAY STARTED!</b>\n<code>{LINE}</code>\n"
        f"Join, collect votes &amp; win 🏆{duration_line}\n\n"
        f"<b><tg-emoji emoji-id='{EMOJI_RIGHT}'>➡️</tg-emoji> Tap the button below to join!</b>",
        reply_markup=InlineKeyboardMarkup([[premium_button("JOIN GIVEAWAY", url=link, emoji_id=EMOJI_JOIN, style=BUTTON_STYLE_SUCCESS)]]),
    )

    await safe_edit(
        query,
        f"<b><tg-emoji emoji-id='{EMOJI_CONFIRM}'>✅</tg-emoji> GIVEAWAY CREATED!</b>\n<code>{LINE}</code>\n"
        f"<b><tg-emoji emoji-id='{EMOJI_SEARCH}'>🔍</tg-emoji> ID:</b> <code>{gid}</code>\n"
        f"<b><tg-emoji emoji-id='{EMOJI_SPEAKER}'>📢</tg-emoji> Channel:</b> {esc(info['display'])}"
        f"{duration_line}\n\n"
        f"<b><tg-emoji emoji-id='{EMOJI_LINK}'>🔗</tg-emoji> LINK:</b>\n<code>{link}</code>",
        InlineKeyboardMarkup([[
            premium_button("MANAGE", callback_data=f"manage_{gid}", emoji_id=EMOJI_MANAGE, style=BUTTON_STYLE_PRIMARY),
            premium_button("MAIN MENU", callback_data="main_menu", emoji_id=EMOJI_MAIN_MENU, style=BUTTON_STYLE_PRIMARY),
        ]]),
    )


# ================= MANAGE ================= #
async def my_giveaways(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    rows = []
    for gid, g in giveaways.items():
        if g.get("creator") == user_id and is_active(g):
            rows.append([premium_button(f"📢 {g.get('channel_display', g.get('channel'))}", callback_data=f"manage_{gid}", emoji_id=EMOJI_MANAGE, style=BUTTON_STYLE_PRIMARY)])

    if rows:
        text = f"<b><tg-emoji emoji-id='{EMOJI_CROWN}'>👑</tg-emoji> YOUR GIVEAWAYS</b>"
    else:
        text = f"<tg-emoji emoji-id='{EMOJI_ERROR}'>❌</tg-emoji> <b>No active giveaways!</b>"
        rows.append([premium_button("CREATE NEW", callback_data="create_giveaway", emoji_id=EMOJI_CREATE, style=BUTTON_STYLE_PRIMARY)])
    rows.append([premium_button("MAIN MENU", callback_data="main_menu", emoji_id=EMOJI_MAIN_MENU, style=BUTTON_STYLE_PRIMARY)])
    await safe_edit(query, text, InlineKeyboardMarkup(rows))


def manage_view(gid, g, admin=False):
    status = "🟢 ACTIVE" if is_active(g) else "🔴 ENDED"
    left = time_left(g)
    timer = f"<b>Time left:</b> {fmt_duration(left)}\n" if (left is not None and is_active(g)) else ""
    text = (
        f"<b><tg-emoji emoji-id='{EMOJI_ARROW}'>➡️</tg-emoji> MANAGEMENT PANEL{' (ADMIN)' if admin else ''}</b>\n<code>{LINE}</code>\n"
        f"<b>ID:</b> <code>{gid}</code>\n"
        f"<b>Status:</b> {status}\n"
        f"<b>Channel:</b> {esc(g.get('channel_display', g.get('channel')))}\n"
        f"{timer}"
        f"<b>Players:</b> {len(g['users'])}\n"
        f"<b>Total votes:</b> {sum(g['vote_counts'].values()):,}\n\n"
        f"<b>Link:</b> <code>{giveaway_link(gid)}</code>"
    )
    rows = [
        [premium_button("ADD VOTES", callback_data=f"addvotes_{gid}", emoji_id=EMOJI_ADD_VOTES, style=BUTTON_STYLE_PRIMARY),
         premium_button("REMOVE VOTES", callback_data=f"removevotes_{gid}", emoji_id=EMOJI_REMOVE_VOTES, style=BUTTON_STYLE_DANGER)],
        [premium_button("LEADERBOARD", callback_data=f"lb_{gid}", emoji_id=EMOJI_LEADERBOARD, style=BUTTON_STYLE_PRIMARY),
         premium_button("POST LIVE BOARD", callback_data=f"postboard_{gid}", emoji_id=EMOJI_CHART, style=BUTTON_STYLE_SUCCESS)],
    ]
    if is_active(g):
        rows.append([premium_button("END GIVEAWAY", callback_data=f"endgiveaway_{gid}", emoji_id=EMOJI_END_GIVEAWAY, style=BUTTON_STYLE_DANGER)])
    rows.append([premium_button("BACK", callback_data="my_giveaways", emoji_id=EMOJI_BACK, style=BUTTON_STYLE_PRIMARY)])
    return text, InlineKeyboardMarkup(rows)


async def guard_manage(query, gid):
    """Returns the giveaway if the caller may manage it, else answers with an alert and returns None."""
    g = giveaways.get(gid)
    if not g:
        await query.answer("Giveaway not found!", show_alert=True)
        return None
    if not can_manage(query.from_user.id, g):
        await query.answer("🔒 Only the giveaway creator can do this.", show_alert=True)
        return None
    await query.answer()
    return g


async def manage_giveaway(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    gid = query.data.split("_")[1]
    g = await guard_manage(query, gid)
    if g:
        text, kb = manage_view(gid, g, admin=is_owner(query.from_user.id) and g.get("creator") != query.from_user.id)
        await safe_edit(query, text, kb)


async def add_votes_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _vote_change_flow(update, context, "add")


async def remove_votes_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _vote_change_flow(update, context, "remove")


async def _vote_change_flow(update, context, action):
    query = update.callback_query
    gid = query.data.split("_")[1]
    if not await guard_manage(query, gid):
        return
    context.user_data["vote_giveaway"] = gid
    context.user_data["vote_action"] = action
    label = "ADD" if action == "add" else "REMOVE"
    await safe_edit(
        query,
        f"<b><tg-emoji emoji-id='{EMOJI_DIAMOND}'>💎</tg-emoji> {label} VOTES</b>\n\n"
        f"Send: <code>USER_ID VOTES</code>\nExample: <code>12345678 10</code>",
        InlineKeyboardMarkup([[premium_button("BACK", callback_data=f"manage_{gid}", emoji_id=EMOJI_BACK, style=BUTTON_STYLE_PRIMARY)]]),
    )


def apply_adjust(gid, uid_str, delta, by):
    g = giveaways[gid]
    old = g["vote_counts"].get(uid_str, 0)
    new = max(0, old + delta)
    g["vote_counts"][uid_str] = new
    g["log"].append({"t": now_iso(), "by": by, "user": uid_str, "delta": delta, "old": old, "new": new})
    g["log"] = g["log"][-100:]
    queue_button_update(gid, uid_str)
    return new


async def process_vote_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    gid = context.user_data.get("vote_giveaway")
    action = context.user_data.get("vote_action")
    g = giveaways.get(gid)
    if not g or not can_manage(update.effective_user.id, g):
        context.user_data.pop("vote_giveaway", None)
        context.user_data.pop("vote_action", None)
        return

    try:
        parts = update.message.text.strip().split()
        target = str(int(parts[0]))
        votes = int(parts[1])
        if votes <= 0:
            raise ValueError
    except Exception:
        await update.message.reply_text(f"<tg-emoji emoji-id='{EMOJI_ALERT}'>🚨</tg-emoji> Invalid! Send <code>USER_ID VOTES</code> (positive number).", parse_mode="HTML")
        return

    if target not in g["users"]:
        await update.message.reply_text(f"<tg-emoji emoji-id='{EMOJI_ERROR}'>❌</tg-emoji> User not found in this giveaway!", parse_mode="HTML")
        return

    new_votes = apply_adjust(gid, target, votes if action == "add" else -votes, update.effective_user.id)
    msg = f"Added +{votes} votes!" if action == "add" else f"Removed {votes} votes!"
    await update.message.reply_text(
        f"<tg-emoji emoji-id='{EMOJI_DIAMOND}'>💎</tg-emoji> {msg}\n<b>New total:</b> {new_votes:,} votes",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[premium_button("BACK", callback_data=f"manage_{gid}", emoji_id=EMOJI_BACK, style=BUTTON_STYLE_PRIMARY)]]),
    )
    context.user_data.pop("vote_giveaway", None)
    context.user_data.pop("vote_action", None)


# ================= LEADERBOARD ================= #
def board_keyboard(gid, g, user_id):
    rows = [[premium_button("REFRESH", callback_data=f"lb_{gid}", emoji_id=EMOJI_REFRESH, style=BUTTON_STYLE_PRIMARY)]]
    if is_active(g):
        rows.append([premium_button("JOIN & VOTE", url=giveaway_link(gid), emoji_id=EMOJI_JOIN, style=BUTTON_STYLE_SUCCESS)])
    if can_manage(user_id, g):
        rows.append([premium_button("BACK", callback_data=f"manage_{gid}", emoji_id=EMOJI_BACK, style=BUTTON_STYLE_PRIMARY)])
    return InlineKeyboardMarkup(rows)


async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Public: anyone with the giveaway id/link can view the leaderboard."""
    query = update.callback_query
    gid = query.data.split("_")[1]
    g = giveaways.get(gid)
    if not g:
        await query.answer("Giveaway not found!", show_alert=True)
        return
    await query.answer("🔄 Updated!")
    await safe_edit(query, build_board(gid, g, viewer=query.from_user.id), board_keyboard(gid, g, query.from_user.id))


async def top_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or context.args[0] not in giveaways:
        await update.message.reply_text("Usage: <code>/top GIVEAWAY_ID</code>", parse_mode="HTML")
        return
    gid = context.args[0]
    g = giveaways[gid]
    await update.message.reply_text(
        build_board(gid, g, viewer=update.effective_user.id), parse_mode="HTML",
        reply_markup=board_keyboard(gid, g, update.effective_user.id),
    )


async def post_board(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Post a self-updating leaderboard message into the channel."""
    query = update.callback_query
    gid = query.data.split("_")[1]
    g = await guard_manage(query, gid)
    if not g:
        return
    if g.get("board_msg_id"):  # replace the old one
        try:
            await context.bot.delete_message(g["channel_id"], g["board_msg_id"])
        except Exception:
            pass
    try:
        kb = None
        if is_active(g):
            kb = InlineKeyboardMarkup([[premium_button("JOIN & VOTE", url=giveaway_link(gid), emoji_id=EMOJI_JOIN, style=BUTTON_STYLE_SUCCESS)]])
        sent = await context.bot.send_message(
            chat_id=g["channel_id"], text=build_board(gid, g), parse_mode="HTML",
            reply_markup=kb, link_preview_options=NO_PREVIEW,
        )
        g["board_msg_id"] = sent.message_id
        mark_dirty()
        try:
            await context.bot.pin_chat_message(g["channel_id"], sent.message_id, disable_notification=True)
        except Exception:
            pass
        await query.answer("✅ Live board posted & will auto-update!", show_alert=True)
    except Exception as e:
        logger.error("post board failed: %s", e)
        await query.answer("❌ Could not post in the channel. Check bot permissions.", show_alert=True)


# ================= END GIVEAWAY ================= #
async def end_giveaway(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    gid = query.data.split("_")[1]
    if not await guard_manage(query, gid):
        return
    await safe_edit(
        query,
        f"<b><tg-emoji emoji-id='{EMOJI_LOCK}'>⚠️</tg-emoji> End this giveaway?</b>\n\nWinners will be announced in the channel.",
        InlineKeyboardMarkup([
            [premium_button("CONFIRM", callback_data=f"confirm_end_{gid}", emoji_id=EMOJI_CONFIRM, style=BUTTON_STYLE_DANGER)],
            [premium_button("CANCEL", callback_data=f"manage_{gid}", emoji_id=EMOJI_CANCEL, style=BUTTON_STYLE_PRIMARY)],
        ]),
    )


async def confirm_end_giveaway(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    gid = query.data.split("_")[2]
    g = await guard_manage(query, gid)
    if not g:
        return
    winner_text = await finish_giveaway(context.bot, gid)
    if winner_text is None:
        await safe_edit(query, "ℹ️ This giveaway was already ended.", back_to_menu())
        return
    await safe_edit(query, f"<b>✅ Giveaway ended!</b>\n\n<b>🏆 WINNERS</b>\n{winner_text}", back_to_menu())


# ================= ADMIN (OWNER) COMMANDS ================= #
def command_payload(update: Update) -> str:
    parts = (update.message.text or "").split(None, 1)
    return parts[1].strip() if len(parts) > 1 else ""


async def send_to_users(bot, text):
    ok = fail = 0
    for uid in list(all_users.keys()):
        if all_users[uid].get("blocked"):
            fail += 1
            continue
        if await send_safe(bot, int(uid), text):
            ok += 1
        else:
            fail += 1
        await asyncio.sleep(0.05)
    return ok, fail


async def send_to_channels(bot, text):
    ok = fail = 0
    seen = set()
    for g in list(giveaways.values()):
        cid = g.get("channel_id")
        if cid and cid not in seen and is_active(g):
            seen.add(cid)
            if await send_safe(bot, cid, text):
                ok += 1
            else:
                fail += 1
            await asyncio.sleep(0.5)
    return ok, fail, len(seen)


@owner_only
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "<b>👑 ADMIN COMMANDS</b>\n\n"
        "<code>/admin</code> - this menu\n"
        "<code>/broadcast &lt;msg&gt;</code> - message all users\n"
        "<code>/bc &lt;msg&gt;</code> - message all active channels\n"
        "<code>/ball &lt;msg&gt;</code> - users + channels\n"
        "<code>/stats</code> - bot statistics\n"
        "<code>/users</code> - recent users\n"
        "<code>/channels</code> - channel history\n"
        "<code>/backup</code> - send the data file here\n"
        "<code>/settings</code> - current settings\n"
        "<code>/testnotify</code> - test owner notification\n"
        "<code>/clear</code> - delete ALL data (auto backup first)\n\n"
        "<code>/g_management &lt;id&gt;</code> - open any giveaway panel\n"
        "<code>/add_vote &lt;id&gt; &lt;user_id&gt; &lt;votes&gt;</code>\n"
        "<code>/remove_vote &lt;id&gt; &lt;user_id&gt; &lt;votes&gt;</code>\n"
        "<code>/ban &lt;user_id&gt;</code> / <code>/unban &lt;user_id&gt;</code>\n\n"
        "<b>Force-sub</b>\n"
        "<code>/addfsub &lt;@channel|id&gt; [invite_link]</code>\n"
        "<code>/removefsub &lt;number|@channel&gt;</code>\n"
        "<code>/fsublist</code>\n\n"
        "<code>/cancel</code> - cancel current action",
        parse_mode="HTML",
    )


@owner_only
async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payload = command_payload(update)
    if not payload:
        admin_sessions[OWNER_ID] = {"step": "waiting_broadcast"}
        await update.message.reply_text(
            "<b>📢 BROADCAST SYSTEM</b>\n\nSend your message now (HTML allowed: "
            "<code>&lt;b&gt;</code> <code>&lt;i&gt;</code> <code>&lt;a href=''&gt;</code> <code>&lt;tg-emoji&gt;</code>).\n\n"
            f"<b>Total users:</b> <code>{len(all_users)}</code>\nSend /cancel to abort.",
            parse_mode="HTML",
        )
        return
    await run_broadcast(update, context, payload)


async def run_broadcast(update, context, text):
    await update.message.reply_text(f"🚀 <b>Broadcast started</b> to <code>{len(all_users)}</code> users...", parse_mode="HTML")
    ok, fail = await send_to_users(context.bot, text)
    admin_sessions.pop(OWNER_ID, None)
    await update.message.reply_text(
        f"<b>✅ BROADCAST COMPLETED!</b>\n\n✅ Sent: <code>{ok}</code>\n❌ Failed: <code>{fail}</code>\n📊 Total: <code>{len(all_users)}</code>",
        parse_mode="HTML",
    )


@owner_only
async def bc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payload = command_payload(update)
    if not payload:
        await update.message.reply_text("❌ Usage: /bc <message>")
        return
    ok, fail, total = await send_to_channels(context.bot, payload)
    await update.message.reply_text(
        f"<b>✅ CHANNEL BROADCAST DONE</b>\n\n✅ Sent: <code>{ok}</code>\n❌ Failed: <code>{fail}</code>\n📊 Channels: <code>{total}</code>",
        parse_mode="HTML",
    )


@owner_only
async def ball_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payload = command_payload(update)
    if not payload:
        await update.message.reply_text("❌ Usage: /ball <message>")
        return
    await update.message.reply_text("🚀 <b>Sending to ALL USERS + ALL CHANNELS...</b>", parse_mode="HTML")
    u_ok, u_fail = await send_to_users(context.bot, payload)
    c_ok, c_fail, c_total = await send_to_channels(context.bot, payload)
    await update.message.reply_text(
        f"<b>✅ DONE</b>\n\n<b>📱 Users:</b> ✅ {u_ok} / ❌ {u_fail}\n<b>📺 Channels:</b> ✅ {c_ok} / ❌ {c_fail} (total {c_total})",
        parse_mode="HTML",
    )


@owner_only
async def g_management_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or context.args[0] not in giveaways:
        await update.message.reply_text("❌ Usage: /g_management <giveaway_id> (id not found?)")
        return
    gid = context.args[0]
    text, kb = manage_view(gid, giveaways[gid], admin=True)
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb, link_preview_options=NO_PREVIEW)


async def _adjust_command(update, context, sign):
    name = "add_vote" if sign > 0 else "remove_vote"
    if len(context.args) != 3:
        await update.message.reply_text(f"❌ Usage: /{name} <giveaway_id> <user_id> <votes>")
        return
    gid = context.args[0]
    try:
        target = str(int(context.args[1]))
        votes = int(context.args[2])
        if votes <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ user_id and votes must be positive numbers.")
        return
    g = giveaways.get(gid)
    if not g:
        await update.message.reply_text(f"❌ Giveaway '{esc(gid)}' not found!")
        return
    if target not in g["users"]:
        await update.message.reply_text(f"❌ User {target} not found in this giveaway!")
        return
    new = apply_adjust(gid, target, sign * votes, update.effective_user.id)
    await update.message.reply_text(
        f"✅ <b>Votes {'added' if sign > 0 else 'removed'}!</b>\n\n"
        f"<b>User:</b> <code>{target}</code> ({esc(g['users'][target])})\n"
        f"<b>Change:</b> {'+' if sign > 0 else '-'}{votes}\n<b>New total:</b> {new:,}",
        parse_mode="HTML",
    )


@owner_only
async def add_vote_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _adjust_command(update, context, +1)


@owner_only
async def remove_vote_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _adjust_command(update, context, -1)


@owner_only
async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        uid = int(context.args[0])
    except Exception:
        await update.message.reply_text("❌ Usage: /ban <user_id>")
        return
    banned.add(uid)
    mark_dirty()
    await update.message.reply_text(f"🚫 User <code>{uid}</code> banned (cannot join or vote).", parse_mode="HTML")


@owner_only
async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        uid = int(context.args[0])
    except Exception:
        await update.message.reply_text("❌ Usage: /unban <user_id>")
        return
    banned.discard(uid)
    mark_dirty()
    await update.message.reply_text(f"✅ User <code>{uid}</code> unbanned.", parse_mode="HTML")


@owner_only
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    active = sum(1 for g in giveaways.values() if is_active(g))
    participants = sum(len(g["users"]) for g in giveaways.values())
    votes = sum(sum(g["vote_counts"].values()) for g in giveaways.values())
    blocked = sum(1 for u in all_users.values() if u.get("blocked"))
    await update.message.reply_text(
        f"<b><tg-emoji emoji-id='{EMOJI_STATS}'>📊</tg-emoji> BOT STATISTICS</b>\n\n"
        f"👥 Users: <code>{len(all_users)}</code> (blocked bot: {blocked})\n"
        f"🎁 Giveaways: <code>{len(giveaways)}</code>  •  🟢 Active: <code>{active}</code>\n"
        f"📺 Channels: <code>{len(channel_history)}</code>\n"
        f"👤 Participants: <code>{participants}</code>\n"
        f"🗳 Votes: <code>{votes:,}</code>\n"
        f"🚫 Banned: <code>{len(banned)}</code>",
        parse_mode="HTML",
    )


@owner_only
async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    recent = list(all_users.values())[-15:][::-1]
    text = f"<b><tg-emoji emoji-id='{EMOJI_USERS}'>👥</tg-emoji> RECENT USERS</b>\n\n"
    for u in recent:
        text += (
            f"<b>👤 {esc(u.get('first_name', 'Unknown'))}</b>\n"
            f"   🆔 <code>{u.get('user_id')}</code>  📝 @{esc(u.get('username') or 'no')}\n"
            f"   📍 {esc(u.get('source', '?'))}\n\n"
        )
    text += f"<b>Total users:</b> <code>{len(all_users)}</code>"
    await update.message.reply_text(text, parse_mode="HTML")


@owner_only
async def channels_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = f"<b><tg-emoji emoji-id='{EMOJI_CHANNEL}'>📺</tg-emoji> CHANNEL HISTORY</b>\n\n<b>🟢 ACTIVE</b>\n"
    found = False
    for ch in channel_history.values():
        for item in ch.get("giveaways", []):
            if item.get("status") == "active":
                found = True
                text += (
                    f"\n📢 <b>{esc(ch.get('channel_display'))}</b> ({ch.get('type', '?').upper()})\n"
                    f"   🆔 <code>{ch.get('channel_id')}</code>  👤 {esc(ch.get('created_by_name'))}\n"
                    f"   🎁 <code>{item.get('giveaway_id')}</code> • {item.get('created_at', '')[:10]}\n"
                )
    if not found:
        text += "<i>None</i>\n"
    text += "\n<b>🔴 PAST</b>\n"
    found = False
    for ch in list(channel_history.values())[-10:]:
        if any(i.get("status") == "ended" for i in ch.get("giveaways", [])):
            found = True
            text += f"\n📢 <b>{esc(ch.get('channel_display'))}</b> — {ch.get('total_giveaways', 0)} giveaways total\n"
    if not found:
        text += "<i>None</i>\n"
    await update.message.reply_text(text[:4000], parse_mode="HTML")


@owner_only
async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    flush_data()
    try:
        with open(DATA_FILE, "rb") as f:
            await update.message.reply_document(
                f, filename=f"votxify-backup-{now_utc().strftime('%Y%m%d-%H%M')}.json",
                caption=f"✅ Backup • {len(all_users)} users • {len(giveaways)} giveaways",
            )
    except Exception as e:
        await update.message.reply_text(f"❌ Backup failed: {esc(e)}")


@owner_only
async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"<b><tg-emoji emoji-id='{EMOJI_SETTINGS}'>⚙️</tg-emoji> SETTINGS</b>\n\n"
        f"<b>Bot:</b> @{BOT_USERNAME}\n<b>Owner ID:</b> <code>{OWNER_ID}</code>\n<b>Data file:</b> <code>{DATA_FILE}</code>\n"
        f"<b>Self vote:</b> {'✅' if ALLOW_SELF_VOTE else '❌'}\n"
        f"<b>One vote per giveaway:</b> {'✅' if SINGLE_VOTE_PER_GIVEAWAY else '❌'}\n"
        f"<b>Leaderboard size:</b> {LEADERBOARD_SIZE}\n"
        f"<b>Force-sub channels:</b> {len(fsub_channels)} (see /fsublist)\n\n"
        "<i>Change these at the top of vote.py.</i>",
        parse_mode="HTML",
    )


@owner_only
async def testnotify_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await notify_owner(context, "🔔 TEST NOTIFICATION", "All systems working fine.")
    await update.message.reply_text("✅ Test notification sent!")


@owner_only
async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"<b><tg-emoji emoji-id='{EMOJI_ALERT}'>⚠️</tg-emoji> DANGER ZONE</b>\n\n"
        f"This deletes <code>{len(all_users)}</code> users, <code>{len(giveaways)}</code> giveaways and "
        f"<code>{len(channel_history)}</code> channel histories.\n<i>A backup copy is saved first.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ CONFIRM CLEAR", callback_data="confirm_clear", style=BUTTON_STYLE_DANGER),
            InlineKeyboardButton("❌ CANCEL", callback_data="main_menu", style=BUTTON_STYLE_PRIMARY),
        ]]),
    )


async def confirm_clear_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_owner(query.from_user.id):
        await query.answer("❌ You are not the owner!", show_alert=True)
        return
    await query.answer()
    flush_data()
    if os.path.exists(DATA_FILE):
        shutil.copy(DATA_FILE, f"{DATA_FILE}.before-clear-{int(now_utc().timestamp())}")
    giveaways.clear()
    all_users.clear()
    channel_history.clear()
    pending_buttons.clear()
    board_dirty.clear()
    flush_data()
    await safe_edit(query, "✅ <b>All data cleared!</b>\n\nA backup copy was saved next to the data file.")


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_sessions.pop(uid, None)
    admin_sessions.pop(uid, None)
    context.user_data.pop("vote_giveaway", None)
    context.user_data.pop("vote_action", None)
    await update.message.reply_text("❌ Cancelled.", reply_markup=back_to_menu())


# ================= ROUTERS ================= #
ROUTES = [
    ("fsub_check", fsub_check_callback, True),
    ("confirm_clear", confirm_clear_callback, True),
    ("create_giveaway", create_giveaway_flow, True),
    ("cancel_creation", cancel_creation, True),
    ("my_giveaways", my_giveaways, True),
    ("main_menu", main_menu, True),
    ("howto", howto_callback, True),
    ("stats_me", my_stats, True),
    ("dur_", handle_duration, False),
    ("retry_join_", retry_join, False),
    ("manage_", manage_giveaway, False),
    ("addvotes_", add_votes_flow, False),
    ("removevotes_", remove_votes_flow, False),
    ("lb_", show_leaderboard, False),
    ("leaderboard_", show_leaderboard, False),   # old buttons still work
    ("postboard_", post_board, False),
    ("endgiveaway_", end_giveaway, False),
    ("confirm_end_", confirm_end_giveaway, False),
    ("join_", handle_join, False),
    ("vote_", handle_vote, False),
]


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data or ""
    for prefix, handler, exact in ROUTES:
        if (data == prefix) if exact else data.startswith(prefix):
            await handler(update, context)
            return
    await query.answer()


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    user_id = update.effective_user.id

    if user_id == OWNER_ID and admin_sessions.get(OWNER_ID, {}).get("step") == "waiting_broadcast":
        await run_broadcast(update, context, update.message.text)
        return
    if user_sessions.get(user_id, {}).get("step") == "waiting_channel":
        await process_channel(update, context)
        return
    if "vote_giveaway" in context.user_data:
        await process_vote_change(update, context)


async def error_handler(update, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Unhandled error: %s", context.error, exc_info=context.error)


# ================= STARTUP ================= #
async def post_init(app: Application):
    await app.bot.set_my_commands([
        BotCommand("start", "Open the main menu"),
        BotCommand("help", "How it works"),
        BotCommand("top", "Show a giveaway leaderboard"),
        BotCommand("cancel", "Cancel the current action"),
    ])
    try:
        await app.bot.set_my_commands(
            [BotCommand("admin", "Owner commands"), BotCommand("stats", "Statistics"), BotCommand("backup", "Download data backup")]
            + [BotCommand("start", "Main menu")],
            scope=BotCommandScopeChat(OWNER_ID),
        )
    except Exception as e:
        logger.warning("owner commands not set: %s", e)
    app.bot_data["maintenance_task"] = asyncio.create_task(maintenance_loop(app))


async def post_shutdown(app: Application):
    task = app.bot_data.get("maintenance_task")
    if task:
        task.cancel()
    flush_data()
    logger.info("Data saved. Bye!")


def main():
    if not TOKEN:
        sys.exit("❌ BOT_TOKEN is missing. Set it as an environment variable or in a .env file.")

    load_data()
    request = HTTPXRequest(connect_timeout=30, read_timeout=30, write_timeout=30, pool_timeout=30)
    app = (
        Application.builder()
        .token(TOKEN)
        .request(request)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    for name, fn in [
        ("start", start), ("help", help_command), ("top", top_command), ("cancel", cancel_command),
        ("admin", admin_command), ("broadcast", broadcast_command), ("bc", bc_command), ("ball", ball_command),
        ("stats", stats_command), ("users", users_command), ("channels", channels_command),
        ("backup", backup_command), ("settings", settings_command), ("testnotify", testnotify_command),
        ("clear", clear_command), ("g_management", g_management_command),
        ("add_vote", add_vote_command), ("remove_vote", remove_vote_command),
        ("ban", ban_command), ("unban", unban_command),
        ("addfsub", addfsub_command), ("removefsub", removefsub_command), ("fsublist", fsublist_command),
    ]:
        app.add_handler(CommandHandler(name, fn))

    app.add_handler(TypeHandler(Update, fsub_gate), group=-1)  # force-sub gate runs first
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    logger.info("🤖 %s is running as @%s (owner %s)", BOT_NAME, BOT_USERNAME, OWNER_ID)
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
