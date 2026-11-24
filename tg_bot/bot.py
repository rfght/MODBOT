import asyncio
import html
import json
import logging
import os
import random
import time
from typing import Dict, Any

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from events import (
    ensure_event_state,
    get_active_event,
    register_event_handlers,
    reward_event_currency_after_battle,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN") or ""
if not BOT_TOKEN:
    logger.warning("BOT_TOKEN / TELEGRAM_BOT_TOKEN is not set in environment variables!")

USERS_FILE = "users.json"
TANKS_FILE = "tanks.json"
FALLBACKS_FILE = "fallbacks.json"
BANNED_FILE = "banned.json"

DEFAULT_TANKS_DB: Dict[str, Dict[str, Any]] = {
    "MS-1": {"tier": 1, "hp": 250, "damage": 40, "pen": 34, "armor": 18, "reload": 3.5, "price": 100},
    "Pz. II": {"tier": 1, "hp": 260, "damage": 35, "pen": 32, "armor": 30, "reload": 3.8, "price": 100},
    "M2 Light": {"tier": 1, "hp": 250, "damage": 40, "pen": 36, "armor": 25, "reload": 3.2, "price": 100},
    "Cruiser II": {"tier": 1, "hp": 270, "damage": 45, "pen": 40, "armor": 22, "reload": 4.0, "price": 100},
    "BT-2": {"tier": 2, "hp": 320, "damage": 45, "pen": 46, "armor": 20, "reload": 3.4, "price": 250},
    "Pz. III A": {"tier": 2, "hp": 340, "damage": 45, "pen": 46, "armor": 30, "reload": 3.6, "price": 250},
    "M3 Stuart": {"tier": 2, "hp": 330, "damage": 45, "pen": 51, "armor": 38, "reload": 3.3, "price": 250},
    "T-26": {"tier": 2, "hp": 310, "damage": 45, "pen": 51, "armor": 15, "reload": 3.5, "price": 250},
    "BT-7": {"tier": 3, "hp": 410, "damage": 55, "pen": 66, "armor": 20, "reload": 3.6, "price": 450},
    "Pz. III": {"tier": 3, "hp": 450, "damage": 60, "pen": 67, "armor": 50, "reload": 4.0, "price": 450},
    "M5 Stuart": {"tier": 3, "hp": 420, "damage": 50, "pen": 62, "armor": 44, "reload": 3.5, "price": 450},
    "SU-76I": {"tier": 3, "hp": 380, "damage": 90, "pen": 86, "armor": 35, "reload": 4.8, "price": 500},
    "FV215B 183": {"tier": 10, "hp": 1850, "damage": 930, "pen": 300, "armor": 152, "reload": 18.5, "price": 0},
    "Pz.Kpfw. VII": {"tier": 10, "hp": 2450, "damage": 560, "pen": 258, "armor": 240, "reload": 14.2, "price": 8500, "exclusive": True},
}

def load_json(path: str, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error("Failed to load %s: %s", path, e)
    return default

def save_json(path: str, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("Failed to save %s: %s", path, e)

TANKS_DB: Dict[str, Dict[str, Any]] = load_json(TANKS_FILE, DEFAULT_TANKS_DB)
if not TANKS_DB:
    TANKS_DB = DEFAULT_TANKS_DB.copy()

USERS: Dict[str, Dict[str, Any]] = load_json(USERS_FILE, {})
FALLBACKS: list = load_json(FALLBACKS_FILE, [])
BANNED: list = load_json(BANNED_FILE, [])

def save_users():
    save_json(USERS_FILE, USERS)

CONTAINERS_DB: Dict[str, Dict[str, Any]] = {
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

RANKS = {
    1: ("Новобранец", 0, 0, "user"),
    2: ("Рядовой", 500, 1, "user"),
    3: ("Ефрейтор", 1500, 2, "user"),
    4: ("Сержант", 3500, 4, "user"),
    5: ("Лейтенант", 7000, 7, "user"),
    6: ("Капитан", 15000, 12, "manual"),
}

ACHIEVEMENTS = {
    "first_win": "Первая победа",
    "collector_10": "Коллекционер (10 танков)",
}

TIER_ROMAN = {
    1: "I", 2: "II", 3: "III", 4: "IV", 5: "V",
    6: "VI", 7: "VII", 8: "VIII", 9: "IX", 10: "X",
}

class UserState(StatesGroup):
    in_battle = State()

def get_tank_tier(tank_name: str) -> int:
    return int(TANKS_DB.get(tank_name, {}).get("tier", 10))

def tier_label(tier: int) -> str:
    return f"{TIER_ROMAN.get(tier, tier)} ур."

async def safe_edit_or_send(message: Message, text: str, reply_markup=None, parse_mode: str | None = "HTML"):
    try:
        await message.edit_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
    except Exception:
        try:
            await message.delete()
        except Exception:
            pass
        await message.answer(text, parse_mode=parse_mode, reply_markup=reply_markup)

def ensure_user(uid: str) -> Dict[str, Any]:
    uid = str(uid)
    if uid not in USERS:
        USERS[uid] = {
            "nickname": "",
            "rank_id": 1,
            "xp": 1000,
            "battles": 0,
            "wins": 0,
            "losses": 0,
            "downloads": 0,
            "ideas": 0,
            "questions": 0,
            "bans": 0,
            "tanks": ["FV215B 183"],
            "selected_tank": "FV215B 183",
            "achievements": [],
        }
        save_users()
    u = USERS[uid]
    u.setdefault("xp", 0)
    u.setdefault("rank_id", 1)
    u.setdefault("battles", 0)
    u.setdefault("wins", 0)
    u.setdefault("losses", 0)
    u.setdefault("downloads", 0)
    u.setdefault("ideas", 0)
    u.setdefault("questions", 0)
    u.setdefault("bans", 0)
    u.setdefault("tanks", ["FV215B 183"])
    u.setdefault("selected_tank", u["tanks"][0] if u["tanks"] else "FV215B 183")
    u.setdefault("achievements", [])
    return u

def get_rank_info(rank_id: int):
    return RANKS.get(rank_id, RANKS[1])

def add_xp(uid: str, amount: int):
    u = ensure_user(uid)
    u["xp"] = max(0, u.get("xp", 0) + int(amount))

def unlock_achievement(uid: str, ach_key: str):
    u = ensure_user(uid)
    if ach_key not in u["achievements"]:
        u["achievements"].append(ach_key)

def tr(_uid: str, key: str, **kwargs) -> str:
    templates = {
        "profile_title": "🎖 <b>Профиль танкиста</b>",
        "profile_nick": "Позывной: <b>{nick}</b>",
        "profile_id": "ID: <code>{uid}</code>",
        "profile_rank": "Звание: <b>{rank}</b>",
        "profile_xp": "Опыт: <b>{xp} XP</b>",
        "profile_stats": "Боёв: <b>{battles}</b> | Побед: <b>{wins}</b> | Поражений: <b>{losses}</b>",
        "profile_tank": "Танк в ангаре: <b>{tank}</b>",
        "profile_next": "До след. звания: <b>{xp_left} XP</b> и <b>{ideas_left} идей</b>",
        "profile_next_manual": "Следующее звание выдаётся вручную",
        "profile_achievements": "🏅 Достижения:\n{list}",
        "profile_no_achievements": "🏅 Достижений пока нет",
        "shop_btn": "🛒 Магазин",
        "shop_title": "🛒 <b>Магазин</b> | Баланс: <b>{xp} XP</b>",
        "btn_friends": "👥 Друзья",
        "btn_invite": "📩 Пригласить",
    }
    tpl = templates.get(key, key)
    return tpl.format(**kwargs) if kwargs else tpl

def build_profile_message(uid: str) -> tuple[str, InlineKeyboardMarkup]:
    data = ensure_user(uid)
    rank_name, _, _, _ = get_rank_info(data["rank_id"])
    next_id = data["rank_id"] + 1
    if next_id in RANKS:
        _, next_xp, next_ideas, next_type = RANKS[next_id]
        if next_type == "user":
            progress_text = tr(
                uid,
                "profile_next",
                xp_left=max(0, next_xp - data["xp"]),
                ideas_left=max(0, next_ideas - data["ideas"]),
            )
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
    ev_state = ensure_event_state(data, ev["id"])
    event_line = f"\n🎪 {html.escape(ev['title'])}: <b>{ev_state['currency']}/{ev['goal']}</b> {ev['currency_emoji']}"
    text = (
        f"{tr(uid, 'profile_title')}\n{tr(uid, 'profile_nick', nick=safe_nick)}\n{tr(uid, 'profile_id', uid=uid)}\n\n"
        f"{tr(uid, 'profile_rank', rank=rank_name)}\n{tr(uid, 'profile_xp', xp=data['xp'])}{event_line}\n"
        f"{tr(uid, 'profile_stats', battles=data.get('battles', 0), wins=data.get('wins', 0), losses=data.get('losses', 0))}\n"
        f"{tr(uid, 'profile_tank', tank=tank_display)}\n{progress_text}\n\n{ach_text}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚔️ Бои", callback_data="battle_menu"), InlineKeyboardButton(text="🚜 Ангар", callback_data="hangar_menu")],
        [InlineKeyboardButton(text=tr(uid, "shop_btn"), callback_data="shop_menu"), InlineKeyboardButton(text=f"🎪 Ивент ({ev['currency_emoji']})", callback_data=f"ev_open_{ev['id']}")],
        [InlineKeyboardButton(text=tr(uid, "btn_friends"), callback_data="friends_menu"), InlineKeyboardButton(text=tr(uid, "btn_invite"), callback_data="invite_friend")],
    ])
    return text, kb

def calculate_shot(attacker: dict, defender: dict, ammo: str) -> tuple[int, str]:
    base_dmg = int(attacker.get("damage", 300))
    pen = int(attacker.get("pen", 200))
    armor = int(defender.get("armor", 100))
    if ammo == "he":
        dmg = int(base_dmg * random.uniform(0.75, 1.15))
        return max(25, dmg), f"фугас нанёс <b>{max(25, dmg)}</b> урона"
    if pen >= armor * 0.9:
        dmg = int(base_dmg * random.uniform(0.85, 1.15))
        return max(20, dmg), f"пробитие! Нанесено <b>{max(20, dmg)}</b> урона"
    if random.random() < 0.35:
        dmg = int(base_dmg * random.uniform(0.65, 0.95))
        return max(15, dmg), f"пробитие слабой зоны! <b>{max(15, dmg)}</b> урона"
    return 0, "рикошет / непробитие (<b>0</b> урона)"

def _run_bot_turn_if_ready(data: dict) -> tuple[dict, int, str]:
    now = time.time()
    e_hp = int(data["e_hp"])
    p_hp = int(data["p_hp"])
    e_reload_ready = float(data.get("e_reload_ready", 0.0))
    e_stats = data["e_stats"]
    p_stats = data["p_stats"]
    if e_hp <= 0 or p_hp <= 0:
        return data, p_hp, ""
    if now < e_reload_ready:
        rem = round(max(0.1, e_reload_ready - now), 1)
        return data, p_hp, f"⏳ Враг на перезарядке ({rem}с).\n"
    bot_ammo = random.choices(["ap", "he"], weights=[0.8, 0.2])[0]
    b_damage, b_msg = calculate_shot(e_stats, p_stats, bot_ammo)
    new_p_hp = max(0, p_hp - b_damage)
    new_e_reload_ready = now + float(e_stats.get("reload", 10.0))
    data["e_reload_ready"] = new_e_reload_ready
    data["p_hp"] = new_p_hp
    line = f"🔫 Враг выстрелил ({'ББ' if bot_ammo == 'ap' else 'ОФ'}): {b_msg}\n"
    return data, new_p_hp, line

storage = MemoryStorage()
dp = Dispatcher(storage=storage)
bot = Bot(token=BOT_TOKEN) if BOT_TOKEN else None

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    uid = str(message.from_user.id)
    ensure_user(uid)
    text, kb = build_profile_message(uid)
    await message.answer(text, parse_mode="HTML", reply_markup=kb)

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
    owned = sorted(data.get("tanks", ["FV215B 183"]), key=lambda t: (get_tank_tier(t), t))
    sel = data.get("selected_tank", owned[0] if owned else "FV215B 183")
    rows = []
    for tank in owned[:20]:
        mark = "✅ " if tank == sel else ""
        t_tier = get_tank_tier(tank)
        rows.append([
            InlineKeyboardButton(
                text=f"{mark}[{TIER_ROMAN.get(t_tier, t_tier)}] {tank}",
                callback_data=f"select_tank_{tank}",
            )
        ])
    rows.append([InlineKeyboardButton(text="🔙 В профиль", callback_data="back_to_profile")])
    text = (
        f"🚜 <b>Твой ангар ({len(owned)} шт.)</b>\n"
        f"Выбранный танк: <b>{html.escape(sel)}</b>\n\n"
        f"Нажми на танк, чтобы выбрать его для боёв:"
    )
    await safe_edit_or_send(callback.message, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("select_tank_"))
async def cb_select_tank(callback: CallbackQuery):
    uid = str(callback.from_user.id)
    data = ensure_user(uid)
    tank_name = callback.data.replace("select_tank_", "", 1)
    if tank_name in data.get("tanks", []):
        data["selected_tank"] = tank_name
        save_users()
        await callback.answer(f"Выбран танк: {tank_name}")
    else:
        await callback.answer("Танка нет в ангаре", show_alert=True)
        return
    owned = sorted(data.get("tanks", [tank_name]), key=lambda t: (get_tank_tier(t), t))
    rows = []
    for tank in owned[:20]:
        mark = "✅ " if tank == tank_name else ""
        t_tier = get_tank_tier(tank)
        rows.append([
            InlineKeyboardButton(
                text=f"{mark}[{TIER_ROMAN.get(t_tier, t_tier)}] {tank}",
                callback_data=f"select_tank_{tank}",
            )
        ])
    rows.append([InlineKeyboardButton(text="🔙 В профиль", callback_data="back_to_profile")])
    text = (
        f"🚜 <b>Твой ангар ({len(owned)} шт.)</b>\n"
        f"Выбранный танк: <b>{html.escape(tank_name)}</b>\n\n"
        f"Нажми на танк, чтобы выбрать его для боёв:"
    )
    await safe_edit_or_send(callback.message, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")

@dp.callback_query(F.data == "shop_menu")
async def cb_shop_menu(callback: CallbackQuery):
    uid = str(callback.from_user.id)
    data = ensure_user(uid)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛡 Танки", callback_data="shop_tanks_menu"), InlineKeyboardButton(text="📦 Контейнеры", callback_data="shop_containers_menu")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_profile")],
    ])
    await safe_edit_or_send(callback.message, tr(uid, "shop_title", xp=data["xp"]) + "\n\nВыбери раздел:", reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "shop_tanks_menu")
async def cb_shop_tanks_menu(callback: CallbackQuery):
    uid = str(callback.from_user.id)
    data = ensure_user(uid)
    rows = []
    for t in range(1, 11, 2):
        rows.append([
            InlineKeyboardButton(text=tier_label(t), callback_data=f"shop_tier_{t}"),
            InlineKeyboardButton(text=tier_label(t + 1), callback_data=f"shop_tier_{t + 1}"),
        ])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="shop_menu")])
    await safe_edit_or_send(
        callback.message,
        f"🛒 <b>Магазин танков</b>\n\nТвой баланс: <b>{data['xp']} XP</b>\nВыбери уровень техники (I–X):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="HTML",
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("shop_tier_"))
async def cb_shop_tier(callback: CallbackQuery):
    uid = str(callback.from_user.id)
    data = ensure_user(uid)
    tier = int(callback.data.replace("shop_tier_", "", 1))
    tier_tanks = [
        (n, st) for n, st in TANKS_DB.items()
        if int(st.get("tier", 10)) == tier and not st.get("exclusive", False)
    ]
    tier_tanks.sort(key=lambda x: x[1].get("price", 0))
    rows = []
    for name, st in tier_tanks[:12]:
        price = int(st.get("price", 1000))
        owned = name in data.get("tanks", [])
        tag = " (в ангаре)" if owned else f" — {price} XP"
        rows.append([InlineKeyboardButton(text=f"{name}{tag}", callback_data=f"buy_tank_{name}")])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="shop_tanks_menu")])
    await safe_edit_or_send(
        callback.message,
        f"🛒 <b>Танки {tier_label(tier)}</b>\n\nТвой баланс: <b>{data['xp']} XP</b>\nВыбери танк:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="HTML",
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("buy_tank_"))
async def cb_buy_tank(callback: CallbackQuery):
    uid = str(callback.from_user.id)
    data = ensure_user(uid)
    tank_name = callback.data.replace("buy_tank_", "", 1)
    st = TANKS_DB.get(tank_name)
    if not st or st.get("exclusive", False):
        await callback.answer("Этот танк нельзя купить напрямую.", show_alert=True)
        return
    if tank_name in data.get("tanks", []):
        await callback.answer("Этот танк уже есть в ангаре!", show_alert=True)
        return
    price = int(st.get("price", 1000))
    if data["xp"] < price:
        await callback.answer(f"Не хватает XP ({data['xp']}/{price}).", show_alert=True)
        return
    data["xp"] -= price
    data.setdefault("tanks", []).append(tank_name)
    if len(data["tanks"]) >= 10:
        unlock_achievement(uid, "collector_10")
    save_users()
    await callback.answer(f"Куплен танк {tank_name}!", show_alert=True)

@dp.callback_query(F.data == "shop_containers_menu")
async def cb_shop_containers_menu(callback: CallbackQuery):
    uid = str(callback.from_user.id)
    data = ensure_user(uid)
    rows = []
    for cid, cdata in CONTAINERS_DB.items():
        rows.append([
            InlineKeyboardButton(text=f"{cdata['name']} ({cdata['price']} XP)", callback_data=f"view_container_{cid}")
        ])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="shop_menu")])
    await safe_edit_or_send(
        callback.message,
        f"📦 <b>Контейнеры</b>\n\nТвой баланс: <b>{data['xp']} XP</b>\nВыбери контейнер:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="HTML",
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("view_container_"))
async def cb_view_container(callback: CallbackQuery):
    cid = callback.data.replace("view_container_", "", 1)
    cdata = CONTAINERS_DB.get(cid)
    if not cdata:
        await callback.answer("Контейнер не найден", show_alert=True)
        return
    tanks_list = "\n".join(f"• {html.escape(t)}" for t in cdata["tanks"])
    text = (
        f"{html.escape(cdata['name'])}\n"
        f"Цена: <b>{cdata['price']} XP</b>\n\n"
        f"<b>Возможный дроп:</b>\n{tanks_list}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔓 Открыть ({cdata['price']} XP)", callback_data=f"buy_container_{cid}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="shop_containers_menu")],
    ])
    await safe_edit_or_send(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("buy_container_"))
async def cb_buy_container(callback: CallbackQuery):
    uid = str(callback.from_user.id)
    data = ensure_user(uid)
    cid = callback.data.replace("buy_container_", "", 1)
    cdata = CONTAINERS_DB.get(cid)
    if not cdata:
        await callback.answer("Контейнер не найден", show_alert=True)
        return
    price = int(cdata["price"])
    if data["xp"] < price:
        await callback.answer(f"Не хватает XP ({data['xp']}/{price}).", show_alert=True)
        return
    data["xp"] -= price
    won_tank = random.choice(cdata["tanks"])
    owned = data.setdefault("tanks", [])
    if won_tank not in owned:
        owned.append(won_tank)
        drop_msg = f"🎉 Выпал новый танк: <b>{html.escape(won_tank)}</b>!"
    else:
        comp = 500
        data["xp"] += comp
        drop_msg = f"♻️ Танк <b>{html.escape(won_tank)}</b> уже есть в ангаре. Компенсация: <b>+{comp} XP</b>."
    if len(owned) >= 10:
        unlock_achievement(uid, "collector_10")
    save_users()
    text = f"{html.escape(cdata['name'])} открыт!\n\n{drop_msg}\nТекущий баланс: <b>{data['xp']} XP</b>"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔓 Открыть ещё", callback_data=f"buy_container_{cid}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="shop_containers_menu")],
    ])
    await safe_edit_or_send(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "battle_menu")
async def cb_battle_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    uid = str(callback.from_user.id)
    data = ensure_user(uid)
    sel_tank = data.get("selected_tank", "FV215B 183")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤖 Бой с ботом", callback_data="battle_vs_bot")],
        [InlineKeyboardButton(text="🚜 Сменить танк в ангаре", callback_data="hangar_menu")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_profile")],
    ])
    await safe_edit_or_send(
        callback.message,
        f"⚔️ <b>Меню боёв</b>\n\nТвой танк: <b>{html.escape(sel_tank)}</b> ({tier_label(get_tank_tier(sel_tank))})",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()

async def _launch_bot_fight(callback: CallbackQuery, state: FSMContext, uid: str, tank_name: str):
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
    now = time.time()
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
        p_reload_ready=0.0,
        e_reload_ready=now + float(bot_stats.get("reload", 10.0)),
        p_stats=tank_stats,
        e_stats=bot_stats,
        p_damage_dealt=0,
        p_shots_hit=0,
    )
    text = (
        f"🤖 <b>Бой против бота ({tier_label(player_tier)})</b>\n\n"
        f"Твой танк: <b>{html.escape(tank_name)}</b> (HP: {tank_stats['hp']})\n"
        f"Танк врага: <b>Неизвестно ({tier_label(player_tier)})</b>\n\nОрудие заряжено — можно стрелять!"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💥 Выстрел (ББ)", callback_data="pve_shoot_ap")],
        [InlineKeyboardButton(text="💥 Выстрел (ОФ)", callback_data="pve_shoot_he")],
        [InlineKeyboardButton(text="🔄 Обновить статус", callback_data="pve_refresh")],
        [InlineKeyboardButton(text="🏳️ Сдаться", callback_data="pve_surrender")],
    ])
    await safe_edit_or_send(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "battle_vs_bot")
async def cb_battle_vs_bot(callback: CallbackQuery, state: FSMContext):
    uid = str(callback.from_user.id)
    data = ensure_user(uid)
    tank_name = data.get("selected_tank", "FV215B 183")
    await _launch_bot_fight(callback, state, uid, tank_name)

@dp.callback_query(UserState.in_battle, F.data == "pve_refresh")
async def cb_pve_refresh(callback: CallbackQuery, state: FSMContext):
    uid = str(callback.from_user.id)
    user_data = ensure_user(uid)
    data = await state.get_data()
    if not data:
        await state.clear()
        await callback.answer("Бой завершён")
        return
    data, p_hp, bot_line = _run_bot_turn_if_ready(data)
    battle_tier = int(data.get("tier", 10))
    e_hp = int(data["e_hp"])
    p_stats = data["p_stats"]
    total_dmg = int(data.get("p_damage_dealt", 0))
    shots_hit = int(data.get("p_shots_hit", 0))
    if p_hp <= 0:
        user_data["losses"] += 1
        user_data["battles"] += 1
        save_users()
        ev_earned, ev_emoji, _ = reward_event_currency_after_battle(
            USERS,
            uid,
            won=False,
            damage_dealt=total_dmg,
            enemy_max_hp=data.get("e_max_hp", 1),
            player_max_hp=data.get("p_max_hp", 1),
            player_hp_left=0,
            shots_hit=shots_hit,
            save_users_fn=save_users,
        )
        ev_line = f"\n🎪 +{ev_earned} {ev_emoji}" if ev_earned > 0 else ""
        text = (
            f"{bot_line}💀 <b>Ты уничтожен!</b>{ev_line}\n"
            f"Танк врага: <b>{html.escape(data['e_tank'])}</b> ({tier_label(battle_tier)})"
        )
        await safe_edit_or_send(
            callback.message,
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="В меню", callback_data="battle_menu")]]),
            parse_mode="HTML",
        )
        await state.clear()
        await callback.answer()
        return
    now = time.time()
    p_rem = max(0.0, float(data.get("p_reload_ready", 0.0)) - now)
    p_status = "ГОТОВО" if p_rem <= 0 else f"{round(p_rem, 1)}с"
    text = (
        f"{bot_line}\n"
        f"❤️ HP: {p_hp} | 💀 HP врага: {e_hp}\n"
        f"🔫 Твоё орудие: <b>{p_status}</b> (КД {p_stats['reload']}с)"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💥 Выстрел (ББ)", callback_data="pve_shoot_ap")],
        [InlineKeyboardButton(text="💥 Выстрел (ОФ)", callback_data="pve_shoot_he")],
        [InlineKeyboardButton(text="🔄 Обновить статус", callback_data="pve_refresh")],
        [InlineKeyboardButton(text="🏳️ Сдаться", callback_data="pve_surrender")],
    ])
    await state.update_data(**data)
    await safe_edit_or_send(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(UserState.in_battle, F.data.startswith("pve_shoot_"))
async def cb_pve_shoot(callback: CallbackQuery, state: FSMContext):
    uid = str(callback.from_user.id)
    user_data = ensure_user(uid)
    data = await state.get_data()
    if not data:
        await state.clear()
        await callback.answer("Бой не активен", show_alert=True)
        return
    now = time.time()
    p_reload_ready = float(data.get("p_reload_ready", 0.0))
    if now < p_reload_ready:
        rem = round(max(0.1, p_reload_ready - now), 1)
        await callback.answer(f"⏳ Перезарядка: ещё {rem}с", show_alert=True)
        return
    ammo = "ap" if callback.data.endswith("ap") else "he"
    p_stats = data["p_stats"]
    e_stats = data["e_stats"]
    p_hp = int(data["p_hp"])
    e_hp = int(data["e_hp"])
    battle_tier = int(data.get("tier", 10))
    damage, msg = calculate_shot(p_stats, e_stats, ammo)
    e_hp = max(0, e_hp - damage)
    total_dmg = int(data.get("p_damage_dealt", 0)) + damage
    shots_hit = int(data.get("p_shots_hit", 0)) + (1 if damage > 0 else 0)
    data["e_hp"] = e_hp
    data["p_damage_dealt"] = total_dmg
    data["p_shots_hit"] = shots_hit
    data["p_reload_ready"] = now + float(p_stats.get("reload", 10.0))
    text = f"Ты выстрелил ({'ББ' if ammo == 'ap' else 'ОФ'}): {msg}\n"
    if e_hp <= 0:
        xp_reward = random.randint(50, 100)
        add_xp(uid, xp_reward)
        user_data["wins"] += 1
        user_data["battles"] += 1
        save_users()
        unlock_achievement(uid, "first_win")
        ev_earned, ev_emoji, _ = reward_event_currency_after_battle(
            USERS,
            uid,
            won=True,
            damage_dealt=total_dmg,
            enemy_max_hp=data.get("e_max_hp", e_stats["hp"]),
            player_max_hp=data.get("p_max_hp", p_stats["hp"]),
            player_hp_left=p_hp,
            shots_hit=shots_hit,
            save_users_fn=save_users,
        )
        ev_line = f"\n🎪 +{ev_earned} {ev_emoji}" if ev_earned > 0 else ""
        text += (
            f"\n💀 <b>Враг уничтожен!</b>\n🏆 Победа! +{xp_reward} XP.{ev_line}\n\n"
            f"👀 Танк врага: <b>{html.escape(data['e_tank'])}</b> ({tier_label(battle_tier)})"
        )
        await safe_edit_or_send(
            callback.message,
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="В меню", callback_data="battle_menu")]]),
            parse_mode="HTML",
        )
        await state.clear()
        await callback.answer()
        return
    data, p_hp, bot_line = _run_bot_turn_if_ready(data)
    text += bot_line
    if p_hp <= 0:
        user_data["losses"] += 1
        user_data["battles"] += 1
        save_users()
        ev_earned, ev_emoji, _ = reward_event_currency_after_battle(
            USERS,
            uid,
            won=False,
            damage_dealt=total_dmg,
            enemy_max_hp=data.get("e_max_hp", e_stats["hp"]),
            player_max_hp=data.get("p_max_hp", p_stats["hp"]),
            player_hp_left=0,
            shots_hit=shots_hit,
            save_users_fn=save_users,
        )
        ev_line = f"\n🎪 +{ev_earned} {ev_emoji}" if ev_earned > 0 else ""
        text += f"\n💀 <b>Ты уничтожен!</b>{ev_line}\nТанк врага: <b>{html.escape(data['e_tank'])}</b> ({tier_label(battle_tier)})"
        await safe_edit_or_send(
            callback.message,
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="В меню", callback_data="battle_menu")]]),
            parse_mode="HTML",
        )
        await state.clear()
        await callback.answer()
        return
    text += (
        f"\n❤️ HP: {p_hp}\n💀 HP врага: {e_hp}\n"
        f"⏱ Твоя перезарядка: {p_stats['reload']}с\n\nСтреляй сразу, как зарядишься!"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💥 Выстрел (ББ)", callback_data="pve_shoot_ap")],
        [InlineKeyboardButton(text="💥 Выстрел (ОФ)", callback_data="pve_shoot_he")],
        [InlineKeyboardButton(text="🔄 Обновить статус", callback_data="pve_refresh")],
        [InlineKeyboardButton(text="🏳️ Сдаться", callback_data="pve_surrender")],
    ])
    await state.update_data(**data)
    await safe_edit_or_send(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(UserState.in_battle, F.data == "pve_surrender")
async def cb_pve_surrender(callback: CallbackQuery, state: FSMContext):
    uid = str(callback.from_user.id)
    user_data = ensure_user(uid)
    data = await state.get_data()
    total_dmg = int(data.get("p_damage_dealt", 0))
    shots_hit = int(data.get("p_shots_hit", 0))
    p_stats = data.get("p_stats", {"hp": 1850})
    e_stats = data.get("e_stats", {"hp": 1850})
    user_data["losses"] += 1
    user_data["battles"] += 1
    save_users()
    ev_earned, ev_emoji, _ = reward_event_currency_after_battle(
        USERS,
        uid,
        won=False,
        damage_dealt=total_dmg,
        enemy_max_hp=data.get("e_max_hp", e_stats["hp"]),
        player_max_hp=data.get("p_max_hp", p_stats["hp"]),
        player_hp_left=int(data.get("p_hp", 0)),
        shots_hit=shots_hit,
        save_users_fn=save_users,
    )
    ev_line = f"\n🎪 +{ev_earned} {ev_emoji}" if ev_earned > 0 else ""
    await state.clear()
    await safe_edit_or_send(
        callback.message,
        f"🏳️ Ты сдался.{ev_line}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="В меню", callback_data="battle_menu")]]),
        parse_mode="HTML",
    )
    await callback.answer()

@dp.callback_query(F.data == "friends_menu")
async def cb_friends_menu(callback: CallbackQuery):
    await safe_edit_or_send(
        callback.message,
        "👥 <b>Друзья</b>\n\nСписок друзей пока пуст.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 В профиль", callback_data="back_to_profile")]]),
        parse_mode="HTML",
    )
    await callback.answer()

@dp.callback_query(F.data == "invite_friend")
async def cb_invite_friend(callback: CallbackQuery):
    uid = str(callback.from_user.id)
    await safe_edit_or_send(
        callback.message,
        f"📩 <b>Приглашение друга</b>\n\nТвой ID для приглашения: <code>{uid}</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 В профиль", callback_data="back_to_profile")]]),
        parse_mode="HTML",
    )
    await callback.answer()

@dp.message(Command("id"))
async def cmd_id(message: Message):
    await message.answer(f"Твой ID: <code>{message.from_user.id}</code>", parse_mode="HTML")

async def main():
    if not BOT_TOKEN:
        raise RuntimeError("Missing required environment variable: BOT_TOKEN / TELEGRAM_BOT_TOKEN")
    register_event_handlers(dp, USERS, TANKS_DB, save_users)
    logger.info("Bot started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
