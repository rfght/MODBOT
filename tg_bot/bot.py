import asyncio
import json
import logging
import os
import random
import re
from datetime import datetime
from threading import Thread

from dotenv import load_dotenv
from flask import Flask

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

keep_alive_app = Flask(__name__)

@keep_alive_app.route("/")
def index():
    return "Bot is running!"

def run_keep_alive():
    port = int(os.getenv("PORT", "8080"))
    keep_alive_app.run(host="0.0.0.0", port=port)

if not os.getenv("REPLIT_DEV_DOMAIN"):
    Thread(target=run_keep_alive, daemon=True).start()

# --- Файлы данных ---
FILE_IDS_PATH = "file_ids.json"
FILE_IDS = {}

USERS_PATH = "users.json"
USERS = {}

BANNED_PATH = "banned.json"
BANNED = {}

MOD_NAMES = {
    "old_font": {"ru": "Старый шрифт", "be": "Стары шрыфт", "en": "Old Font"},
    "old_medals": {"ru": "Старые медали", "be": "Старыя медалі", "en": "Old Medals"},
    "old_ui": {"ru": "Старый UI ангара", "be": "Стары UI ангара", "en": "Old Hangar UI"},
}

# --- СИСТЕМА ЗВАНИЙ И ОПЫТА (20 званий) ---
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
    20: ("Владелец", 0, 0, "staff"),
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
        "lang": "ru",
        "xp": 0,
        "rank_id": 1,
        "downloads": 0,
        "ideas": 0,
        "questions": 0,
        "bans": 0,
        "achievements": [],
        "registered": datetime.now().strftime("%Y-%m-%d"),
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
    global FILE_IDS, USERS, BANNED

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
                    USERS[uid] = base
    except (OSError, json.JSONDecodeError):
        pass

    try:
        with open(BANNED_PATH) as f:
            BANNED.update(json.load(f))
    except (OSError, json.JSONDecodeError):
        pass


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
        "btn_suggest": "Предложить мод",
        "btn_dev": "В разработке",
        "btn_donate": "Поддержать",
        "btn_bug": "Сообщить об ошибке",
        "btn_question": "Задать вопрос",
        "btn_misc": "Разное",
        "btn_lang": "Язык",
        "btn_profile": "Профиль",
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
        "misc_join_text": "К сожалению, набор в команду сейчас закрыт Чтобы делать эти моды, нужно именно то настроение/цель, что есть у наших ребят, а выяснять, есть ли это у вас, нет возможности, мы сейчас полностью укомплектованы и сфокусированы на текущих проектах\n\nНо ты всегда можешь предложить идею для мода через главное меню!",
        "help_menu": "<b>Помощь</b>\n\nВыбери вопрос:",
        "help_install_btn": "Как установить мод",
        "help_remove_btn": "Как удалить мод",
        "help_why_btn": "Зачем нужны данные модификации",
        "help_time_btn": "Сколько разрабатываются моды",
        "help_why_old_btn": "Почему моды только на возвращение старого в игру",
        "help_sleep_btn": "Бот не отвечает",
        "help_install_text": "Как установить мод:\n\nШаг 1: Скачать мод с официального сайта For Blitz или в нашем боте\nШаг 1.1: Установки модов на телефон нету, если нужно, то используйте инструкцию/приложения от For Blitz\nОбрати внимание, моды в этом боте только на ПК\nШаг 2: Распаковать архив или просто зайти в него\nШаг 3: Скопировать папку Data\nШаг 4: Зайти в папку игры: C:\\Games\\Tanks Blitz\nШаг 5: Нажать вставить скопированную папку Data с заменой",
        "help_remove_text": "Как удалить мод:\n\nСамый простой способ, нажать в приложении LGC восстановление игры",
        "help_why_text": "Зачем нужны данные модификации:\n\nМоды возвращают удалённые функции и интерфейс, к которым привыкли игроки Это делает игру комфортнее и привычнее для тех, кто играл раньше",
        "help_time_text": "Сколько разрабатываются моды:\n\nВремя разработки зависит от размера мода, сложности, свободного времени у мододелов, а также от того, насколько часто бывают бухие сервера у картошки",
        "help_why_old_text": "Почему модификации только на возвращение старого в игру:\n\nНостальгия у всей команды по старой игре",
        "help_sleep_text": "Бот не отвечает?\n\nНе пугайся! У нашего бота есть свой график работы (техобслуживание серверов) Обычно перерыв длится не больше часа Пожалуйста, попробуй написать чуть позже!",
        "old_ui_info_text": "Данный мод возвращает:\n• Старую кнопку выбора режима\n• Старый UI хранилища\n• Старую кнопку магазина\n• Старую левую панель\n• Старую кнопку «Тренироваться»\n• Старую кнопку «В Бой»\n• Убраны новые чёрные точки на фоне кнопок боя/выбора режима/взвода\n• Старые иконки для режимов\n• Старые иконки победы/поражения/ничьи во вкладке уведомлений\n• Старые звуки при нажатии кнопок/иконок в ангаре\n• Старые кнопки (зелёные, красные)\n• Старый UI дерева исследования\n• Старый UI окна уведомлений\n• Всякие мелочи",
        "unknown_media_text": "Эт что? Я понимаю только текст и кнопки Выбери нужный раздел на клавиатуре ниже",
        "unavailable_text": "Временно недоступно",
        "break_hard_text": "Хватит меня ломать, я и так еле держусь 🤖",
        "break_soft_text": "Не сломаешь, я крепкий",
        "banned_text": "Ты был забанен {count} раз",
        "no_rights": "У тебя нет прав для этого действия",
        "ban_usage": "Использование: /ban <user_id> <дд.мм.гггг> <чч:мм:сс> [причина]\nИли: /ban <user_id> never [причина]",
        "unban_usage": "Использование: /unban <user_id>",
        "ban_cant_admin": "Нельзя забанить администратора",
        "ban_done": "Пользователь {uid} забанен до {until}. Причина: {reason}",
        "ban_done_forever": "Пользователь {uid} забанен навсегда. Причина: {reason}",
        "unban_done": "Пользователь {uid} разбанен",
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
    },
    "be": {
        "start": "Прывітанне, {name}!\n\nСардэчна запрашаем! Абяры патрэбны раздзел:",
        "choose_lang": "Выбяры мову / Choose language:",
        "lang_changed": "Мова зменена на Беларускую",
        "btn_mods": "Моды", "btn_fun": "Прыколы", "btn_help": "Дапамога", "btn_suggest": "Прапанаваць мод",
        "btn_dev": "У распрацоўцы", "btn_donate": "Падтрымаць", "btn_bug": "Паведаміць пра памылку",
        "btn_question": "Задаць пытанне", "btn_misc": "Рознае", "btn_lang": "Мова", "btn_profile": "Профіль",
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
        "misc_join_text": "На жаль, набор у каманду зараз закрыты Але ты заўсёды можаш прапанаваць ідэю для мода праз галоўнае меню!",
        "help_menu": "<b>Дапамога</b>\n\nАбяры пытанне:",
        "help_install_btn": "Як усталяваць мод", "help_remove_btn": "Як выдаліць мод", "help_why_btn": "Навошта патрэбныя гэтыя мадыфікацыі",
        "help_time_btn": "Колькі распрацоўваюцца моды", "help_why_old_btn": "Чаму моды толькі на вяртанне старога", "help_sleep_btn": "Бот не адказвае",
        "help_install_text": "Як усталяваць мод:\n\nКрок 1: Спампаваць мод\nКрок 2: Распакаваць архіў\nКрок 3: Скапіяваць папку Data\nКрок 4: Зайсці ў папку гульні: C:\\Games\\Tanks Blitz\nКрок 5: Уставіць з заменай",
        "help_remove_text": "Як выдаліць мод:\n\nСамы просты спосаб, націснуць у праграме LGC аднаўленне гульні",
        "help_why_text": "Навошта патрэбныя гэтыя мадыфікацыі:\n\nМоды вяртаюць выдаленыя функцыі і інтэрфейс, да якіх звыкліся гульцы",
        "help_time_text": "Колькі распрацоўваюцца моды:\n\nЧас распрацоўкі залежыць ад памеру мода, складанасці і вольнага часу",
        "help_why_old_text": "Чаму мадыфікацыі толькі на вяртанне старога:\n\nНастальгія ўсёй каманды па старой гульні",
        "help_sleep_text": "Бот не адказвае?\n\nНе палохайся! У нашага бота ёсць свой графік працы Паспрабуй напісаць крыху пазней!",
        "old_ui_info_text": "Гэты мод вяртае:\n• Старую кнопку выбару рэжыму\n• Стары UI сховішча\n• Старую кнопку крамы\n• Старую левую панэль\n• Старую кнопку «Трэніравацца»\n• Старую кнопку «У Бой»\n• Прыбраныя новыя чорныя кропкі на фоне кнопак бою/выбару рэжыму/узвода\n• Старыя іконкі для рэжымаў\n• Старыя іконкі перамогі/паражэння/нічыі ў закладцы апавяшчэнняў\n• Старыя гукі пры націску кнопак/іконак у ангары\n• Старыя кнопкі (зялёныя, чырвоныя)\n• Стары UI дрэва даследавання\n• Стары UI акна апавяшчэнняў\n• Розныя дробязі",
        "unknown_media_text": "Гэта што? Я разумею толькі тэкст і кнопкі Абяры патрэбны раздзел на клавіятуры ніжэй",
        "unavailable_text": "Часова недаступна",
        "break_hard_text": "Хопіць мяне ламаць, я і так ледзь трымаюся 🤖",
        "break_soft_text": "Не зламаеш, я моцны",
        "no_rights": "У цябе няма правоў для гэтага дзеяння",
        "ban_usage": "Выкарыстанне: /ban <user_id> <дд.мм.гггг> <чч:мм:сс> [прычына]\nАбо: /ban <user_id> never [прычына]",
        "unban_usage": "Выкарыстанне: /unban <user_id>",
        "ban_cant_admin": "Нельга забаніць адміністратара",
        "ban_done": "Карыстальнік {uid} забанены да {until}. Прычына: {reason}",
        "ban_done_forever": "Карыстальнік {uid} забанены назаўжды. Прычына: {reason}",
        "unban_done": "Карыстальнік {uid} разбанены",
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
    },
    "en": {
        "start": "Hello, {name}!\n\nWelcome! Choose a section:",
        "choose_lang": "Choose language:",
        "lang_changed": "Language changed to English",
        "btn_mods": "Mods", "btn_fun": "Fun", "btn_help": "Help", "btn_suggest": "Suggest a mod",
        "btn_dev": "In development", "btn_donate": "Support", "btn_bug": "Report a bug",
        "btn_question": "Ask a question", "btn_misc": "Misc", "btn_lang": "Language", "btn_profile": "Profile",
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
        "misc_join_text": "Unfortunately, recruitment is currently closed But you can always suggest a mod idea through the main menu!",
        "help_menu": "<b>Help</b>\n\nChoose a question:",
        "help_install_btn": "How to install a mod", "help_remove_btn": "How to remove a mod", "help_why_btn": "Why are modifications needed",
        "help_time_btn": "How long mods take to develop", "help_why_old_btn": "Why mods only bring back old features", "help_sleep_btn": "Bot is not responding",
        "help_install_text": "How to install a mod:\n\nStep 1: Download the mod\nStep 2: Unzip the archive\nStep 3: Copy the Data folder\nStep 4: Go to the game folder: C:\\Games\\Tanks Blitz\nStep 5: Paste and replace",
        "help_remove_text": "How to remove a mod:\n\nEasiest way is to press restore game in the LGC app",
        "help_why_text": "Why are modifications needed:\n\nMods bring back deleted features and interfaces that players are used to",
        "help_time_text": "How long mods take to develop:\n\nDevelopment time depends on the mod size, complexity, and free time",
        "help_why_old_text": "Why mods only bring back old features:\n\nNostalgia of the whole team for the old game",
        "help_sleep_text": "Bot is not responding?\n\nDon't panic! Our bot has its own work schedule Try again a bit later!",
        "old_ui_info_text": "This mod brings back:\n• Old mode selection button\n• Old storage UI\n• Old shop button\n• Old left panel\n• Old 'Train' button\n• Old 'To Battle' button\n• Removed new black dots on the background of battle/mode selection/platoon buttons\n• Old icons for modes\n• Old victory/defeat/draw icons in the notifications tab\n• Old sounds when pressing buttons/icons in the hangar\n• Old buttons (green, red)\n• Old research tree UI\n• Old notifications window UI\n• Various small things",
        "unknown_media_text": "What is this? I only understand text and buttons Choose a section on the keyboard below",
        "unavailable_text": "Temporarily unavailable",
        "break_hard_text": "Stop breaking me, I'm barely holding on as it is 🤖",
        "break_soft_text": "You won't break me, I'm tough",
        "no_rights": "You have no rights for this action",
        "ban_usage": "Usage: /ban <user_id> <dd.mm.yyyy> <hh:mm:ss> [reason]\nOr: /ban <user_id> never [reason]",
        "unban_usage": "Usage: /unban <user_id>",
        "ban_cant_admin": "Cannot ban an administrator",
        "ban_done": "User {uid} banned until {until}. Reason: {reason}",
        "ban_done_forever": "User {uid} banned forever. Reason: {reason}",
        "unban_done": "User {uid} unbanned",
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
    }
}

def tr(user_id: str, key: str, **kwargs) -> str:
    data = USERS.get(user_id)
    lang = data["lang"] if data else "ru"
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
        await message.answer(
            tr(uid, "banned_bot_text"),
            reply_markup=None
        )
        return True
    return False


# --- Клавиатуры ---
def get_main_keyboard(user_id: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=tr(user_id, "btn_mods")), KeyboardButton(text=tr(user_id, "btn_fun"))],
            [KeyboardButton(text=tr(user_id, "btn_help")), KeyboardButton(text=tr(user_id, "btn_suggest"))],
            [KeyboardButton(text=tr(user_id, "btn_dev")), KeyboardButton(text=tr(user_id, "btn_donate"))],
            [KeyboardButton(text=tr(user_id, "btn_bug")), KeyboardButton(text=tr(user_id, "btn_question"))],
            [KeyboardButton(text=tr(user_id, "btn_misc")), KeyboardButton(text=tr(user_id, "btn_lang"))],
            [KeyboardButton(text=tr(user_id, "btn_profile"))],
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
    if uid not in USERS:
        USERS[uid] = default_user_data()
        save_users()

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

    await message.answer(text, parse_mode="HTML", reply_markup=get_main_keyboard(uid))


@dp.message(F.text.in_([LOCALES["ru"]["btn_profile"], LOCALES["be"]["btn_profile"], LOCALES["en"]["btn_profile"]]))
async def btn_profile_click(message: Message, state: FSMContext):
    await cmd_profile(message, state)


# --- АДМИН: ВЫДАЧА ЗВАНИЙ ---
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


# --- СИСТЕМА БАНОВ ---
@dp.message(Command("ban"))
async def cmd_ban(message: Message):
    uid_admin = str(message.from_user.id)
    rank = USERS.get(uid_admin, {}).get("rank_id", 0)
    if message.from_user.id not in ADMIN_IDS and rank < 18:
        await message.answer(tr(uid_admin, "no_rights"))
        return

    args = message.text.split()
    if len(args) < 3:
        await message.answer(tr(uid_admin, "ban_usage"))
        return
    
    try:
        target_id = int(args[1])
    except ValueError:
        await message.answer(tr(uid_admin, "setrank_bad_id"))
        return

    if target_id in ADMIN_IDS:
        await message.answer(tr(uid_admin, "ban_cant_admin"))
        return

    # Проверка на вечный бан
    forever = False
    until_dt = None
    
    if args[2].lower() in ("never", "навсегда", "назаўжды"):
        forever = True
        reason = " ".join(args[3:]) if len(args) > 3 else "Без причины"
    else:
        if len(args) < 4:
            await message.answer(tr(uid_admin, "ban_usage"))
            return
        try:
            date_str = args[2]
            time_str = args[3]
            until_dt = datetime.strptime(f"{date_str} {time_str}", "%d.%m.%Y %H:%M:%S")
        except ValueError:
            await message.answer(tr(uid_admin, "ban_invalid_date"))
            return

        if until_dt <= datetime.now():
            await message.answer(tr(uid_admin, "ban_past"))
            return
        
        reason = " ".join(args[4:]) if len(args) > 4 else "Без причины"

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
        await message.answer(tr(uid_admin, "unban_done", uid=target_id))
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
    is_new = uid not in USERS

    if is_new:
        USERS[uid] = default_user_data()
        if message.from_user.id in ADMIN_IDS:
            USERS[uid]["rank_id"] = 13
        save_users()

    if is_new:
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


@dp.message(F.text.in_([LOCALES["ru"]["btn_suggest"], LOCALES["be"]["btn_suggest"], LOCALES["en"]["btn_suggest"]]))
async def btn_suggest_mod(message: Message, state: FSMContext):
    if await check_ban_and_block(message):
        return
    await state.set_state(UserState.awaiting_mod_suggestion)
    uid = str(message.from_user.id)
    await message.answer(tr(uid, "suggest_prompt"), parse_mode="HTML", reply_markup=get_main_keyboard(uid))


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
    await message.answer(tr(uid, "bug_prompt"), reply_markup=get_main_keyboard(uid))


@dp.message(UserState.awaiting_bug_report, ~F.text.in_(ALL_MENU_BUTTONS))
async def receive_bug_report(message: Message, state: FSMContext):
    uid = str(message.from_user.id)
    if message.voice or (not message.text and not message.photo and not message.video and not message.document):
        await message.answer(tr(uid, "bug_voice"))
        return
    await state.clear()
    user = message.from_user
    header = f"<b>[ОШИБКА] Сообщение об ошибке</b>\n👤 {user.full_name} (@{user.username})\n🆔 <code>{user.id}</code>\n\n"
    await forward_to_admins(message, header)
    add_xp(uid, 15)
    await message.answer(tr(uid, "bug_thanks"), reply_markup=get_main_keyboard(uid))


@dp.message(F.text.in_([LOCALES["ru"]["btn_question"], LOCALES["be"]["btn_question"], LOCALES["en"]["btn_question"]]))
async def btn_question(message: Message, state: FSMContext):
    if await check_ban_and_block(message):
        return
    await state.set_state(UserState.awaiting_question)
    uid = str(message.from_user.id)
    await message.answer(tr(uid, "question_prompt"), reply_markup=get_main_keyboard(uid))


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


@dp.message(F.text.in_([LOCALES["ru"]["btn_dev"], LOCALES["be"]["btn_dev"], LOCALES["en"]["btn_dev"]]))
async def btn_in_dev(message: Message, state: FSMContext):
    if await check_ban_and_block(message):
        return
    await state.clear()
    uid = str(message.from_user.id)
    await message.answer(tr(uid, "dev_text"), reply_markup=get_main_keyboard(uid))

@dp.message(F.text.in_([LOCALES["ru"]["btn_donate"], LOCALES["be"]["btn_donate"], LOCALES["en"]["btn_donate"]]))
async def btn_donate(message: Message, state: FSMContext):
    if await check_ban_and_block(message):
        return
    await state.clear()
    uid = str(message.from_user.id)
    await message.answer(tr(uid, "donate_text"), reply_markup=get_main_keyboard(uid))

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
            [InlineKeyboardButton(text=tr(uid, "help_sleep_btn"), callback_data="help_sleep")],
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
    key = f"{callback.data}_text"
    if callback.data == "misc_team":
        await callback.message.answer(tr(uid, key), parse_mode="HTML")
    else:
        await callback.message.answer(tr(uid, key))

@dp.message(F.text.in_([LOCALES["ru"]["btn_lang"], LOCALES["be"]["btn_lang"], LOCALES["en"]["btn_lang"]]))
async def btn_lang_click(message: Message, state: FSMContext):
    await cmd_lang(message, state)

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
        await message.answer(tr(uid, "banned_bot_text"), reply_markup=None)
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
    replies_list = LOCALES.get(USERS.get(uid, {}).get("lang", "ru"), LOCALES["ru"])[replies_key]
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
        await message.answer(tr(uid, "banned_bot_text"), reply_markup=None)
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
