import asyncio
import json
import logging
import os
import random
import re
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

# ---------- Файлы данных ----------
FILE_IDS_PATH = "file_ids.json"
FILE_IDS = {}

STATS_PATH = "stats.json"
STATS = {
    "old_font":   {"likes": 0, "dislikes": 0, "msg_id": None, "voters": {}},
    "old_medals": {"likes": 0, "dislikes": 0, "msg_id": None, "voters": {}},
    "old_ui":     {"likes": 0, "dislikes": 0, "msg_id": None, "voters": {}},
}

USERS_PATH = "users.json"
USERS = {}  # {str(user_id): "ru" | "be" | "en"}

MOD_NAMES = {
    "old_font": {"ru": "Старый шрифт", "be": "Стары шрыфт", "en": "Old Font"},
    "old_medals": {"ru": "Старые медали", "be": "Старыя медалі", "en": "Old Medals"},
    "old_ui": {"ru": "Старый UI ангара", "be": "Стары UI ангара", "en": "Old Hangar UI"},
}

# ---------- Загрузка/Сохранение ----------
def load_data():
    global FILE_IDS, STATS, USERS
    # file_ids
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

    # stats
    try:
        with open(STATS_PATH) as f:
            loaded = json.load(f)
            for k in STATS:
                if k in loaded:
                    STATS[k].update(loaded[k])
                    STATS[k].setdefault("voters", {})
    except (OSError, json.JSONDecodeError):
        pass

    # users
    try:
        with open(USERS_PATH) as f:
            USERS.update(json.load(f))
    except (OSError, json.JSONDecodeError):
        pass

def save_file_ids():
    with open(FILE_IDS_PATH, "w") as f:
        json.dump(FILE_IDS, f)

def save_stats():
    with open(STATS_PATH, "w") as f:
        json.dump(STATS, f)

def save_users():
    with open(USERS_PATH, "w") as f:
        json.dump(USERS, f)

load_data()

# ---------- Локализация ----------
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
        "mods_menu": "<b>Моды</b>\n\nВыбери мод:",
        "subscribe_needed": "Чтобы скачать этот мод, пожалуйста, подпишись на наш канал!",
        "btn_subscribe": "Подписаться на канал",
        "version": "Версия мода: {ver}",
        "btn_like": "👍 Лайк",
        "btn_dislike": "👎 Дизлайк",
        "btn_info": "Описание мода",
        "vote_recorded": "Голос учтён!",
        "vote_cancelled": "Голос отменён",
        "cancel": "Отменено. Возвращаюсь в главное меню.",
        "nothing_cancel": "Нечего отменять.",
        "gibberish": ["Братан, может скорую", "Это что за набор символов", "Ты с клавиатурой поссорился", "Кот по клавишам прошёлся", "Я такое не читаю", "Эт что за шифр", "Может, тебе помочь набрать", "Клавиатуру протри", "Тут буквы потерялись", "Я в этом не разбираюсь"],
        "fallback": ["Тут я бессилен. Кнопки внизу выручат", "Не догнал тебя. Жми кнопку из меню", "Такое мне не по зубам. Выбери раздел на клавиатуре", "Я в замешательстве. Кнопки ниже помогут", "Ты говоришь загадками. А я понимаю только кнопки", "Не уловил мысль. Попробуй через меню", "Моя голова не варит. Тыкай кнопку ниже", "Что-то я подвис. Клавиатура внизу спасёт", "Не понял ни слова. Меню в помощь", "Я всего лишь бот. Нажми кнопку из списка"],
        "fun_prompt": "Кидай свой игровой прикол сюда!\n\nЭто может быть:\n• Забавный момент из боя\n• Необычная ситуация с физикой игры\n• Смешной баг или совпадение\n• Любой другой забавный случай из игры\n\nОтправляй хоть видео, хоть фото, хоть текст\nДля отмены напиши /cancel",
        "fun_thanks": "Спасибо! Твой прикол принят. Когда его проверят модераторы, он попадёт в наш канал.",
        "suggest_prompt": "<b>Предложить идею для мода</b>\n\nНапиши описание мода и как что работает, фото/видео/голосовые/видеосообщения не принимаются.\nОно будет переслано администратору.\n\nДля отмены напиши /cancel",
        "suggest_thanks": "Твоя идея отправлена на рассмотрение! Спасибо!",
        "bug_prompt": "Опиши ошибку в моде. Напиши название мода и что именно не так, всё будет передано парням из дружного коллектива MOD_rak.rar.\nДля отмены напиши /cancel",
        "bug_voice": "Напиши подробности текстом и по возможности фото или видео. Голосовые и пустые сообщения не принимаются.",
        "bug_thanks": "Спасибо, сообщение об ошибке передано разработчикам. Постараемся исправить в ближайшее время.",
        "question_prompt": "Задай свой вопрос, и мы ответим тебе прямо здесь!\nНапиши свой вопрос или опиши проблему.\nДля отмены напиши /cancel",
        "question_thanks": "Твой вопрос отправлен! Ожидай ответа здесь.",
        "question_no_group": "Ошибка: группа для заявок не настроена.",
        "dev_text": "Сейчас в разработке:\n\n• Мод на старое окно шансов\n• Старое окно выбора режима\n• Старое окно ТТХ танка \n\nИ всё из этого может и не выйти\nДанный список, это набросок планируемых модов. Что-то выйдет, что-то нет",
        "donate_text": "Поддержать разработку модов\n\n• Расскажи о нашем канале и боте друзьям\n• Предложи идею для нового мода\n",
        "misc_menu": "<b>Разное</b>\n\nВыбери интересующий вопрос:",
        "misc_team_btn": "О команде MOD_rak.rar",
        "misc_join_btn": "Можно ли присоединиться к вам",
        "misc_share_btn": "Поделиться ботом",
        "misc_team_text": "<b>О команде</b>\n\nМы парни-мододелы\nМы те, кто могут отстоять точку зрения\nА наша точка зрения — это старый вид игры\nИ мы не собираемся от неё отступать",
        "misc_join_text": "К сожалению, набор в команду сейчас закрыт. Чтобы делать эти моды, нужно именно то настроение/цель, что есть у наших ребят, а выяснять есть ли это у вас, нет возможности, мы сейчас полностью укомплектованы и сфокусированы на текущих проектах.\n\nНо ты всегда можешь предложить идею для мода через главное меню!",
        "help_menu": "<b>Помощь</b>\n\nВыбери вопрос:",
        "help_install_btn": "Как установить мод",
        "help_remove_btn": "Как удалить мод",
        "help_why_btn": "Зачем нужны данные модификации",
        "help_time_btn": "Сколько разрабатываются моды",
        "help_why_old_btn": "Почему моды только на возвращение старого в игру",
        "help_sleep_btn": "Бот не отвечает",
        "help_install_text": "Как установить мод:\n\nШаг 1. Скачать мод с официального сайта For Blitz или в нашем боте\nШаг 1.1. Установки модов на телефон нету, если нужно, то используйте инструкцию/приложения от For Blitz\nОбрати внимание, моды в этом боте только на ПК\nШаг 2. Распаковать архив или просто зайти в него\nШаг 3. Скопировать папку Data\nШаг 4. Зайти в папку игры: C:\\Games\\Tanks Blitz\nШаг 5. Нажать вставить скопированную папку Data с заменой",
        "help_remove_text": "Как удалить мод:\n\nСамый простой способ — нажать в приложении LGC восстановление игры",
        "help_why_text": "Зачем нужны данные модификации:\n\nМоды возвращают удалённые функции и интерфейс, к которым привыкли игроки. Это делает игру комфортнее и привычнее для тех, кто играл раньше.",
        "help_time_text": "Сколько разрабатываются моды:\n\nВремя разработки зависит от размера мода, сложности, свободного времени у мододелов, а также от того, насколько часто бывают бухие сервера у картошки",
        "help_why_old_text": "Почему модификации только на возвращение старого в игру:\n\nНастальгия у всей команды по старой игре",
        "help_sleep_text": "Бот не отвечает?\n\nНе пугайся! У нашего бота есть свой график работы (техобслуживание серверов). Обычно перерыв длится не больше часа. Пожалуйста, попробуй написать чуть позже!",
    },
    "be": {
        "start": "Прывітанне, {name}!\n\nСардэчна запрашаем! Абяры патрэбны раздзел:",
        "choose_lang": "Выбяры мову / Choose language:",
        "lang_changed": "Мова зменена на Беларускую",
        "btn_mods": "Моды",
        "btn_fun": "Прыколы",
        "btn_help": "Дапамога",
        "btn_suggest": "Прапанаваць мод",
        "btn_dev": "У распрацоўцы",
        "btn_donate": "Падтрымаць",
        "btn_bug": "Паведаміць пра памылку",
        "btn_question": "Задаць пытанне",
        "btn_misc": "Рознае",
        "btn_lang": "Мова",
        "mods_menu": "<b>Моды</b>\n\nАбяры мод:",
        "subscribe_needed": "Каб спампаваць гэты мод, калі ласка, падпішыся на наш канал!",
        "btn_subscribe": "Падпісацца на канал",
        "version": "Версія мода: {ver}",
        "btn_like": "👍 Падабаецца",
        "btn_dislike": "👎 Не падабаецца",
        "btn_info": "Апісанне мода",
        "vote_recorded": "Голас улічаны!",
        "vote_cancelled": "Голас адменены",
        "cancel": "Адменена. Вяртаюся ў галоўнае меню.",
        "nothing_cancel": "Няма чаго адмяняць.",
        "gibberish": ["Браток, можа хуткую", "Гэта што за набор сімвалаў", "Ты з клавіятурай пасварыўся", "Кот па клавішах прайшоўся", "Я такое не чытаю", "Гэта што за шыфр"],
        "fallback": ["Тут я бяссільны. Кнопкі ўнізе выручаць", "Не зразумеў цябе. Цісні кнопку з меню", "Такое мне не па зубах. Абяры раздзел на клавіятуры", "Я ў замяшанні. Кнопкі ніжэй дапамогуць", "Ты гаворыш загадкамі. А я разумею толькі кнопкі"],
        "fun_prompt": "Кідай свой гульнявы прыдуманы выпадак сюды!\n\nГэта можа быць:\n• Забаўны момант з бою\n• Незвычайная сітуацыя з фізікай гульні\n• Смешны баг ці супадзенне\n\nДля адмены напішы /cancel",
        "fun_thanks": "Дзякуй! Твой прыдуманы выпадак прыняты.",
        "suggest_prompt": "<b>Прапанаваць ідэю для мода</b>\n\nНапішы апісанне мода і як што працуе.\nДля адмены напішы /cancel",
        "suggest_thanks": "Твая ідэя адпраўлена на разгляд! Дзякуй!",
        "bug_prompt": "Апішы памылку ў модзе.\nДля адмены напішы /cancel",
        "bug_voice": "Напішы падрабязнасці тэкстам. Галасавыя паведамленні не прымаюцца.",
        "bug_thanks": "Дзякуй, паведамленне пра памылку перададзена распрацоўшчыкам.",
        "question_prompt": "Задай сваё пытанне, і мы адкажам табе прама тут!\nДля адмены напішы /cancel",
        "question_thanks": "Тваё пытанне адпраўлена! Чакай адказу тут.",
        "question_no_group": "Памылка: група для заявак не наладжана.",
        "dev_text": "Зараз у распрацоўцы:\n\n• Мод на старое акно шанцаў\n• Старое акно выбару рэжыму\n• Старое акно ТТХ танка \n\nІ ўсё з гэтага можа і не выйсці",
        "donate_text": "Падтрымаць распрацоўку модаў\n\n• Раскажы пра наш канал і бота сябрам\n• Прапануй ідэю для новага мода\n",
        "misc_menu": "<b>Рознае</b>\n\nАбяры пытанне:",
        "misc_team_btn": "Пра каманду MOD_rak.rar",
        "misc_join_btn": "Ці можна далучыцца да вас",
        "misc_share_btn": "Падзяліцца ботам",
        "misc_team_text": "<b>Пра каманду</b>\n\nМы хлопцы-моддэлы\nМы тыя, хто могуць адстаяць пункт гледжання\nА наш пункт гледжання — гэта стары выгляд гульні",
        "misc_join_text": "На жаль, набор у каманду зараз закрыты. Але ты заўсёды можаш прапанаваць ідэю для мода праз галоўнае меню!",
        "help_menu": "<b>Дапамога</b>\n\nАбяры пытанне:",
        "help_install_btn": "Як усталяваць мод",
        "help_remove_btn": "Як выдаліць мод",
        "help_why_btn": "Навошта патрэбныя дадзеныя мадыфікацыі",
        "help_time_btn": "Колькі распрацоўваюцца моды",
        "help_why_old_btn": "Чаму моды толькі на вяртанне старога",
        "help_sleep_btn": "Бот не адказвае",
        "help_install_text": "Як усталяваць мод:\n\nКрок 1. Спампаваць мод\nКрок 2. Распакаваць архіў\nКрок 3. Скапіяваць папку Data\nКрок 4. Зайсці ў папку гульні: C:\\Games\\Tanks Blitz\nКрок 5. Уставіць з заменай",
        "help_remove_text": "Як выдаліць мод:\n\nСамы просты спосаб — націснуць у праграме LGC аднаўленне гульні",
        "help_why_text": "Навошта патрэбныя дадзеныя мадыфікацыі:\n\nМоды вяртаюць выдаленыя функцыі і інтэрфейс, да якіх звыкліся гульцы.",
        "help_time_text": "Колькі распрацоўваюцца моды:\n\nЧас распрацоўкі залежыць ад памеру мода, складанасці і вольнага часу.",
        "help_why_old_text": "Чаму мадыфікацыі толькі на вяртанне старога:\n\nНастальгія ўсёй каманды па старой гульні",
        "help_sleep_text": "Бот не адказвае?\n\nНе палохайся! У нашага бота ёсць свой графік працы. Паспрабуй напісаць крыху пазней!",
    },
    "en": {
        "start": "Hello, {name}!\n\nWelcome! Choose a section:",
        "choose_lang": "Choose language:",
        "lang_changed": "Language changed to English",
        "btn_mods": "Mods",
        "btn_fun": "Fun",
        "btn_help": "Help",
        "btn_suggest": "Suggest a mod",
        "btn_dev": "In development",
        "btn_donate": "Support",
        "btn_bug": "Report a bug",
        "btn_question": "Ask a question",
        "btn_misc": "Misc",
        "btn_lang": "Language",
        "mods_menu": "<b>Mods</b>\n\nChoose a mod:",
        "subscribe_needed": "To download this mod, please subscribe to our channel!",
        "btn_subscribe": "Subscribe to channel",
        "version": "Mod version: {ver}",
        "btn_like": "👍 Like",
        "btn_dislike": "👎 Dislike",
        "btn_info": "Mod description",
        "vote_recorded": "Vote recorded!",
        "vote_cancelled": "Vote cancelled",
        "cancel": "Cancelled. Returning to main menu.",
        "nothing_cancel": "Nothing to cancel.",
        "gibberish": ["Bro, do you need an ambulance?", "What kind of characters are these?", "Did you fight with your keyboard?", "A cat walked on the keys", "I don't read this", "What kind of cipher is this?"],
        "fallback": ["I'm powerless here. The buttons below will help", "Didn't catch that. Press a button from the menu", "That's beyond me. Choose a section on the keyboard", "I'm confused. The buttons below will help", "You speak in riddles. I only understand buttons"],
        "fun_prompt": "Send your funny gaming moment here!\n\nIt could be:\n• A funny moment from battle\n• An unusual physics situation\n• A funny bug or coincidence\n\nTo cancel, type /cancel",
        "fun_thanks": "Thanks! Your funny moment is accepted.",
        "suggest_prompt": "<b>Suggest a mod idea</b>\n\nWrite a description of the mod and how it works.\nTo cancel, type /cancel",
        "suggest_thanks": "Your idea has been sent for review! Thanks!",
        "bug_prompt": "Describe the bug in the mod.\nTo cancel, type /cancel",
        "bug_voice": "Write details in text. Voice messages are not accepted.",
        "bug_thanks": "Thanks, the bug report has been sent to the developers.",
        "question_prompt": "Ask your question, and we will answer you right here!\nTo cancel, type /cancel",
        "question_thanks": "Your question has been sent! Wait for an answer here.",
        "question_no_group": "Error: support group is not configured.",
        "dev_text": "Currently in development:\n\n• Old chances window mod\n• Old mode selection window\n• Old tank characteristics window\n\nAnd all of this might not even be released",
        "donate_text": "Support mod development\n\n• Tell your friends about our channel and bot\n• Suggest an idea for a new mod\n",
        "misc_menu": "<b>Misc</b>\n\nChoose a question:",
        "misc_team_btn": "About MOD_rak.rar team",
        "misc_join_btn": "Can I join you?",
        "misc_share_btn": "Share the bot",
        "misc_team_text": "<b>About the team</b>\n\nWe are modders\nWe are the ones who can defend a point of view\nAnd our point of view is the old look of the game",
        "misc_join_text": "Unfortunately, recruitment is currently closed. But you can always suggest a mod idea through the main menu!",
        "help_menu": "<b>Help</b>\n\nChoose a question:",
        "help_install_btn": "How to install a mod",
        "help_remove_btn": "How to remove a mod",
        "help_why_btn": "Why are modifications needed",
        "help_time_btn": "How long mods take to develop",
        "help_why_old_btn": "Why mods only bring back old features",
        "help_sleep_btn": "Bot is not responding",
        "help_install_text": "How to install a mod:\n\nStep 1. Download the mod\nStep 2. Unzip the archive\nStep 3. Copy the Data folder\nStep 4. Go to the game folder: C:\\Games\\Tanks Blitz\nStep 5. Paste and replace",
        "help_remove_text": "How to remove a mod:\n\nEasiest way is to press restore game in the LGC app",
        "help_why_text": "Why are modifications needed:\n\nMods bring back deleted features and interfaces that players are used to.",
        "help_time_text": "How long mods take to develop:\n\nDevelopment time depends on the mod size, complexity, and free time.",
        "help_why_old_text": "Why mods only bring back old features:\n\nNostalgia of the whole team for the old game",
        "help_sleep_text": "Bot is not responding?\n\nDon't panic! Our bot has its own work schedule. Try again a bit later!",
    }
}

def _(user_id: int, key: str, **kwargs) -> str:
    lang = USERS.get(str(user_id), "ru")
    text = LOCALES.get(lang, LOCALES["ru"]).get(key, f"[{key}]")
    return text.format(**kwargs) if kwargs else text

# ---------- Динамические клавиатуры ----------
def get_main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=_(user_id, "btn_mods")), KeyboardButton(text=_(user_id, "btn_fun"))],
            [KeyboardButton(text=_(user_id, "btn_help")), KeyboardButton(text=_(user_id, "btn_suggest"))],
            [KeyboardButton(text=_(user_id, "btn_dev")), KeyboardButton(text=_(user_id, "btn_donate"))],
            [KeyboardButton(text=_(user_id, "btn_bug")), KeyboardButton(text=_(user_id, "btn_question"))],
            [KeyboardButton(text=_(user_id, "btn_misc")), KeyboardButton(text=_(user_id, "btn_lang"))],
        ],
        resize_keyboard=True,
    )

def get_mods_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{MOD_NAMES['old_font'][USERS.get(str(user_id), 'ru')]} (v1.0)", callback_data="mod_old_font")],
        [InlineKeyboardButton(text=f"{MOD_NAMES['old_medals'][USERS.get(str(user_id), 'ru')]} (v1.0)", callback_data="mod_old_medals")],
        [InlineKeyboardButton(text=f"{MOD_NAMES['old_ui'][USERS.get(str(user_id), 'ru')]} (v3.0)", callback_data="mod_old_ui")],
    ])

def get_vote_keyboard(user_id: int, mod_key: str) -> InlineKeyboardMarkup:
    btns = [
        [InlineKeyboardButton(text=_(user_id, "btn_like"), callback_data=f"like_{mod_key}"),
         InlineKeyboardButton(text=_(user_id, "btn_dislike"), callback_data=f"dislike_{mod_key}")]
    ]
    if mod_key == "old_ui":
        btns.insert(0, [InlineKeyboardButton(text=_(user_id, "btn_info"), callback_data="mod_old_ui_info")])
    return InlineKeyboardMarkup(inline_keyboard=btns)

# ---------- Все кнопки меню для фильтрации ----------
ALL_MENU_BUTTONS = set()
for lang_data in LOCALES.values():
    for k, v in lang_data.items():
        if k.startswith("btn_") or k.startswith("misc_") and k.endswith("_btn") or k.startswith("help_") and k.endswith("_btn"):
            ALL_MENU_BUTTONS.add(v)

# ---------- Пасхалки ----------
EASTER_EGGS = {
    "рак": "Сам такой 🦀",
    "рак?": "Сам такой 🦀",
    "crab": "Сам такой 🦀",
    "sudo": "Доступ запрещён. Хорошая попытка 😎",
    "sudo su": "Ты кто такой? Иди сюда",
    "старый": "Старый — это классика. Ты наш человек",
    "old": "Old is classic. You are our kind of person",
    "картошка": "Сервера картошки — отдельный вид искусства",
    "potato": "Potato servers are a separate art form",
    "танк": "Какой танк? У нас тут моды, а не полигон",
    "tank": "What tank? We have mods here, not a training ground",
    "лол": "Лол принят. Возвращайся с идеями",
    "lol": "Lol accepted. Come back with ideas",
    "ааа": "Тише-тише, я тут",
    "бля": "Спокойно, без нервов. Кнопки внизу",
    "блять": "Спокойно, без нервов. Кнопки внизу",
    "мод": "Мод? Тогда тебе в «Моды» 👇",
    "mod": "Mod? Then go to 'Mods' 👇",
    "привет": "Привет-привет. Выбирай раздел ниже",
    "hello": "Hello-hello. Choose a section below",
    "hi": "Hi. What do you want? Buttons below",
    "прив": "Прив. Чё хотел? Кнопки внизу",
    "здарова": "Здарова. Чё по модам?",
    "как дела": "Всё отлично, моды пилим. А у тебя?",
    "how are you": "Doing great, making mods. And you?",
    "кто ты": "Я бот MOD_rak.rar. Раздаю моды и собираю идеи",
    "who are you": "I am the MOD_rak.rar bot. I share mods and collect ideas",
    "ты бот": "Да, и горжусь этим. Нажми кнопку",
    "помоги": "Кнопка «Помощь» в меню ниже 👇",
    "help": "The 'Help' button is in the menu below 👇",
    "где моды": "Кнопка «Моды» в меню ниже 👇",
    "where are mods": "The 'Mods' button is in the menu below 👇",
    "скачать": "Кнопка «Моды» в меню ниже 👇",
    "download": "The 'Mods' button is in the menu below 👇",
    "3 часа ночи": "Ты чего не спишь? Иди спать, моды подождут",
    "3 часа": "Ты чего не спишь? Иди спать, моды подождут",
    "ракета": "Ракета не тут. У нас раки 🦀",
    "google": "Гугли сам, я моды раздаю",
    "яндекс": "Яндекс не поможет. Только кнопки ниже",
}
EASTER_EGG_HITS = {}

# ---------- Хелперы ----------
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
        await bot.send_message(chat_id, "Временно недоступно / Time unavailable")
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

async def update_stats_message(mod_key: str):
    likes = STATS[mod_key]["likes"]
    dislikes = STATS[mod_key]["dislikes"]
    msg_id = STATS[mod_key]["msg_id"]
    mod_name = MOD_NAMES[mod_key]["ru"] # В группу статистики летит на русском
    text = f"{mod_name}\n👍 {likes} | 👎 {dislikes}"
    
    if msg_id and TARGET_CHAT_IDS:
        try:
            await bot.edit_message_text(text=text, chat_id=TARGET_CHAT_IDS[0], message_id=msg_id)
        except Exception as e:
            logger.error(f"Не удалось обновить сообщение статистики {mod_key}: {e}")
            STATS[mod_key]["msg_id"] = None
            save_stats()

# ---------- Голосование ----------
def make_vote_handler(mod_key: str, vote: str):
    async def handler(callback: CallbackQuery):
        user_id = str(callback.from_user.id)
        voters = STATS[mod_key].setdefault("voters", {})
        prev = voters.get(user_id)
        mod_name = MOD_NAMES[mod_key]["ru"] # Для админов

        if prev == vote:
            voters.pop(user_id, None)
            field = "likes" if vote == "like" else "dislikes"
            STATS[mod_key][field] = max(0, STATS[mod_key][field] - 1)
            save_stats()
            await update_stats_message(mod_key)
            await callback.answer(_(callback.from_user.id, "vote_cancelled"))
            return

        if prev == "like":
            STATS[mod_key]["likes"] = max(0, STATS[mod_key]["likes"] - 1)
        elif prev == "dislike":
            STATS[mod_key]["dislikes"] = max(0, STATS[mod_key]["dislikes"] - 1)

        voters[user_id] = vote
        emoji = "👍" if vote == "like" else "👎"
        if vote == "like":
            STATS[mod_key]["likes"] += 1
        else:
            STATS[mod_key]["dislikes"] += 1

        save_stats()
        await update_stats_message(mod_key)
        await callback.answer(_(callback.from_user.id, "vote_recorded"))

        if TARGET_CHAT_IDS:
            try:
                await bot.send_message(TARGET_CHAT_IDS[0], f"Пользователь поставил {emoji} моду «{mod_name}»")
            except Exception as exc:
                logger.error(f"Не удалось уведомить группу о голосе: {exc}")

    return handler

for _mod_key in MOD_NAMES:
    dp.callback_query.register(make_vote_handler(_mod_key, "like"), F.data == f"like_{_mod_key}")
    dp.callback_query.register(make_vote_handler(_mod_key, "dislike"), F.data == f"dislike_{_mod_key}")

# ---------- Обработчики ----------
@dp.message(F.document)
async def group_document_handler(message: Message):
    if GROUP_ID_VALUE and str(message.chat.id) == str(GROUP_ID_VALUE):
        doc = message.document
        if doc.file_name:
            FILE_IDS[doc.file_name] = doc.file_id
            save_file_ids()
            logger.info(f"Сохранен файл из группы: {doc.file_name}")
            await message.answer(f"Файл {doc.file_name} сохранен.")

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    
    if str(user_id) not in USERS:
        # Новый пользователь — сразу выбор языка
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
        _(user_id, "start", name=message.from_user.first_name),
        reply_markup=get_main_keyboard(user_id),
    )

@dp.message(Command("lang"))
async def cmd_lang(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        _(message.from_user.id, "choose_lang"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_lang_ru")],
            [InlineKeyboardButton(text="🇧🇾 Беларуская", callback_data="set_lang_be")],
            [InlineKeyboardButton(text="🇬🇧 English", callback_data="set_lang_en")],
        ])
    )

@dp.callback_query(F.data.startswith("set_lang_"))
async def cb_set_lang(callback: CallbackQuery, state: FSMContext):
    lang = callback.data.split("_")[-1]
    USERS[str(callback.from_user.id)] = lang
    save_users()
    
    await callback.message.delete()
    await callback.message.answer(
        _(callback.from_user.id, "lang_changed"),
        reply_markup=get_main_keyboard(callback.from_user.id)
    )
    await callback.answer()

@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    if await state.get_state():
        await state.clear()
        await message.answer(_(message.from_user.id, "cancel"), reply_markup=get_main_keyboard(message.from_user.id))
    else:
        await message.answer(_(message.from_user.id, "nothing_cancel"), reply_markup=get_main_keyboard(message.from_user.id))

@dp.message(F.text.in_([LOCALES["ru"]["btn_mods"], LOCALES["be"]["btn_mods"], LOCALES["en"]["btn_mods"]]))
async def btn_mods(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(_(message.from_user.id, "mods_menu"), parse_mode="HTML", reply_markup=get_mods_keyboard(message.from_user.id))

@dp.callback_query(F.data.startswith("mod_old_"))
async def cb_mod_any(callback: CallbackQuery):
    if callback.data == "mod_old_ui_info":
        await callback.answer()
        await callback.message.answer(_(callback.from_user.id, "help_why_text")) # Используем текст описания
        return
        
    await callback.answer()
    mod_key = callback.data.replace("mod_", "")
    version = "v3.0" if mod_key == "old_ui" else "v1.0"
    
    if not await check_subscription(callback.from_user.id):
        await callback.message.answer(
            _(callback.from_user.id, "subscribe_needed"),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=_(callback.from_user.id, "btn_subscribe"), url=CHANNEL_LINK)]
            ])
        )
        return
        
    await callback.message.answer(_(callback.from_user.id, "version", ver=version))
    ext = "zip" if mod_key == "old_medals" else "rar"
    await send_mod_file(callback.from_user.id, f"{mod_key}.{ext}", reply_markup=get_vote_keyboard(callback.from_user.id, mod_key))

@dp.message(F.text.in_([LOCALES["ru"]["btn_fun"], LOCALES["be"]["btn_fun"], LOCALES["en"]["btn_fun"]]))
async def btn_fun(message: Message, state: FSMContext):
    await state.set_state(UserState.awaiting_fun)
    await message.answer(_(message.from_user.id, "fun_prompt"), reply_markup=get_main_keyboard(message.from_user.id))

@dp.message(UserState.awaiting_fun, ~F.text.in_(ALL_MENU_BUTTONS))
async def receive_fun(message: Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    header = f"<b>Прикол от пользователя!</b>\n👤 {user.full_name} (@{user.username})\n🆔 <code>{user.id}</code>\n\n"
    await forward_to_admins(message, header)
    await message.answer(_(user.id, "fun_thanks"), reply_markup=get_main_keyboard(user.id))

@dp.message(F.text.in_([LOCALES["ru"]["btn_suggest"], LOCALES["be"]["btn_suggest"], LOCALES["en"]["btn_suggest"]]))
async def btn_suggest_mod(message: Message, state: FSMContext):
    await state.set_state(UserState.awaiting_mod_suggestion)
    await message.answer(_(message.from_user.id, "suggest_prompt"), parse_mode="HTML", reply_markup=get_main_keyboard(message.from_user.id))

@dp.message(UserState.awaiting_mod_suggestion, ~F.text.in_(ALL_MENU_BUTTONS))
async def receive_mod_suggestion(message: Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    header = f"<b>Новая идея от пользователя!</b>\n👤 {user.full_name} (@{user.username})\n🆔 <code>{user.id}</code>\n\n"
    await forward_to_admins(message, header)
    await message.answer(_(user.id, "suggest_thanks"), reply_markup=get_main_keyboard(user.id))

@dp.message(F.text.in_([LOCALES["ru"]["btn_bug"], LOCALES["be"]["btn_bug"], LOCALES["en"]["btn_bug"]]))
async def btn_bug_report(message: Message, state: FSMContext):
    await state.set_state(UserState.awaiting_bug_report)
    await message.answer(_(message.from_user.id, "bug_prompt"), reply_markup=get_main_keyboard(message.from_user.id))

@dp.message(UserState.awaiting_bug_report, ~F.text.in_(ALL_MENU_BUTTONS))
async def receive_bug_report(message: Message, state: FSMContext):
    if message.voice or (not message.text and not message.photo and not message.video and not message.document):
        await message.answer(_(message.from_user.id, "bug_voice"))
        return
    await state.clear()
    user = message.from_user
    header = f"<b>[ОШИБКА] Сообщение об ошибке</b>\n👤 {user.full_name} (@{user.username})\n🆔 <code>{user.id}</code>\n\n"
    await forward_to_admins(message, header)
    await message.answer(_(user.id, "bug_thanks"), reply_markup=get_main_keyboard(user.id))

@dp.message(F.text.in_([LOCALES["ru"]["btn_question"], LOCALES["be"]["btn_question"], LOCALES["en"]["btn_question"]]))
async def btn_question(message: Message, state: FSMContext):
    await state.set_state(UserState.awaiting_question)
    await message.answer(_(message.from_user.id, "question_prompt"), reply_markup=get_main_keyboard(message.from_user.id))

@dp.message(UserState.awaiting_question, ~F.text.in_(ALL_MENU_BUTTONS))
async def receive_question(message: Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    header = f"<b>Вопрос от пользователя!</b>\n👤 {user.full_name} (@{user.username})\n🆔 <code>{user.id}</code>\n\nОтветьте на это сообщение (Reply), чтобы отправить ответ пользователю."
    
    if not TARGET_CHAT_IDS:
        await message.answer(_(user.id, "question_no_group"))
        return
        
    for chat_id in TARGET_CHAT_IDS:
        try:
            await bot.send_message(chat_id, header, parse_mode="HTML")
            await message.forward(chat_id)
        except Exception as exc:
            logger.error(f"Не удалось отправить в {chat_id}. Ошибка: {exc}")
            
    await message.answer(_(user.id, "question_thanks"), reply_markup=get_main_keyboard(user.id))

@dp.message(F.text.in_([LOCALES["ru"]["btn_dev"], LOCALES["be"]["btn_dev"], LOCALES["en"]["btn_dev"]]))
async def btn_in_dev(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(_(message.from_user.id, "dev_text"), reply_markup=get_main_keyboard(message.from_user.id))

@dp.message(F.text.in_([LOCALES["ru"]["btn_donate"], LOCALES["be"]["btn_donate"], LOCALES["en"]["btn_donate"]]))
async def btn_donate(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(_(message.from_user.id, "donate_text"), reply_markup=get_main_keyboard(message.from_user.id))

# --- Помощь ---
@dp.message(F.text.in_([LOCALES["ru"]["btn_help"], LOCALES["be"]["btn_help"], LOCALES["en"]["btn_help"]]))
async def btn_help(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    await message.answer(
        _(uid, "help_menu"), 
        parse_mode="HTML", 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=_(uid, "help_install_btn"), callback_data="help_install")],
            [InlineKeyboardButton(text=_(uid, "help_remove_btn"), callback_data="help_remove")],
            [InlineKeyboardButton(text=_(uid, "help_why_btn"), callback_data="help_why")],
            [InlineKeyboardButton(text=_(uid, "help_time_btn"), callback_data="help_time")],
            [InlineKeyboardButton(text=_(uid, "help_why_old_btn"), callback_data="help_why_old")],
            [InlineKeyboardButton(text=_(uid, "help_sleep_btn"), callback_data="help_sleep")],
        ])
    )

@dp.callback_query(F.data.startswith("help_"))
async def cb_help_any(callback: CallbackQuery):
    await callback.answer()
    uid = callback.from_user.id
    key = f"{callback.data}_text"
    await callback.message.answer(_(uid, key))

# --- Разное ---
@dp.message(F.text.in_([LOCALES["ru"]["btn_misc"], LOCALES["be"]["btn_misc"], LOCALES["en"]["btn_misc"]]))
async def btn_misc(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    await message.answer(
        _(uid, "misc_menu"), 
        parse_mode="HTML", 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=_(uid, "misc_team_btn"), callback_data="misc_team")],
            [InlineKeyboardButton(text=_(uid, "misc_join_btn"), callback_data="misc_join")],
            [InlineKeyboardButton(text=_(uid, "misc_share_btn"), url="https://t.me/share/url?url=https://t.me/ModRak1_bot&text=Смотри, какой крутой бот для модов!")],
        ])
    )

@dp.callback_query(F.data.startswith("misc_"))
async def cb_misc_any(callback: CallbackQuery):
    await callback.answer()
    uid = callback.from_user.id
    key = f"{callback.data}_text"
    if callback.data == "misc_team":
        await callback.message.answer(_(uid, key), parse_mode="HTML")
    else:
        await callback.message.answer(_(uid, key))

# --- Языковая кнопка ---
@dp.message(F.text.in_([LOCALES["ru"]["btn_lang"], LOCALES["be"]["btn_lang"], LOCALES["en"]["btn_lang"]]))
async def btn_lang_click(message: Message, state: FSMContext):
    await cmd_lang(message, state)

# --- Ответы из группы ---
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
        await message.reply(f"Не удалось отправить ответ. Ошибка: {e}")

# --- Пасхалки и Fallback ---
@dp.message(F.text)
async def easter_egg_handler(message: Message, state: FSMContext):
    if await state.get_state() is not None:
        return

    text_lower = message.text.strip().lower()
    uid = message.from_user.id

    if text_lower in EASTER_EGGS:
        await message.answer(EASTER_EGGS[text_lower], reply_markup=get_main_keyboard(uid))
        return

    for trigger, reply in EASTER_EGGS.items():
        if len(trigger) >= 3 and trigger in text_lower:
            await message.answer(reply, reply_markup=get_main_keyboard(uid))
            return

    if "сломай" in text_lower or "взломай" in text_lower:
        hits = EASTER_EGG_HITS.get(uid, 0) + 1
        EASTER_EGG_HITS[uid] = hits
        if hits >= 3:
            await message.answer("Хватит меня ломать. Я и так еле держусь 🤖", reply_markup=get_main_keyboard(uid))
        else:
            await message.answer("Не сломаешь. Я крепкий", reply_markup=get_main_keyboard(uid))
        return

    # Fallback
    is_gibberish = False
    if len(text_lower) > 50 and " " not in text_lower:
        is_gibberish = True
    elif len(text_lower) < 3 or text_lower.isdigit() or not any(c.isalpha() for c in text_lower):
        is_gibberish = True

    replies_key = "gibberish" if is_gibberish else "fallback"
    replies_list = LOCALES.get(USERS.get(str(uid), "ru"), LOCALES["ru"])[replies_key]
    await message.answer(random.choice(replies_list), reply_markup=get_main_keyboard(uid))

@dp.message()
async def unknown_media(message: Message, state: FSMContext):
    if await state.get_state() is not None:
        return
    if GROUP_ID_VALUE and str(message.chat.id) == str(GROUP_ID_VALUE):
        return
    await message.answer(
        "Эт что? Я понимаю только текст и кнопки. Выбери нужный раздел на клавиатуре ниже",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

async def main():
    logger.info("Bot started")
    if TARGET_CHAT_IDS:
        for mod_key in MOD_NAMES:
            if not STATS[mod_key]["msg_id"]:
                mod_name = MOD_NAMES[mod_key]["ru"]
                msg = await bot.send_message(
                    TARGET_CHAT_IDS[0],
                    f"{mod_name}\n👍 {STATS[mod_key]['likes']} | 👎 {STATS[mod_key]['dislikes']}"
                )
                STATS[mod_key]["msg_id"] = msg.message_id
                save_stats()
                logger.info(f"Создано сообщение статистики для {mod_key} с ID: {msg.message_id}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
