import asyncio, json, os, time, logging, random, string, threading, io, uuid, re
from html import escape as html_escape
from datetime import datetime
from copy import deepcopy
from collections import defaultdict

import aiohttp
from aiohttp import web as aiohttp_web
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
    ChatMemberUpdated,
    FSInputFile
)
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest

# ========== FILE LOCK FOR RACE CONDITION PROTECTION ==========
_DB_LOCK = threading.RLock()


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("BlastBot")

# ========== PREMIUM EMOJI IDs ==========
EMOJI_FIRE = "5289722755871162900"      # 🔥
EMOJI_STAR = "5372849966689566579"      # ⭐
EMOJI_ROCKET = "5359664288241829619"    # 🚀
EMOJI_CROWN = "6237927637906364256"     # 👑
EMOJI_SHIELD = "6235476345451716705"    # 🛡
EMOJI_MONEY = "6244678063775289843"     # 💰
EMOJI_PHONE = "6239930832128056797"     # 📱
EMOJI_CHECK = "4958689671950369798"     # ✅
EMOJI_CROSS = "4958900559139570572"     # ❌
EMOJI_WARNING = "4958526153955476488"   # ⚠️
EMOJI_LOCK = "4956719506027185156"      # 🔒
EMOJI_GIFT = "5084613633418199991"      # 🎁
EMOJI_BELL = "5098265504796115765"      # 🔔
EMOJI_GEAR = "5116414868357907335"      # ⚙️
EMOJI_VIDEO = "5372849966689566579"     # 📹

FIRE_EFFECT_ID = "5104841245755180586"

SMALL_CAPS_MAP = str.maketrans(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    "ᴀʙᴄᴅᴇғɢʜɪᴊᴋʟᴍɴᴏᴘǫʀsᴛᴜᴠᴡxʏᴢᴀʙᴄᴅᴇғɢʜɪᴊᴋʟᴍɴᴏᴘǫʀsᴛᴜᴠᴡxʏᴢ0123456789"
)

_LOCAL_EMOJI_RE = re.compile(
    r"[\U0001F000-\U0001FAFF\u2300-\u23FF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D]"
)

def sc(text: str) -> str:
    text = _LOCAL_EMOJI_RE.sub("", text)
    return text.translate(SMALL_CAPS_MAP).strip()

def em(emoji_id: str, fallback: str = "⭐") -> str:
    if emoji_id:
        return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'
    return fallback

def btn(text: str, callback_data: str, emoji_id: str = None, fallback_emoji: str = "", style: str = None) -> InlineKeyboardButton:
    label = f"{fallback_emoji} {sc(text)}".strip() if (fallback_emoji and not emoji_id) else sc(text)
    kwargs = {"text": label, "callback_data": callback_data}
    if emoji_id:
        kwargs["icon_custom_emoji_id"] = emoji_id
    if style in ("primary", "success", "danger"):
        kwargs["style"] = style
    try:
        return InlineKeyboardButton(**kwargs)
    except TypeError:
        kwargs.pop("style", None)
        kwargs.pop("icon_custom_emoji_id", None)
        return InlineKeyboardButton(**kwargs)

def btn_url(text: str, url: str, emoji_id: str = None, fallback_emoji: str = "", style: str = None) -> InlineKeyboardButton:
    label = f"{fallback_emoji} {sc(text)}".strip() if (fallback_emoji and not emoji_id) else sc(text)
    kwargs = {"text": label, "url": url}
    if emoji_id:
        kwargs["icon_custom_emoji_id"] = emoji_id
    if style in ("primary", "success", "danger"):
        kwargs["style"] = style
    try:
        return InlineKeyboardButton(**kwargs)
    except TypeError:
        kwargs.pop("style", None)
        kwargs.pop("icon_custom_emoji_id", None)
        return InlineKeyboardButton(**kwargs)

def style_btn(text: str, style: str = "primary", request_contact: bool = False, request_location: bool = False, emoji_id: str = None) -> KeyboardButton:
    kwargs = {
        "text": sc(text),
        "request_contact": request_contact,
        "request_location": request_location
    }
    if style in ("primary", "success", "danger"):
        kwargs["style"] = style
    if emoji_id:
        kwargs["icon_custom_emoji_id"] = emoji_id
    try:
        return KeyboardButton(**kwargs)
    except TypeError:
        kwargs.pop("style", None)
        kwargs.pop("icon_custom_emoji_id", None)
        return KeyboardButton(**kwargs)

def default_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [style_btn("🚀 Start Blast", style="success", emoji_id=EMOJI_ROCKET),
             style_btn("📹 Videos", style="primary", emoji_id=EMOJI_VIDEO)],
            [style_btn("💰 Credits", style="primary", emoji_id=EMOJI_MONEY),
             style_btn("🛑 Stop Blast", style="danger", emoji_id=EMOJI_CROSS)]
        ],
        resize_keyboard=True
    )

MAIN_OWNER = 2109945627
SUPER_ADMIN_NAME = "@Rohit_mxd"
SUPER_ADMIN_LINK = "https://t.me/Rohit_mxd"
SUPER_ADMINS = [5313604885]

BOT_TOKEN = os.getenv("BOT_TOKEN", "873086973T1sruAzJqOhpPL8_R3prWya04").strip()
LOG_CHANNEL_ID = -1003973814935

_DATA_FILE = "blast_data.json"
_VERSION = "v3.2-PREMIUM-FIXED"
_PROGRESS_UPDATE_INTERVAL = 1.0
_SEND_DELAY = 0.3
_BACKGROUND_SCAN_INTERVAL = 60.0

# ⚠️ FIXED SPEEDS - Slower and more reliable
# Speed = delay between each SMS send (seconds)
# FAST   = reliable but quick
# MEDIUM = balanced
# SLOW   = extra reliable for poor connections
SPEED_FAST   = 0.2    # 5 SMS per second per sender (was 0.05 - TOO FAST)
SPEED_MEDIUM = 0.5    # 2 SMS per second per sender (was 0.3)
SPEED_SLOW   = 2.0    # 0.5 SMS per second per sender (was 1.5)
SPEED_DEFAULT = SPEED_MEDIUM

# ⚠️ FIREBASE TIMEOUT SETTINGS
FB_TIMEOUT = 8.0          # Seconds to wait for Firebase response (was infinite!)
FB_RETRY_MAX = 3          # Max retry attempts per SMS
FB_RETRY_DELAY = 1.0      # Delay between retries

async def send_fire_effect_private(bot: Bot, chat_id: int):
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            payload = {"chat_id": chat_id, "text": "🔥", "message_effect_id": FIRE_EFFECT_ID}
            async with session.post(url, json=payload, timeout=5) as resp:
                res = await resp.json()
                if res.get("ok"):
                    msg_id = res["result"]["message_id"]
                    await asyncio.sleep(2)
                    del_url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage"
                    await session.post(del_url, json={"chat_id": chat_id, "message_id": msg_id})
    except Exception as e:
        log.warning(f"Fire Effect Trigger Failed: {e}")

async def send_channel_log(bot: Bot, text: str):
    try:
        await bot.send_message(LOG_CHANNEL_ID, text, parse_mode="HTML")
    except Exception as e:
        log.error(f"Failed to send channel log: {e}")

# ⚠️ FIXED: Firebase PUT with timeout aur retry logic
async def fb_put(fb_url: str, path: str, payload: dict, retry: int = 0) -> bool:
    """
    Firebase me data daalna WITH TIMEOUT aur RETRY LOGIC.
    Agar first attempt fail ho to max 3 baar try karega.
    """
    if not fb_url or not path:
        log.warning(f"[FB_PUT] Invalid FB URL or path")
        return False
    
    try:
        url = f"{fb_url}{path}"
        timeout = aiohttp.ClientTimeout(total=FB_TIMEOUT, connect=5, sock_read=FB_TIMEOUT)
        
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.put(url, json=payload) as resp:
                if resp.status in (200, 201):
                    log.debug(f"[FB_PUT] ✅ Success: {path[:50]}")
                    return True
                else:
                    log.warning(f"[FB_PUT] ❌ HTTP {resp.status}: {path[:50]}")
                    return False
                    
    except asyncio.TimeoutError:
        log.warning(f"[FB_PUT] ⏱ Timeout (attempt {retry+1}/{FB_RETRY_MAX}): {path[:50]}")
        
        # ⚠️ Retry logic: Agar timeout ho to dobara koshish karo
        if retry < FB_RETRY_MAX - 1:
            await asyncio.sleep(FB_RETRY_DELAY)
            return await fb_put(fb_url, path, payload, retry + 1)
        else:
            log.error(f"[FB_PUT] 🔴 Max retries exceeded: {path[:50]}")
            return False
            
    except Exception as e:
        log.error(f"[FB_PUT] 💥 Exception (attempt {retry+1}): {e}")
        
        # Retry on other errors too
        if retry < FB_RETRY_MAX - 1:
            await asyncio.sleep(FB_RETRY_DELAY)
            return await fb_put(fb_url, path, payload, retry + 1)
        else:
            return False

# ⚠️ FIXED: SMS bhejne ka function with retry
async def send_sms_via_device(fb_url: str, dev_id: str, sim_slot: int, to: str, message: str, retry: int = 0) -> bool:
    """
    Send one SMS via a Firebase device WITH RETRY LOGIC.
    Agar first time fail ho to 2 baar aur koshish karega.
    """
    unique_key = uuid.uuid4().hex
    path = f"/clients/{dev_id}/webhookEvent/sms_{unique_key}.json"
    payload = {
        "from":      sim_slot,
        "to":        to.strip(),
        "message":   message.strip(),
        "isSended":  False,
        "timestamp": int(time.time()),
        "uid":       unique_key,
    }
    
    # First attempt
    result = await fb_put(fb_url, path, payload, retry=0)
    
    # Agar pehla attempt fail ho to retry karo
    if not result and retry < 1:
        log.info(f"[SMS_RETRY] Retrying SMS to {to[:10]}... (attempt 2/2)")
        await asyncio.sleep(0.5)
        return await send_sms_via_device(fb_url, dev_id, sim_slot, to, message, retry + 1)
    
    return result

async def check_membership(bot: Bot, uid: int, channel_id: str) -> bool:
    try:
        chat_id = int(str(channel_id).strip())
        member = await bot.get_chat_member(chat_id, uid)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        log.error(f"Force Join check failed for channel {channel_id}: {e}")
        return False

async def user_joined_all(bot: Bot, uid: int, d: dict) -> tuple[bool, list]:
    if is_owner(uid, d):
        return True, []

    fj = d.get("force_join", {})
    if not fj.get("enabled", False):
        return True, []

    channels = fj.get("channels", [])
    missing = []
    for ch in channels:
        if ch.get("required", True):
            if not await check_membership(bot, uid, ch["id"]):
                missing.append(ch)
    return len(missing) == 0, missing

def force_join_text(missing: list) -> str:
    lines = [
        f"{em(EMOJI_CROSS, '⛔')} <b>{sc('bot use karne ke liye pehle join karein!')}</b>\n\n",
        f"{em(EMOJI_BELL, '👇')} ɴɪᴄʜᴇ ᴅɪʏᴇ ɢᴀʏᴇ ᴄʜᴀɴɴᴇʟs/ɢʀᴏᴜᴘs ᴊᴏɪɴ ᴋᴀʀᴇɪɴ:"
    ]
    for ch in missing:
        lines.append(f"\n• <a href='{ch['link']}'>{ch.get('title', 'Channel')}</a>")
    lines.append(f"\n\n<i>{sc('join karne ke baad /start karein ya refresh dabayein.')}</i>")
    return "\n".join(lines)

def force_join_kb(missing: list) -> InlineKeyboardMarkup:
    rows = []
    for ch in missing:
        rows.append([btn_url(f"ᴊᴏɪɴ {ch.get('title', 'Channel')}", ch["link"], EMOJI_BELL, "🔔", style="success")])
    rows.append([btn("ʀᴇғʀᴇsʜ / ᴄʜᴇᴄᴋ", "fj:check", EMOJI_GEAR, "🔄", style="primary")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def fmt_time(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M")

def fmt_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m {seconds % 60}s"

def progress_text(sent_ok: int, sent_fail: int, total: int, credits: int = None, speed: str = "⚡") -> str:
    """SMS progress message - accurately shows sent/failed/remaining"""
    remaining = total - sent_ok
    percentage = int((sent_ok / total * 100)) if total > 0 else 0
    
    text = (
        f"{em(EMOJI_ROCKET, '🚀')} <b>SMS BLAST IN PROGRESS</b>\n\n"
        f"{em(EMOJI_CHECK, '✅')} Sent Successfully: <b>{sent_ok}/{total}</b>\n"
        f"{em(EMOJI_CROSS, '❌')} Failed: <b>{sent_fail}</b>\n"
        f"{em(EMOJI_STAR, '⏳')} Remaining: <b>{remaining}</b>\n"
        f"📊 Progress: <code>{percentage}%</code> {'█' * (percentage // 5)}{' ' * (20 - percentage // 5)}\n"
        f"{em(EMOJI_ROCKET, '🚀')} Speed: <b>{speed}</b>\n"
    )
    
    if credits is not None:
        text += f"{em(EMOJI_MONEY, '💰')} Credits Left: <b>{credits}</b>\n"
    
    text += f"\n{em(EMOJI_BELL, '🔔')} Press <b>Stop</b> button to cancel sending."
    
    return text

def stop_send_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn(f"🛑 Stop Blast", "stop_send", EMOJI_CROSS, "", style="danger")]
    ])

def mask_number(number: str) -> str:
    if len(number) <= 4:
        return number
    return number[:2] + "*" * (len(number) - 4) + number[-2:]

# ⚠️ DUMMY FUNCTIONS - Replace with your actual implementation
def load() -> dict:
    return {"users": {}, "stats": {"total_sent": 0, "total_failed": 0}, "firebases": []}

def save(d: dict):
    pass

def is_owner(uid: int, d: dict) -> bool:
    return uid == MAIN_OWNER or uid in SUPER_ADMINS

def is_admin(uid: int, d: dict) -> bool:
    return is_owner(uid, d)

def get_user_credits(uid: int, d: dict) -> int:
    k = str(uid)
    return d.get("users", {}).get(k, {}).get("credits", 0)

def deduct_credits(uid: int, amount: int, d: dict):
    k = str(uid)
    if k not in d.get("users", {}):
        d["users"][k] = {}
    d["users"][k]["credits"] = d["users"][k].get("credits", 0) - amount

# ⚠️ SESSION TRACKING
class UserSession:
    def __init__(self, uid: int):
        self.uid = uid
        self.task = None
        self.cancelled = False
        self.number = ""
        self.blast_data = {}

USER_SESSIONS = {}
SESSIONS_LOCK = asyncio.Lock()

# ⚠️ FIXED: Main SMS Blast Function with proper retry aur timeout handling
async def run_sms_blast_with_progress(bot: Bot, msg: Message, uid: int, number: str, message: str, count: int, devices: list, speed: float = SPEED_DEFAULT):
    """
    Send SMS with PROPER retry logic aur timeout handling.
    Har SMS ko multiple baar try karega agar fail ho.
    """
    
    async with SESSIONS_LOCK:
        if uid in USER_SESSIONS:
            old_session = USER_SESSIONS[uid]
            if old_session.task and not old_session.task.done():
                await msg.answer(
                    f"{em(EMOJI_WARNING, '⚠️')} <b>Ek sending already chal rahi hai!</b>\n"
                    f"Pehle woh khatam hone do ya stop karein.",
                    parse_mode="HTML"
                )
                return
            del USER_SESSIONS[uid]

        session = UserSession(uid)
        session.number = number
        session.blast_data = load()
        USER_SESSIONS[uid] = session

    is_regular_user = not is_admin(uid, load()) and not is_owner(uid, load())
    current_credits = get_user_credits(uid, load()) if is_regular_user else None

    speed_label_display = "🚀 FAST" if speed == SPEED_FAST else "⚡ MEDIUM" if speed == SPEED_MEDIUM else "🐢 SLOW"

    total_target = count
    sent_ok = 0
    sent_fail = 0
    api_usage_delta = {}

    try:
        progress_msg = await msg.answer(
            progress_text(0, 0, total_target, current_credits, speed_label_display),
            reply_markup=stop_send_kb(),
            parse_mode="HTML"
        )
    except Exception as e:
        log.error(f"Failed to send progress message: {e}")
        async with SESSIONS_LOCK:
            if uid in USER_SESSIONS:
                del USER_SESSIONS[uid]
        return

    last_update_time = time.time()
    start_time = time.time()

    async def do_send():
        nonlocal sent_ok, sent_fail, last_update_time

        try:
            # Build sender slots
            senders = []
            for device in devices:
                fb_id = device.get("fb_id", "")
                fb_url = device.get("fb_url", "")
                dev_id = device.get("dev_id", "")
                if not fb_url or not dev_id:
                    continue
                sims = device.get("sims") or []
                if sims:
                    for s in sims:
                        slot = s.get("simSlotIndex", 0) if isinstance(s, dict) else 0
                        senders.append((fb_id, fb_url, dev_id, slot))
                else:
                    senders.append((fb_id, fb_url, dev_id, 0))

            if not senders:
                log.error(f"[BLAST] User {uid}: 0 sender slots")
                return

            log.info(f"[BLAST] User {uid}: target={total_target} senders={len(senders)} speed={speed}s")

            # Concurrency semaphore
            MAX_CONCURRENT = min(30, max(5, len(senders)))
            sem = asyncio.Semaphore(MAX_CONCURRENT)

            async def blast_one(fb_id: str, fb_url: str, dev_id: str, slot: int) -> bool:
                async with sem:
                    try:
                        # ⚠️ FIXED: Now has retry logic built-in
                        result = await send_sms_via_device(fb_url, dev_id, slot, number, message)
                        if result:
                            log.info(f"[BLAST] ✅ SMS sent to {mask_number(number)}")
                        else:
                            log.warning(f"[BLAST] ❌ SMS failed to {mask_number(number)}")
                        return result
                    except Exception as exc:
                        log.warning(f"[BLAST] Exception: {exc}")
                        return False

            # Main loop - batching with retry support
            remaining = total_target
            sender_idx = 0
            stall_count = 0
            MAX_STALL = 8  # Increased from 6 for slow connections

            while remaining > 0 and not session.cancelled:
                batch_size = min(len(senders), remaining)
                tasks = []
                meta = []
                
                for _ in range(batch_size):
                    fb_id, fb_url, dev_id, slot = senders[sender_idx % len(senders)]
                    tasks.append(blast_one(fb_id, fb_url, dev_id, slot))
                    meta.append(fb_id)
                    sender_idx += 1

                # Execute batch with timeout
                try:
                    results = await asyncio.wait_for(
                        asyncio.gather(*tasks, return_exceptions=True),
                        timeout=FB_TIMEOUT + 5.0  # Allow tasks to complete
                    )
                except asyncio.TimeoutError:
                    log.warning(f"[BLAST] Batch timeout for user {uid}")
                    results = [False] * len(tasks)

                batch_success = 0
                for i, res in enumerate(results):
                    ok = (res is True)
                    fb_id = meta[i]

                    if ok:
                        batch_success += 1
                        sent_ok += 1
                        remaining -= 1

                        if is_regular_user:
                            deduct_credits(uid, 1, session.blast_data)
                            session.blast_data["stats"]["total_sent"] = \
                                session.blast_data["stats"].get("total_sent", 0) + 1
                            k = str(uid)
                            if k in session.blast_data["users"]:
                                session.blast_data["users"][k]["uses"] = \
                                    session.blast_data["users"][k].get("uses", 0) + 1
                            session.blast_data.setdefault("sms_history", {}) \
                                .setdefault(k, []).append({
                                    "number": number,
                                    "message": message[:100],
                                    "timestamp": int(time.time()),
                                    "status": "sent"
                                })
                    else:
                        sent_fail += 1

                    if fb_id not in api_usage_delta:
                        api_usage_delta[fb_id] = {"sent": 0, "failed": 0}
                    api_usage_delta[fb_id]["sent" if ok else "failed"] += 1

                # Stall guard
                if batch_success == 0:
                    stall_count += 1
                    log.warning(f"[BLAST] Stall {stall_count}/{MAX_STALL} - 0 success")
                    if stall_count >= MAX_STALL:
                        log.error(f"[BLAST] Max stall reached - devices may be offline")
                        break
                else:
                    stall_count = 0

                # Progress update
                now = time.time()
                if now - last_update_time >= _PROGRESS_UPDATE_INTERVAL:
                    try:
                        await progress_msg.edit_text(
                            progress_text(sent_ok, sent_fail, total_target, current_credits, speed_label_display),
                            reply_markup=stop_send_kb(),
                            parse_mode="HTML"
                        )
                        last_update_time = now
                    except Exception as e:
                        log.warning(f"Progress update failed: {e}")

                # Speed delay - Slower by default
                await asyncio.sleep(speed)

        except Exception as e:
            log.error(f"[BLAST] do_send error: {e}")
        finally:
            elapsed = int(time.time() - start_time)
            try:
                await progress_msg.edit_text(
                    f"{em(EMOJI_CHECK, '✅')} <b>BLAST COMPLETED!</b>\n\n"
                    f"{em(EMOJI_ROCKET, '🚀')} Total Target: <b>{total_target}</b>\n"
                    f"{em(EMOJI_CHECK, '✅')} Sent: <b>{sent_ok}</b>\n"
                    f"{em(EMOJI_CROSS, '❌')} Failed: <b>{sent_fail}</b>\n"
                    f"{em(EMOJI_BELL, '⏱')} Time Taken: <b>{fmt_duration(elapsed)}</b>\n"
                    f"{em(EMOJI_ROCKET, '🚀')} Speed: <b>{speed_label_display}</b>\n\n"
                    f"<i>Yeh final status hai. SMS bhej chuke hain.</i>",
                    reply_markup=None,
                    parse_mode="HTML"
                )
            except Exception as e:
                log.warning(f"Final message update failed: {e}")

    # Run the blast
    task = asyncio.create_task(do_send())
    session.task = task
    try:
        await task
    finally:
        async with SESSIONS_LOCK:
            if uid in USER_SESSIONS:
                del USER_SESSIONS[uid]

# ===== KEEP-ALIVE SERVER =====
KEEP_ALIVE_PORT = int(os.getenv("PORT", 8080))
APP_URL = os.getenv("APP_URL", "")
_BOT_START_TIME = time.time()

async def _ka_ping(request):
    uptime = int(time.time() - _BOT_START_TIME)
    return aiohttp_web.Response(text=f"✅ Bot Online | Uptime: {uptime}s")

async def start_keep_alive():
    app = aiohttp_web.Application()
    app.router.add_get("/", _ka_ping)
    app.router.add_get("/health", _ka_ping)
    app.router.add_get("/ping", _ka_ping)
    runner = aiohttp_web.AppRunner(app)
    await runner.setup()
    site = aiohttp_web.TCPSite(runner, "0.0.0.0", KEEP_ALIVE_PORT)
    await site.start()
    log.info(f"Keep-Alive server on port {KEEP_ALIVE_PORT}")

# Router setup (minimal for testing)
R = Router()

async def main():
    global _BOT_START_TIME
    _BOT_START_TIME = time.time()

    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is missing.")

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(R)
    me = await bot.get_me()
    log.info(f"@{me.username} — SMS Blast Bot {_VERSION} started!")

    await start_keep_alive()

    try:
        await bot.send_message(
            MAIN_OWNER,
            f"{em(EMOJI_ROCKET, '🚀')} <b>SMS Blast Bot {_VERSION} FIXED VERSION Online!</b>\n"
            f"<b>Improvements:</b>\n"
            f"✅ Firebase timeout: {FB_TIMEOUT}s\n"
            f"✅ Retry attempts: {FB_RETRY_MAX}\n"
            f"✅ Slower SMS speed (more reliable)\n"
            f"✅ Better error handling\n"
            f"@{me.username}",
            parse_mode="HTML"
        )
    except Exception as e:
        log.warning(f"Owner notify: {e}")

    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(main())
