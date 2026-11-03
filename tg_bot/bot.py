import asyncio
import json
import logging
import os
import random
import re
import time
from threading import Thread

from dotenv import load_dotenv
from flask import Flask

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatAction
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

from openai import AsyncOpenAI

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID_VALUE = os.getenv("CHANNEL_ID")
ADMIN_IDS_VALUE = os.getenv("ADMIN_IDS") or os.getenv("TELEGRAM_ADMIN_ID")

GROUP_ID_VALUE = os.getenv("GROUP_ID", "-1002832219010")
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/MOD_rak")

LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")

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
        ADMIN_IDS = [
            int(admin_id.strip())
            for admin_id in ADMIN_IDS_VALUE.split(",")
            if admin_id.strip()
        ]
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

llm_client = (
    AsyncOpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
    if LLM_API_KEY
    else None
)

keep_alive_app = Flask(__name__)


@keep_alive_app.route("/")
def index():
    return "Bot is running!"


def run_keep_alive():
    port = int(os.getenv("PORT", "8080"))
    keep_alive_app.run(host="0.0.0.0", port=port)


if not os.getenv("REPLIT_DEV_DOMAIN"):
    Thread(target=run_keep_alive, daemon=True).start()

FILE_IDS_PATH = "file_ids.json"
FILE_IDS = {}

STATS_PATH = "stats.json"
STATS = {
    "old_font":   {"likes": 0, "dislikes": 0, "msg_id": None, "voters": {}},
    "old_medals": {"likes": 0, "dislikes": 0, "msg_id": None, "voters": {}},
    "old_ui":     {"likes": 0, "dislikes": 0, "msg_id": None, "voters": {}},
}

MOD_NAMES = {
    "old_font": "Старый шрифт",
    "old_medals": "Старые медали",
    "old_ui": "Старый UI ангара",
}


def load_file_ids():
    global FILE_IDS
    FILE_IDS = {
        "old_font.rar": "BQACAgIAAyEFAASo0DuCAAPRaudEoy_WaUJytv6Ax-5vHj49Zk8AAqqZAAJuI4FJZH-8dxswqq09BA",
        "old_medals.zip": "BQACAgIAAyEFAASo0DuCAAPQaudEo89jj1q6kdFa5l4mjYzZCmoAAqmZAAJuI4FJly1Z9B-lN4E9BA",
        "old_ui.rar": "BQACAgIAAyEFAASo0DuCAAPSaudEozVgaEGz-USX1kCO8mw9czsAAp-qAAJqFCBLsufG1Xs4z3E9BA",
    }
    try:
        with open(FILE_IDS_PATH) as file:
            loaded = json.load(file)
            FILE_IDS.update(loaded)
    except (OSError, json.JSONDecodeError):
        pass


def save_file_ids():
    with open(FILE_IDS_PATH, "w") as file:
        json.dump(FILE_IDS, file)


def load_stats():
    global STATS
    try:
        with open(STATS_PATH) as file:
            loaded = json.load(file)
            for key in STATS:
                if key in loaded:
                    STATS[key].update(loaded[key])
                    STATS[key].setdefault("voters", {})
    except (OSError, json.JSONDecodeError):
        pass


def save_stats():
    with open(STATS_PATH, "w") as file:
        json.dump(STATS, file)


load_file_ids()
load_stats()

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Моды"), KeyboardButton(text="Приколы")],
        [KeyboardButton(text="Помощь"), KeyboardButton(text="Предложить мод")],
        [KeyboardButton(text="Идея через ИИ"), KeyboardButton(text="В разработке")],
        [KeyboardButton(text="Поддержать"), KeyboardButton(text="Сообщить об ошибке")],
        [KeyboardButton(text="Задать вопрос"), KeyboardButton(text="Разное")],
    ],
    resize_keyboard=True,
)

subscribe_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="Подписаться на канал", url=CHANNEL_LINK)]
    ]
)

mods_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="Старый шрифт (v1.0)", callback_data="mod_old_font")],
        [InlineKeyboardButton(text="Старые медали (v1.0)", callback_data="mod_old_medals")],
        [InlineKeyboardButton(text="Старый UI ангара (v3.0)", callback_data="mod_old_ui")],
    ]
)

font_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="👍 Лайк", callback_data="like_old_font"),
         InlineKeyboardButton(text="👎 Дизлайк", callback_data="dislike_old_font")]
    ]
)

medals_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="👍 Лайк", callback_data="like_old_medals"),
         InlineKeyboardButton(text="👎 Дизлайк", callback_data="dislike_old_medals")]
    ]
)

ui_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="Описание мода", callback_data="mod_old_ui_info")],
        [InlineKeyboardButton(text="👍 Лайк", callback_data="like_old_ui"),
         InlineKeyboardButton(text="👎 Дизлайк", callback_data="dislike_old_ui")]
    ]
)

help_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="Как установить мод", callback_data="help_install")],
        [InlineKeyboardButton(text="Как удалить мод", callback_data="help_remove")],
        [InlineKeyboardButton(text="Зачем нужны данные модификации", callback_data="help_why")],
        [InlineKeyboardButton(text="Сколько разрабатываются моды", callback_data="help_time")],
        [InlineKeyboardButton(text="Почему моды только на возвращение старого в игру", callback_data="help_why_old")],
        [InlineKeyboardButton(text="Бот не отвечает", callback_data="help_sleep")],
    ]
)

misc_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="О команде MOD_rak.rar", callback_data="misc_team")],
        [InlineKeyboardButton(text="Можно ли присоединиться к вам", callback_data="misc_join")],
        [InlineKeyboardButton(text="Поделиться ботом", url="https://t.me/share/url?url=https://t.me/ModRak1_bot&text=Смотри, какой крутой бот для модов!")],
    ]
)

idea_result_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="Ещё вариант", callback_data="idea_more")],
        [InlineKeyboardButton(text="Отправить админам", callback_data="idea_send")],
    ]
)


class UserState(StatesGroup):
    awaiting_mod_suggestion = State()
    awaiting_fun = State()
    awaiting_bug_report = State()
    awaiting_question = State()
    awaiting_idea = State()


# ---------- Фразы для непонятных сообщений ----------
FALLBACK_REPLIES = [
    "Тут я бессилен. Кнопки внизу выручат",
    "Не догнал тебя. Жми кнопку из меню",
    "Такое мне не по зубам. Выбери раздел на клавиатуре",
    "Я в замешательстве. Кнопки ниже помогут",
    "Ты говоришь загадками. А я понимаю только кнопки",
    "Не уловил мысль. Попробуй через меню",
    "Моя голова не варит. Тыкай кнопку ниже",
    "Что-то я подвис. Клавиатура внизу спасёт",
    "Не понял ни слова. Меню в помощь",
    "Я всего лишь бот. Нажми кнопку из списка",
    "Текст сложный. А кнопки простые",
    "Не разобрал. Выбери нужный раздел внизу",
    "Это выше моего понимания. Кнопки рулят",
    "Не осилил. Давай через меню",
    "Я потерялся в твоих словах. Кнопки выведут",
    "Не врубился. Нажми что-нибудь ниже",
    "Мозг кипит. Просто выбери раздел",
    "Не догоняю. Клавиатура внизу подскажет",
    "Такие ребусы не для меня. Жми кнопку",
    "Не понял. Меню всегда открыто",
    "Я не настолько умный. Кнопки спасут",
    "Путаница какая-то. Выбери раздел ниже",
    "Не уловил суть. Клавиатура рядом",
    "Мои схемы не сработали. Жми кнопку",
    "Слишком сложно. А кнопки — просто",
    "Не разгадал. Меню тебе в руки",
    "Тут без кнопок не разобраться",
    "Не понял тебя. Давай по-простому, через меню",
    "Я в тупике. Кнопки внизу выведут",
    "Не улавливаю. Выбери что-то из списка",
    "Сдаюсь. Кнопки ниже — мой единственный шанс",
    "Не понял, хоть убей. Жми кнопку",
    "Твои слова для меня тёмный лес. Меню рядом",
    "Не догнал. Клавиатура всегда под рукой",
    "Не разобрал. Меню внизу не кусается",
    "Запутался. Кнопки — мой компас",
    "Не понял. Просто нажми на кнопку",
    "Не въехал. Меню подскажет",
    "Тут я пас. Кнопки выручат",
    "Мозг отказал. Жми кнопку из меню",
    "Не уловил. Клавиатура внизу ждёт",
    "Слишком мудрёно. А кнопки простые",
    "Не осилил. Давай через меню",
    "Я в ступоре. Кнопки ниже помогут",
    "Не понял. Выбери раздел на клавиатуре",
    "Сложновато для меня. Жми кнопку",
    "Не догнал. Меню всегда рядом",
    "Тут я не советчик. Кнопки решат",
    "Не разобрался. Клавиатура спасёт",
    "Я сдаюсь. Просто нажми на кнопку",
    "Не понял. Меню тебе в помощь",
    "Не уловил мысль. Кнопки ниже",
    "Загадка для меня. Жми кнопку из списка",
    "Не врубился. Меню под рукой",
    "Мозг не справился. Клавиатура выручит",
    "Не понял ни капли. Выбери раздел",
    "Слишком заумно. А кнопки — ясно",
    "Не догнал. Кнопки внизу ждут",
    "Не разобрал. Меню всегда открыто",
    "Тут я бессилен. Жми кнопку",
    "Не уловил. Клавиатура подскажет",
    "Не понял. Давай по кнопкам",
    "Я в раздумьях. Меню внизу",
    "Не осилил. Просто нажми на кнопку",
    "Сложно слишком. Кнопки спасут",
    "Не догнал. Меню рядом",
    "Не понял. Клавиатура внизу выручит",
    "Запутался вконец. Жми кнопку",
    "Не разобрался. Меню под рукой",
    "Тут я мимо. Кнопки решат",
    "Не уловил. Выбери раздел внизу",
    "Мозг в отпуске. Кнопки работают",
    "Не понял. Жми кнопку из меню",
    "Слишком витиевато. А кнопки прямые",
    "Не догнал. Клавиатура рядом",
    "Не осилил. Меню в помощь",
    "Я в тупике. Жми кнопку",
    "Не понял. Кнопки внизу спасут",
    "Не разобрал. Меню всегда рядом",
    "Тут я слаб. Клавиатура выручит",
    "Не уловил. Жми кнопку из списка",
    "Не въехал. Меню подскажет",
    "Мозг перегрелся. Кнопки остужают",
    "Не понял. Выбери раздел на клавиатуре",
    "Слишком сложно. Кнопки — просто",
    "Не догнал. Меню внизу ждёт",
    "Не разобрался. Жми кнопку",
    "Тут я не помощник. Клавиатура спасёт",
    "Не уловил. Кнопки ниже",
    "Не понял. Меню тебе в руки",
    "Я в ступоре. Жми кнопку",
    "Не осилил. Клавиатура рядом",
    "Слишком мудрёно. А кнопки простые",
    "Не догнал. Меню всегда открыто",
    "Не разобрал. Кнопки выручат",
    "Тут я пас. Жми кнопку из меню",
    "Не уловил. Клавиатура внизу",
    "Не понял. Просто нажми на кнопку",
    "Запутался. Меню подскажет",
    "Не въехал. Кнопки решат",
    "Сдаюсь. Меню внизу",
    "Не догнал. Жми кнопку",
    "Не понял. Клавиатура выручит",
    "Тут я бессилен. Выбери раздел",
]

GIBBERISH_REPLIES = [
    "Братан, может скорую",
    "Это что за набор символов",
    "Ты с клавиатурой поссорился",
    "Кот по клавишам прошёлся",
    "Я такое не читаю",
    "Эт что за шифр",
    "Может, тебе помочь набрать",
    "Клавиатуру протри",
    "Тут буквы потерялись",
    "Я в этом не разбираюсь",
    "Ты на связи",
    "Алле, гараж",
    "Что-то сломалось, да",
    "Это код какой-то",
    "Ты мне голову не ломай",
    "Я такое не ем",
    "Давай по-человечески",
    "Тут я мимо",
    "Кнопки нажми, полегчает",
    "Эт что за абракадабра",
    "Ты случайно отправил, да",
    "Я не понимаю этот язык",
    "Может, отдохнёшь",
    "Клавиши залипли",
    "Тут ничего не разобрать",
    "Это не текст, это шум",
    "Ты как вообще",
    "Я в замешательстве",
    "Может, кнопку нажмёшь",
    "Тут явно что-то не так",
    "Братан, ты в порядке",
    "Это какой-то сбой",
    "Не пугай меня",
    "Я такое не читаю",
    "Ты в себе",
    "Может, чайку",
    "Эт что за дела",
    "Тут без бутылки не разобраться",
    "Ты меня пугаешь",
    "Кнопки ниже, не благодари",
    "Я такое видел впервые",
    "Может, тебе помочь",
    "Тут что-то пошло не так",
    "Ты не туда попал",
    "Я в шоке",
    "Давай ещё раз",
    "Не понял ни капли",
    "Эт что за крик души",
    "Ты меня не провести",
    "Может, отдохнём",
    "Я такое не пишу",
    "Тут я не советчик",
    "Ты какую кнопку жал",
    "Что-то с клавиатурой",
    "Может, попробуешь снова",
    "Ты меня не пугай",
    "Эт что за набор",
    "Я в недоумении",
    "Кнопки внизу спасут",
    "Тут без пол-литры не понять",
    "Может, проще надо",
    "Я не настолько умный",
    "Ты в порядке вообще",
    "Эт что за дела такие",
    "Может, тебе помочь с чем-то",
    "Тут что-то не так",
    "Я в ступоре",
    "Ты меня не проведёшь",
    "Кнопку нажми, полегчает",
    "Может, передохнём",
    "Эт что за шифровка",
    "Я такое не разберу",
    "Тут я бессилен",
    "Ты случайно не туда",
    "Может, попробуешь ещё",
    "Я в шоке, если честно",
    "Ты как вообще это набрал",
    "Эт что за чудо",
    "Может, кнопки нажмёшь",
    "Тут без бутылки не разобраться",
    "Я такое не читаю",
    "Ты меня пугаешь",
    "Кнопки ниже, не благодари",
    "Может, отдохнёшь",
    "Я в недоумении",
    "Эт что за набор символов",
    "Тут я мимо",
    "Ты не туда попал",
    "Может, чайку",
    "Я в замешательстве",
    "Эт что за дела",
    "Тут без пол-литры не понять",
    "Может, проще надо",
    "Я не настолько умный",
    "Ты в порядке вообще",
    "Эт что за дела такие",
    "Может, тебе помочь с чем-то",
    "Тут что-то не так",
    "Я в ступоре",
    "Кнопку нажми, полегчает",
]


# ---------- Пасхалки ----------
EASTER_EGGS = {
    "рак": "Сам такой 🦀",
    "рак?": "Сам такой 🦀",
    "sudo": "Доступ запрещён. Хорошая попытка 😎",
    "sudo su": "Ты кто такой? Иди сюда",
    "старый": "Старый — это классика. Ты наш человек",
    "картошка": "Сервера картошки — отдельный вид искусства",
    "танк": "Какой танк? У нас тут моды, а не полигон",
    "лол": "Лол принят. Возвращайся с идеями",
    "ааа": "Тише-тише, я тут",
    "бля": "Спокойно, без нервов. Кнопки внизу",
    "блять": "Спокойно, без нервов. Кнопки внизу",
    "мод": "Мод? Тогда тебе в «Моды» 👇",
    "привет": "Привет-привет. Выбирай раздел ниже",
    "прив": "Прив. Чё хотел? Кнопки внизу",
    "здарова": "Здарова. Чё по модам?",
    "как дела": "Всё отлично, моды пилим. А у тебя?",
    "кто ты": "Я бот MOD_rak.rar. Раздаю моды и собираю идеи",
    "ты бот": "Да, и горжусь этим. Нажми кнопку",
    "помоги": "Кнопка «Помощь» в меню ниже 👇",
    "где моды": "Кнопка «Моды» в меню ниже 👇",
    "скачать": "Кнопка «Моды» в меню ниже 👇",
    "3 часа ночи": "Ты чего не спишь? Иди спать, моды подождут",
    "3 часа": "Ты чего не спишь? Иди спать, моды подождут",
    "ракета": "Ракета не тут. У нас раки 🦀",
    "google": "Гугли сам, я моды раздаю",
    "яндекс": "Яндекс не поможет. Только кнопки ниже",
}

EASTER_EGG_HITS = {}


# ---------- ИИ-генератор идей ----------
IDEA_SYSTEM_PROMPT = (
    "Ты — креативный мододел из команды MOD_rak.rar для игры Tanks Blitz. "
    "Пользователь описывает, какой мод он хочет. Придумай концепт мода. "
    "Ответ строго в формате:\n"
    "Название: <короткое цепляющее название>\n"
    "Суть: <1-2 предложения, что делает мод>\n"
    "Что меняет: <2-4 пункта через •>\n"
    "Сложность: <Низкая/Средняя/Высокая>\n\n"
    "Без эмодзи. Без лишних вступлений. Пиши по-русски, коротко и по делу."
)

IDEA_CACHE: dict[int, dict] = {}
IDEA_LAST_CALL: dict[int, float] = {}
IDEA_COOLDOWN = 10  # секунд


async def generate_idea(user_prompt: str) -> str:
    if not llm_client:
        return (
            "Название: Мод по заявке\n"
            f"Суть: {user_prompt}\n"
            "Что меняет: • Тут будет твоя идея\n"
            "Сложность: Средняя\n\n"
            "(ИИ не подключён — админ увидит сырой запрос)"
        )
    resp = await llm_client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": IDEA_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.9,
        max_tokens=300,
    )
    return resp.choices[0].message.content.strip()


# ---------- Утилиты ----------
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
        await bot.send_message(chat_id, "Временно недоступно")
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


async def update_stats_message(mod_key: str, mod_name: str):
    likes = STATS[mod_key]["likes"]
    dislikes = STATS[mod_key]["dislikes"]
    msg_id = STATS[mod_key]["msg_id"]
    text = f"{mod_name}\n👍 {likes} | 👎 {dislikes}"

    if msg_id and TARGET_CHAT_IDS:
        try:
            await bot.edit_message_text(
                text=text,
                chat_id=TARGET_CHAT_IDS[0],
                message_id=msg_id,
            )
        except Exception as e:
            logger.error(f"Не удалось обновить сообщение статистики {mod_key}: {e}")
            STATS[mod_key]["msg_id"] = None
            save_stats()


# ---------- Голосование ----------
def make_vote_handler(mod_key: str, mod_name: str, vote: str):
    async def handler(callback: CallbackQuery):
        user_id = str(callback.from_user.id)
        voters = STATS[mod_key].setdefault("voters", {})
        prev = voters.get(user_id)

        if prev == vote:
            voters.pop(user_id, None)
            field = "likes" if vote == "like" else "dislikes"
            STATS[mod_key][field] = max(0, STATS[mod_key][field] - 1)
            save_stats()
            await update_stats_message(mod_key, mod_name)
            await callback.answer("Голос отменён")
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
        await update_stats_message(mod_key, mod_name)
        await callback.answer("Голос учтён!")

        if TARGET_CHAT_IDS:
            try:
                await bot.send_message(
                    TARGET_CHAT_IDS[0],
                    f"Пользователь поставил {emoji} моду «{mod_name}»",
                )
            except Exception as exc:
                logger.error(f"Не удалось уведомить группу о голосе: {exc}")

    return handler


for _mod_key, _mod_name in MOD_NAMES.items():
    dp.callback_query.register(
        make_vote_handler(_mod_key, _mod_name, "like"),
        F.data == f"like_{_mod_key}",
    )
    dp.callback_query.register(
        make_vote_handler(_mod_key, _mod_name, "dislike"),
        F.data == f"dislike_{_mod_key}",
    )


MENU_BUTTONS = {
    "Моды", "Приколы", "Помощь", "Предложить мод",
    "Идея через ИИ", "В разработке", "Поддержать",
    "Сообщить об ошибке", "Задать вопрос", "Разное",
}


# ---------- Обработчики ----------
@dp.message(F.document)
async def group_document_handler(message: Message):
    if GROUP_ID_VALUE and str(message.chat.id) == str(GROUP_ID_VALUE):
        doc = message.document
        if doc.file_name:
            FILE_IDS[doc.file_name] = doc.file_id
            save_file_ids()
            logger.info(f"Сохранен файл из группы: {doc.file_name} | FILE_ID: {doc.file_id}")
            await message.answer(f"Файл {doc.file_name} сохранен.")


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        f"Привет, {message.from_user.first_name}!\n\n"
        "Добро пожаловать! Выбери нужный раздел:",
        reply_markup=main_keyboard,
    )


@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    if await state.get_state():
        await state.clear()
        await message.answer("Отменено. Возвращаюсь в главное меню.", reply_markup=main_keyboard)
    else:
        await message.answer("Нечего отменять.", reply_markup=main_keyboard)


@dp.message(F.text == "Моды")
async def btn_mods(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("<b>Моды</b>\n\nВыбери мод:", parse_mode="HTML", reply_markup=mods_keyboard)


@dp.callback_query(F.data == "mod_old_font")
async def cb_old_font(callback: CallbackQuery):
    await callback.answer()
    if not await check_subscription(callback.from_user.id):
        await callback.message.answer(
            "Чтобы скачать этот мод, пожалуйста, подпишись на наш канал!",
            reply_markup=subscribe_keyboard,
        )
        return
    await callback.message.answer("Версия мода: v1.0")
    await send_mod_file(callback.from_user.id, "old_font.rar", reply_markup=font_keyboard)


@dp.callback_query(F.data == "mod_old_medals")
async def cb_old_medals(callback: CallbackQuery):
    await callback.answer()
    if not await check_subscription(callback.from_user.id):
        await callback.message.answer(
            "Чтобы скачать этот мод, пожалуйста, подпишись на наш канал!",
            reply_markup=subscribe_keyboard,
        )
        return
    await callback.message.answer("Версия мода: v1.0")
    await send_mod_file(callback.from_user.id, "old_medals.zip", reply_markup=medals_keyboard)


@dp.callback_query(F.data == "mod_old_ui")
async def cb_old_ui(callback: CallbackQuery):
    await callback.answer()
    if not await check_subscription(callback.from_user.id):
        await callback.message.answer(
            "Чтобы скачать этот мод, пожалуйста, подпишись на наш канал!",
            reply_markup=subscribe_keyboard,
        )
        return
    await callback.message.answer("Версия мода: v3.0")
    await send_mod_file(callback.from_user.id, "old_ui.rar", reply_markup=ui_keyboard)


@dp.callback_query(F.data == "mod_old_ui_info")
async def cb_old_ui_info(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "Данный мод возвращает:\n"
        "・ Старую кнопку выбора режима\n"
        "・ Старый UI хранилища\n"
        "・ Старую кнопку магазина\n"
        "・ Старую левую панель\n"
        "・ Старую кнопку «Тренироваться»\n"
        "・ Старую кнопку «В Бой»\n"
        "・ Убраны новые чёрные точки на фоне кнопок боя/выбора режима/взвода\n"
        "・ Старые иконки для режимов\n"
        "・ Старые иконки победы/поражения/ничьи во вкладке уведомлений\n"
        "・ Старые звуки при нажатии кнопок/иконок в ангаре\n"
        "・ Старые кнопки (зелёные, красные)\n"
        "・ Старый UI дерева исследования\n"
        "・ Старый UI окна уведомлений\n"
        "・ Всякие мелочи"
    )


@dp.message(F.text == "Приколы")
async def btn_fun(message: Message, state: FSMContext):
    await state.set_state(UserState.awaiting_fun)
    await message.answer(
        "Кидай свой игровой прикол сюда!\n\n"
        "Это может быть:\n"
        "• Забавный момент из боя\n"
        "• Необычная ситуация с физикой игры\n"
        "• Смешной баг или совпадение\n"
        "• Любой другой забавный случай из игры\n\n"
        "Отправляй хоть видео, хоть фото, хоть текст\n"
        "Для отмены напиши /cancel",
        reply_markup=main_keyboard,
    )


@dp.message(UserState.awaiting_fun, ~F.text.in_(MENU_BUTTONS))
async def receive_fun(message: Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    username = f"@{user.username}" if user.username else "нет username"
    header = (
        "<b>Прикол от пользователя!</b>\n"
        f"👤 {user.full_name} ({username})\n"
        f"🆔 <code>{user.id}</code>\n\n"
    )
    await forward_to_admins(message, header)
    await message.answer(
        "Спасибо! Твой прикол принят. Когда его проверят модераторы, он попадёт в наш канал.",
        reply_markup=main_keyboard,
    )


@dp.message(F.text == "Помощь")
async def btn_help(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("<b>Помощь</b>\n\nВыбери вопрос:", parse_mode="HTML", reply_markup=help_keyboard)


@dp.callback_query(F.data == "help_install")
async def cb_help_install(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "Как установить мод:\n\nШаг 1. Скачать мод с официального сайта For Blitz или в нашем боте\n"
        "Шаг 1.1. Установки модов на телефон нету, если нужно, то используйте инструкцию/приложения от For Blitz\n"
        "Обрати внимание, моды в этом боте только на ПК\n"
        "Шаг 2. Распаковать архив или просто зайти в него\n"
        "Шаг 3. Скопировать папку Data\n"
        "Шаг 4. Зайти в папку игры: C:\\Games\\Tanks Blitz\n"
        "Шаг 5. Нажать вставить скопированную папку Data с заменой"
    )


@dp.callback_query(F.data == "help_remove")
async def cb_help_remove(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer("Как удалить мод:\n\nСамый простой способ — нажать в приложении LGC восстановление игры")


@dp.callback_query(F.data == "help_why")
async def cb_help_why(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "Зачем нужны данные модификации:\n\nМоды возвращают удалённые функции и интерфейс, "
        "к которым привыкли игроки. Это делает игру комфортнее и привычнее для тех, кто играл раньше."
    )


@dp.callback_query(F.data == "help_time")
async def cb_help_time(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "Сколько разрабатываются моды:\n\nВремя разработки зависит от размера мода, сложности, "
        "свободного времени у мододелов, а также от того, насколько часто бывают бухие сервера у картошки"
    )


@dp.callback_query(F.data == "help_why_old")
async def cb_help_why_old(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "Почему модификации только на возвращение старого в игру:\n\nНастальгия у всей команды по старой игре"
    )


@dp.callback_query(F.data == "help_sleep")
async def cb_help_sleep(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "Бот не отвечает?\n\n"
        "Не пугайся! У нашего бота есть свой график работы (техобслуживание серверов). "
        "Обычно перерыв длится не больше часа. Пожалуйста, попробуй написать чуть позже!"
    )


@dp.message(F.text == "Предложить мод")
async def btn_suggest_mod(message: Message, state: FSMContext):
    await state.set_state(UserState.awaiting_mod_suggestion)
    await message.answer(
        "<b>Предложить идею для мода</b>\n\n"
        "Напиши описание мода и как что работает, фото/видео/голосовые/видеосообщения не принимаются.\n"
        "Оно будет переслано администратору.\n\n"
        "Для отмены напиши /cancel",
        parse_mode="HTML",
    )


@dp.message(UserState.awaiting_mod_suggestion, ~F.text.in_(MENU_BUTTONS))
async def receive_mod_suggestion(message: Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    username = f"@{user.username}" if user.username else "нет username"
    header = (
        "<b>Новая идея от пользователя!</b>\n"
        f"👤 {user.full_name} ({username})\n"
        f"🆔 <code>{user.id}</code>\n\n"
    )
    await forward_to_admins(message, header)
    await message.answer("Твоя идея отправлена на рассмотрение! Спасибо!", reply_markup=main_keyboard)


# ---------- ИИ-генератор: хендлеры ----------
@dp.message(Command("idea"))
async def cmd_idea(message: Message, state: FSMContext):
    await state.set_state(UserState.awaiting_idea)
    await message.answer(
        "Опиши, какой мод хочешь. Например:\n"
        "«старые иконки танков в ангаре»\n"
        "«вернуть старую музыку в меню»\n\n"
        "Я придумаю концепт и оформлю идею. Для отмены /cancel",
        reply_markup=main_keyboard,
    )


@dp.message(F.text == "Идея через ИИ")
async def btn_idea_ai(message: Message, state: FSMContext):
    await cmd_idea(message, state)


@dp.message(UserState.awaiting_idea, ~F.text.in_(MENU_BUTTONS))
async def receive_idea(message: Message, state: FSMContext):
    await state.clear()
    prompt = message.text.strip()
    if len(prompt) < 3:
        await message.answer("Слишком коротко. Опиши идею подробнее.")
        return

    # rate-limit
    now = time.time()
    last = IDEA_LAST_CALL.get(message.from_user.id, 0)
    if now - last < IDEA_COOLDOWN:
        wait = int(IDEA_COOLDOWN - (now - last))
        await message.answer(
            f"Не так быстро. Подожди {wait} сек и попробуй снова",
            reply_markup=main_keyboard,
        )
        return
    IDEA_LAST_CALL[message.from_user.id] = now

    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    try:
        idea = await generate_idea(prompt)
    except Exception as e:
        logger.error(f"LLM error: {e}")
        idea = None

    if not idea:
        await message.answer(
            "ИИ сейчас недоступен. Напиши идею обычным текстом через «Предложить мод».",
            reply_markup=main_keyboard,
        )
        return

    IDEA_CACHE[message.from_user.id] = {"prompt": prompt, "last_idea": idea}

    await message.answer(
        f"<b>Твой концепт:</b>\n\n{idea}",
        parse_mode="HTML",
        reply_markup=idea_result_keyboard,
    )


@dp.callback_query(F.data == "idea_more")
async def cb_idea_more(callback: CallbackQuery):
    data = IDEA_CACHE.get(callback.from_user.id)
    if not data:
        await callback.answer("Сначала опиши идею через /idea", show_alert=True)
        return

    now = time.time()
    last = IDEA_LAST_CALL.get(callback.from_user.id, 0)
    if now - last < IDEA_COOLDOWN:
        wait = int(IDEA_COOLDOWN - (now - last))
        await callback.answer(f"Подожди {wait} сек", show_alert=True)
        return
    IDEA_LAST_CALL[callback.from_user.id] = now

    await callback.answer("Генерирую ещё вариант...")
    await bot.send_chat_action(callback.message.chat.id, ChatAction.TYPING)

    try:
        idea = await generate_idea(
            data["prompt"] + " (сделай другой вариант, не похожий на предыдущий)"
        )
    except Exception as e:
        logger.error(f"LLM error: {e}")
        await callback.message.answer("ИИ задумался. Попробуй чуть позже.")
        return

    data["last_idea"] = idea
    await callback.message.answer(
        f"<b>Ещё вариант:</b>\n\n{idea}",
        parse_mode="HTML",
        reply_markup=idea_result_keyboard,
    )


@dp.callback_query(F.data == "idea_send")
async def cb_idea_send(callback: CallbackQuery):
    data = IDEA_CACHE.get(callback.from_user.id)
    if not data:
        await callback.answer("Нет идеи для отправки", show_alert=True)
        return

    user = callback.from_user
    username = f"@{user.username}" if user.username else "нет username"
    header = (
        "<b>💡 Идея от ИИ-генератора</b>\n"
        f"👤 {user.full_name} ({username})\n"
        f"🆔 <code>{user.id}</code>\n\n"
        f"<b>Запрос:</b> {data['prompt']}\n\n"
        f"<b>Концепт:</b>\n{data['last_idea']}"
    )

    if not TARGET_CHAT_IDS:
        await callback.answer("Группа не настроена", show_alert=True)
        return

    for chat_id in TARGET_CHAT_IDS:
        try:
            await bot.send_message(chat_id, header, parse_mode="HTML")
        except Exception as exc:
            logger.error(f"Не удалось отправить идею в {chat_id}: {exc}")

    await callback.message.answer(
        "Идея отправлена админам! Спасибо.",
        reply_markup=main_keyboard,
    )
    await callback.answer()


# ---------- Остальные разделы ----------
@dp.message(F.text == "В разработке")
async def btn_in_dev(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Сейчас в разработке:\n\n"
        "• Мод на старое окно шансов\n"
        "• Старое окно выбора режима\n"
        "• Старое окно ТТХ танка \n\n"
        "И всё из этого может и не выйти\n"
        "Данный список, это набросок планируемых модов. Что-то выйдет, что-то нет",
        reply_markup=main_keyboard,
    )


@dp.message(F.text == "Поддержать")
async def btn_donate(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Поддержать разработку модов\n\n"
        "• Расскажи о нашем канале и боте друзьям\n"
        "• Предложи идею для нового мода\n",
        reply_markup=main_keyboard,
    )


@dp.message(F.text == "Сообщить об ошибке")
async def btn_bug_report(message: Message, state: FSMContext):
    await state.set_state(UserState.awaiting_bug_report)
    await message.answer(
        "Опиши ошибку в моде. Напиши название мода и что именно не так, всё будет передано парням из дружного коллектива MOD_rak.rar.\n"
        "Для отмены напиши /cancel",
        reply_markup=main_keyboard,
    )


@dp.message(UserState.awaiting_bug_report, ~F.text.in_(MENU_BUTTONS))
async def receive_bug_report(message: Message, state: FSMContext):
    if message.voice or (not message.text and not message.photo and not message.video and not message.document):
        await message.answer("Напиши подробности текстом и по возможности фото или видео. Голосовые и пустые сообщения не принимаются.")
        return
    await state.clear()
    user = message.from_user
    username = f"@{user.username}" if user.username else "нет username"
    header = (
        "<b>[ОШИБКА] Сообщение об ошибке</b>\n"
        f"👤 {user.full_name} ({username})\n"
        f"🆔 <code>{user.id}</code>\n\n"
    )
    await forward_to_admins(message, header)
    await message.answer(
        "Спасибо, сообщение об ошибке передано разработчикам. Постараемся исправить в ближайшее время.",
        reply_markup=main_keyboard,
    )


@dp.message(F.text == "Задать вопрос")
async def btn_question(message: Message, state: FSMContext):
    await state.set_state(UserState.awaiting_question)
    await message.answer(
        "Задай свой вопрос, и мы ответим тебе прямо здесь!\n"
        "Напиши свой вопрос или опиши проблему.\n"
        "Для отмены напиши /cancel",
        reply_markup=main_keyboard,
    )


@dp.message(UserState.awaiting_question, ~F.text.in_(MENU_BUTTONS))
async def receive_question(message: Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    username = f"@{user.username}" if user.username else "нет username"

    header = (
        "<b>Вопрос от пользователя!</b>\n"
        f"👤 {user.full_name} ({username})\n"
        f"🆔 <code>{user.id}</code>\n\n"
        "Ответьте на это сообщение (Reply), чтобы отправить ответ пользователю."
    )

    if not TARGET_CHAT_IDS:
        await message.answer("Ошибка: группа для заявок не настроена.")
        return

    for chat_id in TARGET_CHAT_IDS:
        try:
            await bot.send_message(chat_id, header, parse_mode="HTML")
            await message.forward(chat_id)
        except Exception as exc:
            logger.error(f"Не удалось отправить в {chat_id}. Ошибка: {exc}")

    await message.answer(
        "Твой вопрос отправлен! Ожидай ответа здесь.",
        reply_markup=main_keyboard,
    )


@dp.message(F.text == "Разное")
async def btn_misc(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "<b>Разное</b>\n\nВыбери интересующий вопрос:",
        parse_mode="HTML",
        reply_markup=misc_keyboard,
    )


@dp.callback_query(F.data == "misc_team")
async def cb_misc_team(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "<b>О команде</b>\n\n"
        "Мы парни-мододелы\n"
        "Мы те, кто могут отстоять точку зрения\n"
        "А наша точка зрения — это старый вид игры\n"
        "И мы не собираемся от неё отступать",
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "misc_join")
async def cb_misc_join(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "К сожалению, набор в команду сейчас закрыт. Чтобы делать эти моды, "
        "нужно именно то настроение/цель, что есть у наших ребят, а выяснять есть ли это у вас, нет возможности, мы сейчас полностью укомплектованы и "
        "сфокусированы на текущих проектах.\n\n"
        "Но ты всегда можешь предложить идею для мода через главное меню!"
    )


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
        await bot.send_message(
            user_id,
            f"<b>Ответ от поддержки:</b>\n\n{message.text}",
            parse_mode="HTML",
        )
        await message.reply("Ответ успешно отправлен пользователю!")
    except Exception as e:
        await message.reply(f"Не удалось отправить ответ (возможно, пользователь заблокировал бота). Ошибка: {e}")


# ---------- Пасхалки (регистрируются ВЫШЕ fallback'а) ----------
@dp.message(F.text)
async def easter_egg_handler(message: Message, state: FSMContext):
    if await state.get_state() is not None:
        return

    text_lower = message.text.strip().lower()

    # точное совпадение
    if text_lower in EASTER_EGGS:
        await message.answer(EASTER_EGGS[text_lower], reply_markup=main_keyboard)
        return

    # подстрока (триггеры длиной >= 3 символов)
    for trigger, reply in EASTER_EGGS.items():
        if len(trigger) >= 3 and trigger in text_lower:
            await message.answer(reply, reply_markup=main_keyboard)
            return

    # «сломай бота» — счётчик
    if "сломай" in text_lower or "взломай" in text_lower:
        hits = EASTER_EGG_HITS.get(message.from_user.id, 0) + 1
        EASTER_EGG_HITS[message.from_user.id] = hits
        if hits >= 3:
            await message.answer(
                "Хватит меня ломать. Я и так еле держусь 🤖",
                reply_markup=main_keyboard,
            )
        else:
            await message.answer("Не сломаешь. Я крепкий", reply_markup=main_keyboard)
        return

    # если не пасхалка — отдаём в общий fallback
    await fallback_reply(message)


# ---------- Fallback ----------
async def fallback_reply(message: Message):
    text = message.text.strip()
    is_gibberish = False

    if len(text) > 50 and " " not in text:
        is_gibberish = True
    elif len(text) < 3 or text.isdigit() or not any(c.isalpha() for c in text):
        is_gibberish = True

    replies = GIBBERISH_REPLIES if is_gibberish else FALLBACK_REPLIES
    await message.answer(random.choice(replies), reply_markup=main_keyboard)


@dp.message()
async def unknown_media(message: Message, state: FSMContext):
    if await state.get_state() is not None:
        return

    if GROUP_ID_VALUE and str(message.chat.id) == str(GROUP_ID_VALUE):
        return

    await message.answer(
        "Эт что? Я понимаю только текст и кнопки. "
        "Пожалуйста, выбери нужный раздел на клавиатуре ниже",
        reply_markup=main_keyboard,
    )


async def main():
    logger.info("Bot started")

    if TARGET_CHAT_IDS:
        for mod_key, mod_name in MOD_NAMES.items():
            if not STATS[mod_key]["msg_id"]:
                msg = await bot.send_message(
                    TARGET_CHAT_IDS[0],
                    f"{mod_name}\n👍 {STATS[mod_key]['likes']} | 👎 {STATS[mod_key]['dislikes']}",
                )
                STATS[mod_key]["msg_id"] = msg.message_id
                save_stats()
                logger.info(f"Создано сообщение статистики для {mod_key} с ID: {msg.message_id}")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
