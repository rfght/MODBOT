import html
import random
import re
from aiogram import F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

LOW_TIER_TANKS = [
    "MS-1", "Pz. II", "M2 Light", "Cruiser II",
    "BT-2", "Pz. III A", "M3 Stuart", "T-26",
    "BT-7", "Pz. III", "M5 Stuart", "SU-76I",
]

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
    state = events_store.setdefault(eid, {"currency": 0, "claimed": []})
    state.setdefault("currency", 0)
    state.setdefault("claimed", [])
    return state


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
) -> tuple[int, str]:
    ev = get_active_event()
    user_data = users_db.get(str(uid))
    if not user_data:
        return 0, ev["currency_emoji"]

    earned = calculate_event_currency(
        won=won,
        damage_dealt=damage_dealt,
        enemy_max_hp=enemy_max_hp,
        player_max_hp=player_max_hp,
        player_hp_left=player_hp_left,
        shots_hit=shots_hit,
    )
    if earned > 0:
        st = ensure_event_state(user_data, ev["id"])
        st["currency"] += earned
        save_users_fn()
    return earned, ev["currency_emoji"]


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

    chain_parts = []
    for idx, r in enumerate(ev["rewards"], start=1):
        if idx in claimed:
            chain_parts.append("✅")
        else:
            chain_parts.append(f"#{idx} ({r['cost']}{emoji}: {r['label']})")

    chain_line = "—".join(chain_parts)
    claimable = get_claimable_indices(user_data, ev)

    text = (
        f"🎪 <b>{html.escape(ev['title'])}</b>\n\n"
        f"Валюта: <b>{html.escape(ev['currency_name'])}</b> — <b>{cur} / {ev['goal']}</b> {emoji}\n"
        f"<i>За победу: 1–3 {emoji}, за поражение: 0–1 {emoji} (зависит от эффективности в бою).</i>\n\n"
        f"<b>Цепочка наград:</b>\n{chain_line}"
    )

    rows = []
    if claimable:
        first_idx = claimable[0]
        last_idx = claimable[-1]
        if first_idx == last_idx:
            btn_text = f"🎁 Забрать №{first_idx}"
        else:
            btn_text = f"🎁 Забрать №{first_idx}-{last_idx}"
        cb_data = f"ev_claim_{ev['id']}_{first_idx}_{last_idx}"
        rows.append([InlineKeyboardButton(text=btn_text, callback_data=cb_data)])

    rows.append([InlineKeyboardButton(text="🔙 В профиль", callback_data="back_to_profile")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


async def _render_event_message(message, text: str, reply_markup: InlineKeyboardMarkup):
    try:
        await message.edit_text(text, parse_mode="HTML", reply_markup=reply_markup)
    except Exception:
        try:
            await message.delete()
        except Exception:
            pass
        await message.answer(text, parse_mode="HTML", reply_markup=reply_markup)


def register_event_handlers(dp, users_db: dict, tanks_db: dict, save_users_fn):
    @dp.callback_query(F.data.startswith("ev_open_"))
    async def cb_ev_open(callback: CallbackQuery):
        uid = str(callback.from_user.id)
        event_id = callback.data.replace("ev_open_", "", 1)
        user_data = users_db.get(uid)
        if not user_data:
            await callback.answer("Профиль не найден", show_alert=True)
            return
        text, kb = build_event_view(user_data, event_id)
        await _render_event_message(callback.message, text, kb)
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
        await _render_event_message(callback.message, text, kb)

        clean_summary = ", ".join(re.sub(r"<[^>]+>", "", s) for s in granted_summaries)
        await callback.answer("Получено: " + clean_summary, show_alert=True)
