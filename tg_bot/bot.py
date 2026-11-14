import asyncio
import json
import logging
import os
import random
import re
import string
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
try:
    with open("tanks.json", encoding="utf-8") as f:
        TANK_NAMES = json.load(f)
except Exception:
    TANK_NAMES = [
        "Т-62А", "Об. 907", "Об. 140", "Т-22 ср.", "Об. 430Б", "M48 Patton", "M60", "E 50 M", "Leopard 1", "Kpz 50 t",
        "FV4202", "STB-1", "WZ-121", "121B", "AMX 30 B", "Progetto 65", "TVP T 50/51", "CS-63", "Carro 45t", "Lion",
        "Т-54", "Об. 283", "M46 Patton", "T54E1", "E 50", "Leopard PT A", "Centurion 7/1", "Cobra", "Type 61", "WZ-120",
        "Т-44", "СТГ", "Объект 274а", "Pershing", "T69", "T95E2", "T26E4", "T25 Pilot 1", "Panther II", "Indien-Pz.",
        "Т-43", "Т-44-85", "Т-34-85 Рыжий", "КВ-13", "T20", "T23E3", "T26E3 Eagle 7", "T42", "VK 30.02 D", "Panther/M10",
        "Т-34-85", "M4A3E8", "M4A3E2", "VK 30.01 P", "VK 30.01 D", "Pz. IV S.", "Cromwell", "Chi-To", "Type 58", "Bretagne Panther",
        "ИС-7", "ИС-4", "ИС-3", "КВ-4", "КВ-2", "Т-150", "Maus", "E 100", "E 75", "VK 45.02 B",
        "T110E5", "T57 Heavy", "T29", "T32", "T34", "AMX 50 B", "AMX M4 54", "Foch B", "Batchat 25t", "AMX 13 90",
        "Grille 15", "WT auf E 100", "JgPz E 100", "Object 268", "Object 263", "T110E3", "T110E4", "FV215b (183)", "FV4005", "Conway",
        "Об. 261", "M40/43", "G.W. E 100", "T92 HMC", "Conqueror GC", "Bat.-Châtillon 155 58", "AMX 13 F3 AM", "Lorraine 155 mle. 50", "FV3805", "СУ-14-2",
        "Sheridan", "T-100 LT", "WZ-132-1", "AMX 13 105", "Rhm. Pzw.", "Spähpanzer SP I C", "M41 Walker Bulldog", "T49", "ЛТТБ", "ЛТ-432"
    ]

# --- ХРАНИЛИЩЕ ИГРОВЫХ КОМНАТ ---
ROOMS = {}

class BattleState(StatesGroup):
    choosing_size = State()
    entering_code = State()

def generate_room_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))

def get_random_tank():
    name = random.choice(TANK_NAMES)
    hp = random.randint(800, 1500)
    return name, hp

MOD_NAMES = {
    "old_font": {"ru": "Старый шрифт", "be": "Стары шрыфт", "en": "Old Font"},
    "old_medals": {"ru": "Старые медали", "be": "Старыя медалі", "en": "Old Medals"},
    "old_ui": {"ru": "Старый UI ангара", "be": "Стары UI ангара", "en": "Old Hangar UI"},
}

# --- СИСТЕМА ЗВАНИЙ И ОПЫТА (21 звание) ---
RANKS = {
    1:  ("Новичок", 0, 0, "user"),
    2:  ("Гость", 100, 0, "user"),
    3:  ("Освоившийся", 300, 0, "user"),
    4:  ("Постоянный", 700, 0, "user"),
    5:  ("Ветеран", 1500, 0, "user"),
    6:  ("Активный", 3000, 0, "user"),
    7:  ("Знаток", 6000, 0, "user"),
    8:  ("Эксперт", 12000, 0, "user"),
    9:  ("Гуру", 24000, 0, "user"),
    10: ("Легенда", 48000, 0, "user"),
    11: ("Идейный", 0, 1, "modder"),
    12: ("Юный мододел", 0, 3, "modder"),
    13: ("Мододел", 0, 5, "modder"),
    14: ("Старший мододел", 0, 10, "modder"),
    15: ("Мастер модов", 0, 20, "modder"),
    16: ("Тестер", 0, 0, "staff"),
    17: ("Младший модератор", 0, 0, "staff"),
    18: ("Модератор", 0, 0, "staff"),
    19: ("Администратор", 0, 0, "staff"),
    20: ("Вице-владелец", 0, 0, "staff"),
    21: ("Владелец", 0, 0, "staff"),
}

ACHIEVEMENTS = {
    "first_download": "Первый мод",
    "mods_10": "10 модов скачано",
    "mods_50": "50 модов скачано",
    "first_idea": "Первая идея",
    "ideas_10": "10 идей",
    "first_question": "Первый вопрос",
    "banned_1": "Первый бан",
    "banned_10": "10 банов",
    "veteran": "Ветеран движения",
}


def default_user_data():
    return {
        "lang": None,
        "xp": 0,
        "rank_id": 1,
        "downloads": 0,
        "ideas": 0,
        "questions": 0,
        "bans": 0,
        "achievements": [],
        "registered": datetime.now().strftime("%Y-%m-%d"),
        "appeal_pending": False,
    }


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
    if user_id not in USERS:
        USERS[user_id] = default_user_data()
    USERS[user_id]["xp"] += amount
    save_users()


def unlock_achievement(user_id: str, ach_key: str):
    data = USERS.get(user_id)
    if data and ach_key not in data["achievements"]:
        data["achievements"].append(ach_key)
        save_users()
        return ACHIEVEMENTS.get(ach_key)
    return None


# --- Загрузка/Сохранение ---
def load_data():
    global FILE_IDS, USERS, BANNED, FALLBACKS

    FILE_IDS = {
        "old_font.rar": "BQACAgIAAyEFAASo0DuCAAPRaudEoy_WaUJytv6Ax-5vHj49Zk8AAqqZAAJuI4FJZH-8dxswqq09BA",
        "old_medals.zip": "BQACAgIAAyEFAASo0DuCAAPQaudEo89jj1q6kdFa5l4mjYzZCmoAAqmZAAJuI4FJly1Z9B-lN4E9BA",
        "old_ui.rar": "BQACAgIAAyEFAASo0DuCAAPSaudEozVgaEGz-USX1kCO8mw9czsAAp-qAAJqFCBLsufG1Xs4z3E9BA",
    }
    try:
        with open(FILE_IDS_PATH) as f:
            FILE_IDS.update(json.load(f))
    except (OSError, json.JSONDecodeError):
        pass

    try:
        with open(USERS_PATH) as f:
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
    except (OSError, json.JSONDecodeError):
        pass

    try:
        with open(BANNED_PATH) as f:
            BANNED.update(json.load(f))
    except (OSError, json.JSONDecodeError):
        pass
        
    try:
        fallback_file_path = os.path.join(os.path.dirname(__file__), "fallbacks.json")
        if not os.path.exists(fallback_file_path):
            fallback_file_path = "fallbacks.json"
            
        with open(fallback_file_path, encoding="utf-8") as f:
            FALLBACKS.update(json.load(f))
    except Exception as e:
        logger.error(f"Ошибка загрузки fallbacks.json: {e}")


def save_file_ids():
    with open(FILE_IDS_PATH, "w") as f:
        json.dump(FILE_IDS, f)


def save_users():
    with open(USERS_PATH, "w") as f:
        json.dump(USERS, f)


def save_banned():
    with open(BANNED_PATH, "w") as f:
        json.dump(BANNED, f)


load_data()

# --- Локализация ---
LOCALES = {
    "ru": {
        "start": "Привет, {name}!\n\nДобро пожаловать! Выбери нужный раздел:",
        "choose_lang": "Выбери язык / Абяры мову / Choose language:",
        "lang_changed": "Язык изменён на Русский",
        "btn_mods": "Моды",
        "btn_fun": "Приколы",
        "btn_help": "Помощь",
        "btn_feedback": "Обратная связь",
        "btn_suggest": "Предложить мод",
        "btn_dev": "В разработке",
        "btn_donate": "Поддержать",
        "btn_bug": "Сообщить об ошибке",
        "btn_question": "Задать вопрос",
        "btn_misc": "Разное",
        "btn_lang": "Язык",
        "btn_profile": "Профиль",
        "btn_back": "Назад",
        "btn_invite": "Пригласить друга",
        "main_menu": "Главное меню",
        "feedback_menu": "<b>Обратная связь</b>\n\nВыбери действие:",
        "mods_menu": "<b>Моды</b>\n\nВыбери мод:",
        "subscribe_needed": "Чтобы скачать этот мод, пожалуйста, подпишись на наш канал!",
        "btn_subscribe": "Подписаться на канал",
        "version": "Версия мода: {ver}",
        "btn_info": "Описание мода",
        "cancel": "Отменено, возвращаюсь в главное меню",
        "nothing_cancel": "Нечего отменять",
        "profile_title": "<b>Профиль</b>",
        "profile_id": "Твой ID: <code>{uid}</code>",
        "profile_rank": "Звание: <b>{rank}</b>",
        "profile_xp": "Опыт: {xp} XP",
        "profile_next": "До следующего звания: {xp_left} XP (и {ideas_left} идей)",
        "profile_next_manual": "Следующее звание выдаётся вручную",
        "profile_stats": "<b>Статистика</b>\nСкачано модов: {downloads}\nПредложено идей: {ideas}\nЗадано вопросов: {questions}\nПолучено банов: {bans}",
        "profile_achievements": "<b>Достижения</b>\n{list}",
        "profile_no_achievements": "Пока нет достижений",
        "rank_up": "Поздравляю! Ты получил новое звание: <b>{rank}</b>",
        "rank_given": "Тебе выдано новое звание: <b>{rank}</b>",
        "ach_unlocked": "Получено достижение: <b>{ach}</b>",
        "fun_prompt": "Кидай свой игровой прикол сюда!\n\nЭто может быть:\n• Забавный момент из боя\n• Необычная ситуация с физикой игры\n• Смешной баг или совпадение\n• Любой другой забавный случай из игры\n\nОтправляй хоть видео, хоть фото, хоть текст\nДля отмены напиши /cancel",
        "fun_thanks": "Спасибо! Твой прикол принят, когда его проверят модераторы, он попадёт в наш канал",
        "suggest_prompt": "<b>Предложить идею для мода</b>\n\nНапиши описание мода и как что работает, фото/видео/голосовые/видеосообщения не принимаются\nОно будет переслано администратору\n\nДля отмены напиши /cancel",
        "suggest_thanks": "Твоя идея отправлена на рассмотрение! Спасибо!",
        "bug_prompt": "Опиши ошибку в моде\nНапиши название мода и что именно не так, всё будет передано парням из дружного коллектива MOD_rak.rar\nДля отмены напиши /cancel",
        "bug_voice": "Напиши подробности текстом и по возможности фото или видео, голосовые и пустые сообщения не принимаются",
        "bug_thanks": "Спасибо, сообщение об ошибке передано разработчикам, постараемся исправить в ближайшее время",
        "question_prompt": "Задай свой вопрос, и мы ответим тебе прямо здесь!\nНапиши свой вопрос или опиши проблему\nДля отмены напиши /cancel",
        "question_thanks": "Твой вопрос отправлен! Ожидай ответа здесь",
        "question_no_group": "Ошибка: группа для заявок не настроена",
        "dev_text": "Сейчас в разработке:\n\n• Мод на старое окно шансов\n• Старое окно выбора режима\n• Старое окно ТТХ танка \n\nИ всё из этого может и не выйти\nДанный список, это набросок планируемых модов Что-то выйдет, что-то нет",
        "donate_text": "Поддержать разработку модов\n\n• Расскажи о нашем канале и боте друзьям\n• Предложи идею для нового мода\n",
        "misc_menu": "<b>Разное</b>\n\nВыбери интересующий вопрос:",
        "misc_team_btn": "О команде MOD_rak.rar",
        "misc_join_btn": "Можно ли присоединиться к вам",
        "misc_share_btn": "Поделиться ботом",
        "misc_team_text": "<b>О команде</b>\n\nМы парни-мододелы\nМы те, кто могут отстоять точку зрения\nА наша точка зрения это старый вид игры\nИ мы не собираемся от неё отступать",
        "help_menu": "<b>Помощь</b>\n\nВыбери вопрос:",
        "help_install_btn": "Как установить мод",
        "help_remove_btn": "Как удалить мод",
        "help_why_btn": "Зачем нужны данные модификации",
        "help_time_btn": "Сколько разрабатываются моды",
        "help_why_old_btn": "Почему моды только на возвращение старого в игру",
        "help_install_text": "Как установить мод:\n\nШаг 1: Скачать мод с официального сайта For Blitz или в нашем боте\nШаг 1.1: Установки модов на телефон нету, если нужно, то используйте инструкцию/приложения от For Blitz\nОбрати внимание, моды в этом боте только на ПК\nШаг 2: Распаковать архив или просто зайти в него\nШаг 3: Скопировать папку Data\nШаг 4: Зайти в папку игры: C:\\Games\\Tanks Blitz\nШаг 5: Нажать вставить скопированную папку Data с заменой",
        "help_remove_text": "Как удалить мод:\n\nСамый простой способ, нажать в приложении LGC восстановление игры",
        "help_why_text": "Зачем нужны данные модификации:\n\nМоды возвращают удалённые функции и интерфейс, к которым привыкли игроки Это делает игру комфортнее и привычнее для тех, кто играл раньше",
        "help_time_text": "Сколько разрабатываются моды:\n\nВремя разработки зависит от размера мода, сложности, свободного времени у мододелов, а также от того, насколько часто бывают бухие сервера у картошки",
        "help_why_old_text": "Почему модификации только на возвращение старого в игру:\n\nНостальгия у всей команды по старой игре",
        "old_ui_info_text": "Данный мод возвращает:\n• Старую кнопку выбора режима\n• Старый UI хранилища\n• Старую кнопку магазина\n• Старую левую панель\n• Старую кнопку «Тренироваться»\n• Старую кнопку «В Бой»\n• Убраны новые чёрные точки на фоне кнопок боя/выбора режима/взвода\n• Старые иконки для режимов\n• Старые иконки победы/поражения/ничьи во вкладке уведомлений\n• Старые звуки при нажатии кнопок/иконок в ангаре\n• Старые кнопки (зелёные, красные)\n• Старый UI дерева исследования\n• Старый UI окна уведомлений\n• Всякие мелочи",
        "unknown_media_text": "Эт что? Я понимаю только текст и кнопки Выбери нужный раздел на клавиатуре ниже",
        "unavailable_text": "Временно недоступно",
        "break_hard_text": "Хватит меня ломать, я и так еле держусь 🤖",
        "break_soft_text": "Не сломаешь, я крепкий",
        "banned_text": "Ты был забанен {count} раз",
        "no_rights": "У тебя нет прав для этого действия",
        "ban_usage": "Использование: /ban <user_id> <дд.мм.гггг> <чч:мм:сс> [причина]\nИли: /ban <user_id> never [причина]\nИли ответьте на сообщение пользователя: /ban [причина]",
        "unban_usage": "Использование: /unban <user_id> или ответьте на сообщение пользователя",
        "ban_cant_admin": "Нельзя забанить администратора",
        "ban_done": "Пользователь {uid} забанен до {until}. Причина: {reason}",
        "ban_done_forever": "Пользователь {uid} забанен навсегда. Причина: {reason}",
        "unban_done": "Пользователь {uid} разбанен",
        "unban_reply_success": "Пользователь {uid} успешно разбанен",
        "unban_not_found": "Этот пользователь не в бане",
        "banlist_empty": "Список банов пуст",
        "banlist_title": "Забаненные:",
        "ban_notify": "Ты был забанен\nПричина: {reason}\nСрок: до {until}",
        "ban_notify_forever": "Ты был забанен\nПричина: {reason}\nСрок: навсегда",
        "setrank_usage": "Использование: /setrank <user_id> <rank_id>",
        "setrank_bad_id": "Неверный формат ID",
        "setrank_no_rank": "Такого звания нет",
        "setrank_done": "Пользователю {uid} выдано звание: {rank}",
        "setrank_notify_fail": "Не удалось отправить уведомление: {err}",
        "banned_bot_text": "Вы забанены в этом боте\nВы будете разбанены либо при решении администратора, либо когда истекет срок бана\nПосмотреть свой срок бана: /mystatus",
        "ban_invalid_date": "Неверный формат даты. Используй: <дд.мм.гггг> <чч:мм:сс> или никогда (never)",
        "ban_past": "Указанное время уже прошло",
        "mystatus_no_ban": "Вы не забанены",
        "mystatus_title": "Ваш бан:",
        "mystatus_until": "Срок бана: до {until}",
        "mystatus_until_forever": "Срок бана: навсегда",
        "mystatus_reason": "Причина: {reason}",
        "staff_empty": "Команда пока пуста",
        "staff_title": "<b>Состав команды:</b>",
        "invite_text": "Пригласи друга в нашего бота и получи +150 XP!\n\nТвоя ссылка:\n{link}\n\nЗа каждого друга, который зайдет, вы оба получите опыт",
        "ref_bonus": "Твой друг зашел по твоей ссылке! Ты получил +150 XP",
        "ref_welcome": "Добро пожаловать по приглашению! Ты и твой друг получили +150 XP",
        "apply_team_btn": "Подать заявку в команду",
        "apply_team_text": "<b>Анкета в команду MOD_rak.rar</b>\n\n⚠️ <b>Примечание:</b> Набор в команду закрыт. Мы не принимаем всех подряд. Нам нужны люди с нужным настроением, опытом и свободным временем. Заполнение анкеты не гарантирует вступление, но мы рассмотрим её, когда откроется набор.\n\nПожалуйста, ответь на все вопросы одним сообщением (или несколькими, но подряд):\n\n1. Твой возраст и часовой пояс?\n2. Есть ли опыт в создании модов (каких игр, какие моды)?\n3. Какие инструменты и софт ты знаешь (Python, Blender, редакторы текстур, 3D-редакторы)?\n4. Сколько времени в день/неделю ты готов уделять проекту?\n5. Почему ты хочешь в команду именно MOD_rak.rar?\n6. Твоя любимая фича старого Танкс Блитц?\n7. Ссылка на твои прошлые работы (если есть)?\n8. Что ты хочешь делать в команде (кодить, рисовать, тестировать, модерировать)?\n\nОтправь ответ одним сообщением. Для отмены напиши /cancel",
        "apply_team_thanks": "Твоя анкета отправлена на рассмотрение! Мы свяжемся с тобой, если ты нам подойдешь.",
        "bug_report_fixed": "Твой баг-репорт исправлен! Спасибо за помощь, ты получил +50 XP.",
        "btn_report_fixed": "✅ Исправлено",
        "appeal_btn": "Подать заявку на разбан",
        "appeal_usage": "Отправь причину, по которой ты хочешь, чтобы тебя разбанили.",
        "appeal_sent": "Твоя заявка на разбан отправлена администраторам.",
        "appeal_already": "Ты уже подал заявку на разбан. Ожидай ответа.",
        "appeal_accept": "Твоя заявка на разбан одобрена! Ты разбанен.",
        "appeal_reject": "Твоя заявка на разбан отклонена.",
        "battle_desc": "⚔️ <b>Танковые бои</b>\n\nЗдесь ты можешь сразиться с другими игроками!\n\n<b>Правила:</b>\n1. Выбираешь формат (или бой с ботом).\n2. Создаешь комнату (или входишь по коду).\n3. Бот выдает каждому случайный танк и HP.\n4. Нажимаешь «Выстрел» и наносишь урон случайному врагу.\n5. Кто последний остался жив — забирает 25-50 XP.\n\n<b>Важно:</b> Ты не знаешь, какой танк у противника, пока не начнется бой!",
        "battle_choose": "Выбери действие:",
        "battle_bot": "🤖 Бой с ботом",
        "battle_create": "Создать комнату",
        "battle_join": "Войти по коду",
        "battle_list": "Список открытых комнат",
        "battle_back": "Назад",
    },
    "be": {
        "start": "Прывітанне, {name}!\n\nСардэчна запрашаем! Абяры патрэбны раздзел:",
        "choose_lang": "Выбяры мову / Choose language:",
        "lang_changed": "Мова зменена на Беларускую",
        "btn_mods": "Моды", "btn_fun": "Прыколы", "btn_help": "Дапамога", "btn_suggest": "Прапанаваць мод",
        "btn_feedback": "Зваротная сувязь", "btn_dev": "У распрацоўцы", "btn_donate": "Падтрымаць", "btn_bug": "Паведаміць пра памылку",
        "btn_question": "Задаць пытанне", "btn_misc": "Рознае", "btn_lang": "Мова", "btn_profile": "Профіль", "btn_back": "Назад", "btn_invite": "Запрасіць сябра",
        "main_menu": "Галоўнае меню",
        "feedback_menu": "<b>Зваротная сувязь</b>\n\nАбяры дзеянне:",
        "mods_menu": "<b>Моды</b>\n\nАбяры мод:", "subscribe_needed": "Каб спампаваць гэты мод, калі ласка, падпішыся на наш канал!",
        "btn_subscribe": "Падпісацца на канал", "version": "Версія мода: {ver}", "btn_info": "Апісанне мода",
        "cancel": "Адменена, вяртаюся ў галоўнае меню", "nothing_cancel": "Няма чаго адмяняць",
        "profile_title": "<b>Профіль</b>", "profile_id": "Твой ID: <code>{uid}</code>", "profile_rank": "Званне: <b>{rank}</b>", "profile_xp": "Вопыт: {xp} XP",
        "profile_next": "Да наступнага звання: {xp_left} XP (і {ideas_left} ідэй)",
        "profile_next_manual": "Наступнае званне выдаецца ўручную",
        "profile_stats": "<b>Статыстыка</b>\nСпампавана модаў: {downloads}\nПрапанавана ідэй: {ideas}\nЗададзена пытанняў: {questions}\nАтрымана банаў: {bans}",
        "profile_achievements": "<b>Дасягненні</b>\n{list}", "profile_no_achievements": "Пакуль няма дасягненняў",
        "rank_up": "Віншую! Ты атрымаў новае званне: <b>{rank}</b>", "rank_given": "Табе выдадзена новае званне: <b>{rank}</b>", "ach_unlocked": "Атрымана дасягненне: <b>{ach}</b>",
        "fun_prompt": "Кідай свой гульнявы прыкол сюды!\n\nГэта можа быць:\n• Забаўны момант з бою\n• Незвычайная сітуацыя з фізікай гульні\n• Смешны баг ці супадзенне\n\nДля адмены напішы /cancel",
        "fun_thanks": "Дзякуй! Твой гульнявы прыкол прыняты",
        "suggest_prompt": "<b>Прапанаваць ідэю для мода</b>\n\nНапішы апісанне мода і як што працуе\nДля адмены напішы /cancel",
        "suggest_thanks": "Твая ідэя адпраўлена на разгляд! Дзякуй!",
        "bug_prompt": "Апішы памылку ў модзе\nДля адмены напішы /cancel",
        "bug_voice": "Напішы падрабязнасці тэкстам, галасавыя паведамленні не прымаюцца",
        "bug_thanks": "Дзякуй, паведамленне пра памылку перададзена распрацоўшчыкам",
        "question_prompt": "Задай сваё пытанне, і мы адкажам табе прама тут!\nДля адмены напішы /cancel",
        "question_thanks": "Тваё пытанне адпраўлена! Чакай адказу тут",
        "question_no_group": "Памылка: група для заявак не наладжана",
        "dev_text": "Зараз у распрацоўцы:\n\n• Мод на старое акно шанцаў\n• Старое акно выбару рэжыму\n• Старое акно ТТХ танка \n\nІ ўсё з гэтага можа і не выйсці",
        "donate_text": "Падтрымаць распрацоўку модаў\n\n• Раскажы пра наш канал і бота сябрам\n• Прапануй ідэю для новага мода\n",
        "misc_menu": "<b>Рознае</b>\n\nАбяры пытанне:",
        "misc_team_btn": "Пра каманду MOD_rak.rar",
        "misc_join_btn": "Ці можна далучыцца да вас",
        "misc_share_btn": "Падзяліцца ботам",
        "misc_team_text": "<b>Пра каманду</b>\n\nМы хлопцы-модадзелы\nМы тыя, хто могуць адстаяць пункт гледжання\nА наш пункт гледжання гэта стары выгляд гульні",
        "help_menu": "<b>Дапамога</b>\n\nАбяры пытанне:",
        "help_install_btn": "Як усталяваць мод", "help_remove_btn": "Як выдаліць мод", "help_why_btn": "Навошта патрэбныя гэтыя мадыфікацыі",
        "help_time_btn": "Колькі распрацоўваюцца моды", "help_why_old_btn": "Чаму моды толькі на вяртанне старога",
        "help_install_text": "Як усталяваць мод:\n\nКрок 1: Спампаваць мод\nКрок 2: Распакаваць архіў\nКрок 3: Скапіяваць папку Data\nКрок 4: Зайсці ў папку гульні: C:\\Games\\Tanks Blitz\nКрок 5: Уставіць з заменай",
        "help_remove_text": "Як выдаліць мод:\n\nСамы просты спосаб, націснуць у праграме LGC аднаўленне гульні",
        "help_why_text": "Навошта патрэбныя гэтыя мадыфікацыі:\n\nМоды вяртаюць выдаленыя функцыі і інтэрфейс, да якіх звыкліся гульцы",
        "help_time_text": "Колькі распрацоўваюцца моды:\n\nЧас распрацоўкі залежыць ад памеру мода, складанасці і вольнага часу",
        "help_why_old_text": "Чаму мадыфікацыі толькі на вяртанне старога:\n\nНастальгія ўсёй каманды па старой гульні",
        "old_ui_info_text": "Гэты мод вяртае:\n• Старую кнопку выбару рэжыму\n• Стары UI сховішча\n• Старую кнопку крамы\n• Старую левую панэль\n• Старую кнопку «Трэніравацца»\n• Старую кнопку «У Бой»\n• Прыбраныя новыя чорныя кропкі на фоне кнопак бою/выбару рэжыму/узвода\n• Старыя іконкі для рэжымаў\n• Старыя іконкі перамогі/паражэння/нічыі ў закладцы апавяшчэнняў\n• Старыя гукі пры націску кнопак/іконак у ангары\n• Старыя кнопкі (зялёныя, чырвоныя)\n• Стары UI дрэва даследавання\n• Стары UI акна апавяшчэнняў\n• Розныя дробязі",
        "unknown_media_text": "Гэта што? Я разумею толькі тэкст і кнопкі Абяры патрэбны раздзел на клавіятуры ніжэй",
        "unavailable_text": "Часова недаступна",
        "break_hard_text": "Хопіць мяне ламаць, я і так ледзь трымаюся 🤖",
        "break_soft_text": "Не зламаеш, я моцны",
        "no_rights": "У цябе няма правоў для гэтага дзеяння",
        "ban_usage": "Выкарыстанне: /ban <user_id> <дд.мм.гггг> <чч:мм:сс> [прычына]\nАбо: /ban <user_id> never [прычына]\nАбо адкажыце на паведамленне: /ban [прычына]",
        "unban_usage": "Выкарыстанне: /unban <user_id> або адкажыце на паведамленне карыстальніка",
        "ban_cant_admin": "Нельга забаніць адміністратара",
        "ban_done": "Карыстальнік {uid} забанены да {until}. Прычына: {reason}",
        "ban_done_forever": "Карыстальнік {uid} забанены назаўжды. Прычына: {reason}",
        "unban_done": "Карыстальнік {uid} разбанены",
        "unban_reply_success": "Карыстальнік {uid} паспяхова разбанены",
        "unban_not_found": "Гэты карыстальнік не ў бане",
        "banlist_empty": "Спіс банаў пусты",
        "banlist_title": "Забаненыя:",
        "ban_notify": "Ты быў забанены\nПрычына: {reason}\nТэрмін: да {until}",
        "ban_notify_forever": "Ты быў забанены\nПрычына: {reason}\nТэрмін: назаўжды",
        "setrank_usage": "Выкарыстанне: /setrank <user_id> <rank_id>",
        "setrank_bad_id": "Няверны фармат ID",
        "setrank_no_rank": "Такога звання няма",
        "setrank_done": "Карыстальніку {uid} выдадзена званне: {rank}",
        "setrank_notify_fail": "Не ўдалося адправіць апавяшчэнне: {err}",
        "banned_bot_text": "Вы забанены ў гэтым боце\nВы будзеце разбаненыя альбо па рашэнні адміністратара, альбо калі скончыцца тэрмін бану\nПаглядзець свой тэрмін бану: /mystatus",
        "ban_invalid_date": "Няверны фармат даты. Выкарыстоўвай: <дд.мм.гггг> <чч:мм:сс> або never",
        "ban_past": "Паказаны час ужо прайшоў",
        "mystatus_no_ban": "Вы не забанены",
        "mystatus_title": "Ваш бан:",
        "mystatus_until": "Тэрмін бану: да {until}",
        "mystatus_until_forever": "Тэрмін бану: назаўжды",
        "mystatus_reason": "Прычына: {reason}",
        "staff_empty": "Каманда пакуль пустая",
        "staff_title": "<b>Склад каманды:</b>",
        "invite_text": "Запрасі сябра ў нашага бота і атрымай +150 XP!\n\nТвая спасылка:\n{link}\n\nЗа кожнага сябра, які зайдзе, вы абодва атрымаеце вопыт",
        "ref_bonus": "Твой сябар зайшоў па тваёй спасылцы! Ты атрымаў +150 XP",
        "ref_welcome": "Сардэчна запрашаем па запрашэнні! Ты і твой сябар атрымалі +150 XP",
        "apply_team_btn": "Падаць заяўку ў каманду",
        "apply_team_text": "<b>Анкета ў каманду MOD_rak.rar</b>\n\n⚠️ <b>Заўвага:</b> Набор у каманду закрыты. Мы не прымаем усіх запар. Нам патрэбныя людзі з патрэбным настроем, вопытам і вольным часам. Запаўненне анкеты не гарантуе ўступ, але мы разгледзім яе, калі адкрыецца набор.\n\nКалі ласка, адкажы на ўсе пытанні адным паведамленнем:\n\n1. Твой узрост і часавы пояс?\n2. Ці ёсць вопыт у стварэнні модаў?\n3. Якія інструменты ты ведаеш?\n4. Колькі часу ты гатовы ўдзяляць праекту?\n5. Чаму ты хочаш у MOD_rak.rar?\n6. Твая любімая фіча старога Танкс Бліц?\n7. Спасылка на твае мінулыя працы?\n8. Што ты хочаш рабіць у камандзе?\n\nАдпраў адказ адным паведамленнем. Для адмены напішы /cancel",
        "apply_team_thanks": "Твая анкета адпраўлена на разгляд! Мы звяжамся з табой, калі ты нам падыдзеш.",
        "bug_report_fixed": "Твой баг-рэпарт выпраўлены! Дзякуй за дапамогу, ты атрымаў +50 XP.",
        "btn_report_fixed": "✅ Выпраўлена",
        "appeal_btn": "Падаць заяўку на разбан",
        "appeal_usage": "Адпраў прычыну, па якой ты хочаш, каб цябе разбанілі.",
        "appeal_sent": "Твая заяўка на разбан адпраўлена адміністратарам.",
        "appeal_already": "Ты ўжо падаў заяўку на разбан. Чакай адказу.",
        "appeal_accept": "Твая заяўка на разбан ухвалена! Ты разбанены.",
        "appeal_reject": "Твая заяўка на разбан адхілена.",
        "battle_desc": "⚔️ <b>Танкавыя баі</b>\n\nТут ты можаш змагацца з іншымі гульцамі!\n\n<b>Правілы:</b>\n1. Выбіраеш фармат (або бой з ботам).\n2. Ствараеш пакой (або ўваходзіш па кодзе).\n3. Бот выдае кожнаму выпадковы танк і HP.\n4. Націскаеш «Стрэл» і наносіш урон выпадковаму ворагу.\n5. Хто апошні застаўся жывы — забірае 25-50 XP.\n\n<b>Важна:</b> Ты не ведаеш, які танк у суперніка!",
        "battle_choose": "Абяры дзеянне:",
        "battle_bot": "🤖 Бой з ботам",
        "battle_create": "Стварыць пакой",
        "battle_join": "Увайсці па кодзе",
        "battle_list": "Спіс адкрытых пакояў",
        "battle_back": "Назад",
    },
    "en": {
        "start": "Hello, {name}!\n\nWelcome! Choose a section:",
        "choose_lang": "Choose language:",
        "lang_changed": "Language changed to English",
        "btn_mods": "Mods", "btn_fun": "Fun", "btn_help": "Help", "btn_suggest": "Suggest a mod",
        "btn_feedback": "Feedback", "btn_dev": "In development", "btn_donate": "Support", "btn_bug": "Report a bug",
        "btn_question": "Ask a question", "btn_misc": "Misc", "btn_lang": "Language", "btn_profile": "Profile", "btn_back": "Back", "btn_invite": "Invite a friend",
        "main_menu": "Main menu",
        "feedback_menu": "<b>Feedback</b>\n\nChoose an action:",
        "mods_menu": "<b>Mods</b>\n\nChoose a mod:", "subscribe_needed": "To download this mod, please subscribe to our channel!",
        "btn_subscribe": "Subscribe to channel", "version": "Mod version: {ver}", "btn_info": "Mod description",
        "cancel": "Cancelled, returning to main menu", "nothing_cancel": "Nothing to cancel",
        "profile_title": "<b>Profile</b>", "profile_id": "Your ID: <code>{uid}</code>", "profile_rank": "Rank: <b>{rank}</b>", "profile_xp": "XP: {xp}",
        "profile_next": "To next rank: {xp_left} XP (and {ideas_left} ideas)",
        "profile_next_manual": "Next rank is given manually",
        "profile_stats": "<b>Stats</b>\nMods downloaded: {downloads}\nIdeas suggested: {ideas}\nQuestions asked: {questions}\nBans received: {bans}",
        "profile_achievements": "<b>Achievements</b>\n{list}", "profile_no_achievements": "No achievements yet",
        "rank_up": "Congratulations! You reached a new rank: <b>{rank}</b>", "rank_given": "You were given a new rank: <b>{rank}</b>", "ach_unlocked": "Achievement unlocked: <b>{ach}</b>",
        "fun_prompt": "Send your funny gaming moment here!\n\nIt could be:\n• A funny moment from battle\n• An unusual physics situation\n• A funny bug or coincidence\n\nTo cancel, type /cancel",
        "fun_thanks": "Thanks! Your funny moment is accepted",
        "suggest_prompt": "<b>Suggest a mod idea</b>\n\nWrite a description of the mod and how it works\nTo cancel, type /cancel",
        "suggest_thanks": "Your idea has been sent for review! Thanks!",
        "bug_prompt": "Describe the bug in the mod\nTo cancel, type /cancel",
        "bug_voice": "Write details in text, voice messages are not accepted",
        "bug_thanks": "Thanks, the bug report has been sent to the developers",
        "question_prompt": "Ask your question, and we will answer you right here!\nTo cancel, type /cancel",
        "question_thanks": "Your question has been sent! Wait for an answer here",
        "question_no_group": "Error: support group is not configured",
        "dev_text": "Currently in development:\n\n• Old chances window mod\n• Old mode selection window\n• Old tank characteristics window\n\nAnd all of this might not even be released",
        "donate_text": "Support mod development\n\n• Tell your friends about our channel and bot\n• Suggest an idea for a new mod\n",
        "misc_menu": "<b>Misc</b>\n\nChoose a question:",
        "misc_team_btn": "About MOD_rak.rar team", "misc_join_btn": "Can I join you?", "misc_share_btn": "Share the bot",
        "misc_team_text": "<b>About the team</b>\n\nWe are modders\nWe are the ones who can defend a point of view\nAnd our point of view is the old look of the game",
        "help_menu": "<b>Help</b>\n\nChoose a question:",
        "help_install_btn": "How to install a mod", "help_remove_btn": "How to remove a mod", "help_why_btn": "Why are modifications needed",
        "help_time_btn": "How long mods take to develop", "help_why_old_btn": "Why mods only bring back old features",
        "help_install_text": "How to install a mod:\n\nStep 1: Download the mod\nStep 2: Unzip the archive\nStep 3: Copy the Data folder\nStep 4: Go to the game folder: C:\\Games\\Tanks Blitz\nStep 5: Paste and replace",
        "help_remove_text": "How to remove a mod:\n\nEasiest way is to press restore game in the LGC app",
        "help_why_text": "Why are modifications needed:\n\nMods bring back deleted features and interfaces that players are used to",
        "help_time_text": "How long mods take to develop:\n\nDevelopment time depends on the mod size, complexity, and free time",
        "help_why_old_text": "Why mods only bring back old features:\n\nNostalgia of the whole team for the old game",
        "old_ui_info_text": "This mod brings back:\n• Old mode selection button\n• Old storage UI\n• Old shop button\n• Old left panel\n• Old 'Train' button\n• Old 'To Battle' button\n• Removed new black dots on the background of battle/mode selection/platoon buttons\n• Old icons for modes\n• Old victory/defeat/draw icons in the notifications tab\n• Old sounds when pressing buttons/icons in the hangar\n• Old buttons (green, red)\n• Old research tree UI\n• Old notifications window UI\n• Various small things",
        "unknown_media_text": "What is this? I only understand text and buttons Choose a section on the keyboard below",
        "unavailable_text": "Temporarily unavailable",
        "break_hard_text": "Stop breaking me, I'm barely holding on as it is 🤖",
        "break_soft_text": "You won't break me, I'm tough",
        "no_rights": "You have no rights for this action",
        "ban_usage": "Usage: /ban <user_id> <dd.mm.yyyy> <hh:mm:ss> [reason]\nOr: /ban <user_id> never [reason]\nOr reply to user's message: /ban [reason]",
        "unban_usage": "Usage: /unban <user_id> or reply to user's message",
        "ban_cant_admin": "Cannot ban an administrator",
        "ban_done": "User {uid} banned until {until}. Reason: {reason}",
        "ban_done_forever": "User {uid} banned forever. Reason: {reason}",
        "unban_done": "User {uid} unbanned",
        "unban_reply_success": "User {uid} successfully unbanned",
        "unban_not_found": "This user is not banned",
        "banlist_empty": "Ban list is empty",
        "banlist_title": "Banned users:",
        "ban_notify": "You were banned\nReason: {reason}\nTerm: until {until}",
        "ban_notify_forever": "You were banned\nReason: {reason}\nTerm: forever",
        "setrank_usage": "Usage: /setrank <user_id> <rank_id>",
        "setrank_bad_id": "Invalid ID format",
        "setrank_no_rank": "No such rank",
        "setrank_done": "User {uid} given rank: {rank}",
        "setrank_notify_fail": "Failed to send notification: {err}",
        "banned_bot_text": "You are banned in this bot\nYou will be unbanned either by administrator decision or when the ban expires\nCheck your ban term: /mystatus",
        "ban_invalid_date": "Invalid date format. Use: <dd.mm.yyyy> <hh:mm:ss> or never",
        "ban_past": "The specified time has already passed",
        "mystatus_no_ban": "You are not banned",
        "mystatus_title": "Your ban:",
        "mystatus_until": "Ban term: until {until}",
        "mystatus_until_forever": "Ban term: forever",
        "mystatus_reason": "Reason: {reason}",
        "staff_empty": "Team is empty",
        "staff_title": "<b>Team list:</b>",
        "invite_text": "Invite a friend to our bot and get +150 XP!\n\nYour link:\n{link}\n\nFor each friend who joins, both of you get XP",
        "ref_bonus": "Your friend joined using your link! You received +150 XP",
        "ref_welcome": "Welcome by invitation! You and your friend received +150 XP",
        "apply_team_btn": "Apply to the team",
        "apply_team_text": "<b>Application to MOD_rak.rar team</b>\n\n⚠️ <b>Note:</b> Recruitment is closed. We don't accept just anyone. We need people with the right mindset, experience and free time. Filling out this form does not guarantee acceptance, but we will review it when recruitment opens.\n\nPlease answer all questions in one message:\n\n1. Your age and time zone?\n2. Do you have modding experience?\n3. What tools and software do you know?\n4. How much time can you dedicate?\n5. Why do you want to join MOD_rak.rar?\n6. Your favorite old Tanks Blitz feature?\n7. Link to your past works?\n8. What do you want to do in the team?\n\nSend your answer in one message. To cancel, type /cancel",
        "apply_team_thanks": "Your application has been sent for review! We will contact you if you fit.",
        "bug_report_fixed": "Your bug report has been fixed! Thanks for helping, you received +50 XP.",
        "btn_report_fixed": "✅ Fixed",
        "appeal_btn": "Submit an appeal",
        "appeal_usage": "Send the reason why you want to be unbanned.",
        "appeal_sent": "Your appeal has been sent to the administrators.",
        "appeal_already": "You have already submitted an appeal. Wait for a response.",
        "appeal_accept": "Your appeal has been approved! You are unbanned.",
        "appeal_reject": "Your appeal has been rejected.",
        "battle_desc": "⚔️ <b>Tank Battles</b>\n\nHere you can fight other players!\n\n<b>Rules:</b>\n1. Choose format (or fight a bot).\n2. Create a room (or join by code).\n3. Bot gives each player a random tank and HP.\n4. Press 'Shoot' to deal damage to a random enemy.\n5. Last one standing gets 25-50 XP.\n\n<b>Important:</b> You don't know the enemy's tank until battle starts!",
        "battle_choose": "Choose an action:",
        "battle_bot": "🤖 Fight with bot",
        "battle_create": "Create a room",
        "battle_join": "Join by code",
        "battle_list": "List of open rooms",
        "battle_back": "Back",
    }
}

def tr(user_id: str, key: str, **kwargs) -> str:
    data = USERS.get(user_id)
    lang = data["lang"] if data and data.get("lang") else "ru"
    text = LOCALES.get(lang, LOCALES["ru"]).get(key, f"[{key}]")
    return text.format(**kwargs) if kwargs else text


# --- Проверка бана ---
def is_banned(user_id: str) -> tuple[bool, dict]:
    if user_id not in BANNED:
        return False, {}
    info = BANNED[user_id]
    until_str = info.get("until", "")
    if until_str == "never":
        return True, info
    try:
        until = datetime.strptime(until_str, "%Y-%m-%d %H:%M:%S")
    except (KeyError, ValueError):
        return False, {}
    if datetime.now() >= until:
        del BANNED[user_id]
        save_banned()
        return False, {}
    return True, info


async def check_ban_and_block(message: Message) -> bool:
    uid = str(message.from_user.id)
    banned, info = is_banned(uid)
    if banned:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=tr(uid, "appeal_btn"), callback_data="appeal_ban")]
        ])
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
    lang = USERS.get(user_id, {}).get("lang", "ru")
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{MOD_NAMES['old_font'][lang]} (v1.0)", callback_data="mod_old_font")],
        [InlineKeyboardButton(text=f"{MOD_NAMES['old_medals'][lang]} (v1.0)", callback_data="mod_old_medals")],
        [InlineKeyboardButton(text=f"{MOD_NAMES['old_ui'][lang]} (v3.0)", callback_data="mod_old_ui")],
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
    awaiting_mod_suggestion = State()
    awaiting_fun = State()
    awaiting_bug_report = State()
    awaiting_question = State()
    awaiting_team_apply = State()
    awaiting_appeal = State()
    in_battle = State()

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


# --- ПРОФИЛЬ ---
@dp.message(Command("profile"))
async def cmd_profile(message: Message, state: FSMContext):
    if await check_ban_and_block(message):
        return
    await state.clear()
    uid = str(message.from_user.id)
    
    if uid not in USERS or not USERS[uid].get("lang"):
        await cmd_start(message, state)
        return

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
        f"{tr(uid, 'profile_id', uid=uid)}\n\n"
        f"{tr(uid, 'profile_rank', rank=rank_name)}\n"
        f"{tr(uid, 'profile_xp', xp=data['xp'])}\n"
        f"{progress_text}\n\n"
        f"{tr(uid, 'profile_stats', downloads=data['downloads'], ideas=data['ideas'], questions=data['questions'], bans=data['bans'])}\n\n"
        f"{ach_text}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚔️ Бои", callback_data="battle_menu")],
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


# --- ИГРА ---
@dp.callback_query(F.data == "battle_menu")
async def cb_battle_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear() # Очищаем возможный стейт PvE
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

@dp.callback_query(F.data == "back_to_profile")
async def cb_back_to_profile(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await cmd_profile(callback.message, state)

# --- PvE (Бой с ботом) ---
@dp.callback_query(F.data == "battle_vs_bot")
async def cb_battle_vs_bot(callback: CallbackQuery, state: FSMContext):
    uid = str(callback.from_user.id)
    await callback.answer()
    
    p_tank, p_hp = get_random_tank()
    e_tank, e_hp = get_random_tank()
    
    await state.set_state(UserState.in_battle)
    await state.update_data(
        is_pve=True,
        p_hp=p_hp, p_tank=p_tank,
        e_hp=e_hp, e_tank=e_tank
    )
    
    text = (
        f"🤖 <b>Бой против бота начался!</b>\n\n"
        f"Твой танк: <b>{p_tank}</b> (HP: {p_hp})\n"
        f"Танк врага: <b>Неизвестно</b> (HP: ???)\n\n"
        f"Твой ход!"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💥 Выстрел", callback_data="pve_shoot")],
        [InlineKeyboardButton(text="🏳️ Сдаться", callback_data="pve_surrender")]
    ])
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "pve_shoot", UserState.in_battle)
async def cb_pve_shoot(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    
    if not data.get("is_pve"):
        return
        
    p_hp = data["p_hp"]
    e_hp = data["e_hp"]
    p_tank = data["p_tank"]
    e_tank = data["e_tank"]
    
    # Игрок стреляет
    p_dmg = random.randint(150, 300)
    e_hp -= p_dmg
    
    text = f"💥 Ты попал по врагу на {p_dmg} урона!\n"
    
    if e_hp <= 0:
        # Победа
        uid = str(callback.from_user.id)
        xp_reward = random.randint(25, 50)
        add_xp(uid, xp_reward)
        text += f"\n💀 <b>Враг уничтожен!</b>\n🏆 Победа! Ты получил +{xp_reward} XP.\n\n👀 Танк врага был: <b>{e_tank}</b> (HP: {data['e_hp']})"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="В меню боев", callback_data="battle_menu")]
        ])
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        await state.clear()
        return
        
    # Бот стреляет в ответ
    e_dmg = random.randint(150, 300)
    p_hp -= e_dmg
    text += f"🔫 Враг стреляет в ответ на {e_dmg} урона!\n"
    
    if p_hp <= 0:
        # Поражение
        text += f"\n💀 <b>Ты уничтожен!</b>\nТанк врага был: <b>{e_tank}</b> (HP: {e_hp + p_dmg})."
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="В меню боев", callback_data="battle_menu")]
        ])
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        await state.clear()
        return
        
    await state.update_data(p_hp=p_hp, e_hp=e_hp)
    
    text += (
        f"\n❤️ Твое HP: <b>{p_hp}</b>\n"
        f"💀 HP врага: <b>{e_hp}</b>\n\n"
        f"Твой ход:"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💥 Выстрел", callback_data="pve_shoot")],
        [InlineKeyboardButton(text="🏳️ Сдаться", callback_data="pve_surrender")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "pve_surrender", UserState.in_battle)
async def cb_pve_surrender(callback: CallbackQuery, state: FSMContext):
    await callback.answer("Ты сдался")
    await state.clear()
    await callback.message.edit_text("🏳️ Ты сдался. Возвращайся, когда наберешься сил!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="В меню боев", callback_data="battle_menu")]
    ]))

# --- PvP (Комнаты) ---
@dp.callback_query(F.data == "create_room")
async def cb_create_room(callback: CallbackQuery, state: FSMContext):
    uid = str(callback.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 на 1", callback_data="create_2")],
        [InlineKeyboardButton(text="2 на 2", callback_data="create_4")],
        [InlineKeyboardButton(text="3 на 3", callback_data="create_6")],
        [InlineKeyboardButton(text="4 на 4", callback_data="create_8")]
    ])
    await state.set_state(BattleState.choosing_size)
    await callback.message.edit_text("Выбери формат боя:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(BattleState.choosing_size, F.data.startswith("create_"))
async def cb_create_size(callback: CallbackQuery, state: FSMContext):
    max_players = int(callback.data.replace("create_", ""))
    await state.clear()
    
    uid = str(callback.from_user.id)
    code = generate_room_code()
    
    ROOMS[code] = {
        "players": [uid],
        "max_players": max_players,
        "is_private": False,
        "status": "waiting",
        "hp": {},
        "tank": {}
    }
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Скрыть комнату", callback_data=f"hide_{code}")],
        [InlineKeyboardButton(text="Начать бой", callback_data=f"start_battle_{code}")],
        [InlineKeyboardButton(text="Выйти", callback_data=f"leave_{code}")]
    ])
    
    text = (
        f"🏠 Комната создана!\n\n"
        f"Код для входа: <code>{code}</code>\n"
        f"Формат: {max_players // 2} на {max_players // 2}\n"
        f"Игроков: 1/{max_players}\n\n"
        f"<i>Отправь код друзьям или нажми 'Начать бой', если играешь 1 на 1.</i>"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("hide_"))
async def cb_hide_room(callback: CallbackQuery):
    code = callback.data.replace("hide_", "")
    if code in ROOMS:
        ROOMS[code]["is_private"] = True
        await callback.message.edit_text(callback.message.text + "\n\n🔒 <i>Комната скрыта из общего списка.</i>", parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("leave_"))
async def cb_leave_room(callback: CallbackQuery, state: FSMContext):
    code = callback.data.replace("leave_", "")
    if code in ROOMS:
        del ROOMS[code]
    await callback.answer("Ты вышел из комнаты")
    await cb_back_to_profile(callback, state)

@dp.callback_query(F.data == "join_by_code")
async def cb_join_by_code(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BattleState.entering_code)
    await callback.message.edit_text("Введи код комнаты (4 символа):")
    await callback.answer()

@dp.message(BattleState.entering_code)
async def process_code(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    await state.clear()
    uid = str(message.from_user.id)
    
    if code not in ROOMS:
        await message.answer("❌ Комната с таким кодом не найдена.")
        return
        
    room = ROOMS[code]
    if room["status"] != "waiting":
        await message.answer("❌ Бой уже начался.")
        return
        
    if uid in room["players"]:
        await message.answer("Ты уже в этой комнате.")
        return
        
    if len(room["players"]) >= room["max_players"]:
        await message.answer("❌ Комната заполнена.")
        return
        
    room["players"].append(uid)
    
    if len(room["players"]) == room["max_players"]:
        await start_room_battle(code, message.chat.id)
    else:
        await message.answer(f"✅ Ты зашел в комнату {code}. Ждем остальных ({len(room['players'])}/{room['max_players']}).")

@dp.callback_query(F.data == "list_rooms")
async def cb_list_rooms(callback: CallbackQuery):
    open_rooms = {k: v for k, v in ROOMS.items() if v["status"] == "waiting" and not v["is_private"]}
    
    if not open_rooms:
        await callback.answer("Нет открытых комнат. Создай свою!", show_alert=True)
        return
        
    lines = ["<b>Открытые комнаты:</b>\n"]
    for code, room in open_rooms.items():
        lines.append(f"<code>{code}</code> | {len(room['players'])}/{room['max_players']}")
    
    lines.append("\n<i>Нажми на код в сообщении, чтобы скопировать, и введи его в 'Войти по коду'.</i>")
    await callback.message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Назад", callback_data="battle_menu")]
    ]))
    await callback.answer()

@dp.callback_query(F.data.startswith("start_battle_"))
async def cb_start_battle_manual(callback: CallbackQuery):
    code = callback.data.replace("start_battle_", "")
    if code not in ROOMS:
        await callback.answer("Комната не найдена")
        return
    
    room = ROOMS[code]
    if room["max_players"] == 2 and len(room["players"]) >= 1:
        await callback.message.edit_text("⚔️ Бой начинается...")
        await start_room_battle(code, callback.message.chat.id)
    else:
        await callback.answer("Ждем остальных игроков!", show_alert=True)

async def start_room_battle(code: str, chat_id: int):
    room = ROOMS[code]
    room["status"] = "battle"
    
    text = "⚔️ <b>Бой начался!</b>\n\n"
    for uid in room["players"]:
        tank, hp = get_random_tank()
        room["hp"][uid] = hp
        room["tank"][uid] = tank
        text += f"👤 <code>{uid}</code> — {tank} (HP: {hp})\n"
        
    text += "\n<i>Каждый игрок может выстрелить раз в 5 секунд. Наноси урон врагам!</i>"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💥 Выстрел", callback_data=f"shoot_{code}")]
    ])
    
    try:
        await bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=kb)
    except:
        pass

@dp.callback_query(F.data.startswith("shoot_"))
async def cb_shoot(callback: CallbackQuery):
    code = callback.data.replace("shoot_", "")
    uid = str(callback.from_user.id)
    
    if code not in ROOMS or ROOMS[code]["status"] != "battle":
        await callback.answer("Бой не найден или уже закончен.", show_alert=True)
        return
        
    room = ROOMS[code]
    if uid not in room["players"]:
        await callback.answer("Ты не участник этого боя.", show_alert=True)
        return
        
    enemies = [p for p in room["players"] if p != uid]
    if not enemies:
        await callback.answer("Нет врагов.", show_alert=True)
        return
        
    target = random.choice(enemies)
    damage = random.randint(100, 300)
    
    room["hp"][target] -= damage
    
    text = f"💥 <b>{room['tank'][uid]}</b> попал в <b>{room['tank'][target]}</b> на {damage} урона!\n"
    text += f"❤️ У {room['tank'][target]} осталось {max(0, room['hp'][target])} HP."
    
    if room["hp"][target] <= 0:
        text += f"\n\n💀 <b>{room['tank'][target]}</b> уничтожен!"
        room["players"].remove(target)
        
        if len(room["players"]) == 1:
            winner = room["players"][0]
            xp_reward = random.randint(25, 50)
            add_xp(winner, xp_reward)
            text += f"\n\n🏆 <b>Победитель: {room['tank'][winner]}!</b>\n💰 +{xp_reward} XP"
            
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="👀 Узнать противника", callback_data=f"reveal_{code}")]
            ])
            
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
            room["status"] = "finished"
            return
            
    await callback.message.edit_text(text, parse_mode="HTML")
    await callback.answer("Выстрел!")

@dp.callback_query(F.data.startswith("reveal_"))
async def cb_reveal(callback: CallbackQuery):
    code = callback.data.replace("reveal_", "")
    uid = str(callback.from_user.id)
    
    if code not in ROOMS:
        await callback.answer("Информация о бое утеряна.", show_alert=True)
        return
        
    room = ROOMS[code]
    text = "🔍 <b>Данные о бое:</b>\n\n"
    for player_uid, tank in room["tank"].items():
        hp = room["hp"].get(player_uid, 0)
        status = "выжил" if hp > 0 else "уничтожен"
        text += f"<code>{player_uid}</code> — {tank} (Осталось HP: {max(0, hp)}) — {status}\n"
        
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()
    
    if code in ROOMS:
        del ROOMS[code]


# --- АДМИН: ВЫДАЧА ЗВАНИЙ И СПИСОК КОМАНДЫ ---
@dp.message(Command("setrank"))
async def cmd_setrank(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    args = message.text.split()
    if len(args) < 3:
        await message.answer(tr(str(message.from_user.id), "setrank_usage"))
        return
    try:
        target_id = str(args[1])
        rank_id = int(args[2])
    except ValueError:
        await message.answer(tr(str(message.from_user.id), "setrank_bad_id"))
        return

    if rank_id not in RANKS:
        await message.answer(tr(str(message.from_user.id), "setrank_no_rank"))
        return

    if target_id not in USERS:
        USERS[target_id] = default_user_data()

    USERS[target_id]["rank_id"] = rank_id
    save_users()
    admin_uid = str(message.from_user.id)
    await message.answer(tr(admin_uid, "setrank_done", uid=target_id, rank=RANKS[rank_id][0]))

    try:
        await bot.send_message(
            int(target_id),
            tr(target_id, "rank_given", rank=RANKS[rank_id][0]),
            parse_mode="HTML"
        )
    except Exception as e:
        await message.answer(tr(admin_uid, "setrank_notify_fail", err=e))

@dp.message(Command("staff"))
async def cmd_staff(message: Message):
    uid_admin = str(message.from_user.id)
    rank_admin = USERS.get(uid_admin, {}).get("rank_id", 0)
    
    if message.from_user.id not in ADMIN_IDS and rank_admin < 19:
        await message.answer(tr(uid_admin, "no_rights"))
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
        rank_name = RANKS[rank_id][0]
        xp = data.get("xp", 0)
        ideas = data.get("ideas", 0)
        bans = data.get("bans", 0)
        text_lines.append(f"<b>{rank_name}</b> | ID: <code>{uid}</code>\n└ XP: {xp} | Идей: {ideas} | Банов: {bans}\n")
    
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
        
    args = message.text.split(maxsplit=2)
    
    if message.reply_to_message and len(args) >= 2:
        target_user_id = None
        
        if message.reply_to_message.text:
            match = USER_ID_RE.search(message.reply_to_message.text)
            if match:
                target_user_id = int(match.group(1))
            elif message.reply_to_message.forward_from:
                target_user_id = message.reply_to_message.forward_from.id
                
        if not target_user_id:
            await message.answer("❌ Не удалось найти ID пользователя в сообщении. Напиши вручную: `/reply <id> <текст>`")
            return
            
        reply_text = args[1] if len(args) > 1 else ""
        
    elif len(args) >= 3:
        try:
            target_user_id = int(args[1])
            reply_text = args[2]
        except ValueError:
            await message.answer("❌ Неверный формат ID. Используй: `/reply <user_id> <текст>`")
            return
    else:
        await message.answer("❌ Использование:\n1. Ответь (Reply) на сообщение бота с ID и напиши `/reply <текст>`\n2. Или напиши `/reply <user_id> <текст>`")
        return

    try:
        await bot.send_message(
            target_user_id, 
            f"<b>✉️ Сообщение от администрации:</b>\n\n{reply_text}", 
            parse_mode="HTML"
        )
        await message.answer(f"✅ Сообщение успешно доставлено пользователю {target_user_id}")
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить сообщение. Возможно, пользователь заблокировал бота.\nОшибка: {e}")


# --- СИСТЕМА БАНОВ ---
@dp.message(Command("ban"))
async def cmd_ban(message: Message):
    uid_admin = str(message.from_user.id)
    rank = USERS.get(uid_admin, {}).get("rank_id", 0)
    if message.from_user.id not in ADMIN_IDS and rank < 18:
        await message.answer(tr(uid_admin, "no_rights"))
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
        await message.answer(tr(uid_admin, "ban_cant_admin"))
        return

    forever = False
    until_dt = None
    
    if reason_args and reason_args[0].lower() in ("never", "навсегда", "назаўжды"):
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
                date_str = reason_args[0]
                time_str = reason_args[1]
                until_dt = datetime.strptime(f"{date_str} {time_str}", "%d.%m.%Y %H:%M:%S")
            except ValueError:
                await message.answer(tr(uid_admin, "ban_invalid_date"))
                return

            if until_dt <= datetime.now():
                await message.answer(tr(uid_admin, "ban_past"))
                return
            
            reason = " ".join(reason_args[2:]) if len(reason_args) > 2 else "Без причины"

    target_str = str(target_id)
    
    BANNED[target_str] = {
        "reason": reason,
        "until": "never" if forever else until_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "date_banned": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "banned_by": message.from_user.id
    }
    save_banned()

    if target_str not in USERS:
        USERS[target_str] = default_user_data()
    USERS[target_str]["bans"] += 1
    save_users()

    if USERS[target_str]["bans"] == 1:
        ach = unlock_achievement(target_str, "banned_1")
        if ach:
            try:
                await bot.send_message(target_id, tr(target_str, "ach_unlocked", ach=ach), parse_mode="HTML")
            except:
                pass
    elif USERS[target_str]["bans"] == 10:
        ach = unlock_achievement(target_str, "banned_10")
        if ach:
            try:
                await bot.send_message(target_id, tr(target_str, "ach_unlocked", ach=ach), parse_mode="HTML")
            except:
                pass

    if TARGET_CHAT_IDS:
        try:
            await bot.ban_chat_member(TARGET_CHAT_IDS[0], target_id)
        except Exception as e:
            logger.error(f"Не удалось забанить в группе: {e}")

    try:
        if forever:
            await bot.send_message(target_id, tr(target_str, "ban_notify_forever", reason=reason))
        else:
            await bot.send_message(target_id, tr(target_str, "ban_notify", reason=reason, until=until_dt.strftime("%d.%m.%Y %H:%M:%S")))
    except:
        pass

    if TARGET_CHAT_IDS:
        try:
            if forever:
                await bot.send_message(
                    TARGET_CHAT_IDS[0],
                    f"Пользователь {target_id} забанен навсегда\nПричина: {reason}\nЗабанил: {message.from_user.id}"
                )
            else:
                await bot.send_message(
                    TARGET_CHAT_IDS[0],
                    f"Пользователь {target_id} забанен до {until_dt.strftime('%d.%m.%Y %H:%M:%S')}\nПричина: {reason}\nЗабанил: {message.from_user.id}"
                )
        except:
            pass

    if forever:
        await message.answer(tr(uid_admin, "ban_done_forever", uid=target_id, reason=reason))
    else:
        await message.answer(tr(uid_admin, "ban_done", uid=target_id, until=until_dt.strftime("%d.%m.%Y %H:%M:%S"), reason=reason))


@dp.message(Command("unban"))
async def cmd_unban(message: Message):
    uid_admin = str(message.from_user.id)
    rank = USERS.get(uid_admin, {}).get("rank_id", 0)
    if message.from_user.id not in ADMIN_IDS and rank < 18:
        await message.answer(tr(uid_admin, "no_rights"))
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
        if TARGET_CHAT_IDS:
            try:
                await bot.unban_chat_member(TARGET_CHAT_IDS[0], target_id)
            except Exception as e:
                logger.error(f"Не удалось разбанить в группе: {e}")
        await message.answer(tr(uid_admin, "unban_reply_success", uid=target_id))
    else:
        await message.answer(tr(uid_admin, "unban_not_found"))


@dp.message(Command("banlist"))
async def cmd_banlist(message: Message):
    uid_admin = str(message.from_user.id)
    rank = USERS.get(uid_admin, {}).get("rank_id", 0)
    if message.from_user.id not in ADMIN_IDS and rank < 18:
        await message.answer(tr(uid_admin, "no_rights"))
        return

    if not BANNED:
        await message.answer(tr(uid_admin, "banlist_empty"))
        return

    lines = []
    for uid, info in BANNED.items():
        until = info.get("until", "?")
        if until == "never":
            until = "навсегда"
        lines.append(f"• {uid} | до {until} | {info.get('reason', '')}")
    await message.answer(tr(uid_admin, "banlist_title") + "\n" + "\n".join(lines))


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

    text = (
        f"{tr(uid, 'mystatus_title')}\n"
        f"{until_text}\n"
        f"{tr(uid, 'mystatus_reason', reason=info.get('reason', '?'))}"
    )
    await message.answer(text, reply_markup=None)


# --- Обработчики ---
@dp.message(F.document)
async def group_document_handler(message: Message):
    if GROUP_ID_VALUE and str(message.chat.id) == str(GROUP_ID_VALUE):
        doc = message.document
        if doc.file_name:
            FILE_IDS[doc.file_name] = doc.file_id
            save_file_ids()
            logger.info(f"Сохранен файл из группы: {doc.file_name}")
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
            except Exception as e:
                logger.error(f"Не удалось забанить при входе: {e}")


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    if await check_ban_and_block(message):
        return
    await state.clear()
    uid = str(message.from_user.id)
    
    args = message.text.split()
    is_new = uid not in USERS
    
    if len(args) > 1 and args[1].startswith("ref_"):
        referrer_id = args[1].replace("ref_", "")
        if referrer_id in USERS and referrer_id != uid and is_new:
            add_xp(referrer_id, 150)
            add_xp(uid, 150)
            try:
                await bot.send_message(int(referrer_id), tr(referrer_id, "ref_bonus"))
            except:
                pass
            await message.answer(tr(uid, "ref_welcome"))
    
    if is_new:
        USERS[uid] = default_user_data()
        if message.from_user.id in ADMIN_IDS:
            USERS[uid]["rank_id"] = 13
        save_users()

    if not USERS[uid].get("lang"):
        await message.answer(
            "Выбери язык / Абяры мову / Choose language:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_lang_ru")],
                [InlineKeyboardButton(text="🇧🇾 Беларуская", callback_data="set_lang_be")],
                [InlineKeyboardButton(text="🇬🇧 English", callback_data="set_lang_en")],
            ])
        )
        return

    await message.answer(
        tr(uid, "start", name=message.from_user.first_name),
        reply_markup=get_main_keyboard(uid),
    )


@dp.message(Command("lang"))
async def cmd_lang(message: Message, state: FSMContext):
    if await check_ban_and_block(message):
        return
    await state.clear()
    await message.answer(
        tr(str(message.from_user.id), "choose_lang"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_lang_ru")],
            [InlineKeyboardButton(text="🇧🇾 Беларуская", callback_data="set_lang_be")],
            [InlineKeyboardButton(text="🇬🇧 English", callback_data="set_lang_en")],
        ])
    )


@dp.callback_query(F.data.startswith("set_lang_"))
async def cb_set_lang(callback: CallbackQuery, state: FSMContext):
    uid = str(callback.from_user.id)
    banned, _ = is_banned(uid)
    if banned:
        await callback.answer("Вы забанены", show_alert=True)
        return
    lang = callback.data.split("_")[-1]
    if uid not in USERS:
        USERS[uid] = default_user_data()
    USERS[uid]["lang"] = lang
    save_users()

    await callback.message.delete()
    await callback.message.answer(
        tr(uid, "lang_changed"),
        reply_markup=get_main_keyboard(uid)
    )
    await callback.answer()


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


@dp.message(Command("testgroup"))
async def cmd_test_group(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await easter_egg_handler(message, state)
        return

    if not TARGET_CHAT_IDS:
        await message.answer("❌ TARGET_CHAT_IDS пуст, GROUP_ID не задан в секретах")
        return

    await message.answer(f"Пробую отправить в группу `{TARGET_CHAT_IDS[0]}`")
    try:
        await bot.send_message(TARGET_CHAT_IDS[0], "✅ Тестовое сообщение из бота! Связь есть")
        await message.answer("✅ Успешно отправлено в группу!")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


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
    banned, _ = is_banned(uid)
    if banned:
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
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=tr(uid, "btn_subscribe"), url=CHANNEL_LINK)]
            ])
        )
        return

    await callback.message.answer(tr(uid, "version", ver=version))
    ext = "zip" if mod_key == "old_medals" else "rar"
    kb = get_mod_info_keyboard(uid) if mod_key == "old_ui" else None
    await send_mod_file(callback.from_user.id, f"{mod_key}.{ext}", reply_markup=kb)

    if uid not in USERS:
        USERS[uid] = default_user_data()
    USERS[uid]["downloads"] += 1
    add_xp(uid, 10)
    save_users()

    new_rank = check_rank_up(uid)
    if new_rank:
        await callback.message.answer(tr(uid, "rank_up", rank=new_rank))

    if USERS[uid]["downloads"] == 1:
        ach = unlock_achievement(uid, "first_download")
        if ach:
            await callback.message.answer(tr(uid, "ach_unlocked", ach=ach))
    elif USERS[uid]["downloads"] == 10:
        ach = unlock_achievement(uid, "mods_10")
        if ach:
            await callback.message.answer(tr(uid, "ach_unlocked", ach=ach))
    elif USERS[uid]["downloads"] == 50:
        ach = unlock_achievement(uid, "mods_50")
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
    user = message.from_user
    header = f"<b>Прикол от пользователя!</b>\n👤 {user.full_name} (@{user.username})\n🆔 <code>{user.id}</code>\n\n"
    await forward_to_admins(message, header)
    add_xp(uid, 5)
    await message.answer(tr(uid, "fun_thanks"), reply_markup=get_main_keyboard(uid))


# --- ОБРАТНАЯ СВЯЗЬ ---
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
    user = message.from_user
    header = f"<b>Новая идея от пользователя!</b>\n👤 {user.full_name} (@{user.username})\n🆔 <code>{user.id}</code>\n\n"
    await forward_to_admins(message, header)

    if uid not in USERS:
        USERS[uid] = default_user_data()
    USERS[uid]["ideas"] += 1
    add_xp(uid, 25)
    save_users()

    new_rank = check_rank_up(uid)
    if new_rank:
        await message.answer(tr(uid, "rank_up", rank=new_rank))

    if USERS[uid]["ideas"] == 1:
        ach = unlock_achievement(uid, "first_idea")
        if ach:
            await message.answer(tr(uid, "ach_unlocked", ach=ach))
    elif USERS[uid]["ideas"] == 10:
        ach = unlock_achievement(uid, "ideas_10")
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
    user = message.from_user
    header = f"<b>[ОШИБКА] Сообщение об ошибке</b>\n👤 {user.full_name} (@{user.username})\n🆔 <code>{user.id}</code>\n\n"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr(uid, "btn_report_fixed"), callback_data=f"bug_fixed_{uid}")]
    ])
    
    if TARGET_CHAT_IDS:
        for chat_id in TARGET_CHAT_IDS:
            try:
                await bot.send_message(chat_id, header, parse_mode="HTML", reply_markup=kb)
                await message.forward(chat_id)
            except Exception as exc:
                logger.error(f"Не удалось отправить в {chat_id}. Ошибка: {exc}")
                
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
    user = message.from_user
    header = f"<b>Вопрос от пользователя!</b>\n👤 {user.full_name} (@{user.username})\n🆔 <code>{user.id}</code>\n\nОтветьте на это сообщение (Reply), чтобы отправить ответ пользователю"

    if not TARGET_CHAT_IDS:
        await message.answer(tr(uid, "question_no_group"))
        return

    for chat_id in TARGET_CHAT_IDS:
        try:
            await bot.send_message(chat_id, header, parse_mode="HTML")
            await message.forward(chat_id)
        except Exception as exc:
            logger.error(f"Не удалось отправить в {chat_id}. Ошибка: {exc}")

    if uid not in USERS:
        USERS[uid] = default_user_data()
    USERS[uid]["questions"] += 1
    add_xp(uid, 5)
    save_users()

    if USERS[uid]["questions"] == 1:
        ach = unlock_achievement(uid, "first_question")
        if ach:
            await message.answer(tr(uid, "ach_unlocked", ach=ach))

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
            except Exception as exc:
                logger.error(f"Ошибка отправки анкеты: {exc}")
                
    await message.answer(tr(uid, "apply_team_thanks"), reply_markup=get_main_keyboard(uid))

# --- ОБРАБОТКА ИСПРАВЛЕННЫХ БАГОВ ---
@dp.callback_query(F.data.startswith("bug_fixed_"))
async def cb_bug_fixed(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Только админ может это делать", show_alert=True)
        return
    
    target_id = callback.data.split("_")[-1]
    add_xp(target_id, 50)
    
    try:
        await bot.send_message(int(target_id), tr(target_id, "bug_report_fixed"))
    except:
        pass
        
    await callback.message.edit_text(callback.message.text + "\n\n✅ <b>Статус: Исправлено</b>", parse_mode="HTML")
    await callback.answer("Пользователь уведомлен!")

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
    
    if USERS.get(uid, {}).get("appeal_pending"):
        await message.answer(tr(uid, "appeal_already"))
        return
        
    if uid not in USERS:
        USERS[uid] = default_user_data()
    USERS[uid]["appeal_pending"] = True
    save_users()
    
    user = message.from_user
    header = (
        f"<b>🔓 Заявка на разбан!</b>\n"
        f"👤 {user.full_name} (@{user.username})\n"
        f"🆔 <code>{user.id}</code>\n"
        f"Причина: {message.text}\n\n"
        f"<i>Ответьте на это сообщение (Reply), чтобы разбанить пользователя.</i>"
    )
    
    if TARGET_CHAT_IDS:
        for chat_id in TARGET_CHAT_IDS:
            try:
                await bot.send_message(chat_id, header, parse_mode="HTML")
            except Exception as exc:
                logger.error(f"Ошибка отправки заявки: {exc}")
                
    await message.answer(tr(uid, "appeal_sent"))


# --- ПОМОЩЬ ---
@dp.message(F.text.in_([LOCALES["ru"]["btn_help"], LOCALES["be"]["btn_help"], LOCALES["en"]["btn_help"]]))
async def btn_help(message: Message, state: FSMContext):
    if await check_ban_and_block(message):
        return
    await state.clear()
    uid = str(message.from_user.id)
    await message.answer(
        tr(uid, "help_menu"),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=tr(uid, "help_install_btn"), callback_data="help_install")],
            [InlineKeyboardButton(text=tr(uid, "help_remove_btn"), callback_data="help_remove")],
            [InlineKeyboardButton(text=tr(uid, "help_why_btn"), callback_data="help_why")],
            [InlineKeyboardButton(text=tr(uid, "help_time_btn"), callback_data="help_time")],
            [InlineKeyboardButton(text=tr(uid, "help_why_old_btn"), callback_data="help_why_old")],
        ])
    )

@dp.callback_query(F.data.startswith("help_"))
async def cb_help_any(callback: CallbackQuery):
    uid = str(callback.from_user.id)
    banned, _ = is_banned(uid)
    if banned:
        await callback.answer("Вы забанены", show_alert=True)
        return
    await callback.answer()
    key = f"{callback.data}_text"
    await callback.message.answer(tr(uid, key))


# --- РАЗНОЕ ---
@dp.message(F.text.in_([LOCALES["ru"]["btn_misc"], LOCALES["be"]["btn_misc"], LOCALES["en"]["btn_misc"]]))
async def btn_misc(message: Message, state: FSMContext):
    if await check_ban_and_block(message):
        return
    await state.clear()
    uid = str(message.from_user.id)
    await message.answer(
        tr(uid, "misc_menu"),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=tr(uid, "btn_dev"), callback_data="misc_dev")],
            [InlineKeyboardButton(text=tr(uid, "btn_donate"), callback_data="misc_donate")],
            [InlineKeyboardButton(text=tr(uid, "btn_lang"), callback_data="misc_lang")],
            [InlineKeyboardButton(text=tr(uid, "misc_team_btn"), callback_data="misc_team")],
            [InlineKeyboardButton(text=tr(uid, "misc_join_btn"), callback_data="misc_join")],
            [InlineKeyboardButton(text=tr(uid, "misc_share_btn"), url="https://t.me/share/url?url=https://t.me/ModRak1_bot&text=Смотри, какой крутой бот для модов!")],
        ])
    )

@dp.callback_query(F.data.startswith("misc_"))
async def cb_misc_any(callback: CallbackQuery):
    uid = str(callback.from_user.id)
    banned, _ = is_banned(uid)
    if banned:
        await callback.answer("Вы забанены", show_alert=True)
        return
    await callback.answer()
    
    if callback.data == "misc_dev":
        await callback.message.answer(tr(uid, "dev_text"))
    elif callback.data == "misc_donate":
        await callback.message.answer(tr(uid, "donate_text"))
    elif callback.data == "misc_lang":
        await callback.message.answer(
            tr(uid, "choose_lang"),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_lang_ru")],
                [InlineKeyboardButton(text="🇧🇾 Беларуская", callback_data="set_lang_be")],
                [InlineKeyboardButton(text="🇬🇧 English", callback_data="set_lang_en")],
            ])
        )
    elif callback.data == "misc_join":
        await callback.message.answer(
            "Набор в команду сейчас закрыт. Но ты можешь заполнить анкету, и мы рассмотрим её, когда откроется набор!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=tr(uid, "apply_team_btn"), callback_data="apply_team")]
            ])
        )
    else:
        key = f"{callback.data}_text"
        if callback.data == "misc_team":
            await callback.message.answer(tr(uid, key), parse_mode="HTML")
        else:
            await callback.message.answer(tr(uid, key))


USER_ID_RE = re.compile(r"🆔 <code>(\d+)</code>")

@dp.message(F.reply_to_message, F.chat.id.in_(TARGET_CHAT_IDS))
async def handle_group_reply(message: Message):
    replied_msg = message.reply_to_message
    if not replied_msg or not replied_msg.text:
        return
    match = USER_ID_RE.search(replied_msg.text)
    if not match:
        return
    user_id = int(match.group(1))
    try:
        await bot.send_message(user_id, f"<b>Ответ от поддержки:</b>\n\n{message.text}", parse_mode="HTML")
        await message.reply("Ответ успешно отправлен пользователю!")
    except Exception as e:
        await message.reply(f"Не удалось отправить ответ, ошибка: {e}")

@dp.message(F.text)
async def easter_egg_handler(message: Message, state: FSMContext):
    if await state.get_state() is not None:
        return
    
    uid = str(message.from_user.id)
    banned, _ = is_banned(uid)
    if banned:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=tr(uid, "appeal_btn"), callback_data="appeal_ban")]
        ])
        await message.answer(tr(uid, "banned_bot_text"), reply_markup=kb)
        return
        
    if uid not in USERS or not USERS[uid].get("lang"):
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
    if GROUP_ID_VALUE and str(message.chat.id) == str(GROUP_ID_VALUE):
        return
    uid = str(message.from_user.id)
    banned, _ = is_banned(uid)
    if banned:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=tr(uid, "appeal_btn"), callback_data="appeal_ban")]
        ])
        await message.answer(tr(uid, "banned_bot_text"), reply_markup=kb)
        return
        
    if uid not in USERS or not USERS[uid].get("lang"):
        await cmd_start(message, state)
        return
        
    await message.answer(
        tr(uid, "unknown_media_text"),
        reply_markup=get_main_keyboard(uid)
    )

async def main():
    logger.info("Bot started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
