import asyncio
import html
import json
import logging
import os
import random
import re
import string
import time
from datetime import datetime

from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    ChatMemberUpdated,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from aiogram.exceptions import TelegramBadRequest

from texts import LOCALES, ACHIEVEMENTS
from events import (
    ensure_event_state,
    get_active_event,
    register_event_handlers,
    reward_event_currency_after_battle,
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID_VALUE = os.getenv("CHANNEL_ID")
ADMIN_IDS_VALUE = os.getenv("ADMIN_IDS") or os.getenv("TELEGRAM_ADMIN_ID")

GROUP_ID_VALUE = os.getenv("GROUP_ID", "-1002832219010")
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/MOD_rak")

if not BOT_TOKEN:
    raise RuntimeError("Missing required environment variable: BOT_TOKEN")

CHANNEL_ID = None
if CHANNEL_ID_VALUE:
    try:
        CHANNEL_ID = int(CHANNEL_ID_VALUE)
    except ValueError:
        CHANNEL_ID = CHANNEL_ID_VALUE

ADMIN_IDS = []
if ADMIN_IDS_VALUE:
    try:
        ADMIN_IDS = [int(a.strip()) for a in ADMIN_IDS_VALUE.split(",") if a.strip()]
    except ValueError:
        raise RuntimeError("ADMIN_IDS must contain numeric Telegram IDs")

TARGET_CHAT_IDS = []
if GROUP_ID_VALUE:
    try:
        TARGET_CHAT_IDS.append(int(GROUP_ID_VALUE))
    except ValueError:
        TARGET_CHAT_IDS.append(GROUP_ID_VALUE)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

FILE_IDS_PATH = "file_ids.json"
FILE_IDS = {}
USERS_PATH = "users.json"
USERS = {}
BANNED_PATH = "banned.json"
BANNED = {}
FALLBACKS_PATH = "fallbacks.json"
FALLBACKS = {}

TIER_ROMAN = {
    1: "I", 2: "II", 3: "III", 4: "IV", 5: "V",
    6: "VI", 7: "VII", 8: "VIII", 9: "IX", 10: "X"
}


def tier_label(tier: int) -> str:
    return f"{TIER_ROMAN.get(tier, str(tier))} ур."


TANKS_DB = {}
try:
    with open("tanks.json", encoding="utf-8") as f:
        TANKS_DB = json.load(f)
    logger.info(f"Успешно загружено {len(TANKS_DB)} танков.")
except Exception as e:
    logger.error(f"Ошибка загрузки tanks.json: {e}")
    TANKS_DB = {"FV215B 183": {"tier": 10, "hp": 1850, "damage": 930, "pen": 300, "armor": 152, "reload": 18.5, "price": 0}}


def get_tank_tier(tank_name: str) -> int:
    return int(TANKS_DB.get(tank_name, {}).get("tier", 10))


ROOMS = {}


class UserState(StatesGroup):
    awaiting_nickname = State()
    awaiting_mod_suggestion = State()
    awaiting_fun = State()
    awaiting_bug_report = State()
    awaiting_question = State()
    awaiting_team_apply = State()
    awaiting_appeal = State()
    awaiting_friend_msg = State()
    in_battle = State()
    choosing_size = State()
    entering_code = State()


MOD_NAMES = {
    "old_font": {"ru": "Старый шрифт", "be": "Стары шрыфт", "en": "Old Font"},
    "old_medals": {"ru": "Старые медали", "be": "Старыя медалі", "en": "Old Medals"},
    "old_ui": {"ru": "Старый UI ангара", "be": "Стары UI ангара", "en": "Old Hangar UI"},
}

RANKS = {
    1:  ("Новичок", 0, 0, "user"), 2:  ("Гость", 100, 0, "user"), 3:  ("Освоившийся", 300, 0, "user"),
    4:  ("Постоянный", 700, 0, "user"), 5:  ("Ветеран", 1500, 0, "user"), 6:  ("Активный", 3000, 0, "user"),
    7:  ("Знаток", 6000, 0, "user"), 8:  ("Эксперт", 12000, 0, "user"), 9:  ("Гуру", 24000, 0, "user"),
    10: ("Легенда", 48000, 0, "user"), 11: ("Идейный", 0, 1, "modder"), 12: ("Юный мододел", 0, 3, "modder"),
    13: ("Мододел", 0, 5, "modder"), 14: ("Старший мододел", 0, 10, "modder"), 15: ("Мастер модов", 0, 20, "modder"),
    16: ("Тестер", 0, 0, "staff"), 17: ("Младший модератор", 0, 0, "staff"), 18: ("Модератор", 0, 0, "staff"),
    19: ("Администратор", 0, 0, "staff"), 20: ("Вице-владелец", 0, 0, "staff"), 21: ("Владелец", 0, 0, "staff"),
}


def default_user_data():
    return {
        "lang": None, "nickname": None, "xp": 0, "rank_id": 1, "downloads": 0, "ideas": 0, "questions": 0, "bans": 0,
        "achievements": [], "registered": datetime.now().strftime("%Y-%m-%d"), "appeal_pending": False,
        "tanks": ["FV215B 183"], "selected_tank": "FV215B 183", "battles": 0, "wins": 0, "losses": 0,
        "friends": [], "friend_requests": [], "last_anim_msg": None, "containers": 0, "events": {}
    }


def ensure_user(uid: str) -> dict:
    uid = str(uid)
    if uid not in USERS:
        USERS[uid] = default_user_data()
    return USERS[uid]


def get_rank_info(rank_id: int):
    return RANKS.get(rank_id, RANKS[1])


def check_rank_up(user_id: str):
    data = USERS.get(user_id)
    if not data:
        return None
    current_id = data["rank_id"]
    next_id = current_id + 1
    if next_id not in RANKS:
        return None
    _, req_xp, req_ideas, rank_type = RANKS[next_id]
    if rank_type != "user":
        return None
    if data["xp"] >= req_xp and data["ideas"] >= req_ideas:
        data["rank_id"] = next_id
        save_users()
        return RANKS[next_id][0]
    return None


def add_xp(user_id: str, amount: int):
    data = ensure_user(user_id)
    data["xp"] += amount
    save_users()


def unlock_achievement(user_id: str, ach_key: str):
    data = USERS.get(user_id)
    if data and ach_key not in data["achievements"]:
        data["achievements"].append(ach_key)
        save_users()
        return ACHIEVEMENTS.get(ach_key)
    return None


def get_display_name(uid: str) -> str:
    user = USERS.get(str(uid), {})
    nick = user.get("nickname")
    if nick:
        return html.escape(str(nick))
    return f"Танкист_{str(uid)[-4:]}"


def load_data():
    global FILE_IDS, USERS, BANNED, FALLBACKS
    FILE_IDS = {
        "old_font.rar": "BQACAgIAAyEFAASo0DuCAAPRaudEoy_WaUJytv6Ax-5vHj49Zk8AAqqZAAJuI4FJZH-8dxswqq09BA",
        "old_medals.zip": "BQACAgIAAyEFAASo0DuCAAPQaudEo89jj1q6kdFa5l4mjYzZCmoAAqmZAAJuI4FJly1Z9B-lN4E9BA",
        "old_ui.rar": "BQACAgIAAyEFAASo0DuCAAPSaudEozVgaEGz-USX1kCO8mw9czsAAp-qAAJqFCBLsufG1Xs4z3E9BA",
        "container_open.gif": "CgACAgIAAxkBAAEkuYhq_rVAcm5eopqKZ30jCMZM1yKjfQACDZoAAuC5MEvOX4UijG052z0E"
    }
    try:
        with open(FILE_IDS_PATH, encoding="utf-8") as f:
            FILE_IDS.update(json.load(f))
    except Exception:
        pass
    try:
        with open(USERS_PATH, encoding="utf-8") as f:
            raw = json.load(f)
            for uid, val in raw.items():
                if isinstance(val, str):
                    new_data = default_user_data()
                    new_data["lang"] = val
                    USERS[uid] = new_data
                else:
                    base = default_user_data()
                    base.update(val)
                    if "lang" not in val or val["lang"] not in ["ru", "be", "en"]:
                        base["lang"] = None
                    USERS[uid] = base
    except Exception:
        pass
    try:
        with open(BANNED_PATH, encoding="utf-8") as f:
            BANNED.update(json.load(f))
    except Exception:
        pass
    try:
        fallback_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fallbacks.json")
        if not os.path.exists(fallback_file_path):
            fallback_file_path = "fallbacks.json"
        with open(fallback_file_path, encoding="utf-8") as f:
            FALLBACKS.update(json.load(f))
    except Exception as e:
        logger.error(f"Ошибка загрузки fallbacks.json: {e}")


def save_file_ids():
    with open(FILE_IDS_PATH, "w", encoding="utf-8") as f:
        json.dump(FILE_IDS, f, ensure_ascii=False, indent=2)


def save_users():
    with open(USERS_PATH, "w", encoding="utf-8") as f:
        json.dump(USERS, f, ensure_ascii=False, indent=2)


def save_banned():
    with open(BANNED_PATH, "w", encoding="utf-8") as f:
        json.dump(BANNED, f, ensure_ascii=False, indent=2)


load_data()


async def safe_edit_or_send(message: Message, text: str, reply_markup=None, parse_mode: str | None = "HTML"):
    try:
        await message.edit_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
    except Exception:
        try:
            await message.delete()
        except Exception:
            pass
        await message.answer(text, parse_mode=parse_mode, reply_markup=reply_markup)


def tr(user_id: str, key: str, **kwargs) -> str:
    data = USERS.get(user_id)
    lang = data["lang"] if data and data.get("lang") else "ru"
    text = LOCALES.get(lang, LOCALES["ru"]).get(key, f"[{key}]")
    return text.format(**kwargs) if kwargs else text


def is_banned(user_id: str) -> tuple[bool, dict]:
    if user_id not in BANNED:
        return False, {}
    info = BANNED[user_id]
    until_str = info.get("until", "")
    if until_str == "never":
        return True, info
    try:
        until = datetime.strptime(until_str, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return False, {}
    if datetime.now() >= until:
        del BANNED[user_id]
        save_banned()
        return False, {}
    return True, info


async def check_ban_and_block(message: Message) -> bool:
    uid = str(message.from_user.id)
    banned, _ = is_banned(uid)
    if banned:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(uid, "appeal_btn"), callback_data="appeal_ban")]])
        await message.answer(tr(uid, "banned_bot_text"), reply_markup=kb)
        return True
    return False


def get_main_keyboard(user_id: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=tr(user_id, "btn_mods")), KeyboardButton(text=tr(user_id, "btn_fun"))],
            [KeyboardButton(text=tr(user_id, "btn_profile")), KeyboardButton(text=tr(user_id, "btn_help"))],
            [KeyboardButton(text=tr(user_id, "btn_feedback")), KeyboardButton(text=tr(user_id, "btn_misc"))],
        ],
        resize_keyboard=True,
    )


def get_feedback_keyboard(user_id: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=tr(user_id, "btn_suggest"))],
            [KeyboardButton(text=tr(user_id, "btn_bug")), KeyboardButton(text=tr(user_id, "btn_question"))],
            [KeyboardButton(text=tr(user_id, "btn_back"))],
        ],
        resize_keyboard=True,
    )


def get_mods_keyboard(user_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Старый шрифт (v1.0)", callback_data="mod_old_font")],
        [InlineKeyboardButton(text="Старые медали (v1.0)", callback_data="mod_old_medals")],
        [InlineKeyboardButton(text="Старый UI ангара (v3.0)", callback_data="mod_old_ui")],
    ])


def get_mod_info_keyboard(user_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(user_id, "btn_info"), callback_data="mod_old_ui_info")]])


ALL_MENU_BUTTONS = set()
for lang_data in LOCALES.values():
    for k, v in lang_data.items():
        if k.startswith("btn_") or (k.startswith("misc_") and k.endswith("_btn")) or (k.startswith("help_") and k.endswith("_btn")):
            ALL_MENU_BUTTONS.add(v)

EASTER_EGGS = {
    "рак": "Сам такой 🦀", "crab": "Сам такой 🦀", "sudo": "Доступ запрещён, хорошая попытка 😎", "sudo su": "Ты кто такой? Иди сюда",
    "старый": "Старый это классика, ты наш человек", "old": "Old is classic, you are our kind of person",
    "картошка": "Сервера картошки это отдельный вид искусства", "potato": "Potato servers are a separate art form",
    "танк": "Какой танк? У нас тут моды, а не полигон", "tank": "What tank? We have mods here, not a training ground",
    "лол": "Лол принят, возвращайся с идеями", "lol": "Lol accepted, come back with ideas",
    "ааа": "Тихо, я тут", "мод": "Мод? Тогда тебе в «Моды» 👇", "mod": "Mod? Then go to 'Mods' 👇",
    "привет": "Привет, выбирай раздел ниже", "hello": "Hello, choose a section below", "hi": "Hi, what do you want? Buttons below",
    "прив": "Прив, чё хотел? Кнопки внизу", "здарова": "Здарова, чё по модам?",
    "как дела": "Всё отлично, моды пилим, а у тебя?", "how are you": "Doing great, making mods, and you?",
    "кто ты": "Я бот MOD_rak.rar, раздаю моды и собираю идеи", "who are you": "I am the MOD_rak.rar bot, I share mods and collect ideas",
    "ты бот": "Да, и горжусь этим, нажми кнопку", "помоги": "Кнопка «Помощь» в меню ниже 👇", "help": "The 'Help' button is in the menu below 👇",
    "где моды": "Кнопка «Моды» в меню ниже 👇", "where are mods": "The 'Mods' button is in the menu below 👇",
    "скачать": "Кнопка «Моды» в меню ниже 👇", "download": "The 'Mods' button is in the menu below 👇",
    "3 часа ночи": "Ты чего не спишь? Иди спать, моды подождут", "3 часа": "Ты чего не спишь? Иди спать, моды подождут",
    "ракета": "Ракета не тут, у нас раки 🦀", "google": "Гугли сам, я моды раздаю", "яндекс": "Яндекс не поможет, только кнопки ниже",
}
EASTER_EGG_HITS = {}


def find_file_id(base_name: str):
    base_lower = base_name.lower()
    if base_name in FILE_IDS:
        return base_name, FILE_IDS[base_name]
    for stored_name, file_id in FILE_IDS.items():
        if stored_name.rsplit(".", 1)[0].lower() == base_lower:
            return stored_name, file_id
    return None


async def check_subscription(user_id: int) -> bool:
    if not CHANNEL_ID:
        return True
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        if member.status in ["creator", "administrator", "member"]:
            return True
    except TelegramBadRequest as e:
        logger.error(f"Ошибка проверки подписки: {e}")
    return False


async def send_mod_file(chat_id: int, base_name: str, reply_markup=None):
    result = find_file_id(base_name)
    if not result:
        await bot.send_message(chat_id, tr(str(chat_id), "unavailable_text"))
        return
    _, file_id = result
    await bot.send_document(chat_id, file_id, reply_markup=reply_markup)


async def forward_to_admins(message: Message, header: str):
    if not TARGET_CHAT_IDS:
        return
    for chat_id in TARGET_CHAT_IDS:
        try:
            await bot.send_message(chat_id, header, parse_mode="HTML")
            await message.forward(chat_id)
        except Exception as exc:
            logger.error(f"Не удалось отправить в {chat_id}. Ошибка: {exc}")


def format_user_header(user) -> str:
    safe_name = html.escape(user.full_name or "Без имени")
    username_str = f"@{html.escape(user.username)}" if user.username else "без юзернейма"
    return f"👤 {safe_name} ({username_str})\n🆔 <code>{user.id}</code>"


def build_profile_message(uid: str) -> tuple[str, InlineKeyboardMarkup]:
    data = ensure_user(uid)
    rank_name, _, _, _ = get_rank_info(data["rank_id"])

    next_id = data["rank_id"] + 1
    if next_id in RANKS:
        _, next_xp, next_ideas, next_type = RANKS[next_id]
        if next_type == "user":
            progress_text = tr(uid, "profile_next", xp_left=max(0, next_xp - data["xp"]), ideas_left=max(0, next_ideas - data["ideas"]))
        else:
            progress_text = tr(uid, "profile_next_manual")
    else:
        progress_text = "Максимальное звание"

    ach_text = (
        tr(uid, "profile_achievements", list="\n".join([f"• {ACHIEVEMENTS.get(a, a)}" for a in data["achievements"]]))
        if data["achievements"]
        else tr(uid, "profile_no_achievements")
    )

    safe_nick = html.escape(data["nickname"]) if data.get("nickname") else "Не задан"
    sel_tank = data.get("selected_tank", "FV215B 183")
    sel_tier = get_tank_tier(sel_tank)
    tank_display = f"{html.escape(sel_tank)} ({tier_label(sel_tier)})"

    ev = get_active_event()
    ev_st = ensure_event_state(data, ev["id"])
    event_line = f"\n🎪 {html.escape(ev['title'])}: <b>{ev_st['currency']}/{ev['goal']}</b> {ev['currency_emoji']}"

    text = (
        f"{tr(uid, 'profile_title')}\n{tr(uid, 'profile_nick', nick=safe_nick)}\n{tr(uid, 'profile_id', uid=uid)}\n\n"
        f"{tr(uid, 'profile_rank', rank=rank_name)}\n{tr(uid, 'profile_xp', xp=data['xp'])}{event_line}\n"
        f"{tr(uid, 'profile_stats', battles=data.get('battles', 0), wins=data.get('wins', 0), losses=data.get('losses', 0), downloads=data['downloads'], ideas=data['ideas'], questions=data['questions'], bans=data['bans'])}\n"
        f"{tr(uid, 'profile_tank', tank=tank_display)}\n{progress_text}\n\n{ach_text}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚔️ Бои", callback_data="battle_menu"), InlineKeyboardButton(text="🚜 Ангар", callback_data="hangar_menu")],
        [InlineKeyboardButton(text=tr(uid, "shop_btn"), callback_data="shop_menu"), InlineKeyboardButton(text=f"🎪 Ивент ({ev['currency_emoji']})", callback_data=f"ev_open_{ev['id']}")],
        [InlineKeyboardButton(text=tr(uid, "btn_friends"), callback_data="friends_menu"), InlineKeyboardButton(text=tr(uid, "btn_invite"), callback_data="invite_friend")]
    ])
    return text, kb


# --- ПРОФИЛЬ И АНГАР ---
@dp.message(Command("profile"))
async def cmd_profile(message: Message, state: FSMContext):
    await state.clear()
    if await check_ban_and_block(message):
        return
    uid = str(message.from_user.id)

    if uid not in USERS:
        await cmd_start(message, state)
        return

    text, kb = build_profile_message(uid)
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@dp.message(F.text.in_([LOCALES["ru"]["btn_profile"], LOCALES["be"]["btn_profile"], LOCALES["en"]["btn_profile"]]))
async def btn_profile_click(message: Message, state: FSMContext):
    await cmd_profile(message, state)


@dp.callback_query(F.data == "back_to_profile")
async def cb_back_to_profile(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    uid = str(callback.from_user.id)
    text, kb = build_profile_message(uid)
    await safe_edit_or_send(callback.message, text, reply_markup=kb, parse_mode="HTML")


@dp.callback_query(F.data == "hangar_menu")
async def cb_hangar_menu(callback: CallbackQuery):
    uid = str(callback.from_user.id)
    data = ensure_user(uid)
    owned = data.get("tanks", ["FV215B 183"])
    selected = data.get("selected_tank", "FV215B 183")

    sorted_owned = sorted(owned, key=lambda t: (get_tank_tier(t), t))

    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for t in sorted_owned:
        t_tier = get_tank_tier(t)
        mark = "✅ " if t == selected else ""
        kb.inline_keyboard.append([
            InlineKeyboardButton(text=f"{mark}[{TIER_ROMAN.get(t_tier, t_tier)}] {t}", callback_data=f"hangar_select_{t}")
        ])
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 В профиль", callback_data="back_to_profile")])

    text = (
        f"🚜 <b>Твой ангар ({len(owned)} шт.)</b>\n\n"
        f"Текущий танк: <b>{html.escape(selected)}</b> ({tier_label(get_tank_tier(selected))})\n"
        f"Выбери танк для боёв:"
    )
    await safe_edit_or_send(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data.startswith("hangar_select_"))
async def cb_hangar_select(callback: CallbackQuery):
    uid = str(callback.from_user.id)
    tank_name = callback.data.replace("hangar_select_", "")
    data = ensure_user(uid)
    if tank_name in data.get("tanks", []):
        data["selected_tank"] = tank_name
        save_users()
        await callback.answer(f"Выбран танк: {tank_name} ({tier_label(get_tank_tier(tank_name))})", show_alert=True)
    await cb_hangar_menu(callback)


@dp.callback_query(F.data == "invite_friend")
async def cb_invite_friend(callback: CallbackQuery):
    uid = str(callback.from_user.id)
    me = await bot.get_me()
    ref_link = f"https://t.me/{me.username}?start=ref_{uid}"
    await callback.message.answer(
        f"🤝 <b>Пригласи друга и получите по +150 XP!</b>\n\nТвоя реферальная ссылка:\n<code>{ref_link}</code>",
        parse_mode="HTML"
    )
    await callback.answer()


# --- ДРУЗЬЯ ---
@dp.callback_query(F.data == "friends_menu")
async def cb_friends_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    uid = str(callback.from_user.id)
    data = ensure_user(uid)
    text = tr(uid, "friends_title")
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    if data.get("friend_requests"):
        text += "\n" + tr(uid, "friends_requests") + "\n"
        for req_uid in data["friend_requests"]:
            kb.inline_keyboard.append([
                InlineKeyboardButton(text=f"✅ {get_display_name(req_uid)}", callback_data=f"friend_accept_{req_uid}"),
                InlineKeyboardButton(text="❌", callback_data=f"friend_decline_{req_uid}")
            ])
    text += "\n" + tr(uid, "friends_list") + "\n"
    if data.get("friends"):
        for f_uid in data["friends"]:
            kb.inline_keyboard.append([InlineKeyboardButton(text=f"💬 {get_display_name(f_uid)}", callback_data=f"friend_msg_{f_uid}")])
    else:
        text += tr(uid, "friends_empty")
    kb.inline_keyboard.append([InlineKeyboardButton(text=tr(uid, "btn_back"), callback_data="back_to_profile")])
    await safe_edit_or_send(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data.startswith("friend_accept_"))
async def cb_friend_accept(callback: CallbackQuery, state: FSMContext):
    uid = str(callback.from_user.id)
    req_uid = callback.data.replace("friend_accept_", "")
    data = ensure_user(uid)
    if req_uid in data.get("friend_requests", []):
        data["friend_requests"].remove(req_uid)
        if req_uid not in data.setdefault("friends", []):
            data["friends"].append(req_uid)
        req_data = ensure_user(req_uid)
        if uid not in req_data.setdefault("friends", []):
            req_data["friends"].append(uid)
        save_users()
        await callback.answer(tr(uid, "friend_req_accept", name=get_display_name(req_uid)), show_alert=True)
        try:
            await bot.send_message(int(req_uid), f"✅ <b>{get_display_name(uid)}</b> принял твою заявку в друзья!", parse_mode="HTML")
        except Exception:
            pass
    await cb_friends_menu(callback, state)


@dp.callback_query(F.data.startswith("friend_decline_"))
async def cb_friend_decline(callback: CallbackQuery, state: FSMContext):
    uid = str(callback.from_user.id)
    req_uid = callback.data.replace("friend_decline_", "")
    data = ensure_user(uid)
    if req_uid in data.get("friend_requests", []):
        data["friend_requests"].remove(req_uid)
        save_users()
        await callback.answer(tr(uid, "friend_req_decline"), show_alert=True)
    await cb_friends_menu(callback, state)


@dp.callback_query(F.data.startswith("friend_req_"))
async def cb_friend_req(callback: CallbackQuery):
    sender_uid = str(callback.from_user.id)
    target_uid = callback.data.replace("friend_req_", "")
    if target_uid == sender_uid:
        await callback.answer("Это ты сам!", show_alert=True)
        return
    target_data = USERS.get(target_uid)
    if not target_data:
        await callback.answer("Игрок не найден", show_alert=True)
        return
    if sender_uid in target_data.get("friends", []):
        await callback.answer("Вы уже друзья!", show_alert=True)
        return
    if sender_uid in target_data.get("friend_requests", []):
        await callback.answer("Заявка уже отправлена!", show_alert=True)
        return
    target_data.setdefault("friend_requests", []).append(sender_uid)
    save_users()
    try:
        await bot.send_message(
            int(target_uid),
            f"🔔 Тебе пришла заявка в друзья от <b>{get_display_name(sender_uid)}</b>!\nЗайди в Профиль -> Друзья.",
            parse_mode="HTML"
        )
    except Exception:
        pass
    await callback.answer(tr(sender_uid, "friend_req_sent"), show_alert=True)


@dp.callback_query(F.data.startswith("friend_msg_"))
async def cb_friend_msg(callback: CallbackQuery, state: FSMContext):
    target_uid = callback.data.replace("friend_msg_", "")
    await state.set_state(UserState.awaiting_friend_msg)
    await state.update_data(friend_target=target_uid)
    await callback.message.answer(tr(str(callback.from_user.id), "friend_msg_prompt", name=get_display_name(target_uid)), parse_mode="HTML")
    await callback.answer()


@dp.message(UserState.awaiting_friend_msg, ~F.text.in_(ALL_MENU_BUTTONS))
async def process_friend_msg(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("Пожалуйста, отправь текстовое сообщение.")
        return
    data = await state.get_data()
    target_uid = data.get("friend_target")
    uid = str(message.from_user.id)
    msg_text = html.escape(message.text)
    await state.clear()
    if not target_uid:
        return
    try:
        await bot.send_message(
            int(target_uid),
            tr(target_uid, "friend_msg_received", name=get_display_name(uid), text=msg_text),
            parse_mode="HTML"
        )
        await message.answer(tr(uid, "friend_msg_sent"), reply_markup=get_main_keyboard(uid))
        user_data = ensure_user(uid)
        if "social" not in user_data["achievements"]:
            user_data["achievements"].append("social")
            save_users()
    except Exception:
        await message.answer("Не удалось отправить (возможно, пользователь заблокировал бота).", reply_markup=get_main_keyboard(uid))


# --- МАГАЗИН ---
CONTAINERS_DB = {
    "ussr": {
        "name": "📦 Контейнер СССР",
        "price": 2000,
        "tanks": [
            "Т-62А", "Об. 907", "Об. 140", "Т-22 ср.", "Об. 430Б",
            "ИС-7", "ИС-4", "IS-3", "KV-4", "T-54",
            "KV-2", "SU-152", "ISU-152", "ST-I", "T-10", "Object 704"
        ],
    },
    "germany": {
        "name": "📦 Контейнер Германии",
        "price": 2000,
        "tanks": [
            "Leopard 1", "E 50 M", "Kpz 50 t", "Maus", "E 100",
            "E 75", "VK 45.02 B", "Tiger II", "Panther II", "JgPz E 100",
            "Tiger (P)", "Rhm.-Borsig Waffenträger", "Jagdtiger", "Grille 15"
        ],
    },
    "usa": {
        "name": "📦 Контейнер США",
        "price": 2000,
        "tanks": [
            "M48 Patton", "M60", "T110E5", "T57 Heavy", "T29",
            "T32", "T34", "Pershing", "T69", "T95E2",
            "T95", "T54E1", "T30", "AMX 13 105", "Sheridan"
        ],
    },
    "uk": {
        "name": "📦 Контейнер Британии",
        "price": 2000,
        "tanks": [
            "FV4202", "FV4005", "FV215b (183)", "Conway", "Cromwell",
            "Centurion 7/1", "AT 15", "Charioteer", "Black Prince", "Tortoise",
            "Super Conqueror"
        ],
    },
    "france": {
        "name": "📦 Контейнер Франции",
        "price": 2000,
        "tanks": [
            "AMX 50 B", "AMX M4 54", "Foch B", "Batchat 25t", "AMX 13 90",
            "AMX 50 100", "Lorraine 40 t", "AMX 13 75", "BDR G1 B", "ARL 44",
            "AMX 50 120", "Foch 155"
        ],
    },
    "asia": {
        "name": "📦 Контейнер Азии",
        "price": 2000,
        "tanks": [
            "Type 5 Heavy", "STB-1", "WZ-121", "121B", "Type 61",
            "WZ-120", "Chi-To", "Chi-Ri", "Type 58", "Ha-Go",
            "113", "WZ-111 5A", "Ho-Ri Type III", "Type 71"
        ],
    },
    "europe": {
        "name": "📦 Контейнер Европы",
        "price": 2000,
        "tanks": [
            "Progetto 65", "TVP T 50/51", "CS-63", "Carro 45t", "Lion",
            "Object 263", "T110E3", "T110E4", "FV217 Badger", "Object 705A",
            "Emil II", "Kranvagn", "Minotauro", "M-VI-Yoh", "Vz. 55"
        ],
    },
    "premium": {
        "name": "💎 Премиум контейнер",
        "price": 5000,
        "tanks": [
            "Object 277", "Object 907", "M60", "121B", "Carro 45t",
            "T95E2", "IS-6", "T26E4 SuperPershing", "Type 59", "T-34-85 Рыжий",
            "Obj. 252U", "Chimera", "T54E2 Shark", "Škoda T 56", "Progetto 46", "Rheinmetall Skorpion G"
        ],
    },
    "top": {
        "name": "🏆 Топовый контейнер (X ур.)",
        "price": 8000,
        "tanks": [
            "IS-7", "Maus", "E 100", "T110E5", "T57 Heavy",
            "FV215B 183", "FV4005", "Object 268", "Leopard 1", "AMX 50 B"
        ],
    },
    "secret": {
        "name": "🕶 Секретный контейнер",
        "price": 10000,
        "tanks": [
            "Type 5 Heavy", "FV4005", "Object 277", "Kpz 50 t",
            "VK 90.01 (P)", "Chieftain Mk. 6",
            "Smasher", "Helsing", "Dracula", "Action X"
        ],
    },
}


@dp.callback_query(F.data == "shop_menu")
async def cb_shop_menu(callback: CallbackQuery):
    uid = str(callback.from_user.id)
    data = ensure_user(uid)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Танки по уровням (I–X)", callback_data="shop_tanks_menu")],
        [InlineKeyboardButton(text="📦 Контейнеры", callback_data="shop_containers_menu")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_profile")]
    ])
    text = tr(uid, "shop_title", xp=data["xp"]) + "\n\nВыбери раздел:"
    await safe_edit_or_send(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "shop_tanks_menu")
async def cb_shop_tanks_menu(callback: CallbackQuery):
    uid = str(callback.from_user.id)
    data = ensure_user(uid)
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    row = []
    for t in range(1, 11):
        row.append(InlineKeyboardButton(text=f"{TIER_ROMAN[t]} ур.", callback_data=f"shop_tier_{t}"))
        if len(row) == 5:
            kb.inline_keyboard.append(row)
            row = []
    if row:
        kb.inline_keyboard.append(row)
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="shop_menu")])
    text = f"🛒 <b>Магазин танков</b>\n\nТвой баланс: <b>{data['xp']} XP</b>\nВыбери уровень техники (I–X):"
    await safe_edit_or_send(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data.startswith("shop_tier_"))
async def cb_shop_tier(callback: CallbackQuery):
    uid = str(callback.from_user.id)
    tier = int(callback.data.replace("shop_tier_", ""))
    data = ensure_user(uid)
    owned = data.get("tanks", [])

    tier_tanks = [
        (name, stats) for name, stats in TANKS_DB.items()
        if int(stats.get("tier", 10)) == tier and not stats.get("exclusive", False)
    ]
    tier_tanks.sort(key=lambda x: x[1].get("price", 0))

    if not tier_tanks:
        await callback.answer(f"На {tier_label(tier)} нет доступных танков.", show_alert=True)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for name, stats in tier_tanks[:12]:
        prefix = "✅ " if name in owned else ""
        kb.inline_keyboard.append([
            InlineKeyboardButton(text=f"{prefix}{name} ({stats.get('price', 0)} XP)", callback_data=f"shop_view_{name}")
        ])
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 К выбору уровня", callback_data="shop_tanks_menu")])

    text = f"🛒 <b>Танки {tier_label(tier)}</b>\n\nТвой баланс: <b>{data['xp']} XP</b>\nВыбери танк:"
    await safe_edit_or_send(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "shop_containers_menu")
async def cb_shop_containers_menu(callback: CallbackQuery):
    uid = str(callback.from_user.id)
    data = ensure_user(uid)
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for c_id, c_data in CONTAINERS_DB.items():
        kb.inline_keyboard.append([InlineKeyboardButton(text=f"{c_data['name']} ({c_data['price']} XP)", callback_data=f"shop_container_view_{c_id}")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="shop_menu")])
    text = f"📦 <b>Контейнеры</b>\n\nТвой баланс: <b>{data['xp']} XP</b>\nВыбери контейнер:"
    await safe_edit_or_send(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data.startswith("shop_container_view_"))
async def cb_shop_container_view(callback: CallbackQuery):
    c_id = callback.data.replace("shop_container_view_", "")
    c_data = CONTAINERS_DB.get(c_id)
    if not c_data:
        await callback.answer("Контейнер не найден", show_alert=True)
        return
    text = f"<b>{c_data['name']}</b>\n\nЦена: <b>{c_data['price']} XP</b>\n\n<b>Возможные танки:</b>\n"
    text += "\n".join([f"• {html.escape(t)} ({tier_label(get_tank_tier(t))})" for t in c_data['tanks']])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Купить и открыть", callback_data=f"buy_container_{c_id}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="shop_containers_menu")]
    ])
    await safe_edit_or_send(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data.startswith("buy_container_"))
async def cb_buy_container(callback: CallbackQuery):
    uid = str(callback.from_user.id)
    c_id = callback.data.replace("buy_container_", "")
    c_data = CONTAINERS_DB.get(c_id)
    if not c_data:
        await callback.answer("Контейнер не найден", show_alert=True)
        return
    data = ensure_user(uid)
    if data["xp"] < c_data["price"]:
        await callback.answer("Недостаточно XP!", show_alert=True)
        return
    data["xp"] -= c_data["price"]
    data["containers"] = data.get("containers", 0) + 1
    save_users()
    await callback.answer()
    await open_container(callback.message, uid, c_id)


async def open_container(message: Message, uid: str, c_id: str):
    data = ensure_user(uid)
    c_data = CONTAINERS_DB.get(c_id)
    if not c_data:
        return

    if data.get("last_anim_msg"):
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=data["last_anim_msg"])
        except Exception:
            pass

    GIF_ID = FILE_IDS.get("container_open.gif")
    if GIF_ID:
        try:
            anim_msg = await bot.send_animation(chat_id=message.chat.id, animation=GIF_ID, caption="Открываем контейнер...")
            data["last_anim_msg"] = anim_msg.message_id
            save_users()
        except Exception as e:
            logger.error(f"Ошибка отправки гифки: {e}")

    await asyncio.sleep(2.5)
    tank_name = random.choice(c_data["tanks"])
    default_tank_stats = {"tier": 10, "hp": 1500, "damage": 400, "pen": 240, "armor": 120, "reload": 10.0}
    stats = {**default_tank_stats, **TANKS_DB.get(tank_name, {})}
    t_tier = int(stats.get("tier", 10))

    if tank_name in data.get("tanks", []):
        compensation = 500
        add_xp(uid, compensation)
        result_text = (
            f"🎁 Из контейнера выпал <b>{html.escape(tank_name)}</b> ({tier_label(t_tier)}), но он у тебя уже есть!\n"
            f"💰 Ты получаешь компенсацию: <b>+{compensation} XP</b>."
        )
    else:
        data.setdefault("tanks", []).append(tank_name)
        save_users()
        result_text = (
            f"🎉 <b>Поздравляю!</b>\n"
            f"Из контейнера выпал новый танк: <b>{html.escape(tank_name)}</b> ({tier_label(t_tier)})!\n\n"
            + tr(uid, "tank_stats", **stats)
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Открыть еще", callback_data="shop_containers_menu")],
        [InlineKeyboardButton(text="🔙 В профиль", callback_data="back_to_profile")]
    ])
    await safe_edit_or_send(message, result_text, reply_markup=kb, parse_mode="HTML")


@dp.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery):
    await callback.answer()


@dp.callback_query(F.data.startswith("shop_view_"))
async def cb_shop_view(callback: CallbackQuery):
    uid = str(callback.from_user.id)
    tank_name = callback.data.replace("shop_view_", "")
    stats = TANKS_DB.get(tank_name)
    if not stats:
        await callback.answer("Танк не найден", show_alert=True)
        return
    data = ensure_user(uid)
    is_owned = tank_name in data.get("tanks", [])
    t_tier = int(stats.get("tier", 10))
    text = f"<b>{html.escape(tank_name)}</b> — Уровень: <b>{tier_label(t_tier)}</b>\n\n" + tr(uid, "tank_stats", **stats)
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    if is_owned:
        if data.get("selected_tank") == tank_name:
            kb.inline_keyboard.append([InlineKeyboardButton(text="✅ Выбран", callback_data="noop")])
        else:
            kb.inline_keyboard.append([InlineKeyboardButton(text=tr(uid, "shop_select"), callback_data=f"shop_select_{tank_name}")])
    else:
        kb.inline_keyboard.append([InlineKeyboardButton(text=tr(uid, "shop_buy", price=stats.get("price", 0)), callback_data=f"shop_buy_{tank_name}")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"shop_tier_{t_tier}")])
    await safe_edit_or_send(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data.startswith("shop_buy_"))
async def cb_shop_buy(callback: CallbackQuery):
    uid = str(callback.from_user.id)
    tank_name = callback.data.replace("shop_buy_", "")
    stats = TANKS_DB.get(tank_name)
    if not stats:
        await callback.answer("Танк не найден", show_alert=True)
        return
    data = ensure_user(uid)
    if stats.get("exclusive", False):
        await callback.answer("Этот танк нельзя купить!", show_alert=True)
        return
    price = stats.get("price", 0)
    if data["xp"] < price:
        await callback.answer(tr(uid, "shop_not_enough", price=price), show_alert=True)
        return
    data["xp"] -= price
    if tank_name not in data.setdefault("tanks", []):
        data["tanks"].append(tank_name)
    data["selected_tank"] = tank_name
    save_users()
    unlock_achievement(uid, "tank_buyer")
    await callback.answer(tr(uid, "shop_bought", tank=tank_name), show_alert=True)
    await cb_shop_view(callback)


@dp.callback_query(F.data.startswith("shop_select_"))
async def cb_shop_select(callback: CallbackQuery):
    uid = str(callback.from_user.id)
    tank_name = callback.data.replace("shop_select_", "")
    data = ensure_user(uid)
    if tank_name in data.get("tanks", []):
        data["selected_tank"] = tank_name
        save_users()
        await callback.answer(tr(uid, "shop_selected", tank=tank_name), show_alert=True)
    await cb_shop_view(callback)


# --- БОИ (СТРОГО ПО УРОВНЯМ) ---
@dp.callback_query(F.data == "battle_menu")
async def cb_battle_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    uid = str(callback.from_user.id)
    data = ensure_user(uid)
    sel_tank = data.get("selected_tank", "FV215B 183")
    sel_tier = get_tank_tier(sel_tank)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr(uid, "battle_bot"), callback_data="battle_vs_bot")],
        [InlineKeyboardButton(text=f"🏠 Создать комнату ({tier_label(sel_tier)})", callback_data="create_room")],
        [InlineKeyboardButton(text=tr(uid, "battle_join"), callback_data="join_by_code")],
        [InlineKeyboardButton(text=tr(uid, "battle_list"), callback_data="list_rooms")],
        [InlineKeyboardButton(text="🚜 Сменить танк / уровень", callback_data="hangar_menu")],
        [InlineKeyboardButton(text=tr(uid, "battle_back"), callback_data="back_to_profile")]
    ])
    header = (
        f"{tr(uid, 'battle_desc')}\n\n"
        f"🚜 Выбранный танк: <b>{html.escape(sel_tank)}</b> ({tier_label(sel_tier)})\n"
        f"⚖️ <i>Балансировщик: бои проходят строго против техники своего уровня!</i>\n\n"
        f"{tr(uid, 'battle_choose')}"
    )
    await safe_edit_or_send(callback.message, header, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


def calculate_shot(attacker_stats, target_stats, ammo_type):
    if random.random() < 0.10:
        return 0, "Промах! Снаряд ушел мимо."
    pen_variance = random.uniform(0.95, 1.05)
    effective_pen = attacker_stats["pen"] * pen_variance
    target_armor = target_stats["armor"]
    dmg_variance = random.uniform(0.75, 1.25)
    if ammo_type == "ap":
        if effective_pen < target_armor:
            return 0, f"Рикошет! Броня {target_armor} мм выдержала удар."
        final_dmg = int(attacker_stats["damage"] * dmg_variance)
        return final_dmg, f"Пробитие! Урон: {final_dmg}"
    else:
        base_he = attacker_stats["damage"] * 0.5
        final_dmg = int(base_he * dmg_variance)
        return final_dmg, f"ОФ попал! Урон: {final_dmg}"


async def _launch_bot_fight(callback: CallbackQuery, state: FSMContext, uid: str, tank_name: str):
    user_data = ensure_user(uid)
    default_stats = {"tier": 10, "hp": 1850, "damage": 930, "pen": 300, "armor": 152, "reload": 18.5}
    tank_stats = TANKS_DB.get(tank_name, default_stats).copy()
    player_tier = int(tank_stats.get("tier", 10))

    same_tier_tanks = [
        n for n, st in TANKS_DB.items()
        if int(st.get("tier", 10)) == player_tier and n != tank_name
    ]
    if not same_tier_tanks:
        same_tier_tanks = [n for n, st in TANKS_DB.items() if int(st.get("tier", 10)) == player_tier] or [tank_name]

    bot_tank_name = random.choice(same_tier_tanks)
    bot_stats = TANKS_DB.get(bot_tank_name, default_stats).copy()

    user_data["selected_tank"] = tank_name
    save_users()

    await state.set_state(UserState.in_battle)
    await state.update_data(
        is_pve=True,
        tier=player_tier,
        p_hp=tank_stats["hp"],
        p_max_hp=tank_stats["hp"],
        e_hp=bot_stats["hp"],
        e_max_hp=bot_stats["hp"],
        p_tank=tank_name,
        e_tank=bot_tank_name,
        p_reload_ready=0,
        p_stats=tank_stats,
        e_stats=bot_stats,
        p_damage_dealt=0,
        p_shots_hit=0,
    )

    text = (
        f"🤖 <b>Бой против бота ({tier_label(player_tier)})</b>\n\n"
        f"Твой танк: <b>{html.escape(tank_name)}</b> (HP: {tank_stats['hp']})\n"
        f"Танк врага: <b>Неизвестно ({tier_label(player_tier)})</b>\n\nТвой ход!"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💥 Выстрел (ББ)", callback_data="pve_shoot_ap")],
        [InlineKeyboardButton(text="💥 Выстрел (ОФ)", callback_data="pve_shoot_he")],
        [InlineKeyboardButton(text="🏳️ Сдаться", callback_data="pve_surrender")]
    ])
    await safe_edit_or_send(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "battle_vs_bot")
async def cb_battle_vs_bot(callback: CallbackQuery, state: FSMContext):
    uid = str(callback.from_user.id)
    data = ensure_user(uid)
    sel_tank = data.get("selected_tank", "FV215B 183")
    await _launch_bot_fight(callback, state, uid, sel_tank)


@dp.callback_query(F.data.startswith("start_bot_fight_"))
async def cb_start_bot_fight(callback: CallbackQuery, state: FSMContext):
    uid = str(callback.from_user.id)
    tank_name = callback.data.replace("start_bot_fight_", "")
    await _launch_bot_fight(callback, state, uid, tank_name)


@dp.callback_query(F.data.startswith("pve_shoot_"), UserState.in_battle)
async def cb_pve_shoot(callback: CallbackQuery, state: FSMContext):
    uid = str(callback.from_user.id)
    user_data = ensure_user(uid)
    data = await state.get_data()
    if not data.get("is_pve"):
        await callback.answer()
        return

    now = time.time()
    reload_ready = data.get("p_reload_ready", 0)
    if now < reload_ready:
        left = round(reload_ready - now, 1)
        await callback.answer(f"Орудие перезаряжается! Осталось {left}с", show_alert=True)
        return

    await callback.answer()
    ammo = callback.data.replace("pve_shoot_", "")
    p_stats, e_stats = data["p_stats"], data["e_stats"]
    p_hp, e_hp = data["p_hp"], data["e_hp"]
    p_max_hp = data.get("p_max_hp", p_stats["hp"])
    e_max_hp = data.get("e_max_hp", e_stats["hp"])
    p_damage_dealt = data.get("p_damage_dealt", 0)
    p_shots_hit = data.get("p_shots_hit", 0)
    battle_tier = data.get("tier", get_tank_tier(data.get("p_tank", "")))

    damage, msg = calculate_shot(p_stats, e_stats, ammo)
    e_hp -= damage
    if damage > 0:
        p_damage_dealt += damage
        p_shots_hit += 1

    text = f"Ты выстрелил ({'ББ' if ammo == 'ap' else 'ОФ'}): {msg}\n"

    if e_hp <= 0:
        xp_reward = random.randint(50, 100)
        add_xp(uid, xp_reward)
        user_data["wins"] += 1
        user_data["battles"] += 1
        save_users()
        unlock_achievement(uid, "first_win")
        earned_ev, ev_emoji = reward_event_currency_after_battle(
            USERS, uid, won=True, damage_dealt=p_damage_dealt, enemy_max_hp=e_max_hp,
            player_max_hp=p_max_hp, player_hp_left=p_hp, shots_hit=p_shots_hit,
            save_users_fn=save_users,
        )
        text += (
            f"\n💀 <b>Враг уничтожен!</b>\n🏆 Победа! +{xp_reward} XP | +{earned_ev} {ev_emoji}.\n\n"
            f"👀 Танк врага: <b>{html.escape(data['e_tank'])}</b> ({tier_label(battle_tier)})"
        )
        await safe_edit_or_send(
            callback.message,
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="В меню", callback_data="battle_menu")]]),
            parse_mode="HTML",
        )
        await state.clear()
        return

    bot_ammo = random.choices(["ap", "he"], weights=[0.8, 0.2])[0]
    b_damage, b_msg = calculate_shot(e_stats, p_stats, bot_ammo)
    p_hp -= b_damage
    text += f"🔫 Враг выстрелил ({'ББ' if bot_ammo == 'ap' else 'ОФ'}): {b_msg}\n"

    if p_hp <= 0:
        user_data["losses"] += 1
        user_data["battles"] += 1
        save_users()
        earned_ev, ev_emoji = reward_event_currency_after_battle(
            USERS, uid, won=False, damage_dealt=p_damage_dealt, enemy_max_hp=e_max_hp,
            player_max_hp=p_max_hp, player_hp_left=0, shots_hit=p_shots_hit,
            save_users_fn=save_users,
        )
        ev_line = f"\n🎪 Ивент: +{earned_ev} {ev_emoji}" if earned_ev > 0 else ""
        text += f"\n💀 <b>Ты уничтожен!</b>{ev_line}\nТанк врага: <b>{html.escape(data['e_tank'])}</b> ({tier_label(battle_tier)})"
        await safe_edit_or_send(
            callback.message,
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="В меню", callback_data="battle_menu")]]),
            parse_mode="HTML",
        )
        await state.clear()
        return

    new_reload_ready = time.time() + p_stats["reload"]
    text += f"\n❤️ HP: {p_hp}\n💀 HP врага: {e_hp}\n⏱ Перезарядка: {p_stats['reload']}с\n\nТвой ход:"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💥 Выстрел (ББ)", callback_data="pve_shoot_ap")],
        [InlineKeyboardButton(text="💥 Выстрел (ОФ)", callback_data="pve_shoot_he")],
        [InlineKeyboardButton(text="🏳️ Сдаться", callback_data="pve_surrender")]
    ])
    await state.update_data(
        p_hp=p_hp, e_hp=e_hp, p_reload_ready=new_reload_ready,
        p_damage_dealt=p_damage_dealt, p_shots_hit=p_shots_hit,
    )
    await safe_edit_or_send(callback.message, text, reply_markup=kb, parse_mode="HTML")


@dp.callback_query(F.data == "pve_surrender", UserState.in_battle)
async def cb_pve_surrender(callback: CallbackQuery, state: FSMContext):
    await callback.answer("Ты сдался")
    uid = str(callback.from_user.id)
    user_data = ensure_user(uid)
    data = await state.get_data()
    user_data["losses"] += 1
    user_data["battles"] += 1
    save_users()
    reward_event_currency_after_battle(
        USERS, uid, won=False,
        damage_dealt=data.get("p_damage_dealt", 0),
        enemy_max_hp=data.get("e_max_hp", 1500),
        player_max_hp=data.get("p_max_hp", 1500),
        player_hp_left=0,
        shots_hit=data.get("p_shots_hit", 0),
        save_users_fn=save_users,
    )
    await state.clear()
    await safe_edit_or_send(
        callback.message,
        "🏳️ Ты сдался.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="В меню", callback_data="battle_menu")]]),
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "create_room")
async def cb_create_room(callback: CallbackQuery, state: FSMContext):
    uid = str(callback.from_user.id)
    data = ensure_user(uid)
    sel_tank = data.get("selected_tank", "FV215B 183")
    sel_tier = get_tank_tier(sel_tank)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 на 1", callback_data="create_2")],
        [InlineKeyboardButton(text="2 на 2", callback_data="create_4")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="battle_menu")]
    ])
    await state.set_state(UserState.choosing_size)
    text = (
        f"🏠 <b>Создание комнаты</b>\n\n"
        f"Твой танк: <b>{html.escape(sel_tank)}</b> ({tier_label(sel_tier)})\n"
        f"Уровень комнаты: <b>{tier_label(sel_tier)}</b> (войти смогут только игроки на танках {tier_label(sel_tier)})\n\n"
        f"Выбери формат:"
    )
    await safe_edit_or_send(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(UserState.choosing_size, F.data.startswith("create_"))
async def cb_create_size(callback: CallbackQuery, state: FSMContext):
    max_players = int(callback.data.replace("create_", ""))
    await state.clear()
    uid = str(callback.from_user.id)
    data = ensure_user(uid)
    sel_tank = data.get("selected_tank", "FV215B 183")
    room_tier = get_tank_tier(sel_tank)

    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    while code in ROOMS:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    ROOMS[code] = {
        "players": [uid],
        "max_players": max_players,
        "tier": room_tier,
        "is_private": False,
        "status": "waiting",
        "hp": {},
        "tank": {},
        "stats": {},
        "reload": {},
    }
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Скрыть", callback_data=f"hide_{code}")],
        [InlineKeyboardButton(text="Начать бой", callback_data=f"start_battle_{code}")],
        [InlineKeyboardButton(text="Выйти", callback_data=f"leave_{code}")]
    ])
    text = (
        f"🏠 Комната: <code>{code}</code>\n"
        f"🎚 Уровень боёв: <b>{tier_label(room_tier)}</b>\n"
        f"👥 Игроков: 1/{max_players}"
    )
    await safe_edit_or_send(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data.startswith("hide_"))
async def cb_hide_room(callback: CallbackQuery):
    code = callback.data.replace("hide_", "")
    if code in ROOMS and not ROOMS[code]["is_private"]:
        ROOMS[code]["is_private"] = True
        await safe_edit_or_send(callback.message, callback.message.text + "\n🔒 Скрыто", reply_markup=callback.message.reply_markup, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data.startswith("leave_"))
async def cb_leave_room(callback: CallbackQuery, state: FSMContext):
    code = callback.data.replace("leave_", "")
    uid = str(callback.from_user.id)
    if code in ROOMS:
        if uid in ROOMS[code]["players"]:
            ROOMS[code]["players"].remove(uid)
        if not ROOMS[code]["players"]:
            del ROOMS[code]
    await callback.answer("Вышел")
    await cb_back_to_profile(callback, state)


@dp.callback_query(F.data == "join_by_code")
async def cb_join_by_code(callback: CallbackQuery, state: FSMContext):
    await state.set_state(UserState.entering_code)
    await safe_edit_or_send(callback.message, "Введи код комнаты:", reply_markup=None, parse_mode=None)
    await callback.answer()


@dp.message(UserState.entering_code)
async def process_code(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ Введи текстовый код комнаты.")
        return
    code = message.text.strip().upper()
    await state.clear()
    uid = str(message.from_user.id)
    if code not in ROOMS:
        await message.answer("❌ Комната не найдена.")
        return
    room = ROOMS[code]
    if room["status"] != "waiting" or len(room["players"]) >= room["max_players"]:
        await message.answer("❌ Нельзя зайти (бой уже идёт или комната заполнена).")
        return
    if uid in room["players"]:
        await message.answer("Ты уже тут.")
        return

    user_data = ensure_user(uid)
    sel_tank = user_data.get("selected_tank", "FV215B 183")
    player_tier = get_tank_tier(sel_tank)
    room_tier = room.get("tier", 10)

    if player_tier != room_tier:
        await message.answer(
            f"❌ <b>Неподходящий уровень техники!</b>\n\n"
            f"Эта комната создана для боёв <b>{tier_label(room_tier)}</b>.\n"
            f"Твой выбранный танк: <b>{html.escape(sel_tank)}</b> ({tier_label(player_tier)}).\n\n"
            f"Выбери в ангаре танк <b>{tier_label(room_tier)}</b> и попробуй снова.",
            parse_mode="HTML"
        )
        return

    room["players"].append(uid)
    if len(room["players"]) == room["max_players"]:
        await start_room_battle(code, message.chat.id)
    else:
        await message.answer(
            f"✅ Ты вошёл в комнату <code>{code}</code> ({tier_label(room_tier)}).\n"
            f"Ожидаем игроков ({len(room['players'])}/{room['max_players']}).",
            parse_mode="HTML"
        )


@dp.callback_query(F.data == "list_rooms")
async def cb_list_rooms(callback: CallbackQuery):
    uid = str(callback.from_user.id)
    user_data = ensure_user(uid)
    sel_tank = user_data.get("selected_tank", "FV215B 183")
    player_tier = get_tank_tier(sel_tank)

    open_rooms = {k: v for k, v in ROOMS.items() if v["status"] == "waiting" and not v["is_private"]}
    if not open_rooms:
        await callback.answer("Нет открытых комнат.", show_alert=True)
        return

    lines = [f"<b>Открытые комнаты</b> (твой танк: {tier_label(player_tier)}):\n"]
    for c, r in open_rooms.items():
        r_tier = r.get("tier", 10)
        mark = "✅" if r_tier == player_tier else "🔒"
        lines.append(f"{mark} <code>{c}</code> | <b>{tier_label(r_tier)}</b> | Игроков: {len(r['players'])}/{r['max_players']}")

    await safe_edit_or_send(
        callback.message,
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Назад", callback_data="battle_menu")]]),
        parse_mode="HTML",
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("start_battle_"))
async def cb_start_battle_manual(callback: CallbackQuery):
    code = callback.data.replace("start_battle_", "")
    if code not in ROOMS:
        await callback.answer("Комната не найдена", show_alert=True)
        return
    room = ROOMS[code]
    if len(room["players"]) < 2:
        await callback.answer("Нужно минимум 2 игрока для начала боя!", show_alert=True)
        return
    await safe_edit_or_send(callback.message, "⚔️ Бой начинается...", reply_markup=None, parse_mode=None)
    await callback.answer()
    await start_room_battle(code, callback.message.chat.id)


async def start_room_battle(code, chat_id):
    room = ROOMS[code]
    room_tier = room.get("tier", 10)

    for uid in list(room["players"]):
        tank_name = USERS.get(uid, {}).get("selected_tank", "FV215B 183")
        if get_tank_tier(tank_name) != room_tier:
            room["players"].remove(uid)
            try:
                await bot.send_message(
                    int(uid),
                    f"❌ Ты был исключён из комнаты <code>{code}</code>, так как сменил танк на другой уровень (нужен {tier_label(room_tier)}).",
                    parse_mode="HTML"
                )
            except Exception:
                pass

    if len(room["players"]) < 2:
        room["status"] = "waiting"
        for uid in room["players"]:
            try:
                await bot.send_message(int(uid), "⚠️ Недостаточно игроков нужного уровня для старта боя. Ожидаем ещё игроков.")
            except Exception:
                pass
        return

    room["status"] = "battle"
    room["turn_index"] = 0
    room["reload"] = {p: 0 for p in room["players"]}
    text = f"⚔️ <b>Бой начался! ({tier_label(room_tier)})</b>\n\n"
    for uid in room["players"]:
        tank_name = USERS.get(uid, {}).get("selected_tank", "FV215B 183")
        stats = TANKS_DB.get(tank_name, {"tier": room_tier, "hp": 1850, "damage": 930, "pen": 300, "armor": 152, "reload": 18.5}).copy()
        room["hp"][uid] = stats["hp"]
        room["tank"][uid] = tank_name
        room["stats"][uid] = stats
        text += f"👤 <b>{get_display_name(uid)}</b> — {html.escape(tank_name)} [{tier_label(room_tier)}] (HP: {stats['hp']})\n"
    first_uid = room["players"][0]
    text += f"\nХод игрока <b>{get_display_name(first_uid)}</b>!"
    for uid in room["players"]:
        try:
            kb = None
            if uid == first_uid:
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💥 Выстрел (ББ)", callback_data=f"pvp_shoot_ap_{code}")],
                    [InlineKeyboardButton(text="💥 Выстрел (ОФ)", callback_data=f"pvp_shoot_he_{code}")]
                ])
            await bot.send_message(int(uid), text, parse_mode="HTML", reply_markup=kb)
        except Exception:
            pass


@dp.callback_query(F.data.startswith("pvp_shoot_"))
async def cb_pvp_shoot(callback: CallbackQuery):
    parts = callback.data.split("_")
    ammo = parts[2]
    code = parts[3]
    uid = str(callback.from_user.id)
    if code not in ROOMS or ROOMS[code]["status"] != "battle":
        await callback.answer("Бой уже завершён.", show_alert=True)
        return
    room = ROOMS[code]
    if uid != room["players"][room["turn_index"]]:
        await callback.answer("Не твой ход!", show_alert=True)
        return
    now = time.time()
    reload_ready = room["reload"].get(uid, 0)
    if now < reload_ready:
        left = round(reload_ready - now, 1)
        await callback.answer(f"Перезарядка! Осталось {left}с", show_alert=True)
        return
    enemies = [p for p in room["players"] if p != uid]
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for enemy in enemies:
        kb.inline_keyboard.append([InlineKeyboardButton(text=f"Цель: {get_display_name(enemy)}", callback_data=f"pvp_target_{code}_{enemy}_{ammo}")])
    await safe_edit_or_send(callback.message, "Выбери цель:", reply_markup=kb, parse_mode=None)
    await callback.answer()


@dp.callback_query(F.data.startswith("pvp_target_"))
async def cb_pvp_target(callback: CallbackQuery):
    parts = callback.data.split("_")
    code = parts[2]
    target_id = parts[3]
    ammo = parts[4]
    uid = str(callback.from_user.id)
    if code not in ROOMS or ROOMS[code]["status"] != "battle":
        await callback.answer("Бой уже завершён.", show_alert=True)
        return
    room = ROOMS[code]
    if uid != room["players"][room["turn_index"]]:
        await callback.answer("Не твой ход!", show_alert=True)
        return
    if target_id not in room["players"]:
        await callback.answer("Цель уже уничтожена!", show_alert=True)
        return

    damage, msg = calculate_shot(room["stats"][uid], room["stats"][target_id], ammo)
    room["hp"][target_id] -= damage
    text = f"💥 <b>{get_display_name(uid)}</b> выстрелил в <b>{get_display_name(target_id)}</b> ({'ББ' if ammo == 'ap' else 'ОФ'})!\n{msg}\n"
    text += f"❤️ У {get_display_name(target_id)} осталось {max(0, room['hp'][target_id])} HP."

    if room["hp"][target_id] <= 0:
        text += f"\n\n💀 <b>{get_display_name(target_id)}</b> уничтожен!"
        target_index = room["players"].index(target_id)
        room["players"].remove(target_id)
        if target_index < room["turn_index"]:
            room["turn_index"] -= 1
        if room["turn_index"] >= len(room["players"]):
            room["turn_index"] = 0

        loser_data = ensure_user(target_id)
        loser_data["losses"] += 1
        loser_data["battles"] += 1

        if len(room["players"]) == 1:
            winner = room["players"][0]
            xp_reward = random.randint(50, 100)
            add_xp(winner, xp_reward)
            winner_data = ensure_user(winner)
            winner_data["wins"] += 1
            winner_data["battles"] += 1
            unlock_achievement(winner, "first_win")
            text += f"\n\n🏆 <b>Победитель: {get_display_name(winner)}!</b>\n💰 +{xp_reward} XP"
            save_users()

            kb_winner = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🤝 Добавить в друзья", callback_data=f"friend_req_{target_id}")]])
            kb_loser = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🤝 Добавить в друзья", callback_data=f"friend_req_{winner}")]])

            try:
                await bot.send_message(int(winner), text, parse_mode="HTML", reply_markup=kb_winner)
            except Exception:
                pass
            try:
                await bot.send_message(int(target_id), text, parse_mode="HTML", reply_markup=kb_loser)
            except Exception:
                pass
            del ROOMS[code]
            await callback.answer()
            return
        else:
            try:
                await bot.send_message(int(target_id), text, parse_mode="HTML")
            except Exception:
                pass

    room["turn_index"] = (room["turn_index"] + 1) % len(room["players"])
    next_uid = room["players"][room["turn_index"]]
    room["reload"][uid] = time.time() + room["stats"][uid]["reload"]
    save_users()

    for p in room["players"]:
        try:
            msg_text = text + f"\n\nСледующий ход: <b>{get_display_name(next_uid)}</b>"
            kb = None
            if p == next_uid:
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💥 Выстрел (ББ)", callback_data=f"pvp_shoot_ap_{code}")],
                    [InlineKeyboardButton(text="💥 Выстрел (ОФ)", callback_data=f"pvp_shoot_he_{code}")]
                ])
            await bot.send_message(int(p), msg_text, parse_mode="HTML", reply_markup=kb)
        except Exception:
            pass
    await callback.answer()


# --- ОСТАЛЬНЫЕ ХЕНДЛЕРЫ (МОДЫ, АДМИНКА, СТАРТ, ПАСХАЛКИ) ---
@dp.message(F.text.in_([LOCALES["ru"]["btn_mods"], LOCALES["be"]["btn_mods"], LOCALES["en"]["btn_mods"]]))
async def btn_mods(message: Message, state: FSMContext):
    if await check_ban_and_block(message):
        return
    await state.clear()
    uid = str(message.from_user.id)
    await message.answer(tr(uid, "mods_menu"), parse_mode="HTML", reply_markup=get_mods_keyboard(uid))


@dp.callback_query(F.data.startswith("mod_old_"))
async def cb_mod_any(callback: CallbackQuery):
    uid = str(callback.from_user.id)
    if is_banned(uid)[0]:
        await callback.answer("Вы забанены", show_alert=True)
        return
    if callback.data == "mod_old_ui_info":
        await callback.answer()
        await callback.message.answer(tr(uid, "old_ui_info_text"))
        return
    await callback.answer()
    mod_key = callback.data.replace("mod_", "")
    version = "v3.0" if mod_key == "old_ui" else "v1.0"
    if not await check_subscription(callback.from_user.id):
        await callback.message.answer(
            tr(uid, "subscribe_needed"),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(uid, "btn_subscribe"), url=CHANNEL_LINK)]])
        )
        return
    await callback.message.answer(tr(uid, "version", ver=version))
    ext = "zip" if mod_key == "old_medals" else "rar"
    kb = get_mod_info_keyboard(uid) if mod_key == "old_ui" else None
    await send_mod_file(callback.from_user.id, f"{mod_key}.{ext}", reply_markup=kb)
    user_data = ensure_user(uid)
    user_data["downloads"] += 1
    add_xp(uid, 10)
    save_users()
    new_rank = check_rank_up(uid)
    if new_rank:
        await callback.message.answer(tr(uid, "rank_up", rank=new_rank))
    if user_data["downloads"] in (1, 10, 50):
        ach = unlock_achievement(uid, f"mods_{user_data['downloads']}" if user_data["downloads"] > 1 else "first_download")
        if ach:
            await callback.message.answer(tr(uid, "ach_unlocked", ach=ach))


@dp.message(F.text.in_([LOCALES["ru"]["btn_fun"], LOCALES["be"]["btn_fun"], LOCALES["en"]["btn_fun"]]))
async def btn_fun(message: Message, state: FSMContext):
    if await check_ban_and_block(message):
        return
    await state.set_state(UserState.awaiting_fun)
    uid = str(message.from_user.id)
    await message.answer(tr(uid, "fun_prompt"), reply_markup=get_main_keyboard(uid))


@dp.message(UserState.awaiting_fun, ~F.text.in_(ALL_MENU_BUTTONS))
async def receive_fun(message: Message, state: FSMContext):
    await state.clear()
    uid = str(message.from_user.id)
    header = f"<b>Прикол от пользователя!</b>\n{format_user_header(message.from_user)}\n\n"
    await forward_to_admins(message, header)
    add_xp(uid, 5)
    await message.answer(tr(uid, "fun_thanks"), reply_markup=get_main_keyboard(uid))


@dp.message(F.text.in_([LOCALES["ru"]["btn_feedback"], LOCALES["be"]["btn_feedback"], LOCALES["en"]["btn_feedback"]]))
async def btn_feedback(message: Message, state: FSMContext):
    if await check_ban_and_block(message):
        return
    await state.clear()
    uid = str(message.from_user.id)
    await message.answer(tr(uid, "feedback_menu"), parse_mode="HTML", reply_markup=get_feedback_keyboard(uid))


@dp.message(F.text.in_([LOCALES["ru"]["btn_back"], LOCALES["be"]["btn_back"], LOCALES["en"]["btn_back"]]))
async def btn_back(message: Message, state: FSMContext):
    await state.clear()
    uid = str(message.from_user.id)
    await message.answer(tr(uid, "main_menu"), reply_markup=get_main_keyboard(uid))


@dp.message(F.text.in_([LOCALES["ru"]["btn_suggest"], LOCALES["be"]["btn_suggest"], LOCALES["en"]["btn_suggest"]]))
async def btn_suggest_mod(message: Message, state: FSMContext):
    if await check_ban_and_block(message):
        return
    await state.set_state(UserState.awaiting_mod_suggestion)
    uid = str(message.from_user.id)
    await message.answer(tr(uid, "suggest_prompt"), parse_mode="HTML", reply_markup=get_feedback_keyboard(uid))


@dp.message(UserState.awaiting_mod_suggestion, ~F.text.in_(ALL_MENU_BUTTONS))
async def receive_mod_suggestion(message: Message, state: FSMContext):
    await state.clear()
    uid = str(message.from_user.id)
    header = f"<b>Новая идея от пользователя!</b>\n{format_user_header(message.from_user)}\n\n"
    await forward_to_admins(message, header)
    user_data = ensure_user(uid)
    user_data["ideas"] += 1
    add_xp(uid, 25)
    save_users()
    new_rank = check_rank_up(uid)
    if new_rank:
        await message.answer(tr(uid, "rank_up", rank=new_rank))
    if user_data["ideas"] in (1, 10):
        ach = unlock_achievement(uid, f"ideas_{user_data['ideas']}" if user_data["ideas"] > 1 else "first_idea")
        if ach:
            await message.answer(tr(uid, "ach_unlocked", ach=ach))
    await message.answer(tr(uid, "suggest_thanks"), reply_markup=get_main_keyboard(uid))


@dp.message(F.text.in_([LOCALES["ru"]["btn_bug"], LOCALES["be"]["btn_bug"], LOCALES["en"]["btn_bug"]]))
async def btn_bug_report(message: Message, state: FSMContext):
    if await check_ban_and_block(message):
        return
    await state.set_state(UserState.awaiting_bug_report)
    uid = str(message.from_user.id)
    await message.answer(tr(uid, "bug_prompt"), reply_markup=get_feedback_keyboard(uid))


@dp.message(UserState.awaiting_bug_report, ~F.text.in_(ALL_MENU_BUTTONS))
async def receive_bug_report(message: Message, state: FSMContext):
    uid = str(message.from_user.id)
    if message.voice or (not message.text and not message.photo and not message.video and not message.document):
        await message.answer(tr(uid, "bug_voice"))
        return
    await state.clear()
    header = f"<b>[ОШИБКА] Сообщение об ошибке</b>\n{format_user_header(message.from_user)}\n\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(uid, "btn_report_fixed"), callback_data=f"bug_fixed_{uid}")]])
    if TARGET_CHAT_IDS:
        for chat_id in TARGET_CHAT_IDS:
            try:
                await bot.send_message(chat_id, header, parse_mode="HTML", reply_markup=kb)
                await message.forward(chat_id)
            except Exception as exc:
                logger.error(f"Не удалось отправить: {exc}")
    add_xp(uid, 15)
    await message.answer(tr(uid, "bug_thanks"), reply_markup=get_main_keyboard(uid))


@dp.message(F.text.in_([LOCALES["ru"]["btn_question"], LOCALES["be"]["btn_question"], LOCALES["en"]["btn_question"]]))
async def btn_question(message: Message, state: FSMContext):
    if await check_ban_and_block(message):
        return
    await state.set_state(UserState.awaiting_question)
    uid = str(message.from_user.id)
    await message.answer(tr(uid, "question_prompt"), reply_markup=get_feedback_keyboard(uid))


@dp.message(UserState.awaiting_question, ~F.text.in_(ALL_MENU_BUTTONS))
async def receive_question(message: Message, state: FSMContext):
    await state.clear()
    uid = str(message.from_user.id)
    header = f"<b>Вопрос от пользователя!</b>\n{format_user_header(message.from_user)}\n\nОтветьте на это сообщение (Reply), чтобы отправить ответ пользователю"
    if not TARGET_CHAT_IDS:
        await message.answer(tr(uid, "question_no_group"))
        return
    for chat_id in TARGET_CHAT_IDS:
        try:
            await bot.send_message(chat_id, header, parse_mode="HTML")
            await message.forward(chat_id)
        except Exception as exc:
            logger.error(f"Не удалось отправить: {exc}")
    user_data = ensure_user(uid)
    user_data["questions"] += 1
    add_xp(uid, 5)
    save_users()
    if user_data["questions"] == 1:
        ach = unlock_achievement(uid, "first_question")
        if ach:
            await message.answer(tr(uid, "ach_unlocked", ach=ach))
    await message.answer(tr(uid, "question_thanks"), reply_markup=get_main_keyboard(uid))


@dp.callback_query(F.data == "apply_team")
async def cb_apply_team(callback: CallbackQuery, state: FSMContext):
    uid = str(callback.from_user.id)
    await callback.answer()
    await state.set_state(UserState.awaiting_team_apply)
    await callback.message.answer(tr(uid, "apply_team_text"), parse_mode="HTML")


@dp.message(UserState.awaiting_team_apply, ~F.text.in_(ALL_MENU_BUTTONS))
async def receive_team_apply(message: Message, state: FSMContext):
    await state.clear()
    uid = str(message.from_user.id)
    header = f"<b>📝 Анкета в команду!</b>\n{format_user_header(message.from_user)}\n\n"
    if TARGET_CHAT_IDS:
        for chat_id in TARGET_CHAT_IDS:
            try:
                await bot.send_message(chat_id, header, parse_mode="HTML")
                await message.forward(chat_id)
            except Exception as exc:
                logger.error(f"Ошибка отправки: {exc}")
    await message.answer(tr(uid, "apply_team_thanks"), reply_markup=get_main_keyboard(uid))


@dp.callback_query(F.data.startswith("bug_fixed_"))
async def cb_bug_fixed(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Только админ", show_alert=True)
        return
    target_id = callback.data.split("_")[-1]
    add_xp(target_id, 50)
    try:
        await bot.send_message(int(target_id), tr(target_id, "bug_report_fixed"))
    except Exception:
        pass
    await safe_edit_or_send(callback.message, (callback.message.html_text or "") + "\n\n✅ <b>Статус: Исправлено</b>", reply_markup=None, parse_mode="HTML")
    await callback.answer("Уведомлен!")


@dp.callback_query(F.data == "appeal_ban")
async def cb_appeal_ban(callback: CallbackQuery, state: FSMContext):
    uid = str(callback.from_user.id)
    await callback.answer()
    await state.set_state(UserState.awaiting_appeal)
    await callback.message.answer(tr(uid, "appeal_usage"), reply_markup=None)


@dp.message(UserState.awaiting_appeal)
async def receive_appeal(message: Message, state: FSMContext):
    await state.clear()
    uid = str(message.from_user.id)
    user_data = ensure_user(uid)
    if user_data.get("appeal_pending"):
        await message.answer(tr(uid, "appeal_already"))
        return
    user_data["appeal_pending"] = True
    save_users()
    safe_reason = html.escape(message.text or "[медиа-файл без текста]")
    header = (
        f"<b>🔓 Заявка на разбан!</b>\n{format_user_header(message.from_user)}\n"
        f"Причина: {safe_reason}\n\n<i>Ответьте на это сообщение (Reply), чтобы разбанить.</i>"
    )
    if TARGET_CHAT_IDS:
        for chat_id in TARGET_CHAT_IDS:
            try:
                await bot.send_message(chat_id, header, parse_mode="HTML")
            except Exception as exc:
                logger.error(f"Ошибка: {exc}")
    await message.answer(tr(uid, "appeal_sent"))


@dp.message(F.text.in_([LOCALES["ru"]["btn_help"], LOCALES["be"]["btn_help"], LOCALES["en"]["btn_help"]]))
async def btn_help(message: Message, state: FSMContext):
    if await check_ban_and_block(message):
        return
    await state.clear()
    uid = str(message.from_user.id)
    await message.answer(tr(uid, "help_menu"), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr(uid, "help_install_btn"), callback_data="help_install")],
        [InlineKeyboardButton(text=tr(uid, "help_remove_btn"), callback_data="help_remove")],
        [InlineKeyboardButton(text=tr(uid, "help_why_btn"), callback_data="help_why")],
        [InlineKeyboardButton(text=tr(uid, "help_time_btn"), callback_data="help_time")],
        [InlineKeyboardButton(text=tr(uid, "help_why_old_btn"), callback_data="help_why_old")],
    ]))


@dp.callback_query(F.data.startswith("help_"))
async def cb_help_any(callback: CallbackQuery):
    uid = str(callback.from_user.id)
    if is_banned(uid)[0]:
        await callback.answer("Вы забанены", show_alert=True)
        return
    await callback.answer()
    key = f"{callback.data}_text"
    await callback.message.answer(tr(uid, key))


@dp.message(F.text.in_([LOCALES["ru"]["btn_misc"], LOCALES["be"]["btn_misc"], LOCALES["en"]["btn_misc"]]))
async def btn_misc(message: Message, state: FSMContext):
    if await check_ban_and_block(message):
        return
    await state.clear()
    uid = str(message.from_user.id)
    await message.answer(tr(uid, "misc_menu"), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr(uid, "btn_dev"), callback_data="misc_dev")],
        [InlineKeyboardButton(text=tr(uid, "btn_donate"), callback_data="misc_donate")],
        [InlineKeyboardButton(text=tr(uid, "btn_lang"), callback_data="misc_lang")],
        [InlineKeyboardButton(text=tr(uid, "misc_team_btn"), callback_data="misc_team")],
        [InlineKeyboardButton(text=tr(uid, "misc_join_btn"), callback_data="misc_join")],
        [InlineKeyboardButton(text=tr(uid, "misc_share_btn"), url="https://t.me/share/url?url=https://t.me/ModRak1_bot&text=Смотри, какой крутой бот для модов!")],
    ]))


@dp.callback_query(F.data.startswith("misc_"))
async def cb_misc_any(callback: CallbackQuery):
    uid = str(callback.from_user.id)
    if is_banned(uid)[0]:
        await callback.answer("Вы забанены", show_alert=True)
        return
    await callback.answer()
    if callback.data == "misc_dev":
        await callback.message.answer(tr(uid, "dev_text"))
    elif callback.data == "misc_donate":
        await callback.message.answer(tr(uid, "donate_text"))
    elif callback.data == "misc_lang":
        await callback.message.answer(tr(uid, "choose_lang"), reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_lang_ru")],
            [InlineKeyboardButton(text="🇧🇾 Беларуская", callback_data="set_lang_be")],
            [InlineKeyboardButton(text="🇬🇧 English", callback_data="set_lang_en")],
        ]))
    elif callback.data == "misc_join":
        await callback.message.answer(tr(uid, "misc_join_text"), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(uid, "apply_team_btn"), callback_data="apply_team")]]))
    else:
        key = f"{callback.data}_text"
        if callback.data == "misc_team":
            await callback.message.answer(tr(uid, key), parse_mode="HTML")
        else:
            await callback.message.answer(tr(uid, key))


@dp.message(Command("setrank"))
async def cmd_setrank(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    args = message.text.split()
    if len(args) < 3:
        await message.answer(tr(str(message.from_user.id), "setrank_usage"))
        return
    try:
        target_id = str(int(args[1]))
        rank_id = int(args[2])
    except ValueError:
        await message.answer(tr(str(message.from_user.id), "setrank_bad_id"))
        return
    if rank_id not in RANKS:
        await message.answer(tr(str(message.from_user.id), "setrank_no_rank"))
        return
    user_data = ensure_user(target_id)
    user_data["rank_id"] = rank_id
    save_users()
    admin_uid = str(message.from_user.id)
    await message.answer(tr(admin_uid, "setrank_done", uid=target_id, rank=RANKS[rank_id][0]))
    try:
        await bot.send_message(int(target_id), tr(target_id, "rank_given", rank=RANKS[rank_id][0]), parse_mode="HTML")
    except Exception as e:
        await message.answer(tr(admin_uid, "setrank_notify_fail", err=e))


@dp.message(Command("staff"))
async def cmd_staff(message: Message):
    uid_admin = str(message.from_user.id)
    if message.from_user.id not in ADMIN_IDS and USERS.get(uid_admin, {}).get("rank_id", 0) < 19:
        return
    staff_list = []
    for uid, data in USERS.items():
        rank_id = data.get("rank_id", 1)
        if rank_id in RANKS:
            _, _, _, rank_type = RANKS[rank_id]
            if rank_type in ("modder", "staff"):
                staff_list.append((rank_id, uid, data))
    if not staff_list:
        await message.answer(tr(uid_admin, "staff_empty"))
        return
    staff_list.sort(key=lambda x: x[0], reverse=True)
    text_lines = [tr(uid_admin, "staff_title") + "\n"]
    for rank_id, uid, data in staff_list:
        text_lines.append(f"<b>{RANKS[rank_id][0]}</b> | ID: <code>{uid}</code>\n└ XP: {data.get('xp', 0)} | Идей: {data.get('ideas', 0)}\n")
    full_text = "\n".join(text_lines)
    if len(full_text) > 4000:
        parts = []
        current_part = ""
        for line in text_lines:
            if len(current_part) + len(line) > 4000:
                parts.append(current_part)
                current_part = line + "\n"
            else:
                current_part += line + "\n"
        if current_part:
            parts.append(current_part)
        for part in parts:
            await message.answer(part, parse_mode="HTML")
    else:
        await message.answer(full_text, parse_mode="HTML")


@dp.message(Command("reply"))
async def cmd_reply(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    if message.reply_to_message:
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.answer("❌ Использование: /reply <текст> (в ответ на сообщение)")
            return
        target_user_id = None
        src_text = message.reply_to_message.html_text or message.reply_to_message.text or ""
        match = USER_ID_RE.search(src_text)
        if match:
            target_user_id = int(match.group(1))
        elif message.reply_to_message.forward_from:
            target_user_id = message.reply_to_message.forward_from.id
        if not target_user_id:
            await message.answer("❌ Не удалось найти ID в сообщении.")
            return
        reply_text = args[1]
    else:
        args = message.text.split(maxsplit=2)
        if len(args) < 3:
            await message.answer("❌ Использование: /reply <id> <текст>")
            return
        try:
            target_user_id = int(args[1])
            reply_text = args[2]
        except ValueError:
            await message.answer("❌ Неверный ID.")
            return
    try:
        await bot.send_message(target_user_id, f"<b>✉️ Сообщение от администрации:</b>\n\n{html.escape(reply_text)}", parse_mode="HTML")
        await message.answer(f"✅ Доставлено пользователю {target_user_id}")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


@dp.message(Command("ban"))
async def cmd_ban(message: Message):
    uid_admin = str(message.from_user.id)
    if message.from_user.id not in ADMIN_IDS and USERS.get(uid_admin, {}).get("rank_id", 0) < 18:
        return
    target_id = None
    args = message.text.split()
    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
        reason_args = args[1:]
    else:
        if len(args) < 3:
            await message.answer(tr(uid_admin, "ban_usage"))
            return
        try:
            target_id = int(args[1])
            reason_args = args[2:]
        except ValueError:
            await message.answer(tr(uid_admin, "setrank_bad_id"))
            return
    if target_id in ADMIN_IDS:
        return
    forever = False
    until_dt = None
    if reason_args and reason_args[0].lower() in ("never", "навсегда"):
        forever = True
        reason = " ".join(reason_args[1:]) if len(reason_args) > 1 else "Без причины"
    else:
        if len(reason_args) < 2 and not message.reply_to_message:
            await message.answer(tr(uid_admin, "ban_usage"))
            return
        if message.reply_to_message:
            forever = True
            reason = " ".join(reason_args) if reason_args else "Без причины"
        else:
            try:
                until_dt = datetime.strptime(f"{reason_args[0]} {reason_args[1]}", "%d.%m.%Y %H:%M:%S")
            except ValueError:
                await message.answer(tr(uid_admin, "ban_invalid_date"))
                return
            if until_dt <= datetime.now():
                await message.answer(tr(uid_admin, "ban_past"))
                return
            reason = " ".join(reason_args[2:]) if len(reason_args) > 2 else "Без причины"
    target_str = str(target_id)
    BANNED[target_str] = {"reason": reason, "until": "never" if forever else until_dt.strftime("%Y-%m-%d %H:%M:%S")}
    save_banned()
    target_user = ensure_user(target_str)
    target_user["bans"] += 1
    target_user["appeal_pending"] = False
    save_users()
    if TARGET_CHAT_IDS:
        try:
            await bot.ban_chat_member(TARGET_CHAT_IDS[0], target_id)
        except Exception:
            pass
    try:
        if forever:
            await bot.send_message(target_id, tr(target_str, "ban_notify_forever", reason=reason))
        else:
            await bot.send_message(target_id, tr(target_str, "ban_notify", reason=reason, until=until_dt.strftime("%d.%m.%Y %H:%M:%S")))
    except Exception:
        pass
    if forever:
        await message.answer(tr(uid_admin, "ban_done_forever", uid=target_id, reason=reason))
    else:
        await message.answer(tr(uid_admin, "ban_done", uid=target_id, until=until_dt.strftime("%d.%m.%Y %H:%M:%S"), reason=reason))


@dp.message(Command("unban"))
async def cmd_unban(message: Message):
    uid_admin = str(message.from_user.id)
    if message.from_user.id not in ADMIN_IDS:
        return
    target_id = None
    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
    else:
        args = message.text.split()
        if len(args) < 2:
            await message.answer(tr(uid_admin, "unban_usage"))
            return
        try:
            target_id = int(args[1])
        except ValueError:
            await message.answer(tr(uid_admin, "setrank_bad_id"))
            return
    target_str = str(target_id)
    if target_str in BANNED:
        del BANNED[target_str]
        save_banned()
        if target_str in USERS:
            USERS[target_str]["appeal_pending"] = False
            save_users()
        if TARGET_CHAT_IDS:
            try:
                await bot.unban_chat_member(TARGET_CHAT_IDS[0], target_id)
            except Exception:
                pass
        await message.answer(tr(uid_admin, "unban_reply_success", uid=target_id))
    else:
        await message.answer(tr(uid_admin, "unban_not_found"))


@dp.message(Command("banlist"))
async def cmd_banlist(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    if not BANNED:
        await message.answer(tr(str(message.from_user.id), "banlist_empty"))
        return
    lines = []
    for uid, info in BANNED.items():
        until = info.get("until", "?")
        if until == "never":
            until = "навсегда"
        lines.append(f"• {uid} | до {until} | {info.get('reason', '')}")
    await message.answer(tr(str(message.from_user.id), "banlist_title") + "\n" + "\n".join(lines))


@dp.message(Command("mystatus"))
async def cmd_mystatus(message: Message):
    uid = str(message.from_user.id)
    banned, info = is_banned(uid)
    if not banned:
        await message.answer(tr(uid, "mystatus_no_ban"))
        return
    until = info.get("until", "")
    if until == "never":
        until_text = tr(uid, "mystatus_until_forever")
    else:
        until_text = tr(uid, "mystatus_until", until=datetime.strptime(until, "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y %H:%M:%S"))
    text = f"{tr(uid, 'mystatus_title')}\n{until_text}\n{tr(uid, 'mystatus_reason', reason=info.get('reason', '?'))}"
    await message.answer(text)


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    if await check_ban_and_block(message):
        return
    await state.clear()
    uid = str(message.from_user.id)
    args = (message.text or "").split()
    is_new = uid not in USERS

    if is_new:
        USERS[uid] = default_user_data()
        if message.from_user.id in ADMIN_IDS:
            USERS[uid]["rank_id"] = 13
        save_users()

    if len(args) > 1 and args[1].startswith("ref_"):
        referrer_id = args[1].replace("ref_", "")
        if referrer_id in USERS and referrer_id != uid and is_new:
            add_xp(referrer_id, 150)
            add_xp(uid, 150)
            try:
                await bot.send_message(int(referrer_id), tr(referrer_id, "ref_bonus"))
            except Exception:
                pass
            await message.answer(tr(uid, "ref_welcome"))

    if not USERS[uid].get("nickname"):
        await state.set_state(UserState.awaiting_nickname)
        await message.answer(tr(uid, "nickname_prompt"), reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="/cancel")]], resize_keyboard=True))
        return

    if not USERS[uid].get("lang"):
        await message.answer("Выбери язык / Абяры мову / Choose language:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_lang_ru")],
            [InlineKeyboardButton(text="🇧🇾 Беларуская", callback_data="set_lang_be")],
            [InlineKeyboardButton(text="🇬🇧 English", callback_data="set_lang_en")],
        ]))
        return

    await message.answer(tr(uid, "start", name=message.from_user.first_name), reply_markup=get_main_keyboard(uid))


@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    if await check_ban_and_block(message):
        return
    uid = str(message.from_user.id)
    if await state.get_state():
        await state.clear()
        await message.answer(tr(uid, "cancel"), reply_markup=get_main_keyboard(uid))
    else:
        await message.answer(tr(uid, "nothing_cancel"), reply_markup=get_main_keyboard(uid))


@dp.message(UserState.awaiting_nickname)
async def process_nickname(message: Message, state: FSMContext):
    uid = str(message.from_user.id)
    if not message.text:
        await message.answer(tr(uid, "nickname_invalid"))
        return
    nick = message.text.strip()
    if len(nick) < 3 or len(nick) > 15 or " " in nick:
        await message.answer(tr(uid, "nickname_invalid"))
        return
    if any((u.get("nickname") or "").lower() == nick.lower() for u in USERS.values()):
        await message.answer(tr(uid, "nickname_taken"))
        return
    user_data = ensure_user(uid)
    user_data["nickname"] = nick
    save_users()
    await state.clear()
    safe_nick = html.escape(nick)
    if not user_data.get("lang"):
        await message.answer(
            tr(uid, "nickname_success", nick=safe_nick) + "\n\nВыбери язык / Абяры мову / Choose language:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_lang_ru")],
                [InlineKeyboardButton(text="🇧🇾 Беларуская", callback_data="set_lang_be")],
                [InlineKeyboardButton(text="🇬🇧 English", callback_data="set_lang_en")],
            ])
        )
    else:
        await message.answer(tr(uid, "nickname_success", nick=safe_nick), parse_mode="HTML", reply_markup=get_main_keyboard(uid))


@dp.message(Command("lang"))
async def cmd_lang(message: Message, state: FSMContext):
    if await check_ban_and_block(message):
        return
    await state.clear()
    await message.answer(tr(str(message.from_user.id), "choose_lang"), reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_lang_ru")],
        [InlineKeyboardButton(text="🇧🇾 Беларуская", callback_data="set_lang_be")],
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="set_lang_en")],
    ]))


@dp.callback_query(F.data.startswith("set_lang_"))
async def cb_set_lang(callback: CallbackQuery):
    uid = str(callback.from_user.id)
    if is_banned(uid)[0]:
        await callback.answer("Вы забанены", show_alert=True)
        return
    lang = callback.data.split("_")[-1]
    user_data = ensure_user(uid)
    user_data["lang"] = lang
    save_users()
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(tr(uid, "lang_changed"), reply_markup=get_main_keyboard(uid))
    await callback.answer()


@dp.message(Command("testgroup"))
async def cmd_test_group(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await easter_egg_handler(message, state)
        return
    if not TARGET_CHAT_IDS:
        await message.answer("❌ TARGET_CHAT_IDS пуст")
        return
    try:
        await bot.send_message(TARGET_CHAT_IDS[0], "✅ Тест связи")
        await message.answer("✅ Успешно отправлено!")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


@dp.message(F.document)
async def group_document_handler(message: Message):
    if GROUP_ID_VALUE and str(message.chat.id) == str(GROUP_ID_VALUE):
        doc = message.document
        if doc.file_name:
            FILE_IDS[doc.file_name] = doc.file_id
            save_file_ids()
            await message.answer(f"Файл {doc.file_name} сохранен")


@dp.chat_member(F.chat.id.in_(TARGET_CHAT_IDS))
async def on_chat_member(event: ChatMemberUpdated):
    if event.new_chat_member.status in ("member", "restricted"):
        uid = str(event.new_chat_member.user.id)
        banned, _ = is_banned(uid)
        if banned:
            try:
                await bot.ban_chat_member(event.chat.id, event.new_chat_member.user.id)
                await bot.send_message(event.chat.id, f"Пользователь {uid} в чёрном списке и был удалён")
            except Exception:
                pass


USER_ID_RE = re.compile(r"🆔\s*(?:<code>)?(\d+)(?:</code>)?")


@dp.message(F.reply_to_message, F.chat.id.in_(TARGET_CHAT_IDS))
async def handle_group_reply(message: Message):
    replied_msg = message.reply_to_message
    if not replied_msg:
        return
    src_text = replied_msg.html_text or replied_msg.text or ""
    match = USER_ID_RE.search(src_text)
    if not match:
        return
    user_id = int(match.group(1))
    target_str = str(user_id)

    if "Заявка на разбан!" in src_text:
        if target_str in BANNED:
            del BANNED[target_str]
            save_banned()
        if target_str in USERS:
            USERS[target_str]["appeal_pending"] = False
            save_users()
        for chat_id in TARGET_CHAT_IDS:
            try:
                await bot.unban_chat_member(chat_id, user_id)
            except Exception:
                pass
        try:
            reply_note = f"\n\nКомментарий: {html.escape(message.text)}" if message.text else ""
            await bot.send_message(user_id, f"✅ <b>Ваша заявка на разбан одобрена!</b>{reply_note}", parse_mode="HTML")
            await message.reply(f"✅ Пользователь {user_id} разбанен и уведомлен!")
        except Exception as e:
            await message.reply(f"✅ Пользователь {user_id} разбанен, но не удалось отправить ЛС: {e}")
        return

    if not message.text:
        await message.reply("❌ Отправьте текстовый ответ.")
        return

    try:
        await bot.send_message(user_id, f"<b>Ответ от поддержки:</b>\n\n{html.escape(message.text)}", parse_mode="HTML")
        await message.reply("Ответ отправлен!")
    except Exception as e:
        await message.reply(f"Ошибка: {e}")


@dp.message(F.text)
async def easter_egg_handler(message: Message, state: FSMContext):
    if await state.get_state() is not None:
        return
    if message.chat.type != "private":
        return
    uid = str(message.from_user.id)
    if is_banned(uid)[0]:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(uid, "appeal_btn"), callback_data="appeal_ban")]])
        await message.answer(tr(uid, "banned_bot_text"), reply_markup=kb)
        return
    if uid not in USERS or not USERS[uid].get("lang") or not USERS[uid].get("nickname"):
        await cmd_start(message, state)
        return
    text_lower = message.text.strip().lower()
    if text_lower in EASTER_EGGS:
        await message.answer(EASTER_EGGS[text_lower], reply_markup=get_main_keyboard(uid))
        return
    for trigger, reply in EASTER_EGGS.items():
        if len(trigger) >= 3 and trigger in text_lower:
            await message.answer(reply, reply_markup=get_main_keyboard(uid))
            return
    if "сломай" in text_lower or "взломай" in text_lower or "hack" in text_lower or "break" in text_lower:
        hits = EASTER_EGG_HITS.get(uid, 0) + 1
        EASTER_EGG_HITS[uid] = hits
        if hits >= 3:
            await message.answer(tr(uid, "break_hard_text"), reply_markup=get_main_keyboard(uid))
        else:
            await message.answer(tr(uid, "break_soft_text"), reply_markup=get_main_keyboard(uid))
        return
    is_gibberish = False
    if len(text_lower) > 50 and " " not in text_lower:
        is_gibberish = True
    elif len(text_lower) < 3 or text_lower.isdigit() or not any(c.isalpha() for c in text_lower):
        is_gibberish = True
    replies_key = "gibberish" if is_gibberish else "fallback"
    user_lang = USERS.get(uid, {}).get("lang") or "ru"
    lang_fallbacks = FALLBACKS.get(user_lang, FALLBACKS.get("ru", {}))
    replies_list = lang_fallbacks.get(replies_key, ["Ошибка загрузки фраз"])
    await message.answer(random.choice(replies_list), reply_markup=get_main_keyboard(uid))


@dp.message()
async def unknown_media(message: Message, state: FSMContext):
    if await state.get_state() is not None:
        return
    if message.chat.type != "private":
        return
    uid = str(message.from_user.id)
    if is_banned(uid)[0]:
        return
    if uid not in USERS or not USERS[uid].get("lang") or not USERS[uid].get("nickname"):
        await cmd_start(message, state)
        return
    await message.answer(tr(uid, "unknown_media_text"), reply_markup=get_main_keyboard(uid))


async def main():
    register_event_handlers(dp, USERS, TANKS_DB, save_users)
    logger.info("Bot started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())