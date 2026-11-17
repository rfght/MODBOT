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
    CallbackQuery,
    ChatMemberUpdated,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
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

# --- Файлы данных ---
FILE_IDS_PATH = "file_ids.json"
FILE_IDS = {}

USERS_PATH = "users.json"
USERS = {}

BANNED_PATH = "banned.json"
BANNED = {}

FALLBACKS_PATH = "fallbacks.json"
FALLBACKS = {}

# --- ЗАГРУЗКА ТАНКОВ ---
TANKS_DB = {}
try:
    with open("tanks.json", encoding="utf-8") as f:
        TANKS_DB = json.load(f)
    logger.info(f"Успешно загружено {len(TANKS_DB)} танков.")
except Exception as e:
    logger.error(f"Ошибка загрузки tanks.json: {e}")
    TANKS_DB = {"FV215B 183": {"hp": 1800, "damage": 950, "pen": 300, "armor": 152, "reload": 18.5, "price": 0}}

MOD_NAMES = {
    "old_font": {"ru": "Старый шрифт", "be": "Стары шрыфт", "en": "Old Font"},
    "old_medals": {"ru": "Старые медали", "be": "Старыя медалі", "en": "Old Medals"},
    "old_ui": {"ru": "Старый UI ангара", "be": "Стары UI ангара", "en": "Old Hangar UI"},
}

# --- СИСТЕМА ЗВАНИЙ И ОПЫТА (21 звание) ---
RANKS = {
    1:  ("Новичок", 0, 0, "user"), 2:  ("Гость", 100, 0, "user"), 3:  ("Освоившийся", 300, 0, "user"),
    4:  ("Постоянный", 700, 0, "user"), 5:  ("Ветеран", 1500, 0, "user"), 6:  ("Активный", 3000, 0, "user"),
    7:  ("Знаток", 6000, 0, "user"), 8:  ("Эксперт", 12000, 0, "user"), 9:  ("Гуру", 24000, 0, "user"),
    10: ("Легенда", 48000, 0, "user"), 11: ("Идейный", 0, 1, "modder"), 12: ("Юный мододел", 0, 3, "modder"),
    13: ("Мододел", 0, 5, "modder"), 14: ("Старший мододел", 0, 10, "modder"), 15: ("Мастер модов", 0, 20, "modder"),
    16: ("Тестер", 0, 0, "staff"), 17: ("Младший модератор", 0, 0, "staff"), 18: ("Модератор", 0, 0, "staff"),
    19: ("Администратор", 0, 0, "staff"), 20: ("Вице-владелец", 0, 0, "staff"), 21: ("Владелец", 0, 0, "staff"),
}

ACHIEVEMENTS = {
    "first_download": "Первый мод", "mods_10": "10 модов скачано", "mods_50": "50 модов скачано",
    "first_idea": "Первая идея", "ideas_10": "10 идей", "first_question": "Первый вопрос",
    "banned_1": "Первый бан", "banned_10": "10 банов", "veteran": "Ветеран движения",
    "tank_buyer": "Покупатель танков", "first_win": "Первая победа", "social": "Душа компании"
}

def default_user_data():
    return {
        "lang": None,
        "nickname": None,
        "xp": 0,
        "rank_id": 1,
        "downloads": 0,
        "ideas": 0,
        "questions": 0,
        "bans": 0,
        "achievements": [],
        "registered": datetime.now().strftime("%Y-%m-%d"),
        "appeal_pending": False,
        "tanks": ["FV215B 183"],
        "selected_tank": "FV215B 183",
        "battles": 0,
        "wins": 0,
        "losses": 0,
        "friends": [],
        "friend_requests": []
    }

def get_rank_info(rank_id: int):
    return RANKS.get(rank_id, RANKS[1])

def check_rank_up(user_id: str):
    data = USERS.get(user_id)
    if not data: return None
    current_id = data["rank_id"]
    next_id = current_id + 1
    if next_id not in RANKS: return None
    _, req_xp, req_ideas, rank_type = RANKS[next_id]
    if rank_type != "user": return None
    if data["xp"] >= req_xp and data["ideas"] >= req_ideas:
        data["rank_id"] = next_id
        save_users()
        return RANKS[next_id][0]
    return None

def add_xp(user_id: str, amount: int):
    if user_id not in USERS: USERS[user_id] = default_user_data()
    USERS[user_id]["xp"] += amount
    save_users()

def unlock_achievement(user_id: str, ach_key: str):
    data = USERS.get(user_id)
    if data and ach_key not in data["achievements"]:
        data["achievements"].append(ach_key)
        save_users()
        return ACHIEVEMENTS.get(ach_key)
    return None

def get_display_name(uid: str):
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
                base = default_user_data()
                base.update(val)
                USERS[uid] = base
    except: pass
    try:
        with open(BANNED_PATH) as f: BANNED.update(json.load(f))
    except: pass
    try:
        fallback_file_path = os.path.join(os.path.dirname(__file__), "fallbacks.json")
        if not os.path.exists(fallback_file_path): fallback_file_path = "fallbacks.json"
        with open(fallback_file_path, encoding="utf-8") as f: FALLBACKS.update(json.load(f))
    except: pass

def save_file_ids():
    with open(FILE_IDS_PATH, "w") as f: json.dump(FILE_IDS, f)
def save_users():
    with open(USERS_PATH, "w") as f: json.dump(USERS, f, ensure_ascii=False)
def save_banned():
    with open(BANNED_PATH, "w") as f: json.dump(BANNED, f)

load_data()

# --- Локализация ---
LOCALES = {
    "ru": {
        "start": "Привет, {name}!\n\nДобро пожаловать! Выбери нужный раздел:",
        "choose_lang": "Выбери язык / Абяры мову / Choose language:",
        "lang_changed": "Язык изменён на Русский",
        "btn_mods": "Моды", "btn_fun": "Приколы", "btn_help": "Помощь", "btn_suggest": "Предложить мод",
        "btn_feedback": "Обратная связь", "btn_dev": "В разработке", "btn_donate": "Поддержать", "btn_bug": "Сообщить об ошибке",
        "btn_question": "Задать вопрос", "btn_misc": "Разное", "btn_lang": "Язык", "btn_profile": "Профиль", "btn_back": "Назад", "btn_invite": "Пригласить друга",
        "main_menu": "Главное меню", "feedback_menu": "<b>Обратная связь</b>\n\nВыбери действие:",
        "mods_menu": "<b>Моды</b>\n\nВыбери мод:", "subscribe_needed": "Чтобы скачать этот мод, пожалуйста, подпишись на наш канал!",
        "btn_subscribe": "Подписаться на канал", "version": "Версия мода: {ver}", "btn_info": "Описание мода",
        "cancel": "Отменено, возвращаюсь в главное меню", "nothing_cancel": "Нечего отменять",
        "profile_title": "<b>Профиль</b>", "profile_nick": "Ник: <b>{nick}</b>", "profile_rank": "Звание: <b>{rank}</b>", "profile_xp": "Опыт: {xp} XP",
        "profile_stats": "<b>Статистика</b>\nБоёв: {battles} | Побед: {wins} | Поражений: {losses}\nМодов: {downloads} | Идей: {ideas} | Вопросов: {questions} | Банов: {bans}",
        "profile_tank": "Твой танк: <b>{tank}</b>", "profile_next": "До следующего звания: {xp_left} XP (и {ideas_left} идей)",
        "profile_next_manual": "Следующее звание выдаётся вручную",
        "profile_achievements": "<b>Достижения</b>\n{list}", "profile_no_achievements": "Пока нет достижений",
        "rank_up": "Поздравляю! Ты получил новое звание: <b>{rank}</b>", "rank_given": "Тебе выдано новое звание: <b>{rank}</b>", "ach_unlocked": "Получено достижение: <b>{ach}</b>",
        "fun_prompt": "Кидай свой игровой прикол сюда!\n\nЭто может быть:\n• Забавный момент из боя\n• Необычная ситуация с физикой игры\n• Смешной баг или совпадение\n• Любой другой забавный случай из игры\n\nОтправляй хоть видео, хоть фото, хоть текст\nДля отмены напиши /cancel",
        "fun_thanks": "Спасибо! Твой прикол принят, когда его проверят модераторы, он попадёт в наш канал",
        "suggest_prompt": "<b>Предложить идею для мода</b>\n\nНапиши описание мода и как что работает, фото/видео/голосовые/видеосообщения не принимаются\nОно будет переслано администратору\n\nДля отмены напиши /cancel",
        "suggest_thanks": "Твоя идея отправлена на рассмотрение! Спасибо!",
        "bug_prompt": "Опиши ошибку в моде\nНапиши название мода и что именно не так, всё будет передано парням из дружного коллектива MOD_rak.rar\nДля отмены напиши /cancel",
        "bug_voice": "Напиши подробности текстом и по возможности фото или видео, голосовые и пустые сообщения не принимаются",
        "bug_thanks": "Спасибо, сообщение об ошибке передано разработчикам, постараемся исправить в ближайшее время",
        "question_prompt": "Задай свой вопрос, и мы ответим тебе прямо здесь!\nНапиши свой вопрос или опиши проблему\nДля отмены напиши /cancel",
        "question_thanks": "Твой вопрос отправлен! Ожидай ответа здесь", "question_no_group": "Ошибка: группа для заявок не настроена",
        "dev_text": "Сейчас в разработке:\n\n• Мод на старое окно шансов\n• Старое окно выбора режима\n• Старое окно ТТХ танка \n\nИ всё из этого может и не выйти\nДанный список, это набросок планируемых модов Что-то выйдет, что-то нет",
        "donate_text": "Поддержать разработку модов\n\n• Расскажи о нашем канале и боте друзьям\n• Предложи идею для нового мода\n",
        "misc_menu": "<b>Разное</b>\n\nВыбери интересующий вопрос:",
        "misc_team_btn": "О команде MOD_rak.rar", "misc_join_btn": "Можно ли присоединиться к вам", "misc_share_btn": "Поделиться ботом",
        "misc_team_text": "<b>О команде</b>\n\nМы парни-мододелы\nМы те, кто могут отстоять точку зрения\nА наша точка зрения это старый вид игры\nИ мы не собираемся от неё отступать",
        "misc_join_text": "Набор в команду сейчас закрыт. Но ты можешь заполнить анкету, и мы рассмотрим её, когда откроется набор!",
        "help_menu": "<b>Помощь</b>\n\nВыбери вопрос:",
        "help_install_btn": "Как установить мод", "help_remove_btn": "Как удалить мод", "help_why_btn": "Зачем нужны данные модификации",
        "help_time_btn": "Сколько разрабатываются моды", "help_why_old_btn": "Почему моды только на возвращение старого в игру",
        "help_install_text": "Как установить мод:\n\nШаг 1: Скачать мод с официального сайта For Blitz или в нашем боте\nШаг 1.1: Установки модов на телефон нету, если нужно, то используйте инструкцию/приложения от For Blitz\nОбрати внимание, моды в этом боте только на ПК\nШаг 2: Распаковать архив или просто зайти в него\nШаг 3: Скопировать папку Data\nШаг 4: Зайти в папку игры: C:\\Games\\Tanks Blitz\nШаг 5: Нажать вставить скопированную папку Data с заменой",
        "help_remove_text": "Как удалить мод:\n\nСамый простой способ, нажать в приложении LGC восстановление игры",
        "help_why_text": "Зачем нужны данные модификации:\n\nМоды возвращают удалённые функции и интерфейс, к которым привыкли игроки Это делает игру комфортнее и привычнее для тех, кто играл раньше",
        "help_time_text": "Сколько разрабатываются моды:\n\nВремя разработки зависит от размера мода, сложности, свободного времени у мододелов, а также от того, насколько часто бывают бухие сервера у картошки",
        "help_why_old_text": "Почему модификации только на возвращение старого в игру:\n\nНостальгия у всей команды по старой игре",
        "old_ui_info_text": "Данный мод возвращает:\n• Старую кнопку выбора режима\n• Старый UI хранилища\n• Старую кнопку магазина\n• Старую левую панель\n• Старую кнопку «Тренироваться»\n• Старую кнопку «В Бой»\n• Убраны новые чёрные точки на фоне кнопок боя/выбора режима/взвода\n• Старые иконки для режимов\n• Старые иконки победы/поражения/ничьи во вкладке уведомлений\n• Старые звуки при нажатии кнопок/иконок в ангаре\n• Старые кнопки (зелёные, красные)\n• Старый UI дерева исследования\n• Старый UI окна уведомлений\n• Всякие мелочи",
        "unknown_media_text": "Эт что? Я понимаю только текст и кнопки Выбери нужный раздел на клавиатуре ниже",
        "unavailable_text": "Временно недоступно", "break_hard_text": "Хватит меня ломать, я и так еле держусь 🤖", "break_soft_text": "Не сломаешь, я крепкий",
        "no_rights": "У тебя нет прав для этого действия",
        "ban_usage": "Использование: /ban <user_id> <дд.мм.гггг> <чч:мм:сс> [причина]\nИли: /ban <user_id> never [причина]\nИли ответьте на сообщение пользователя: /ban [причина]",
        "unban_usage": "Использование: /unban <user_id> или ответьте на сообщение пользователя",
        "ban_cant_admin": "Нельзя забанить администратора",
        "ban_done": "Пользователь {uid} забанен до {until}. Причина: {reason}", "ban_done_forever": "Пользователь {uid} забанен навсегда. Причина: {reason}",
        "unban_done": "Пользователь {uid} разбанен", "unban_reply_success": "Пользователь {uid} успешно разбанен", "unban_not_found": "Этот пользователь не в бане",
        "banlist_empty": "Список банов пуст", "banlist_title": "Забаненные:",
        "ban_notify": "Ты был забанен\nПричина: {reason}\nСрок: до {until}", "ban_notify_forever": "Ты был забанен\nПричина: {reason}\nСрок: навсегда",
        "setrank_usage": "Использование: /setrank <user_id> <rank_id>", "setrank_bad_id": "Неверный формат ID", "setrank_no_rank": "Такого звания нет",
        "setrank_done": "Пользователю {uid} выдано звание: {rank}", "setrank_notify_fail": "Не удалось отправить уведомление: {err}",
        "banned_bot_text": "Вы забанены в этом боте\nВы будете разбанены либо при решении администратора, либо когда истекет срок бана\nПосмотреть свой срок бана: /mystatus",
        "ban_invalid_date": "Неверный формат даты. Используй: <дд.мм.гггг> <чч:мм:сс> или никогда (never)", "ban_past": "Указанное время уже прошло",
        "mystatus_no_ban": "Вы не забанены", "mystatus_title": "Ваш бан:", "mystatus_until": "Срок бана: до {until}", "mystatus_until_forever": "Срок бана: навсегда", "mystatus_reason": "Причина: {reason}",
        "staff_empty": "Команда пока пуста", "staff_title": "<b>Состав команды:</b>",
        "invite_text": "Пригласи друга в нашего бота и получи +150 XP!\n\nТвоя ссылка:\n{link}\n\nЗа каждого друга, который зайдет, вы оба получите опыт",
        "ref_bonus": "Твой друг зашел по твоей ссылке! Ты получил +150 XP", "ref_welcome": "Добро пожаловать по приглашению! Ты и твой друг получили +150 XP",
        "apply_team_btn": "Подать заявку в команду",
        "apply_team_text": "<b>Анкета в команду MOD_rak.rar</b>\n\n⚠️ <b>Примечание:</b> Набор в команду закрыт. Мы не принимаем всех подряд. Нам нужны люди с нужным настроением, опытом и свободным временем. Заполнение анкеты не гарантирует вступление, но мы рассмотрим её, когда откроется набор.\n\nПожалуйста, ответь на все вопросы одним сообщением (или несколькими, но подряд):\n\n1. Твой возраст и часовой пояс?\n2. Есть ли опыт в создании модов (каких игр, какие моды)?\n3. Какие инструменты и софт ты знаешь (Python, Blender, редакторы текстур, 3D-редакторы)?\n4. Сколько времени в день/неделю ты готов уделять проекту?\n5. Почему ты хочешь в команду именно MOD_rak.rar?\n6. Твоя любимая фича старого Танкс Блитц?\n7. Ссылка на твои прошлые работы (если есть)?\n8. Что ты хочешь делать в команде (кодить, рисовать, тестировать, модерировать)?\n\nОтправь ответ одним сообщением. Для отмены напиши /cancel",
        "apply_team_thanks": "Твоя анкета отправлена на рассмотрение! Мы свяжемся с тобой, если ты нам подойдешь.",
        "bug_report_fixed": "Твой баг-репорт исправлен! Спасибо за помощь, ты получил +50 XP.", "btn_report_fixed": "✅ Исправлено",
        "appeal_btn": "Подать заявку на разбан", "appeal_usage": "Отправь причину, по которой ты хочешь, чтобы тебя разбанили.",
        "appeal_sent": "Твоя заявка на разбан отправлена администраторам.", "appeal_already": "Ты уже подал заявку на разбан. Ожидай ответа.",
        "appeal_accept": "Твоя заявка на разбан одобрена! Ты разбанен.", "appeal_reject": "Твоя заявка на разбан отклонена.",
        "battle_desc": "⚔️ <b>Танковые бои</b>\n\nЗдесь ты можешь сразиться с другими игроками!\n\n<b>Правила:</b>\n1. Выбираешь формат (или бой с ботом).\n2. Создаешь комнату (или входишь по коду).\n3. Бот выдает танк из твоего ангара.\n4. Ходы идут по очереди! Выбирай снаряд и цель.\n5. Кто последний остался жив — забирает 25-50 XP.\n\n<b>Важно:</b> Ты видишь только ник противника!",
        "battle_choose": "Выбери действие:",
        "battle_bot": "🤖 Бой с ботом", "battle_create": "Создать комнату", "battle_join": "Войти по коду", "battle_list": "Список открытых комнат", "battle_back": "Назад",
        "shop_btn": "🛒 Магазин танков", "shop_title": "🛒 <b>Магазин танков</b>\n\nТвой баланс: <b>{xp} XP</b>\nВыбери танк:", 
        "shop_buy": "Купить за {price} XP", "shop_bought": "✅ Ты купил <b>{tank}</b>!", "shop_not_enough": "❌ Нужно {price} XP.", 
        "shop_select": "Выбрать", "shop_selected": "🚀 Теперь твой танк: <b>{tank}</b>!",
        "tank_stats": "❤️ HP: {hp}\n💥 Урон: {damage}\n🎯 Пробитие: {pen}\n🛡 Броня: {armor}\n⏱ Перезарядка: {reload}с",
        "btn_friends": "👥 Друзья", "friends_title": "<b>Друзья</b>", "friends_requests": "\n🔔 <b>Входящие заявки:</b>", "friends_list": "\n👥 <b>Твои друзья:</b>",
        "friends_empty": "\nУ тебя пока нет друзей.", "friends_accept": "Принять", "friends_decline": "Отклонить",
        "nickname_prompt": "Придумай себе ник (от 3 до 15 символов):", "nickname_taken": "Этот ник уже занят!",
        "nickname_invalid": "Ник должен быть от 3 до 15 символов без пробелов.", "nickname_success": "Отлично, твой ник теперь <b>{nick}</b>!",
        "friend_req_sent": "Заявка отправлена!", "friend_req_accept": "Ты принял заявку от {name}!", "friend_req_decline": "Заявка отклонена.",
        "friend_msg_prompt": "Напиши сообщение для <b>{name}</b>:", "friend_msg_sent": "Сообщение отправлено!",
        "friend_msg_received": "✉️ <b>Сообщение от друга ({name}):</b>\n\n{text}", "add_friend_btn": "🤝 Добавить в друзья",
    },
    "be": {}, "en": {}
}
for lang in ["be", "en"]: LOCALES[lang] = LOCALES["ru"].copy()

def tr(user_id: str, key: str, **kwargs) -> str:
    data = USERS.get(user_id)
    lang = data["lang"] if data and data.get("lang") else "ru"
    text = LOCALES.get(lang, LOCALES["ru"]).get(key, f"[{key}]")
    return text.format(**kwargs) if kwargs else text

# --- Проверка бана ---
def is_banned(user_id: str) -> tuple[bool, dict]:
    if user_id not in BANNED: return False, {}
    info = BANNED[user_id]
    until_str = info.get("until", "")
    if until_str == "never": return True, info
    try: until = datetime.strptime(until_str, "%Y-%m-%d %H:%M:%S")
    except (KeyError, ValueError): return False, {}
    if datetime.now() >= until:
        del BANNED[user_id]; save_banned(); return False, {}
    return True, info

async def check_ban_and_block(message: Message) -> bool:
    uid = str(message.from_user.id)
    banned, info = is_banned(uid)
    if banned:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(uid, "appeal_btn"), callback_data="appeal_ban")]])
        await message.answer(tr(uid, "banned_bot_text"), reply_markup=kb)
        return True
    return False

# --- Клавиатуры ---
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
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr(user_id, "btn_info"), callback_data="mod_old_ui_info")]
    ])

ALL_MENU_BUTTONS = set()
for lang_data in LOCALES.values():
    for k, v in lang_data.items():
        if k.startswith("btn_") or (k.startswith("misc_") and k.endswith("_btn")) or (k.startswith("help_") and k.endswith("_btn")):
            ALL_MENU_BUTTONS.add(v)

# --- Пасхалки ---
EASTER_EGGS = {
    "рак": "Сам такой 🦀", "crab": "Сам такой 🦀",
    "sudo": "Доступ запрещён, хорошая попытка 😎", "sudo su": "Ты кто такой? Иди сюда",
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

# --- Хелперы ---
def find_file_id(base_name: str):
    base_lower = base_name.lower()
    if base_name in FILE_IDS: return base_name, FILE_IDS[base_name]
    for stored_name, file_id in FILE_IDS.items():
        if stored_name.rsplit(".", 1)[0].lower() == base_lower: return stored_name, file_id
    return None

async def check_subscription(user_id: int) -> bool:
    if not CHANNEL_ID: return True
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        if member.status in ["creator", "administrator", "member"]: return True
    except TelegramBadRequest as e: logger.error(f"Ошибка проверки подписки: {e}")
    return False

async def send_mod_file(chat_id: int, base_name: str, reply_markup=None):
    result = find_file_id(base_name)
    if not result:
        await bot.send_message(chat_id, tr(str(chat_id), "unavailable_text")); return
    _, file_id = result
    await bot.send_document(chat_id, file_id, reply_markup=reply_markup)

async def forward_to_admins(message: Message, header: str):
    if not TARGET_CHAT_IDS: return
    for chat_id in TARGET_CHAT_IDS:
        try:
            await bot.send_message(chat_id, header, parse_mode="HTML")
            await message.forward(chat_id)
        except Exception as exc: logger.error(f"Не удалось отправить в {chat_id}. Ошибка: {exc}")

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
            try: await bot.send_message(int(referrer_id), tr(referrer_id, "ref_bonus"))
            except: pass
            await message.answer(tr(uid, "ref_welcome"))
    
    if is_new:
        USERS[uid] = default_user_data()
        if message.from_user.id in ADMIN_IDS: USERS[uid]["rank_id"] = 13
        save_users()

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
    
    if uid not in USERS or not USERS[uid].get("nickname"):
        await cmd_start(message, state); return

    data = USERS[uid]
    rank_name, req_xp, req_ideas, _ = get_rank_info(data["rank_id"])

    next_id = data["rank_id"] + 1
    if next_id in RANKS:
        next_name, next_xp, next_ideas, next_type = RANKS[next_id]
        if next_type == "user":
            xp_left = max(0, next_xp - data["xp"])
            ideas_left = max(0, next_ideas - data["ideas"])
            progress_text = tr(uid, "profile_next", xp_left=xp_left, ideas_left=ideas_left)
        else:
            progress_text = tr(uid, "profile_next_manual")
    else:
        progress_text = "Максимальное звание"

    if data["achievements"]:
        ach_list = "\n".join([f"• {ACHIEVEMENTS.get(a, a)}" for a in data["achievements"]])
        ach_text = tr(uid, "profile_achievements", list=ach_list)
    else:
        ach_text = tr(uid, "profile_no_achievements")

    text = (
        f"{tr(uid, 'profile_title')}\n"
        f"{tr(uid, 'profile_nick', nick=data['nickname'])}\n\n"
        f"{tr(uid, 'profile_rank', rank=rank_name)}\n"
        f"{tr(uid, 'profile_xp', xp=data['xp'])}\n"
        f"{tr(uid, 'profile_stats', battles=data.get('battles',0), wins=data.get('wins',0), losses=data.get('losses',0), downloads=data['downloads'], ideas=data['ideas'], questions=data['questions'], bans=data['bans'])}\n"
        f"{tr(uid, 'profile_tank', tank=data.get('selected_tank', 'FV215B 183'))}\n"
        f"{progress_text}\n\n"
        f"{ach_text}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚔️ Бои", callback_data="battle_menu")],
        [InlineKeyboardButton(text=tr(uid, "shop_btn"), callback_data="shop_menu")],
        [InlineKeyboardButton(text=tr(uid, "btn_friends"), callback_data="friends_menu")],
        [InlineKeyboardButton(text=tr(uid, "btn_invite"), callback_data="invite_friend")]
    ])
    await message.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.message(F.text.in_([LOCALES["ru"]["btn_profile"], LOCALES["be"]["btn_profile"], LOCALES["en"]["btn_profile"]]))
async def btn_profile_click(message: Message, state: FSMContext):
    await cmd_profile(message, state)

@dp.callback_query(F.data == "invite_friend")
async def cb_invite(callback: CallbackQuery):
    uid = str(callback.from_user.id)
    bot_username = (await bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start=ref_{uid}"
    await callback.message.answer(tr(uid, "invite_text", link=ref_link))
    await callback.answer()

@dp.callback_query(F.data == "back_to_profile")
async def cb_back_to_profile(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await cmd_profile(callback.message, state)

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
        await callback.answer(tr(uid, "friend_req_accept", name=get_display_name(req_uid)), show_alert=True)
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
        await callback.answer(tr(uid, "friend_req_decline"), show_alert=True)
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

def calculate_shot(attacker_stats, target_stats, ammo_type):
    if random.random() < 0.10: return 0, "Промах! Снаряд ушел мимо."
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

@dp.callback_query(F.data == "battle_vs_bot")
async def cb_battle_vs_bot(callback: CallbackQuery, state: FSMContext):
    uid = str(callback.from_user.id)
    data = USERS.get(uid, default_user_data())
    tank_name = data.get("selected_tank", "FV215B 183")
    tank_stats = TANKS_DB.get(tank_name, {"hp": 1800, "damage": 950, "pen": 300, "armor": 152, "reload": 18.5}).copy()
    bot_tank_name = random.choice([n for n in TANKS_DB if n != "FV215B 183"])
    bot_stats = TANKS_DB[bot_tank_name].copy()
    
    await state.set_state(UserState.in_battle)
    await state.update_data(is_pve=True, p_hp=tank_stats["hp"], e_hp=bot_stats["hp"], p_tank=tank_name, e_tank=bot_tank_name, p_reload_ready=0, p_stats=tank_stats, e_stats=bot_stats)
    
    text = f"🤖 <b>Бой против бота</b>\n\nТвой танк: <b>{tank_name}</b> (HP: {tank_stats['hp']})\nТанк врага: <b>Неизвестно</b>\n\nТвой ход!"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💥 Выстрел (ББ)", callback_data="pve_shoot_ap")],
        [InlineKeyboardButton(text="💥 Выстрел (ОФ)", callback_data="pve_shoot_he")],
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
    
    damage, msg = calculate_shot(p_stats, e_stats, ammo)
    e_hp -= damage
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
    
    bot_ammo = random.choices(["ap", "he"], weights=[0.8, 0.2])[0]
    b_damage, b_msg = calculate_shot(e_stats, p_stats, bot_ammo)
    p_hp -= b_damage
    text += f"🔫 Враг выстрелил ({'ББ' if bot_ammo=='ap' else 'ОФ'}): {b_msg}\n"
    
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
        [InlineKeyboardButton(text="🏳️ Сдаться", callback_data="pve_surrender")]
    ])
    await state.update_data(p_hp=p_hp, e_hp=e_hp)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "pve_surrender", UserState.in_battle)
async def cb_pve_surrender(callback: CallbackQuery, state: FSMContext):
    await callback.answer("Ты сдался")
    USERS[str(callback.from_user.id)]["losses"] += 1
    USERS[str(callback.from_user.id)]["battles"] += 1
    save_users()
    await state.clear()
    await callback.message.edit_text("🏳️ Ты сдался.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="В меню", callback_data="battle_menu")]]))

# --- PVP ---
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
    ROOMS[code] = {"players": [uid], "max_players": max_players, "is_private": False, "status": "waiting", "hp": {}, "tank": {}, "stats": {}, "reload": {}}
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
    room["reload"] = {p: 0 for p in room["players"]}
    text = "⚔️ <b>Бой начался!</b>\n\n"
    for uid in room["players"]:
        tank_name = USERS.get(uid, {}).get("selected_tank", "FV215B 183")
        stats = TANKS_DB.get(tank_name, {"hp": 1800, "damage": 950, "pen": 300, "armor": 152, "reload": 18.5}).copy()
        room["hp"][uid] = stats["hp"]; room["tank"][uid] = tank_name; room["stats"][uid] = stats
        text += f"👤 <b>{get_display_name(uid)}</b> — {tank_name} (HP: {stats['hp']})\n"
    text += "\nХод первого игрока!"
    for uid in room["players"]:
        try:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💥 Выстрел (ББ)", callback_data=f"pvp_shoot_ap_{code}")],
                [InlineKeyboardButton(text="💥 Выстрел (ОФ)", callback_data=f"pvp_shoot_he_{code}")]
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
    
    damage, msg = calculate_shot(room["stats"][uid], room["stats"][target_id], ammo)
    room["hp"][target_id] -= damage
    text = f"💥 <b>{get_display_name(uid)}</b> выстрелил в <b>{get_display_name(target_id)}</b> ({'ББ' if ammo=='ap' else 'ОФ'})!\n{msg}\n"
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
                    [InlineKeyboardButton(text="💥 Выстрел (ОФ)", callback_data=f"pvp_shoot_he_{code}")]
                ])
            await bot.send_message(int(p), msg_text, parse_mode="HTML", reply_markup=kb)
        except: pass
    await callback.answer()

# --- МОДЫ И ОБРАТНАЯ СВЯЗЬ ---
@dp.message(F.text.in_([LOCALES["ru"]["btn_mods"], LOCALES["be"]["btn_mods"], LOCALES["en"]["btn_mods"]]))
async def btn_mods(message: Message, state: FSMContext):
    if await check_ban_and_block(message): return
    await state.clear()
    uid = str(message.from_user.id)
    await message.answer(tr(uid, "mods_menu"), parse_mode="HTML", reply_markup=get_mods_keyboard(uid))

@dp.callback_query(F.data.startswith("mod_old_"))
async def cb_mod_any(callback: CallbackQuery):
    uid = str(callback.from_user.id)
    banned, _ = is_banned(uid)
    if banned: await callback.answer("Вы забанены", show_alert=True); return

    if callback.data == "mod_old_ui_info":
        await callback.answer(); await callback.message.answer(tr(uid, "old_ui_info_text")); return

    await callback.answer()
    mod_key = callback.data.replace("mod_", "")
    version = "v3.0" if mod_key == "old_ui" else "v1.0"

    if not await check_subscription(callback.from_user.id):
        await callback.message.answer(tr(uid, "subscribe_needed"), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(uid, "btn_subscribe"), url=CHANNEL_LINK)]]))
        return

    await callback.message.answer(tr(uid, "version", ver=version))
    ext = "zip" if mod_key == "old_medals" else "rar"
    kb = get_mod_info_keyboard(uid) if mod_key == "old_ui" else None
    await send_mod_file(callback.from_user.id, f"{mod_key}.{ext}", reply_markup=kb)

    if uid not in USERS: USERS[uid] = default_user_data()
    USERS[uid]["downloads"] += 1
    add_xp(uid, 10)
    save_users()

    new_rank = check_rank_up(uid)
    if new_rank: await callback.message.answer(tr(uid, "rank_up", rank=new_rank))

    if USERS[uid]["downloads"] in (1, 10, 50):
        ach = unlock_achievement(uid, f"mods_{USERS[uid]['downloads']}" if USERS[uid]["downloads"] > 1 else "first_download")
        if ach: await callback.message.answer(tr(uid, "ach_unlocked", ach=ach))

@dp.message(F.text.in_([LOCALES["ru"]["btn_fun"], LOCALES["be"]["btn_fun"], LOCALES["en"]["btn_fun"]]))
async def btn_fun(message: Message, state: FSMContext):
    if await check_ban_and_block(message): return
    await state.set_state(UserState.awaiting_fun)
    uid = str(message.from_user.id)
    await message.answer(tr(uid, "fun_prompt"), reply_markup=get_main_keyboard(uid))

@dp.message(UserState.awaiting_fun, ~F.text.in_(ALL_MENU_BUTTONS))
async def receive_fun(message: Message, state: FSMContext):
    await state.clear()
    uid = str(message.from_user.id)
    user = message.from_user
    header = f"<b>Прикол от пользователя!</b>\n👤 {user.full_name} (@{user.username})\n🆔 <code>{user.id}</code>\n\n"
    await forward_to_admins(message, header)
    add_xp(uid, 5)
    await message.answer(tr(uid, "fun_thanks"), reply_markup=get_main_keyboard(uid))

@dp.message(F.text.in_([LOCALES["ru"]["btn_feedback"], LOCALES["be"]["btn_feedback"], LOCALES["en"]["btn_feedback"]]))
async def btn_feedback(message: Message, state: FSMContext):
    if await check_ban_and_block(message): return
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
    if await check_ban_and_block(message): return
    await state.set_state(UserState.awaiting_mod_suggestion)
    uid = str(message.from_user.id)
    await message.answer(tr(uid, "suggest_prompt"), parse_mode="HTML", reply_markup=get_feedback_keyboard(uid))

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

    if USERS[uid]["ideas"] in (1, 10):
        ach = unlock_achievement(uid, f"ideas_{USERS[uid]['ideas']}" if USERS[uid]["ideas"] > 1 else "first_idea")
        if ach: await message.answer(tr(uid, "ach_unlocked", ach=ach))

    await message.answer(tr(uid, "suggest_thanks"), reply_markup=get_main_keyboard(uid))

@dp.message(F.text.in_([LOCALES["ru"]["btn_bug"], LOCALES["be"]["btn_bug"], LOCALES["en"]["btn_bug"]]))
async def btn_bug_report(message: Message, state: FSMContext):
    if await check_ban_and_block(message): return
    await state.set_state(UserState.awaiting_bug_report)
    uid = str(message.from_user.id)
    await message.answer(tr(uid, "bug_prompt"), reply_markup=get_feedback_keyboard(uid))

@dp.message(UserState.awaiting_bug_report, ~F.text.in_(ALL_MENU_BUTTONS))
async def receive_bug_report(message: Message, state: FSMContext):
    uid = str(message.from_user.id)
    if message.voice or (not message.text and not message.photo and not message.video and not message.document):
        await message.answer(tr(uid, "bug_voice")); return
    await state.clear()
    user = message.from_user
    header = f"<b>[ОШИБКА] Сообщение об ошибке</b>\n👤 {user.full_name} (@{user.username})\n🆔 <code>{user.id}</code>\n\n"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(uid, "btn_report_fixed"), callback_data=f"bug_fixed_{uid}")]])
    
    if TARGET_CHAT_IDS:
        for chat_id in TARGET_CHAT_IDS:
            try:
                await bot.send_message(chat_id, header, parse_mode="HTML", reply_markup=kb)
                await message.forward(chat_id)
            except Exception as exc: logger.error(f"Не удалось отправить: {exc}")
                
    add_xp(uid, 15)
    await message.answer(tr(uid, "bug_thanks"), reply_markup=get_main_keyboard(uid))

@dp.message(F.text.in_([LOCALES["ru"]["btn_question"], LOCALES["be"]["btn_question"], LOCALES["en"]["btn_question"]]))
async def btn_question(message: Message, state: FSMContext):
    if await check_ban_and_block(message): return
    await state.set_state(UserState.awaiting_question)
    uid = str(message.from_user.id)
    await message.answer(tr(uid, "question_prompt"), reply_markup=get_feedback_keyboard(uid))

@dp.message(UserState.awaiting_question, ~F.text.in_(ALL_MENU_BUTTONS))
async def receive_question(message: Message, state: FSMContext):
    await state.clear()
    uid = str(message.from_user.id)
    user = message.from_user
    header = f"<b>Вопрос от пользователя!</b>\n👤 {user.full_name} (@{user.username})\n🆔 <code>{user.id}</code>\n\nОтветьте на это сообщение (Reply), чтобы отправить ответ пользователю"

    if not TARGET_CHAT_IDS: await message.answer(tr(uid, "question_no_group")); return

    for chat_id in TARGET_CHAT_IDS:
        try:
            await bot.send_message(chat_id, header, parse_mode="HTML")
            await message.forward(chat_id)
        except Exception as exc: logger.error(f"Не удалось отправить: {exc}")

    if uid not in USERS: USERS[uid] = default_user_data()
    USERS[uid]["questions"] += 1
    add_xp(uid, 5)
    save_users()

    if USERS[uid]["questions"] == 1:
        ach = unlock_achievement(uid, "first_question")
        if ach: await message.answer(tr(uid, "ach_unlocked", ach=ach))

    await message.answer(tr(uid, "question_thanks"), reply_markup=get_main_keyboard(uid))

# --- АНКЕТА В КОМАНДУ ---
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
    user = message.from_user
    header = f"<b>📝 Анкета в команду!</b>\n👤 {user.full_name} (@{user.username})\n🆔 <code>{user.id}</code>\n\n"
    
    if TARGET_CHAT_IDS:
        for chat_id in TARGET_CHAT_IDS:
            try:
                await bot.send_message(chat_id, header, parse_mode="HTML")
                await message.forward(chat_id)
            except Exception as exc: logger.error(f"Ошибка отправки: {exc}")
                
    await message.answer(tr(uid, "apply_team_thanks"), reply_markup=get_main_keyboard(uid))

# --- ОБРАБОТКА ИСПРАВЛЕННЫХ БАГОВ ---
@dp.callback_query(F.data.startswith("bug_fixed_"))
async def cb_bug_fixed(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: await callback.answer("Только админ", show_alert=True); return
    target_id = callback.data.split("_")[-1]
    add_xp(target_id, 50)
    try: await bot.send_message(int(target_id), tr(target_id, "bug_report_fixed"))
    except: pass
    await callback.message.edit_text(callback.message.text + "\n\n✅ <b>Статус: Исправлено</b>", parse_mode="HTML")
    await callback.answer("Уведомлен!")

# --- ЗАЯВКА НА РАЗБАН ---
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
    if USERS.get(uid, {}).get("appeal_pending"): await message.answer(tr(uid, "appeal_already")); return
    if uid not in USERS: USERS[uid] = default_user_data()
    USERS[uid]["appeal_pending"] = True
    save_users()
    
    user = message.from_user
    header = f"<b>🔓 Заявка на разбан!</b>\n👤 {user.full_name} (@{user.username})\n🆔 <code>{user.id}</code>\nПричина: {message.text}\n\n<i>Ответьте на это сообщение (Reply), чтобы разбанить.</i>"
    
    if TARGET_CHAT_IDS:
        for chat_id in TARGET_CHAT_IDS:
            try: await bot.send_message(chat_id, header, parse_mode="HTML")
            except Exception as exc: logger.error(f"Ошибка: {exc}")
                
    await message.answer(tr(uid, "appeal_sent"))

# --- ПОМОЩЬ ---
@dp.message(F.text.in_([LOCALES["ru"]["btn_help"], LOCALES["be"]["btn_help"], LOCALES["en"]["btn_help"]]))
async def btn_help(message: Message, state: FSMContext):
    if await check_ban_and_block(message): return
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
    if is_banned(uid)[0]: await callback.answer("Вы забанены", show_alert=True); return
    await callback.answer()
    key = f"{callback.data}_text"
    await callback.message.answer(tr(uid, key))

# --- РАЗНОЕ ---
@dp.message(F.text.in_([LOCALES["ru"]["btn_misc"], LOCALES["be"]["btn_misc"], LOCALES["en"]["btn_misc"]]))
async def btn_misc(message: Message, state: FSMContext):
    if await check_ban_and_block(message): return
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
    if is_banned(uid)[0]: await callback.answer("Вы забанены", show_alert=True); return
    await callback.answer()
    
    if callback.data == "misc_dev": await callback.message.answer(tr(uid, "dev_text"))
    elif callback.data == "misc_donate": await callback.message.answer(tr(uid, "donate_text"))
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
        if callback.data == "misc_team": await callback.message.answer(tr(uid, key), parse_mode="HTML")
        else: await callback.message.answer(tr(uid, key))

# --- АДМИНКА ---
@dp.message(Command("setrank"))
async def cmd_setrank(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    args = message.text.split()
    if len(args) < 3:
        await message.answer(tr(str(message.from_user.id), "setrank_usage")); return
    try:
        target_id = str(args[1]); rank_id = int(args[2])
    except ValueError:
        await message.answer(tr(str(message.from_user.id), "setrank_bad_id")); return

    if rank_id not in RANKS:
        await message.answer(tr(str(message.from_user.id), "setrank_no_rank")); return

    if target_id not in USERS: USERS[target_id] = default_user_data()

    USERS[target_id]["rank_id"] = rank_id
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
    rank_admin = USERS.get(uid_admin, {}).get("rank_id", 0)
    if message.from_user.id not in ADMIN_IDS and rank_admin < 19:
        await message.answer(tr(uid_admin, "no_rights")); return

    staff_list = []
    for uid, data in USERS.items():
        rank_id = data.get("rank_id", 1)
        if rank_id in RANKS:
            _, _, _, rank_type = RANKS[rank_id]
            if rank_type in ("modder", "staff"): staff_list.append((rank_id, uid, data))
    
    if not staff_list:
        await message.answer(tr(uid_admin, "staff_empty")); return

    staff_list.sort(key=lambda x: x[0], reverse=True)
    text_lines = [tr(uid_admin, "staff_title") + "\n"]
    for rank_id, uid, data in staff_list:
        text_lines.append(f"<b>{RANKS[rank_id][0]}</b> | Ник: <b>{data.get('nickname', 'Не задан')}</b>\n└ XP: {data.get('xp', 0)} | Идей: {data.get('ideas', 0)}\n")
    
    full_text = "\n".join(text_lines)
    if len(full_text) > 4000:
        parts = []; current_part = ""
        for line in text_lines:
            if len(current_part) + len(line) > 4000:
                parts.append(current_part); current_part = line + "\n"
            else: current_part += line + "\n"
        if current_part: parts.append(current_part)
        for part in parts: await message.answer(part, parse_mode="HTML")
    else:
        await message.answer(full_text, parse_mode="HTML")

@dp.message(Command("reply"))
async def cmd_reply(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    args = message.text.split(maxsplit=2)
    
    if message.reply_to_message and len(args) >= 2:
        target_user_id = None
        if message.reply_to_message.text:
            match = USER_ID_RE.search(message.reply_to_message.text)
            if match: target_user_id = int(match.group(1))
            elif message.reply_to_message.forward_from: target_user_id = message.reply_to_message.forward_from.id
        if not target_user_id:
            await message.answer("❌ Не удалось найти ID в сообщении. Напиши: `/reply <id> <текст>`"); return
        reply_text = args[1] if len(args) > 1 else ""
    elif len(args) >= 3:
        try: target_user_id = int(args[1]); reply_text = args[2]
        except ValueError: await message.answer("❌ Неверный ID."); return
    else:
        await message.answer("❌ Использование:\n1. Ответь на сообщение с ID: `/reply <текст>`\n2. Или: `/reply <user_id> <текст>`"); return

    try:
        await bot.send_message(target_user_id, f"<b>✉️ Сообщение от администрации:</b>\n\n{reply_text}", parse_mode="HTML")
        await message.answer(f"✅ Доставлено пользователю {target_user_id}")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("ban"))
async def cmd_ban(message: Message):
    uid_admin = str(message.from_user.id)
    if message.from_user.id not in ADMIN_IDS and USERS.get(uid_admin, {}).get("rank_id", 0) < 18:
        await message.answer(tr(uid_admin, "no_rights")); return

    target_id = None; args = message.text.split()
    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id; reason_args = args[1:]
    else:
        if len(args) < 3: await message.answer(tr(uid_admin, "ban_usage")); return
        try: target_id = int(args[1]); reason_args = args[2:]
        except ValueError: await message.answer(tr(uid_admin, "setrank_bad_id")); return

    if target_id in ADMIN_IDS: await message.answer(tr(uid_admin, "ban_cant_admin")); return

    forever = False; until_dt = None
    if reason_args and reason_args[0].lower() in ("never", "навсегда", "назаўжды"):
        forever = True; reason = " ".join(reason_args[1:]) if len(reason_args) > 1 else "Без причины"
    else:
        if len(reason_args) < 2 and not message.reply_to_message: await message.answer(tr(uid_admin, "ban_usage")); return
        if message.reply_to_message:
            forever = True; reason = " ".join(reason_args) if reason_args else "Без причины"
        else:
            try: until_dt = datetime.strptime(f"{reason_args[0]} {reason_args[1]}", "%d.%m.%Y %H:%M:%S")
            except ValueError: await message.answer(tr(uid_admin, "ban_invalid_date")); return
            if until_dt <= datetime.now(): await message.answer(tr(uid_admin, "ban_past")); return
            reason = " ".join(reason_args[2:]) if len(reason_args) > 2 else "Без причины"

    target_str = str(target_id)
    BANNED[target_str] = {"reason": reason, "until": "never" if forever else until_dt.strftime("%Y-%m-%d %H:%M:%S"), "date_banned": datetime.now().strftime("%Y-%m-%d %H:%M"), "banned_by": message.from_user.id}
    save_banned()

    if target_str not in USERS: USERS[target_str] = default_user_data()
    USERS[target_str]["bans"] += 1
    save_users()

    if USERS[target_str]["bans"] in (1, 10):
        ach = unlock_achievement(target_str, f"banned_{USERS[target_str]['bans']}")
        if ach:
            try: await bot.send_message(target_id, tr(target_str, "ach_unlocked", ach=ach), parse_mode="HTML")
            except: pass

    if TARGET_CHAT_IDS:
        try: await bot.ban_chat_member(TARGET_CHAT_IDS[0], target_id)
        except: pass

    try:
        if forever: await bot.send_message(target_id, tr(target_str, "ban_notify_forever", reason=reason))
        else: await bot.send_message(target_id, tr(target_str, "ban_notify", reason=reason, until=until_dt.strftime("%d.%m.%Y %H:%M:%S")))
    except: pass

    if forever: await message.answer(tr(uid_admin, "ban_done_forever", uid=target_id, reason=reason))
    else: await message.answer(tr(uid_admin, "ban_done", uid=target_id, until=until_dt.strftime("%d.%m.%Y %H:%M:%S"), reason=reason))

@dp.message(Command("unban"))
async def cmd_unban(message: Message):
    uid_admin = str(message.from_user.id)
    if message.from_user.id not in ADMIN_IDS and USERS.get(uid_admin, {}).get("rank_id", 0) < 18:
        await message.answer(tr(uid_admin, "no_rights")); return

    target_id = None
    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
    else:
        args = message.text.split()
        if len(args) < 2: await message.answer(tr(uid_admin, "unban_usage")); return
        try: target_id = int(args[1])
        except ValueError: await message.answer(tr(uid_admin, "setrank_bad_id")); return

    target_str = str(target_id)
    if target_str in BANNED:
        del BANNED[target_str]; save_banned()
        if TARGET_CHAT_IDS:
            try: await bot.unban_chat_member(TARGET_CHAT_IDS[0], target_id)
            except: pass
        await message.answer(tr(uid_admin, "unban_reply_success", uid=target_id))
    else:
        await message.answer(tr(uid_admin, "unban_not_found"))

@dp.message(Command("banlist"))
async def cmd_banlist(message: Message):
    uid_admin = str(message.from_user.id)
    if message.from_user.id not in ADMIN_IDS and USERS.get(uid_admin, {}).get("rank_id", 0) < 18:
        await message.answer(tr(uid_admin, "no_rights")); return

    if not BANNED: await message.answer(tr(uid_admin, "banlist_empty")); return

    lines = []
    for uid, info in BANNED.items():
        until = info.get("until", "?")
        if until == "never": until = "навсегда"
        lines.append(f"• {uid} | до {until} | {info.get('reason', '')}")
    await message.answer(tr(uid_admin, "banlist_title") + "\n" + "\n".join(lines))

@dp.message(Command("mystatus"))
async def cmd_mystatus(message: Message):
    uid = str(message.from_user.id)
    banned, info = is_banned(uid)
    if not banned: await message.answer(tr(uid, "mystatus_no_ban")); return

    until = info.get("until", "")
    if until == "never": until_text = tr(uid, "mystatus_until_forever")
    else: until_text = tr(uid, "mystatus_until", until=datetime.strptime(until, "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y %H:%M:%S"))

    text = f"{tr(uid, 'mystatus_title')}\n{until_text}\n{tr(uid, 'mystatus_reason', reason=info.get('reason', '?'))}"
    await message.answer(text, reply_markup=None)

# --- Прочие обработчики ---
@dp.message(F.document)
async def group_document_handler(message: Message):
    if GROUP_ID_VALUE and str(message.chat.id) == str(GROUP_ID_VALUE):
        doc = message.document
        if doc.file_name:
            FILE_IDS[doc.file_name] = doc.file_id
            save_file_ids()
            await message.answer(f"Файл {doc.file_name} сохранен")

@dp.chat_member(F.chat.id == GROUP_ID_VALUE)
async def on_chat_member(event: ChatMemberUpdated):
    if event.new_chat_member.status in ("member", "restricted"):
        uid = str(event.new_chat_member.user.id)
        banned, _ = is_banned(uid)
        if banned:
            try:
                await bot.ban_chat_member(event.chat.id, event.new_chat_member.user.id)
                await bot.send_message(event.chat.id, f"Пользователь {uid} в чёрном списке и был удалён")
            except: pass

@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    if await check_ban_and_block(message): return
    uid = str(message.from_user.id)
    if await state.get_state():
        await state.clear()
        await message.answer(tr(uid, "cancel"), reply_markup=get_main_keyboard(uid))
    else:
        await message.answer(tr(uid, "nothing_cancel"), reply_markup=get_main_keyboard(uid))

@dp.message(Command("lang"))
async def cmd_lang(message: Message, state: FSMContext):
    if await check_ban_and_block(message): return
    await state.clear()
    await message.answer(tr(str(message.from_user.id), "choose_lang"), reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_lang_ru")],
        [InlineKeyboardButton(text="🇧🇾 Беларуская", callback_data="set_lang_be")],
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="set_lang_en")],
    ]))

@dp.callback_query(F.data.startswith("set_lang_"))
async def cb_set_lang(callback: CallbackQuery, state: FSMContext):
    uid = str(callback.from_user.id)
    banned, _ = is_banned(uid)
    if banned: await callback.answer("Вы забанены", show_alert=True); return
    lang = callback.data.split("_")[-1]
    if uid not in USERS: USERS[uid] = default_user_data()
    USERS[uid]["lang"] = lang
    save_users()
    await callback.message.delete()
    await callback.message.answer(tr(uid, "lang_changed"), reply_markup=get_main_keyboard(uid))
    await callback.answer()

@dp.message(Command("testgroup"))
async def cmd_test_group(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await easter_egg_handler(message, state); return
    if not TARGET_CHAT_IDS: await message.answer("❌ TARGET_CHAT_IDS пуст"); return
    try:
        await bot.send_message(TARGET_CHAT_IDS[0], "✅ Тест связи")
        await message.answer("✅ Успешно отправлено!")
    except Exception as e: await message.answer(f"❌ Ошибка: {e}")

USER_ID_RE = re.compile(r"🆔 <code>(\d+)</code>")

@dp.message(F.reply_to_message, F.chat.id.in_(TARGET_CHAT_IDS))
async def handle_group_reply(message: Message):
    replied_msg = message.reply_to_message
    if not replied_msg or not replied_msg.text: return
    match = USER_ID_RE.search(replied_msg.text)
    if not match: return
    user_id = int(match.group(1))
    try:
        await bot.send_message(user_id, f"<b>Ответ от поддержки:</b>\n\n{message.text}", parse_mode="HTML")
        await message.reply("Ответ отправлен!")
    except Exception as e: await message.reply(f"Ошибка: {e}")

@dp.message(F.text)
async def easter_egg_handler(message: Message, state: FSMContext):
    if await state.get_state() is not None: return
    
    uid = str(message.from_user.id)
    banned, _ = is_banned(uid)
    if banned:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(uid, "appeal_btn"), callback_data="appeal_ban")]])
        await message.answer(tr(uid, "banned_bot_text"), reply_markup=kb); return
        
    if uid not in USERS or not USERS[uid].get("lang"):
        await cmd_start(message, state); return

    text_lower = message.text.strip().lower()

    if text_lower in EASTER_EGGS:
        await message.answer(EASTER_EGGS[text_lower], reply_markup=get_main_keyboard(uid)); return

    for trigger, reply in EASTER_EGGS.items():
        if len(trigger) >= 3 and trigger in text_lower:
            await message.answer(reply, reply_markup=get_main_keyboard(uid)); return

    if "сломай" in text_lower or "взломай" in text_lower or "hack" in text_lower or "break" in text_lower:
        hits = EASTER_EGG_HITS.get(uid, 0) + 1
        EASTER_EGG_HITS[uid] = hits
        if hits >= 3: await message.answer(tr(uid, "break_hard_text"), reply_markup=get_main_keyboard(uid))
        else: await message.answer(tr(uid, "break_soft_text"), reply_markup=get_main_keyboard(uid))
        return

    is_gibberish = False
    if len(text_lower) > 50 and " " not in text_lower: is_gibberish = True
    elif len(text_lower) < 3 or text_lower.isdigit() or not any(c.isalpha() for c in text_lower): is_gibberish = True

    replies_key = "gibberish" if is_gibberish else "fallback"
    user_lang = USERS.get(uid, {}).get("lang") or "ru"
    lang_fallbacks = FALLBACKS.get(user_lang, FALLBACKS.get("ru", {}))
    replies_list = lang_fallbacks.get(replies_key, ["Ошибка загрузки фраз"])
    
    await message.answer(random.choice(replies_list), reply_markup=get_main_keyboard(uid))

@dp.message()
async def unknown_media(message: Message, state: FSMContext):
    if await state.get_state() is not None: return
    if GROUP_ID_VALUE and str(message.chat.id) == str(GROUP_ID_VALUE): return
    uid = str(message.from_user.id)
    banned, _ = is_banned(uid)
    if banned:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(uid, "appeal_btn"), callback_data="appeal_ban")]])
        await message.answer(tr(uid, "banned_bot_text"), reply_markup=kb); return
        
    if uid not in USERS or not USERS[uid].get("lang"):
        await cmd_start(message, state); return
        
    await message.answer(tr(uid, "unknown_media_text"), reply_markup=get_main_keyboard(uid))

async def main():
    logger.info("Bot started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
