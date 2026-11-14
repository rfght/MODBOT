import asyncio
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
    CallbackQuery, ChatMemberUpdated, InlineKeyboardButton,
    InlineKeyboardMarkup, KeyboardButton, Message, ReplyKeyboardMarkup,
)
from aiogram.exceptions import TelegramBadRequest

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID_VALUE = os.getenv("CHANNEL_ID")
ADMIN_IDS_VALUE = os.getenv("ADMIN_IDS") or os.getenv("TELEGRAM_ADMIN_ID")
GROUP_ID_VALUE = os.getenv("GROUP_ID", "-1002832219010")
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/MOD_rak")

if not BOT_TOKEN:
    raise RuntimeError("Missing required environment variable: BOT_TOKEN")

CHANNEL_ID = int(CHANNEL_ID_VALUE) if CHANNEL_ID_VALUE and CHANNEL_ID_VALUE.isdigit() else CHANNEL_ID_VALUE
ADMIN_IDS = [int(a.strip()) for a in ADMIN_IDS_VALUE.split(",") if a.strip()] if ADMIN_IDS_VALUE else []
TARGET_CHAT_IDS = [int(GROUP_ID_VALUE)] if GROUP_ID_VALUE and GROUP_ID_VALUE.lstrip("-").isdigit() else []

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- ФАЙЛЫ ---
FILE_IDS_PATH = "file_ids.json"
FILE_IDS = {}
USERS_PATH = "users.json"
USERS = {}
BANNED_PATH = "banned.json"
BANNED = {}
FALLBACKS_PATH = "fallbacks.json"
FALLBACKS = {}

# --- БАЗА ТАНКОВ (с характеристиками) ---
TANKS_DB = {
    "FV215B 183": {"hp": 1800, "damage": 950, "pen": 300, "armor": 152, "reload": 18.5, "price": 0},
    "E 100": {"hp": 2400, "damage": 460, "pen": 235, "armor": 200, "reload": 13.0, "price": 8000},
    "Maus": {"hp": 2600, "damage": 460, "pen": 246, "armor": 250, "reload": 13.5, "price": 8000},
    "IS-7": {"hp": 2400, "damage": 490, "pen": 250, "armor": 150, "reload": 12.0, "price": 8000},
    "T110E5": {"hp": 2200, "damage": 400, "pen": 258, "armor": 180, "reload": 9.0, "price": 8000},
    "T57 Heavy": {"hp": 2100, "damage": 400, "pen": 258, "armor": 150, "reload": 22.0, "price": 8500},
    "JgPz E 100": {"hp": 2200, "damage": 1050, "pen": 299, "armor": 250, "reload": 18.0, "price": 8500},
    "Object 268": {"hp": 2000, "damage": 750, "pen": 293, "armor": 187, "reload": 15.0, "price": 8000},
    "FV4005": {"hp": 1900, "damage": 1150, "pen": 310, "armor": 130, "reload": 20.0, "price": 8500},
    "Tiger II": {"hp": 1850, "damage": 310, "pen": 225, "armor": 150, "reload": 7.6, "price": 4000},
    "AMX 50 100": {"hp": 1700, "damage": 310, "pen": 232, "armor": 100, "reload": 19.5, "price": 4500},
    "IS-3": {"hp": 1500, "damage": 390, "pen": 225, "armor": 120, "reload": 11.0, "price": 4000},
    "T-54": {"hp": 1600, "damage": 320, "pen": 201, "armor": 120, "reload": 8.0, "price": 4000},
    "Pershing": {"hp": 1450, "damage": 240, "pen": 180, "armor": 100, "reload": 6.5, "price": 3800},
    "Panther II": {"hp": 1500, "damage": 240, "pen": 198, "armor": 100, "reload": 5.8, "price": 3800},
    "T-34-85": {"hp": 930, "damage": 200, "pen": 128, "armor": 45, "reload": 6.6, "price": 1500},
    "M4A3E8": {"hp": 980, "damage": 160, "pen": 128, "armor": 63, "reload": 5.0, "price": 1500},
    "Cromwell": {"hp": 900, "damage": 150, "pen": 145, "armor": 63, "reload": 4.5, "price": 1500},
    "Leopard 1": {"hp": 1800, "damage": 350, "pen": 250, "armor": 120, "reload": 7.0, "price": 6000}
}
for i in range(1, 30):
    TANKS_DB[f"Танк_{i}"] = {"hp": random.randint(900, 2000), "damage": random.randint(200, 500), "pen": random.randint(150, 280), "armor": random.randint(60, 180), "reload": round(random.uniform(5, 15), 1), "price": random.randint(1500, 7000)}

# --- ЗВАНИЯ И ОПЫТ ---
RANKS = {
    1: ("Новичок", 0, 0), 2: ("Гость", 100, 0), 3: ("Освоившийся", 300, 0), 4: ("Постоянный", 700, 0),
    5: ("Ветеран", 1500, 0), 6: ("Активный", 3000, 0), 7: ("Знаток", 6000, 0), 8: ("Эксперт", 12000, 0),
    9: ("Гуру", 24000, 0), 10: ("Легенда", 48000, 0), 11: ("Идейный", 0, 1), 12: ("Юный мододел", 0, 3),
    13: ("Мододел", 0, 5), 14: ("Старший мододел", 0, 10), 15: ("Мастер модов", 0, 20),
    16: ("Тестер", 0, 0), 17: ("Младший модератор", 0, 0), 18: ("Модератор", 0, 0), 19: ("Администратор", 0, 0),
    20: ("Вице-владелец", 0, 0), 21: ("Владелец", 0, 0),
}
ACHIEVEMENTS = {
    "first_download": "Первый мод", "mods_10": "10 модов", "mods_50": "50 модов",
    "first_idea": "Первая идея", "first_question": "Первый вопрос", "veteran": "Ветеран",
    "banned_1": "Первый бан", "banned_10": "10 банов", "tank_buyer": "Покупатель танков",
    "first_win": "Первая победа", "win_10": "10 побед", "social": "Душа компании"
}

def default_user_data():
    return {
        "lang": "ru", "nickname": None, "xp": 0, "rank_id": 1, "downloads": 0, "ideas": 0, "questions": 0, "bans": 0,
        "achievements": [], "registered": datetime.now().strftime("%Y-%m-%d"), "appeal_pending": False,
        "tanks": ["FV215B 183"], "selected_tank": "FV215B 183",
        "battles": 0, "wins": 0, "losses": 0, "friends": [], "friend_requests": []
    }

def get_rank_info(rank_id): return RANKS.get(rank_id, RANKS[1])

def check_rank_up(user_id):
    data = USERS.get(user_id)
    if not data: return None
    current_id = data["rank_id"]
    next_id = current_id + 1
    if next_id not in RANKS or next_id > 10: return None
    _, req_xp, req_ideas = RANKS[next_id]
    if data["xp"] >= req_xp and data["ideas"] >= req_ideas:
        data["rank_id"] = next_id
        save_users()
        return RANKS[next_id][0]
    return None

def add_xp(user_id, amount):
    if user_id not in USERS: USERS[user_id] = default_user_data()
    USERS[user_id]["xp"] += amount
    save_users()

def unlock_achievement(user_id, ach_key):
    data = USERS.get(user_id)
    if data and ach_key not in data["achievements"]:
        data["achievements"].append(ach_key)
        save_users()
        return ACHIEVEMENTS.get(ach_key)
    return None

def get_display_name(uid):
    user = USERS.get(str(uid), {})
    nick = user.get("nickname")
    if nick: return nick
    return f"Танкист_{str(uid)[-4:]}"

def load_data():
    global FILE_IDS, USERS, BANNED, FALLBACKS
    FILE_IDS = {
        "old_font.rar": "BQACAgIAAyEFAASo0DuCAAPRaudEoy_WaUJytv6Ax-5vHj49Zk8AAqqZAAJuI4FJZH-8dxswqq09BA",
        "old_medals.zip": "BQACAgIAAyEFAASo0DuCAAPQaudEo89jj1q6kdFa5l4mjYzZCmoAAqmZAAJuI4FJly1Z9B-lN4E9BA",
        "old_ui.rar": "BQACAgIAAyEFAASo0DuCAAPSaudEozVgaEGz-USX1kCO8mw9czsAAp-qAAJqFCBLsufG1Xs4z3E9BA",
    }
    try:
        with open(FILE_IDS_PATH) as f: FILE_IDS.update(json.load(f))
    except: pass
    try:
        with open(USERS_PATH) as f:
            raw = json.load(f)
            for uid, val in raw.items():
                base = default_user_data(); base.update(val)
                USERS[uid] = base
    except: pass
    try:
        with open(BANNED_PATH) as f: BANNED.update(json.load(f))
    except: pass
    try:
        with open(FALLBACKS_PATH, encoding="utf-8") as f: FALLBACKS.update(json.load(f))
    except: pass

def save_file_ids():
    with open(FILE_IDS_PATH, "w") as f: json.dump(FILE_IDS, f)
def save_users():
    with open(USERS_PATH, "w") as f: json.dump(USERS, f, ensure_ascii=False)
def save_banned():
    with open(BANNED_PATH, "w") as f: json.dump(BANNED, f)

load_data()

# --- ЛОКАЛИЗАЦИЯ ---
LOCALES = {
    "ru": {
        "start": "Привет, {name}!\n\nДобро пожаловать! Выбери нужный раздел:",
        "choose_lang": "Выбери язык / Абяры мову / Choose language:",
        "lang_changed": "Язык изменён на Русский",
        "btn_mods": "Моды", "btn_fun": "Приколы", "btn_help": "Помощь", "btn_suggest": "Предложить мод",
        "btn_feedback": "Обратная связь", "btn_dev": "В разработке", "btn_donate": "Поддержать",
        "btn_bug": "Сообщить об ошибке", "btn_question": "Задать вопрос", "btn_misc": "Разное",
        "btn_lang": "Язык", "btn_profile": "Профиль", "btn_back": "Назад", "btn_invite": "Пригласить друга",
        "main_menu": "Главное меню", "feedback_menu": "<b>Обратная связь</b>\n\nВыбери действие:",
        "mods_menu": "<b>Моды</b>\n\nВыбери мод:", "subscribe_needed": "Чтобы скачать этот мод, подпишись на канал!",
        "btn_subscribe": "Подписаться на канал", "version": "Версия мода: {ver}", "btn_info": "Описание мода",
        "cancel": "Отменено", "nothing_cancel": "Нечего отменять",
        "profile_title": "<b>Профиль</b>", "profile_nick": "Ник: <b>{nick}</b>", "profile_rank": "Звание: <b>{rank}</b>",
        "profile_xp": "Опыт: {xp} XP", "profile_stats": "<b>Статистика</b>\nБоёв: {battles} | Побед: {wins} | Поражений: {losses}\nМодов: {downloads} | Идей: {ideas} | Вопросов: {questions}",
        "profile_tank": "Твой танк: <b>{tank}</b>", "profile_next": "До след. звания: {xp_left} XP (и {ideas_left} идей)",
        "profile_manual": "Следующее звание вручную",
        "btn_friends": "👥 Друзья", "shop_btn": "🛒 Магазин танков",
        "friends_title": "<b>Друзья</b>", "friends_requests": "\n🔔 <b>Входящие заявки:</b>", "friends_list": "\n👥 <b>Твои друзья:</b>",
        "friends_empty": "\nУ тебя пока нет друзей.", "friends_accept": "Принять", "friends_decline": "Отклонить",
        "nickname_prompt": "Придумай себе ник (от 3 до 15 символов):", "nickname_taken": "Этот ник уже занят!",
        "nickname_invalid": "Ник должен быть от 3 до 15 символов без пробелов.", "nickname_success": "Отлично, твой ник теперь <b>{nick}</b>!",
        "friend_req_sent": "Заявка отправлена!", "friend_req_accept": "Ты принял заявку от {name}!", "friend_req_decline": "Заявка отклонена.",
        "friend_msg_prompt": "Напиши сообщение для <b>{name}</b>:", "friend_msg_sent": "Сообщение отправлено!",
        "friend_msg_received": "✉️ <b>Сообщение от друга ({name}):</b>\n\n{text}",
        "battle_desc": "⚔️ <b>Танковые бои</b>\n\nЗдесь ты можешь сразиться с другими игроками!\n\n<b>Правила:</b>\n1. Выбираешь формат (или бой с ботом).\n2. Бот выдает танк из твоего ангара.\n3. Ходы по очереди! Выбирай снаряд и цель.\n4. Кто последний остался жив — забирает XP.\n\n<b>Важно:</b> Ты видишь только ник противника!",
        "battle_choose": "Выбери действие:", "battle_bot": "🤖 Бой с ботом", "battle_create": "Создать комнату",
        "battle_join": "Войти по коду", "battle_list": "Список комнат", "battle_back": "Назад",
        "shop_title": "🛒 <b>Магазин танков</b>\n\nТвой баланс: <b>{xp} XP</b>\nВыбери танк:", "shop_buy": "Купить за {price} XP",
        "shop_bought": "✅ Ты купил <b>{tank}</b>!", "shop_not_enough": "❌ Нужно {price} XP.", "shop_select": "Выбрать",
        "shop_selected": "🚀 Теперь твой танк: <b>{tank}</b>!",
        "tank_stats": "❤️ HP: {hp}\n💥 Урон: {damage}\n🎯 Пробитие: {pen}\n🛡 Броня: {armor}\n⏱ Перезарядка: {reload}с",
        "add_friend_btn": "🤝 Добавить в друзья",
    },
    "be": {}, "en": {}
}
for lang in ["be", "en"]: LOCALES[lang] = LOCALES["ru"].copy()

def tr(user_id, key, **kwargs):
    data = USERS.get(user_id)
    lang = data["lang"] if data and data.get("lang") else "ru"
    text = LOCALES.get(lang, LOCALES["ru"]).get(key, f"[{key}]")
    return text.format(**kwargs) if kwargs else text

# --- ПРОВЕРКА БАНА ---
def is_banned(user_id):
    if user_id not in BANNED: return False, {}
    info = BANNED[user_id]
    until_str = info.get("until", "")
    if until_str == "never": return True, info
    try: until = datetime.strptime(until_str, "%Y-%m-%d %H:%M:%S")
    except: return False, {}
    if datetime.now() >= until:
        del BANNED[user_id]; save_banned(); return False, {}
    return True, info

async def check_ban_and_block(message):
    uid = str(message.from_user.id)
    banned, info = is_banned(uid)
    if banned:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Подать заявку на разбан", callback_data="appeal_ban")]])
        await message.answer("Вы забанены в этом боте.\nПосмотреть свой срок бана: /mystatus", reply_markup=kb)
        return True
    return False

# --- КЛАВИАТУРЫ ---
def get_main_keyboard(uid):
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=tr(uid, "btn_mods")), KeyboardButton(text=tr(uid, "btn_fun"))],
        [KeyboardButton(text=tr(uid, "btn_profile")), KeyboardButton(text=tr(uid, "btn_help"))],
        [KeyboardButton(text=tr(uid, "btn_feedback")), KeyboardButton(text=tr(uid, "btn_misc"))],
    ], resize_keyboard=True)

def get_feedback_keyboard(uid):
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=tr(uid, "btn_suggest"))],
        [KeyboardButton(text=tr(uid, "btn_bug")), KeyboardButton(text=tr(uid, "btn_question"))],
        [KeyboardButton(text=tr(uid, "btn_back"))],
    ], resize_keyboard=True)

def get_mods_keyboard(uid):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Старый шрифт (v1.0)", callback_data="mod_old_font")],
        [InlineKeyboardButton(text="Старые медали (v1.0)", callback_data="mod_old_medals")],
        [InlineKeyboardButton(text="Старый UI ангара (v3.0)", callback_data="mod_old_ui")],
    ])

ALL_MENU_BUTTONS = set()
for d in LOCALES.values():
    for k, v in d.items():
        if k.startswith("btn_") or (k.startswith("misc_") and k.endswith("_btn")) or (k.startswith("help_") and k.endswith("_btn")):
            ALL_MENU_BUTTONS.add(v)

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

# --- ХЕЛПЕРЫ ---
def find_file_id(base_name):
    base_lower = base_name.lower()
    if base_name in FILE_IDS: return base_name, FILE_IDS[base_name]
    for name, fid in FILE_IDS.items():
        if name.rsplit(".", 1)[0].lower() == base_lower: return name, fid
    return None

async def check_subscription(user_id):
    if not CHANNEL_ID: return True
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ["creator", "administrator", "member"]
    except: return False

async def send_mod_file(chat_id, base_name, reply_markup=None):
    result = find_file_id(base_name)
    if not result:
        await bot.send_message(chat_id, "Временно недоступно"); return
    _, fid = result
    await bot.send_document(chat_id, fid, reply_markup=reply_markup)

async def forward_to_admins(message, header):
    for chat_id in TARGET_CHAT_IDS:
        try:
            await bot.send_message(chat_id, header, parse_mode="HTML")
            await message.forward(chat_id)
        except Exception as e: logger.error(f"Ошибка: {e}")

# --- СТАРТ И НИК ---
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    if await check_ban_and_block(message): return
    await state.clear()
    uid = str(message.from_user.id)
    args = message.text.split()
    is_new = uid not in USERS
    
    if len(args) > 1 and args[1].startswith("ref_"):
        referrer_id = args[1].replace("ref_", "")
        if referrer_id in USERS and referrer_id != uid and is_new:
            add_xp(referrer_id, 150); add_xp(uid, 150)
            try: await bot.send_message(int(referrer_id), "Твой друг зашел! +150 XP")
            except: pass
            await message.answer("Добро пожаловать по приглашению! +150 XP")
    
    if is_new:
        USERS[uid] = default_user_data()
        if message.from_user.id in ADMIN_IDS: USERS[uid]["rank_id"] = 13
        save_users()

    if not USERS[uid].get("nickname"):
        await state.set_state(UserState.awaiting_nickname)
        await message.answer(tr(uid, "nickname_prompt"), reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="/cancel")]], resize_keyboard=True))
        return

    await message.answer(tr(uid, "start", name=message.from_user.first_name), reply_markup=get_main_keyboard(uid))

@dp.message(UserState.awaiting_nickname)
async def process_nickname(message: Message, state: FSMContext):
    uid = str(message.from_user.id)
    nick = message.text.strip()
    if len(nick) < 3 or len(nick) > 15 or " " in nick:
        await message.answer(tr(uid, "nickname_invalid")); return
    if any(u.get("nickname", "").lower() == nick.lower() for u in USERS.values()):
        await message.answer(tr(uid, "nickname_taken")); return
    USERS[uid]["nickname"] = nick
    save_users()
    await state.clear()
    await message.answer(tr(uid, "nickname_success", nick=nick), reply_markup=get_main_keyboard(uid))

# --- ПРОФИЛЬ ---
@dp.message(Command("profile"))
async def cmd_profile(message: Message, state: FSMContext):
    if await check_ban_and_block(message): return
    await state.clear()
    uid = str(message.from_user.id)
    if uid not in USERS: await cmd_start(message, state); return
    data = USERS[uid]
    rank_name, _, _ = get_rank_info(data["rank_id"])
    nick = data.get("nickname") or "Не задан"
    next_id = data["rank_id"] + 1
    if next_id in RANKS and next_id <= 10:
        _, next_xp, next_ideas = RANKS[next_id]
        progress = tr(uid, "profile_next", xp_left=max(0, next_xp - data["xp"]), ideas_left=max(0, next_ideas - data["ideas"]))
    else: progress = tr(uid, "profile_manual")
    ach_text = "\n".join([f"• {ACHIEVEMENTS.get(a, a)}" for a in data["achievements"]]) if data["achievements"] else "Нет"
    text = (
        f"{tr(uid, 'profile_title')}\n{tr(uid, 'profile_nick', nick=nick)}\n\n"
        f"{tr(uid, 'profile_rank', rank=rank_name)}\n{tr(uid, 'profile_xp', xp=data['xp'])}\n"
        f"{tr(uid, 'profile_stats', battles=data['battles'], wins=data['wins'], losses=data['losses'], downloads=data['downloads'], ideas=data['ideas'], questions=data['questions'])}\n"
        f"{tr(uid, 'profile_tank', tank=data.get('selected_tank', 'FV215B 183'))}\n{progress}\n\n<b>Достижения:</b>\n{ach_text}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚔️ Бои", callback_data="battle_menu")],
        [InlineKeyboardButton(text=tr(uid, "shop_btn"), callback_data="shop_menu")],
        [InlineKeyboardButton(text=tr(uid, "btn_friends"), callback_data="friends_menu")],
        [InlineKeyboardButton(text=tr(uid, "btn_invite"), callback_data="invite_friend")]
    ])
    await message.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.message(F.text.in_([LOCALES["ru"]["btn_profile"]]))
async def btn_profile_click(message: Message, state: FSMContext): await cmd_profile(message, state)

@dp.callback_query(F.data == "back_to_profile")
async def cb_back_to_profile(callback: CallbackQuery, state: FSMContext):
    await state.clear(); await callback.answer(); await cmd_profile(callback.message, state)

# --- ДРУЗЬЯ ---
@dp.callback_query(F.data == "friends_menu")
async def cb_friends_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    uid = str(callback.from_user.id)
    data = USERS[uid]
    text = tr(uid, "friends_title")
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    if data.get("friend_requests"):
        text += tr(uid, "friends_requests") + "\n"
        for req_uid in data["friend_requests"]:
            req_name = get_display_name(req_uid)
            kb.inline_keyboard.append([
                InlineKeyboardButton(text=f"✅ {req_name}", callback_data=f"friend_accept_{req_uid}"),
                InlineKeyboardButton(text="❌", callback_data=f"friend_decline_{req_uid}")
            ])
    text += tr(uid, "friends_list") + "\n"
    if data.get("friends"):
        for f_uid in data["friends"]:
            f_name = get_display_name(f_uid)
            kb.inline_keyboard.append([InlineKeyboardButton(text=f"💬 {f_name}", callback_data=f"friend_msg_{f_uid}")])
    else: text += tr(uid, "friends_empty")
    kb.inline_keyboard.append([InlineKeyboardButton(text=tr(uid, "btn_back"), callback_data="back_to_profile")])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("friend_accept_"))
async def cb_friend_accept(callback: CallbackQuery):
    uid = str(callback.from_user.id)
    req_uid = callback.data.replace("friend_accept_", "")
    data = USERS.get(uid)
    if req_uid in data.get("friend_requests", []):
        data["friend_requests"].remove(req_uid)
        data.setdefault("friends", []).append(req_uid)
        USERS[req_uid].setdefault("friends", []).append(uid)
        save_users()
        await callback.answer(f"Ты принял заявку от {get_display_name(req_uid)}!", show_alert=True)
        try: await bot.send_message(int(req_uid), f"✅ {get_display_name(uid)} принял твою заявку в друзья!")
        except: pass
    await cb_friends_menu(callback, FSMContext(storage=dp.storage, key=None, chat_id=None, user_id=None))

@dp.callback_query(F.data.startswith("friend_decline_"))
async def cb_friend_decline(callback: CallbackQuery):
    uid = str(callback.from_user.id)
    req_uid = callback.data.replace("friend_decline_", "")
    if req_uid in USERS[uid].get("friend_requests", []):
        USERS[uid]["friend_requests"].remove(req_uid)
        save_users()
        await callback.answer("Заявка отклонена.", show_alert=True)
    await cb_friends_menu(callback, FSMContext(storage=dp.storage, key=None, chat_id=None, user_id=None))

@dp.callback_query(F.data.startswith("friend_req_"))
async def cb_friend_req(callback: CallbackQuery):
    sender_uid = str(callback.from_user.id)
    target_uid = callback.data.replace("friend_req_", "")
    if target_uid == sender_uid: await callback.answer("Это ты сам!", show_alert=True); return
    target_data = USERS.get(target_uid)
    if not target_data: await callback.answer("Игрок не найден", show_alert=True); return
    if sender_uid in target_data.get("friends", []): await callback.answer("Вы уже друзья!", show_alert=True); return
    if sender_uid in target_data.get("friend_requests", []): await callback.answer("Заявка уже отправлена!", show_alert=True); return
    target_data.setdefault("friend_requests", []).append(sender_uid)
    save_users()
    try: await bot.send_message(int(target_uid), f"🔔 Тебе пришла заявка в друзья от <b>{get_display_name(sender_uid)}</b>!\nЗайди в Профиль -> Друзья.", parse_mode="HTML")
    except: pass
    await callback.answer("Заявка отправлена!", show_alert=True)

@dp.callback_query(F.data.startswith("friend_msg_"))
async def cb_friend_msg(callback: CallbackQuery, state: FSMContext):
    target_uid = callback.data.replace("friend_msg_", "")
    await state.set_state(UserState.awaiting_friend_msg)
    await state.update_data(friend_target=target_uid)
    await callback.message.answer(tr(str(callback.from_user.id), "friend_msg_prompt", name=get_display_name(target_uid)), parse_mode="HTML")
    await callback.answer()

@dp.message(UserState.awaiting_friend_msg, ~F.text.in_(ALL_MENU_BUTTONS))
async def process_friend_msg(message: Message, state: FSMContext):
    data = await state.get_data()
    target_uid = data.get("friend_target")
    uid = str(message.from_user.id)
    await state.clear()
    if not target_uid: return
    try:
        await bot.send_message(int(target_uid), tr(target_uid, "friend_msg_received", name=get_display_name(uid), text=message.text), parse_mode="HTML")
        await message.answer(tr(uid, "friend_msg_sent"), reply_markup=get_main_keyboard(uid))
        if "social" not in USERS[uid]["achievements"]:
            USERS[uid]["achievements"].append("social"); save_users()
    except:
        await message.answer("Не удалось отправить (возможно, пользователь заблокировал бота).", reply_markup=get_main_keyboard(uid))

# --- МАГАЗИН ---
@dp.callback_query(F.data == "shop_menu")
async def cb_shop_menu(callback: CallbackQuery):
    uid = str(callback.from_user.id)
    data = USERS.get(uid, default_user_data())
    owned = data.get("tanks", [])
    available = {name: stats for name, stats in TANKS_DB.items() if name not in owned}
    if not available: await callback.message.answer("Все танки скуплены!"); await callback.answer(); return
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for name, stats in list(available.items())[:10]:
        kb.inline_keyboard.append([InlineKeyboardButton(text=f"{name} ({stats['price']} XP)", callback_data=f"shop_view_{name}")])
    kb.inline_keyboard.append([InlineKeyboardButton(text=tr(uid, "battle_back"), callback_data="back_to_profile")])
    await callback.message.edit_text(tr(uid, "shop_title", xp=data["xp"]), parse_mode="HTML", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("shop_view_"))
async def cb_shop_view(callback: CallbackQuery):
    uid = str(callback.from_user.id)
    tank_name = callback.data.replace("shop_view_", "")
    stats = TANKS_DB.get(tank_name)
    if not stats: await callback.answer("Танк не найден"); return
    data = USERS.get(uid, default_user_data())
    is_owned = tank_name in data.get("tanks", [])
    text = f"<b>{tank_name}</b>\n\n" + tr(uid, "tank_stats", **stats)
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    if is_owned:
        if data.get("selected_tank") == tank_name: kb.inline_keyboard.append([InlineKeyboardButton(text="✅ Выбран", callback_data="noop")])
        else: kb.inline_keyboard.append([InlineKeyboardButton(text=tr(uid, "shop_select"), callback_data=f"shop_select_{tank_name}")])
    else:
        kb.inline_keyboard.append([InlineKeyboardButton(text=tr(uid, "shop_buy", price=stats['price']), callback_data=f"shop_buy_{tank_name}")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="Назад", callback_data="shop_menu")])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("shop_buy_"))
async def cb_shop_buy(callback: CallbackQuery):
    uid = str(callback.from_user.id)
    tank_name = callback.data.replace("shop_buy_", "")
    stats = TANKS_DB.get(tank_name)
    data = USERS.get(uid, default_user_data())
    if data["xp"] < stats["price"]: await callback.answer(tr(uid, "shop_not_enough", price=stats['price']), show_alert=True); return
    data["xp"] -= stats["price"]
    data.setdefault("tanks", []).append(tank_name)
    data["selected_tank"] = tank_name
    save_users()
    unlock_achievement(uid, "tank_buyer")
    await callback.answer(tr(uid, "shop_bought", tank=tank_name), show_alert=True)
    await cb_shop_view(callback)

@dp.callback_query(F.data.startswith("shop_select_"))
async def cb_shop_select(callback: CallbackQuery):
    uid = str(callback.from_user.id)
    tank_name = callback.data.replace("shop_select_", "")
    data = USERS.get(uid, default_user_data())
    if tank_name in data.get("tanks", []):
        data["selected_tank"] = tank_name
        save_users()
        await callback.answer(tr(uid, "shop_selected", tank=tank_name), show_alert=True)
    await cb_shop_view(callback)

# --- БОИ ---
@dp.callback_query(F.data == "battle_menu")
async def cb_battle_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    uid = str(callback.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr(uid, "battle_bot"), callback_data="battle_vs_bot")],
        [InlineKeyboardButton(text=tr(uid, "battle_create"), callback_data="create_room")],
        [InlineKeyboardButton(text=tr(uid, "battle_join"), callback_data="join_by_code")],
        [InlineKeyboardButton(text=tr(uid, "battle_list"), callback_data="list_rooms")],
        [InlineKeyboardButton(text=tr(uid, "battle_back"), callback_data="back_to_profile")]
    ])
    await callback.message.edit_text(tr(uid, "battle_desc") + "\n\n" + tr(uid, "battle_choose"), parse_mode="HTML", reply_markup=kb)
    await callback.answer()

def calculate_shot(attacker_stats, target_stats, ammo_type, target_defending):
    pen_variance = random.uniform(0.95, 1.05)
    effective_pen = attacker_stats["pen"] * pen_variance
    target_armor = target_stats["armor"]
    if target_defending: target_armor = int(target_armor * 1.5)
    dmg_variance = random.uniform(0.75, 1.25)
    if ammo_type == "ap":
        if effective_pen < target_armor: return 0, f"Не пробил! Броня {target_armor} мм выдержала."
        final_dmg = int(attacker_stats["damage"] * dmg_variance)
        return final_dmg, f"Пробитие! Урон: {final_dmg}"
    else:
        base_he = attacker_stats["damage"] * 0.5
        final_dmg = int(base_he * dmg_variance)
        if target_defending: final_dmg = int(final_dmg * 0.5)
        return final_dmg, f"ОФ попал! Урон: {final_dmg}"

# PvE
@dp.callback_query(F.data == "battle_vs_bot")
async def cb_battle_vs_bot(callback: CallbackQuery, state: FSMContext):
    uid = str(callback.from_user.id)
    data = USERS.get(uid, default_user_data())
    tank_name = data.get("selected_tank", "FV215B 183")
    tank_stats = TANKS_DB.get(tank_name, TANKS_DB["FV215B 183"]).copy()
    bot_tank_name = random.choice([n for n in TANKS_DB if n != "FV215B 183"])
    bot_stats = TANKS_DB[bot_tank_name].copy()
    await state.set_state(UserState.in_battle)
    await state.update_data(is_pve=True, turn="player", p_hp=tank_stats["hp"], e_hp=bot_stats["hp"], p_tank=tank_name, e_tank=bot_tank_name, p_defend=False, e_defend=False, p_reload_ready=0, p_stats=tank_stats, e_stats=bot_stats)
    text = f"🤖 <b>Бой против бота</b>\n\nТвой танк: <b>{tank_name}</b> (HP: {tank_stats['hp']})\nТанк врага: <b>Неизвестно</b>\n\nТвой ход!"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💥 Выстрел (ББ)", callback_data="pve_shoot_ap")],
        [InlineKeyboardButton(text="💥 Выстрел (ОФ)", callback_data="pve_shoot_he")],
        [InlineKeyboardButton(text="🛡 Защита", callback_data="pve_defend")],
        [InlineKeyboardButton(text="🏳️ Сдаться", callback_data="pve_surrender")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("pve_shoot_"), UserState.in_battle)
async def cb_pve_shoot(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    if not data.get("is_pve"): return
    ammo = callback.data.replace("pve_shoot_", "")
    p_stats, e_stats = data["p_stats"], data["e_stats"]
    p_hp, e_hp = data["p_hp"], data["e_hp"]
    now = time.time()
    if now < data.get("p_reload_ready", 0): await callback.answer("Орудие перезаряжается!", show_alert=True); return
    damage, msg = calculate_shot(p_stats, e_stats, ammo, data.get("e_defend", False))
    e_hp -= damage; data["e_defend"] = False
    text = f"Ты выстрелил ({'ББ' if ammo=='ap' else 'ОФ'}): {msg}\n"
    if e_hp <= 0:
        xp_reward = random.randint(50, 100)
        add_xp(str(callback.from_user.id), xp_reward)
        USERS[str(callback.from_user.id)]["wins"] += 1
        USERS[str(callback.from_user.id)]["battles"] += 1
        save_users()
        unlock_achievement(str(callback.from_user.id), "first_win")
        text += f"\n💀 <b>Враг уничтожен!</b>\n🏆 Победа! +{xp_reward} XP.\n\n👀 Танк врага: <b>{data['e_tank']}</b>"
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="В меню", callback_data="battle_menu")]]))
        await state.clear(); return
    bot_action = random.choices(["ap", "he", "defend"], weights=[0.6, 0.2, 0.2])[0]
    if bot_action == "defend": data["e_defend"] = True; text += f"🛡 Враг ушел в защиту.\n"
    else:
        b_damage, b_msg = calculate_shot(e_stats, p_stats, bot_action, data.get("p_defend", False))
        p_hp -= b_damage; data["p_defend"] = False
        text += f"🔫 Враг выстрелил: {b_msg}\n"
    if p_hp <= 0:
        USERS[str(callback.from_user.id)]["losses"] += 1
        USERS[str(callback.from_user.id)]["battles"] += 1
        save_users()
        text += f"\n💀 <b>Ты уничтожен!</b>\nТанк врага: <b>{data['e_tank']}</b>"
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="В меню", callback_data="battle_menu")]]))
        await state.clear(); return
    reload_time = p_stats["reload"]
    data["p_reload_ready"] = time.time() + reload_time
    text += f"\n❤️ HP: {p_hp}\n💀 HP врага: {e_hp}\n⏱ Перезарядка: {reload_time}с\n\nТвой ход:"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💥 Выстрел (ББ)", callback_data="pve_shoot_ap")],
        [InlineKeyboardButton(text="💥 Выстрел (ОФ)", callback_data="pve_shoot_he")],
        [InlineKeyboardButton(text="🛡 Защита", callback_data="pve_defend")],
        [InlineKeyboardButton(text="🏳️ Сдаться", callback_data="pve_surrender")]
    ])
    await state.update_data(p_hp=p_hp, e_hp=e_hp)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "pve_defend", UserState.in_battle)
async def cb_pve_defend(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    if not data.get("is_pve"): return
    data["p_defend"] = True
    text = "🛡 Ты ушел в защиту.\n"
    bot_action = random.choices(["ap", "he", "defend"], weights=[0.6, 0.2, 0.2])[0]
    if bot_action == "defend": data["e_defend"] = True; text += "🛡 Враг тоже в защите.\n"
    else:
        b_damage, b_msg = calculate_shot(data["e_stats"], data["p_stats"], bot_action, True)
        p_hp = data["p_hp"] - b_damage
        text += f"🔫 Враг выстрелил: {b_msg}\n"
        data["p_hp"] = p_hp; data["p_defend"] = False
        if p_hp <= 0:
            USERS[str(callback.from_user.id)]["losses"] += 1
            USERS[str(callback.from_user.id)]["battles"] += 1
            save_users()
            await callback.message.edit_text(text + "\n💀 Ты уничтожен!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="В меню", callback_data="battle_menu")]]))
            await state.clear(); return
    reload_time = data["p_stats"]["reload"]
    data["p_reload_ready"] = time.time() + reload_time
    text += f"\n❤️ HP: {data['p_hp']}\n💀 HP врага: {data['e_hp']}\nТвой ход:"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💥 Выстрел (ББ)", callback_data="pve_shoot_ap")],
        [InlineKeyboardButton(text="💥 Выстрел (ОФ)", callback_data="pve_shoot_he")],
        [InlineKeyboardButton(text="🛡 Защита", callback_data="pve_defend")],
        [InlineKeyboardButton(text="🏳️ Сдаться", callback_data="pve_surrender")]
    ])
    await state.update_data(p_hp=data["p_hp"], e_hp=data["e_hp"])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "pve_surrender", UserState.in_battle)
async def cb_pve_surrender(callback: CallbackQuery, state: FSMContext):
    await callback.answer("Ты сдался")
    USERS[str(callback.from_user.id)]["losses"] += 1
    USERS[str(callback.from_user.id)]["battles"] += 1
    save_users()
    await state.clear()
    await callback.message.edit_text("🏳️ Ты сдался.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="В меню", callback_data="battle_menu")]]))

# PvP
ROOMS = {}
def generate_room_code(): return ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))

@dp.callback_query(F.data == "create_room")
async def cb_create_room(callback: CallbackQuery, state: FSMContext):
    uid = str(callback.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 на 1", callback_data="create_2")],
        [InlineKeyboardButton(text="2 на 2", callback_data="create_4")]
    ])
    await state.set_state(UserState.choosing_size)
    await callback.message.edit_text("Выбери формат:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(UserState.choosing_size, F.data.startswith("create_"))
async def cb_create_size(callback: CallbackQuery, state: FSMContext):
    max_players = int(callback.data.replace("create_", ""))
    await state.clear()
    uid = str(callback.from_user.id)
    code = generate_room_code()
    ROOMS[code] = {"players": [uid], "max_players": max_players, "is_private": False, "status": "waiting", "hp": {}, "tank": {}, "stats": {}, "defend": {}, "reload": {}}
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Скрыть", callback_data=f"hide_{code}")],
        [InlineKeyboardButton(text="Начать бой", callback_data=f"start_battle_{code}")],
        [InlineKeyboardButton(text="Выйти", callback_data=f"leave_{code}")]
    ])
    await callback.message.edit_text(f"🏠 Комната: <code>{code}</code>\nИгроков: 1/{max_players}", parse_mode="HTML", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("hide_"))
async def cb_hide_room(callback: CallbackQuery):
    code = callback.data.replace("hide_", "")
    if code in ROOMS: ROOMS[code]["is_private"] = True; await callback.message.edit_text(callback.message.text + "\n🔒 Скрыто", parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("leave_"))
async def cb_leave_room(callback: CallbackQuery, state: FSMContext):
    code = callback.data.replace("leave_", "")
    if code in ROOMS: del ROOMS[code]
    await callback.answer("Вышел"); await cb_back_to_profile(callback, state)

@dp.callback_query(F.data == "join_by_code")
async def cb_join_by_code(callback: CallbackQuery, state: FSMContext):
    await state.set_state(UserState.entering_code)
    await callback.message.edit_text("Введи код комнаты:")
    await callback.answer()

@dp.message(UserState.entering_code)
async def process_code(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    await state.clear()
    uid = str(message.from_user.id)
    if code not in ROOMS: await message.answer("❌ Комната не найдена."); return
    room = ROOMS[code]
    if room["status"] != "waiting" or len(room["players"]) >= room["max_players"]: await message.answer("❌ Нельзя зайти."); return
    if uid in room["players"]: await message.answer("Ты уже тут."); return
    room["players"].append(uid)
    if len(room["players"]) == room["max_players"]: await start_room_battle(code, message.chat.id)
    else: await message.answer(f"✅ В комнате {code}. Ждем ({len(room['players'])}/{room['max_players']}).")

@dp.callback_query(F.data == "list_rooms")
async def cb_list_rooms(callback: CallbackQuery):
    open_rooms = {k: v for k, v in ROOMS.items() if v["status"] == "waiting" and not v["is_private"]}
    if not open_rooms: await callback.answer("Нет комнат.", show_alert=True); return
    lines = ["<b>Комнаты:</b>"] + [f"<code>{c}</code> | {len(r['players'])}/{r['max_players']}" for c, r in open_rooms.items()]
    await callback.message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Назад", callback_data="battle_menu")]]))
    await callback.answer()

@dp.callback_query(F.data.startswith("start_battle_"))
async def cb_start_battle_manual(callback: CallbackQuery):
    code = callback.data.replace("start_battle_", "")
    if code in ROOMS and ROOMS[code]["max_players"] == 2 and len(ROOMS[code]["players"]) >= 1:
        await callback.message.edit_text("⚔️ Бой начинается...")
        await start_room_battle(code, callback.message.chat.id)

async def start_room_battle(code, chat_id):
    room = ROOMS[code]
    room["status"] = "battle"; room["turn_index"] = 0
    room["defend"] = {p: False for p in room["players"]}
    room["reload"] = {p: 0 for p in room["players"]}
    text = "⚔️ <b>Бой начался!</b>\n\n"
    for uid in room["players"]:
        tank_name = USERS.get(uid, {}).get("selected_tank", "FV215B 183")
        stats = TANKS_DB.get(tank_name, TANKS_DB["FV215B 183"]).copy()
        room["hp"][uid] = stats["hp"]; room["tank"][uid] = tank_name; room["stats"][uid] = stats
        text += f"👤 <b>{get_display_name(uid)}</b> — {tank_name} (HP: {stats['hp']})\n"
    text += "\nХод первого игрока!"
    for uid in room["players"]:
        try:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💥 Выстрел (ББ)", callback_data=f"pvp_shoot_ap_{code}")],
                [InlineKeyboardButton(text="💥 Выстрел (ОФ)", callback_data=f"pvp_shoot_he_{code}")],
                [InlineKeyboardButton(text="🛡 Защита", callback_data=f"pvp_defend_{code}")]
            ])
            await bot.send_message(int(uid), text, parse_mode="HTML", reply_markup=kb)
        except: pass

@dp.callback_query(F.data.startswith("pvp_shoot_"))
async def cb_pvp_shoot(callback: CallbackQuery):
    parts = callback.data.split("_"); ammo = parts[2]; code = parts[3]
    uid = str(callback.from_user.id)
    if code not in ROOMS or ROOMS[code]["status"] != "battle": return
    room = ROOMS[code]
    if uid != room["players"][room["turn_index"]]: await callback.answer("Не твой ход!", show_alert=True); return
    if time.time() < room["reload"].get(uid, 0): await callback.answer("Перезарядка!", show_alert=True); return
    enemies = [p for p in room["players"] if p != uid]
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for enemy in enemies:
        kb.inline_keyboard.append([InlineKeyboardButton(text=f"Цель: {get_display_name(enemy)}", callback_data=f"pvp_target_{code}_{enemy}_{ammo}")])
    await callback.message.edit_text("Выбери цель:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("pvp_target_"))
async def cb_pvp_target(callback: CallbackQuery):
    parts = callback.data.split("_"); code = parts[2]; target_id = parts[3]; ammo = parts[4]
    uid = str(callback.from_user.id)
    if code not in ROOMS or ROOMS[code]["status"] != "battle": return
    room = ROOMS[code]
    if uid != room["players"][room["turn_index"]]: return
    damage, msg = calculate_shot(room["stats"][uid], room["stats"][target_id], ammo, room["defend"].get(target_id, False))
    room["hp"][target_id] -= damage; room["defend"][target_id] = False
    text = f"💥 <b>{get_display_name(uid)}</b> попал в <b>{get_display_name(target_id)}</b> ({'ББ' if ammo=='ap' else 'ОФ'})!\n{msg}\n"
    text += f"❤️ У {get_display_name(target_id)} осталось {max(0, room['hp'][target_id])} HP."
    if room["hp"][target_id] <= 0:
        text += f"\n\n💀 <b>{get_display_name(target_id)}</b> уничтожен!"
        room["players"].remove(target_id)
        if room["turn_index"] >= len(room["players"]): room["turn_index"] = 0
        
        USERS[target_id]["losses"] += 1; USERS[target_id]["battles"] += 1
        if len(room["players"]) == 1:
            winner = room["players"][0]
            xp_reward = random.randint(50, 100)
            add_xp(winner, xp_reward)
            USERS[winner]["wins"] += 1; USERS[winner]["battles"] += 1
            unlock_achievement(winner, "first_win")
            text += f"\n\n🏆 <b>Победитель: {get_display_name(winner)}!</b>\n💰 +{xp_reward} XP"
            save_users()
            
            kb_winner = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🤝 Добавить в друзья", callback_data=f"friend_req_{target_id}")]])
            kb_loser = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🤝 Добавить в друзья", callback_data=f"friend_req_{winner}")]])
            
            try: await bot.send_message(int(winner), text, parse_mode="HTML", reply_markup=kb_winner)
            except: pass
            try: await bot.send_message(int(target_id), text, parse_mode="HTML", reply_markup=kb_loser)
            except: pass
            del ROOMS[code]
            return
        
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
                    [InlineKeyboardButton(text="💥 Выстрел (ОФ)", callback_data=f"pvp_shoot_he_{code}")],
                    [InlineKeyboardButton(text="🛡 Защита", callback_data=f"pvp_defend_{code}")]
                ])
            await bot.send_message(int(p), msg_text, parse_mode="HTML", reply_markup=kb)
        except: pass
    await callback.answer()

@dp.callback_query(F.data.startswith("pvp_defend_"))
async def cb_pvp_defend(callback: CallbackQuery):
    code = callback.data.replace("pvp_defend_", "")
    uid = str(callback.from_user.id)
    if code not in ROOMS or ROOMS[code]["status"] != "battle": return
    room = ROOMS[code]
    if uid != room["players"][room["turn_index"]]: return
    room["defend"][uid] = True
    text = f"🛡 <b>{get_display_name(uid)}</b> ушел в защиту."
    room["turn_index"] = (room["turn_index"] + 1) % len(room["players"])
    next_uid = room["players"][room["turn_index"]]
    for p in room["players"]:
        try:
            msg_text = text + f"\n\nСледующий ход: <b>{get_display_name(next_uid)}</b>"
            kb = None
            if p == next_uid:
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💥 Выстрел (ББ)", callback_data=f"pvp_shoot_ap_{code}")],
                    [InlineKeyboardButton(text="💥 Выстрел (ОФ)", callback_data=f"pvp_shoot_he_{code}")],
                    [InlineKeyboardButton(text="🛡 Защита", callback_data=f"pvp_defend_{code}")]
                ])
            await bot.send_message(int(p), msg_text, parse_mode="HTML", reply_markup=kb)
        except: pass
    await callback.answer()

# --- МОДЫ И ОБРАТНАЯ СВЯЗЬ ---
@dp.message(F.text.in_([LOCALES["ru"]["btn_mods"]]))
async def btn_mods(message: Message, state: FSMContext):
    if await check_ban_and_block(message): return
    await state.clear()
    uid = str(message.from_user.id)
    await message.answer(tr(uid, "mods_menu"), parse_mode="HTML", reply_markup=get_mods_keyboard(uid))

@dp.callback_query(F.data.startswith("mod_old_"))
async def cb_mod_any(callback: CallbackQuery):
    uid = str(callback.from_user.id)
    if is_banned(uid)[0]: await callback.answer("Вы забанены", show_alert=True); return
    if callback.data == "mod_old_ui_info":
        await callback.answer(); await callback.message.answer("Описание мода старого UI..."); return
    await callback.answer()
    mod_key = callback.data.replace("mod_", "")
    version = "v3.0" if mod_key == "old_ui" else "v1.0"
    if not await check_subscription(callback.from_user.id):
        await callback.message.answer(tr(uid, "subscribe_needed"), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(uid, "btn_subscribe"), url=CHANNEL_LINK)]]))
        return
    await callback.message.answer(tr(uid, "version", ver=version))
    ext = "zip" if mod_key == "old_medals" else "rar"
    await send_mod_file(callback.from_user.id, f"{mod_key}.{ext}")
    if uid not in USERS: USERS[uid] = default_user_data()
    USERS[uid]["downloads"] += 1
    add_xp(uid, 10)
    save_users()
    new_rank = check_rank_up(uid)
    if new_rank: await callback.message.answer(tr(uid, "rank_up", rank=new_rank))

@dp.message(F.text.in_([LOCALES["ru"]["btn_fun"]]))
async def btn_fun(message: Message, state: FSMContext):
    if await check_ban_and_block(message): return
    await state.set_state(UserState.awaiting_fun)
    await message.answer("Кидай свой игровой прикол сюда!\nДля отмены напиши /cancel", reply_markup=get_main_keyboard(str(message.from_user.id)))

@dp.message(UserState.awaiting_fun, ~F.text.in_(ALL_MENU_BUTTONS))
async def receive_fun(message: Message, state: FSMContext):
    await state.clear()
    uid = str(message.from_user.id)
    user = message.from_user
    header = f"<b>Прикол от пользователя!</b>\n👤 {user.full_name} (@{user.username})\n🆔 <code>{user.id}</code>\n\n"
    await forward_to_admins(message, header)
    add_xp(uid, 5)
    await message.answer("Спасибо! Твой прикол принят.", reply_markup=get_main_keyboard(uid))

@dp.message(F.text.in_([LOCALES["ru"]["btn_feedback"]]))
async def btn_feedback(message: Message, state: FSMContext):
    if await check_ban_and_block(message): return
    await state.clear()
    await message.answer(tr(str(message.from_user.id), "feedback_menu"), parse_mode="HTML", reply_markup=get_feedback_keyboard(str(message.from_user.id)))

@dp.message(F.text.in_([LOCALES["ru"]["btn_back"]]))
async def btn_back(message: Message, state: FSMContext):
    await state.clear()
    uid = str(message.from_user.id)
    await message.answer(tr(uid, "main_menu"), reply_markup=get_main_keyboard(uid))

@dp.message(F.text.in_([LOCALES["ru"]["btn_suggest"]]))
async def btn_suggest_mod(message: Message, state: FSMContext):
    if await check_ban_and_block(message): return
    await state.set_state(UserState.awaiting_mod_suggestion)
    await message.answer("Опиши свою идею для мода. Для отмены /cancel", reply_markup=get_feedback_keyboard(str(message.from_user.id)))

@dp.message(UserState.awaiting_mod_suggestion, ~F.text.in_(ALL_MENU_BUTTONS))
async def receive_mod_suggestion(message: Message, state: FSMContext):
    await state.clear()
    uid = str(message.from_user.id)
    user = message.from_user
    header = f"<b>Новая идея от пользователя!</b>\n👤 {user.full_name} (@{user.username})\n🆔 <code>{user.id}</code>\n\n"
    await forward_to_admins(message, header)
    if uid not in USERS: USERS[uid] = default_user_data()
    USERS[uid]["ideas"] += 1
    add_xp(uid, 25)
    save_users()
    new_rank = check_rank_up(uid)
    if new_rank: await message.answer(tr(uid, "rank_up", rank=new_rank))
    await message.answer("Твоя идея отправлена на рассмотрение!", reply_markup=get_main_keyboard(uid))

@dp.message(F.text.in_([LOCALES["ru"]["btn_bug"]]))
async def btn_bug_report(message: Message, state: FSMContext):
    if await check_ban_and_block(message): return
    await state.set_state(UserState.awaiting_bug_report)
    await message.answer("Опиши ошибку в моде. Для отмены /cancel", reply_markup=get_feedback_keyboard(str(message.from_user.id)))

@dp.message(UserState.awaiting_bug_report, ~F.text.in_(ALL_MENU_BUTTONS))
async def receive_bug_report(message: Message, state: FSMContext):
    uid = str(message.from_user.id)
    if message.voice or (not message.text and not message.photo and not message.video):
        await message.answer("Только текст, фото или видео."); return
    await state.clear()
    user = message.from_user
    header = f"<b>[ОШИБКА]</b>\n👤 {user.full_name} (@{user.username})\n🆔 <code>{user.id}</code>\n\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Исправлено", callback_data=f"bug_fixed_{uid}")]])
    for chat_id in TARGET_CHAT_IDS:
        try:
            await bot.send_message(chat_id, header, parse_mode="HTML", reply_markup=kb)
            await message.forward(chat_id)
        except: pass
    add_xp(uid, 15)
    await message.answer("Спасибо! Информация передана разработчикам.", reply_markup=get_main_keyboard(uid))

@dp.message(F.text.in_([LOCALES["ru"]["btn_question"]]))
async def btn_question(message: Message, state: FSMContext):
    if await check_ban_and_block(message): return
    await state.set_state(UserState.awaiting_question)
    await message.answer("Задай свой вопрос. Для отмены /cancel", reply_markup=get_feedback_keyboard(str(message.from_user.id)))

@dp.message(UserState.awaiting_question, ~F.text.in_(ALL_MENU_BUTTONS))
async def receive_question(message: Message, state: FSMContext):
    await state.clear()
    uid = str(message.from_user.id)
    user = message.from_user
    header = f"<b>Вопрос!</b>\n👤 {user.full_name} (@{user.username})\n🆔 <code>{user.id}</code>\n\nОтветьте Reply, чтобы отправить ответ."
    for chat_id in TARGET_CHAT_IDS:
        try:
            await bot.send_message(chat_id, header, parse_mode="HTML")
            await message.forward(chat_id)
        except: pass
    add_xp(uid, 5)
    await message.answer("Твой вопрос отправлен!", reply_markup=get_main_keyboard(uid))

# --- АДМИНКА ---
@dp.message(Command("ban"))
async def cmd_ban(message: Message):
    uid = str(message.from_user.id)
    if message.from_user.id not in ADMIN_IDS and USERS.get(uid, {}).get("rank_id", 0) < 18:
        return
    args = message.text.split()
    target_id = None
    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
        reason = " ".join(args[1:]) if len(args) > 1 else "Без причины"
        forever = True
    else:
        if len(args) < 3: await message.answer("Использование: /ban <id> <never/дата время> [причина]"); return
        try: target_id = int(args[1])
        except: return
        if args[2].lower() == "never": forever = True
        else:
            try:
                until = datetime.strptime(f"{args[2]} {args[3]}", "%d.%m.%Y %H:%M:%S")
                forever = False
            except: await message.answer("Неверный формат даты"); return
        reason = " ".join(args[4:]) if len(args) > 4 else "Без причины"
    
    if target_id in ADMIN_IDS: await message.answer("Нельзя банить админа"); return
    BANNED[str(target_id)] = {"reason": reason, "until": "never" if forever else until.strftime("%Y-%m-%d %H:%M:%S")}
    save_banned()
    if str(target_id) not in USERS: USERS[str(target_id)] = default_user_data()
    USERS[str(target_id)]["bans"] += 1
    save_users()
    if TARGET_CHAT_IDS:
        try: await bot.ban_chat_member(TARGET_CHAT_IDS[0], target_id)
        except: pass
    await message.answer(f"Пользователь {target_id} забанен.")

@dp.message(Command("unban"))
async def cmd_unban(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    args = message.text.split()
    if len(args) < 2 and not message.reply_to_message: return
    target_id = message.reply_to_message.from_user.id if message.reply_to_message else int(args[1])
    if str(target_id) in BANNED:
        del BANNED[str(target_id)]
        save_banned()
        if TARGET_CHAT_IDS:
            try: await bot.unban_chat_member(TARGET_CHAT_IDS[0], target_id)
            except: pass
        await message.answer("Разбанен.")

@dp.message(Command("setrank"))
async def cmd_setrank(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    args = message.text.split()
    if len(args) < 3: return
    try: target_id = str(args[1]); rank_id = int(args[2])
    except: return
    if target_id not in USERS: USERS[target_id] = default_user_data()
    USERS[target_id]["rank_id"] = rank_id
    save_users()
    await message.answer(f"Выдано звание {RANKS[rank_id][0]} пользователю {target_id}")

@dp.message(Command("reply"))
async def cmd_reply(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    args = message.text.split(maxsplit=2)
    if message.reply_to_message and len(args) >= 2:
        match = re.search(r"🆔 <code>(\d+)</code>", message.reply_to_message.text or "")
        if match:
            target_id = int(match.group(1))
            reply_text = args[1]
            try:
                await bot.send_message(target_id, f"<b>✉️ Ответ поддержки:</b>\n\n{reply_text}", parse_mode="HTML")
                await message.answer("Отправлено!")
            except Exception as e: await message.answer(f"Ошибка: {e}")

# --- РАЗНОЕ ---
@dp.message(F.text.in_([LOCALES["ru"]["btn_misc"]]))
async def btn_misc(message: Message, state: FSMContext):
    if await check_ban_and_block(message): return
    uid = str(message.from_user.id)
    await message.answer("<b>Разное</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="В разработке", callback_data="misc_dev")],
        [InlineKeyboardButton(text="Поддержать", callback_data="misc_donate")],
        [InlineKeyboardButton(text="Язык", callback_data="misc_lang")],
        [InlineKeyboardButton(text="Присоединиться", callback_data="misc_join")],
    ]))

@dp.callback_query(F.data.startswith("misc_"))
async def cb_misc(callback: CallbackQuery, state: FSMContext):
    uid = str(callback.from_user.id)
    await callback.answer()
    if callback.data == "misc_dev": await callback.message.answer("Сейчас в разработке: ...")
    elif callback.data == "misc_donate": await callback.message.answer("Поддержать: ...")
    elif callback.data == "misc_lang": await callback.message.answer("Выбери язык:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Русский", callback_data="set_lang_ru")]]))
    elif callback.data == "misc_join": await callback.message.answer("Набор закрыт.")

@dp.callback_query(F.data.startswith("set_lang_"))
async def cb_set_lang(callback: CallbackQuery):
    uid = str(callback.from_user.id)
    USERS[uid]["lang"] = "ru"
    save_users()
    await callback.message.answer("Язык изменен на Русский", reply_markup=get_main_keyboard(uid))
    await callback.answer()

# --- ЗАГЛУШКИ ---
@dp.message(F.text)
async def fallback_handler(message: Message, state: FSMContext):
    if await state.get_state() is not None: return
    uid = str(message.from_user.id)
    if await check_ban_and_block(message): return
    if uid not in USERS or not USERS[uid].get("nickname"):
        await cmd_start(message, state); return
    await message.answer("Я тебя не понял. Выбери раздел на клавиатуре.", reply_markup=get_main_keyboard(uid))

@dp.message()
async def unknown_media(message: Message, state: FSMContext):
    if await state.get_state() is not None: return
    if GROUP_ID_VALUE and str(message.chat.id) == str(GROUP_ID_VALUE): return
    uid = str(message.from_user.id)
    if is_banned(uid)[0]: return
    await message.answer("Я понимаю только текст и кнопки.", reply_markup=get_main_keyboard(uid))

async def main():
    logger.info("Bot started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
