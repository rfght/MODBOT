import html
import random
import re
import time
from aiogram import F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

LOW_TIER_TANKS = [
    "MS-1", "Pz. II", "M2 Light", "Cruiser II",
    "BT-2", "Pz. III A", "M3 Stuart", "T-26",
    "BT-7", "Pz. III", "M5 Stuart", "SU-76I",
]

EVENT_DURATION_DAYS = 25
EVENT_DURATION_SECONDS = EVENT_DURATION_DAYS * 24 * 3600

IRON_COLOSSUS_EVENT = {
    "id": "iron_colossus",
    "title": "Ивент: «Железный колосс»",
    "currency_name": "Гайки колосса",
    "currency_emoji": "🔩",
    "goal": 255,
    "low_tier_chance": 0.18,
    "rewards": [
        {"cost": 15,  "label": "200 XP", "type": "xp", "amount": 200},
        {"cost": 35,  "label": "Ржавый ящик", "type": "scrappy_crate", "xp": 150},
        {"cost": 60,  "label": "350 XP", "type": "xp", "amount": 350},
        {"cost": 85,  "label": "Ржавый ящик", "type": "scrappy_crate", "xp": 200},
        {"cost": 115, "label": "500 XP", "type": "xp", "amount": 500},
        {"cost": 145, "label": "Ржавый ящик", "type": "scrappy_crate", "xp": 250},
        {"cost": 175, "label": "750 XP", "type": "xp", "amount": 750},
        {"cost": 205, "label": "Ржавый ящик", "type": "scrappy_crate", "xp": 350},
        {"cost": 230, "label": "1000 XP", "type": "xp", "amount": 1000},
        {"cost": 255, "label": "Pz.Kpfw. VII", "type": "tank", "tank_name": "Pz.Kpfw. VII"},
    ],
}

EVENTS_REGISTRY = {
    IRON_COLOSSUS_EVENT["id"]: IRON_COLOSSUS_EVENT,
}

ACTIVE_EVENT_ID = "iron_colossus"

def get_active_event() -> dict:
    return EVENTS_REGISTRY[ACTIVE_EVENT_ID]

def ensure_event_state(user_data: dict, event_id: str | None = None) -> dict:
    eid = event_id or ACTIVE_EVENT_ID
    events_store = user_data.setdefault("events", {})
    now = time.time()
    state = events_store.setdefault(
        eid,
        {
            "currency": 0,
            "claimed": [],
            "started_at": now,
            "expires_at": now + EVENT_DURATION_SECONDS,
        },
    )
    state.setdefault("currency", 0)
    state.setdefault("claimed", [])
    if "started_at" not in state:
        state["started_at"] = now
    if "expires_at" not in state:
        state["expires_at"] = float(state["started_at"]) + EVENT_DURATION_SECONDS
    return state

def get_remaining_seconds(state: dict) -> float:
    return max(0.0, float(state.get("expires_at", 0.0)) - time.time())

def is_event_expired(state: dict) -> bool:
    return get_remaining_seconds(state) <= 0.0

def format_remaining_time(seconds: float) -> str:
    total = max(0, int(seconds))
    days = total // 86400
    rem = total % 86400
    hours = rem // 3600
    minutes = (rem % 3600) // 60
    secs = rem % 60
    if days > 0:
        return f"{days}д {hours}ч {minutes}м"
    if hours > 0:
        return f"{hours}ч {minutes}м {secs}с"
    return f"{minutes}м {secs}с"

def calculate_event_currency(
    won: bool,
    damage_dealt: int,
    enemy_max_hp: int,
    player_max_hp: int,
    player_hp_left: int,
    shots_hit: int,
) -> int:
    dmg_ratio = damage_dealt / max(1, enemy_max_hp)
    hp_saved_ratio = max(0, player_hp_left) / max(1, player_max_hp)
    if won:
        points = 1
        if dmg_ratio >= 0.35 or shots_hit >= 2:
            points += 1
        if dmg_ratio >= 0.75 or (dmg_ratio >= 0.45 and hp_saved_ratio >= 0.5):
            points += 1
        return min(3, max(1, points))
    else:
        if dmg_ratio >= 0.25 or shots_hit >= 2:
            return 1
        return 0

def reward_event_currency_after_battle(
    users_db: dict,
    uid: str,
    won: bool,
    damage_dealt: int,
    enemy_max_hp: int,
    player_max_hp: int,
    player_hp_left: int,
    shots_hit: int,
    save_users_fn,
) -> tuple[int, str, bool]:
    ev = get_active_event()
    user_data = users_db.get(str(uid))
    if not user_data:
        return 0, ev["currency_emoji"], False
    st = ensure_event_state(user_data, ev["id"])
    if is_event_expired(st):
        return 0, ev["currency_emoji"], True
    earned = calculate_event_currency(
        won=won,
        damage_dealt=damage_dealt,
        enemy_max_hp=enemy_max_hp,
        player_max_hp=player_max_hp,
        player_hp_left=player_hp_left,
        shots_hit=shots_hit,
    )
    if earned > 0:
        st["currency"] += earned
        save_users_fn()
    return earned, ev["currency_emoji"], False

def _claim_single_reward(user_data: dict, reward: dict, tanks_db: dict, ev: dict) -> str:
    rtype = reward["type"]
    if rtype == "xp":
        amt = int(reward["amount"])
        user_data["xp"] = user_data.get("xp", 0) + amt
        return f"+{amt} XP"
    if rtype == "tank":
        tname = reward["tank_name"]
        owned = user_data.setdefault("tanks", [])
        if tname not in owned:
            owned.append(tname)
            return f"танк <b>{html.escape(tname)}</b>"
        user_data["xp"] = user_data.get("xp", 0) + 1000
        return f"компенсация 1000 XP (<b>{html.escape(tname)}</b> уже есть)"
    if rtype == "scrappy_crate":
        base_xp = int(reward.get("xp", 200))
        user_data["xp"] = user_data.get("xp", 0) + base_xp
        if random.random() < ev.get("low_tier_chance", 0.18):
            candidates = [t for t in LOW_TIER_TANKS if t in tanks_db] or LOW_TIER_TANKS
            tank = random.choice(candidates)
            owned = user_data.setdefault("tanks", [])
            if tank not in owned:
                owned.append(tank)
                return f"Ржавый ящик: +{base_xp} XP и танк <b>{html.escape(tank)}</b>"
            user_data["xp"] += 250
            return f"Ржавый ящик: +{base_xp + 250} XP (повторка {html.escape(tank)})"
        return f"Ржавый ящик: +{base_xp} XP"
    return reward["label"]

def get_claimable_indices(user_data: dict, ev: dict | None = None) -> list[int]:
    event = ev or get_active_event()
    st = ensure_event_state(user_data, event["id"])
    if is_event_expired(st):
        return []
    cur = st["currency"]
    claimed = set(st["claimed"])
    indices = []
    for idx, r in enumerate(event["rewards"], start=1):
        if idx not in claimed and cur >= r["cost"]:
            indices.append(idx)
    return indices

def build_event_view(user_data: dict, event_id: str | None = None) -> tuple[str, InlineKeyboardMarkup]:
    ev = EVENTS_REGISTRY.get(event_id or ACTIVE_EVENT_ID, get_active_event())
    st = ensure_event_state(user_data, ev["id"])
    cur = st["currency"]
    claimed = set(st["claimed"])
    emoji = ev["currency_emoji"]
    rem_sec = get_remaining_seconds(st)
    expired = rem_sec <= 0.0
    if expired:
        text = (
            f"🎪 <b>{html.escape(ev['title'])}</b>\n\n"
            f"⏳ <b>Событие завершено</b> (срок 25 дней истёк). Награды больше недоступны."
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 В профиль", callback_data="back_to_profile")]
        ])
        return text, kb
    chain_parts = []
    for idx, r in enumerate(ev["rewards"], start=1):
        if idx in claimed:
            chain_parts.append("✅")
        else:
            chain_parts.append(f"{r['cost']}{emoji}: {r['label']}")
    chain_line = "—".join(chain_parts)
    claimable = get_claimable_indices(user_data, ev)
    text = (
        f"🎪 <b>{html.escape(ev['title'])}</b>\n"
        f"⏳ До конца события: <b>{format_remaining_time(rem_sec)}</b>\n\n"
        f"Накоплено: <b>{html.escape(ev['currency_name'])}</b> — <b>{cur} / {ev['goal']}</b> {emoji}\n"
        f"<i>Шкала накопительная: валюта не списывается при заборе наград.</i>\n"
        f"<i>За победу: 1–3 {emoji}, за поражение: 0–1 {emoji} (зависит от эффективности в бою).</i>\n\n"
        f"<b>Цепочка наград:</b>\n{chain_line}"
    )
    rows = []
    if claimable:
        first_idx = claimable[0]
        last_idx = claimable[-1]
        if first_idx == last_idx:
            btn_text = f"Забрать №{first_idx}"
        else:
            btn_text = f"Забрать №{first_idx}-{last_idx}"
        cb_data = f"ev_claim_{ev['id']}_{first_idx}_{last_idx}"
        rows.append([InlineKeyboardButton(text=btn_text, callback_data=cb_data)])
    rows.append([InlineKeyboardButton(text="🔙 В профиль", callback_data="back_to_profile")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)

def register_event_handlers(dp, users_db: dict, tanks_db: dict, save_users_fn, admin_ids: list[int] | None = None):
    allowed_admins = set(admin_ids or [])
    @dp.message(Command("addnuts"))
    async def cmd_addnuts(message: Message):
        uid_sender = str(message.from_user.id)
        if allowed_admins and message.from_user.id not in allowed_admins:
            return
        args = (message.text or "").split()
        if len(args) < 2:
            await message.answer("Использование: /addnuts <кол-во> [user_id]")
            return
        try:
            amount = int(args[1])
        except ValueError:
            await message.answer("❌ Количество должно быть целым числом.")
            return
        target_uid = str(int(args[2])) if len(args) >= 3 and args[2].isdigit() else uid_sender
        user_data = users_db.get(target_uid)
        if not user_data:
            await message.answer("❌ Пользователь не найден в базе.")
            return
        ev = get_active_event()
        st = ensure_event_state(user_data, ev["id"])
        st["currency"] = max(0, st.get("currency", 0) + amount)
        save_users_fn()
        await message.answer(
            f"✅ Начислено <b>{amount}</b> {ev['currency_emoji']} игроку <code>{target_uid}</code>.\n"
            f"Текущий баланс ивента: <b>{st['currency']}</b> {ev['currency_emoji']}",
            parse_mode="HTML",
        )
    @dp.callback_query(F.data.startswith("ev_open_"))
    async def cb_ev_open(callback: CallbackQuery):
        uid = str(callback.from_user.id)
        event_id = callback.data.replace("ev_open_", "", 1)
        user_data = users_db.get(uid)
        if not user_data:
            await callback.answer("Профиль не найден", show_alert=True)
            return
        text, kb = build_event_view(user_data, event_id)
        try:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        except Exception:
            try:
                await callback.message.delete()
            except Exception:
                pass
            await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
        await callback.answer()
    @dp.callback_query(F.data.startswith("ev_claim_"))
    async def cb_ev_claim(callback: CallbackQuery):
        uid = str(callback.from_user.id)
        parts = callback.data.split("_")
        if len(parts) < 5:
            await callback.answer("Ошибка данных", show_alert=True)
            return
        start_idx = int(parts[-2])
        end_idx = int(parts[-1])
        event_id = "_".join(parts[2:-2])
        ev = EVENTS_REGISTRY.get(event_id, get_active_event())
        user_data = users_db.get(uid)
        if not user_data:
            await callback.answer("Профиль не найден", show_alert=True)
            return
        st = ensure_event_state(user_data, ev["id"])
        if is_event_expired(st):
            text, kb = build_event_view(user_data, ev["id"])
            try:
                await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
            except Exception:
                pass
            await callback.answer("Ивент завершён (прошло 25 дней).", show_alert=True)
            return
        cur = st["currency"]
        claimed = set(st["claimed"])
        granted_summaries = []
        for idx in range(start_idx, end_idx + 1):
            if 1 <= idx <= len(ev["rewards"]):
                reward = ev["rewards"][idx - 1]
                if idx not in claimed and cur >= reward["cost"]:
                    claimed.add(idx)
                    granted_summaries.append(f"№{idx}: {_claim_single_reward(user_data, reward, tanks_db, ev)}")
        if not granted_summaries:
            await callback.answer("Награды уже получены или не хватает валюты.", show_alert=True)
            return
        st["claimed"] = sorted(claimed)
        save_users_fn()
        text, kb = build_event_view(user_data, ev["id"])
        try:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        except Exception:
            try:
                await callback.message.delete()
            except Exception:
                pass
            await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
        plain_summary = ", ".join(re.sub(r"<[^>]+>", "", s) for s in granted_summaries)
        await callback.answer("Получено: " + plain_summary, show_alert=True)
