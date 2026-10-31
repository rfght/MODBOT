import asyncio
import json
import logging
import os
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

GROUP_ID_VALUE = "-1002832219010" 

# СЮДА ВПИШИ ССЫЛКУ НА ТВОЙ КАНАЛ (например, "https://t.me/my_channel")
CHANNEL_LINK = "https://t.me/MOD_rak" 

if not BOT_TOKEN:
    raise RuntimeError("Missing required environment variable: BOT_TOKEN")

# CHANNEL_ID
CHANNEL_ID = None
if CHANNEL_ID_VALUE:
    try:
        CHANNEL_ID = int(CHANNEL_ID_VALUE)
    except ValueError:
        CHANNEL_ID = CHANNEL_ID_VALUE

# ADMIN_IDS
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

# Формируем список получателей для пересылки (ТОЛЬКО группа)
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

FILE_IDS_PATH = "file_ids.json"
FILE_IDS = {}

def load_file_ids():
    global FILE_IDS
    try:
        with open(FILE_IDS_PATH) as file:
            FILE_IDS = json.load(file)
    except (OSError, json.JSONDecodeError):
        FILE_IDS = {}

def save_file_ids():
    with open(FILE_IDS_PATH, "w") as file:
        json.dump(FILE_IDS, file)

load_file_ids()

# --- КЛАВИАТУРЫ ---
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Моды"), KeyboardButton(text="Приколы")],
        [KeyboardButton(text="Помощь"), KeyboardButton(text="Предложить мод")],
        [KeyboardButton(text="В разработке"), KeyboardButton(text="Поддержать")],
        [KeyboardButton(text="Сообщить об ошибке"), KeyboardButton(text="Разное")],
    ],
    resize_keyboard=True,
)

# Кнопка подписки (появится, если человек не подписан)
subscribe_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="Подписаться на канал", url=CHANNEL_LINK)]
    ]
)

mods_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="Старый шрифт (v1.0)", callback_data="mod_old_font")],
        [InlineKeyboardButton(text="Старые медали (v1.0)", callback_data="mod_old_medals")],
        [InlineKeyboardButton(text="Старый UI ангара (v1.2)", callback_data="mod_old_ui")],
    ]
)

help_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="Как установить мод", callback_data="help_install")],
        [InlineKeyboardButton(text="Как удалить мод", callback_data="help_remove")],
        [InlineKeyboardButton(text="Зачем нужны данные модификации", callback_data="help_why")],
        [InlineKeyboardButton(text="Сколько разрабатываются моды", callback_data="help_time")],
        [InlineKeyboardButton(text="Почему моды только на возвращение старого в игру", callback_data="help_why_old")],
    ]
)

misc_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="О команде MOD_rak.rar", callback_data="misc_team")],
        [InlineKeyboardButton(text="Можно ли присоединиться к вам", callback_data="misc_join")],
    ]
)

# --- СОСТОЯНИЯ ---
class UserState(StatesGroup):
    awaiting_mod_suggestion = State()
    awaiting_fun = State()
    awaiting_bug_report = State()

# --- ФУНКЦИИ ---
def find_file_id(base_name: str):
    base_lower = base_name.lower()
    if base_name in FILE_IDS:
        return base_name, FILE_IDS[base_name]
    for stored_name, file_id in FILE_IDS.items():
        if stored_name.rsplit(".", 1)[0].lower() == base_lower:
            return stored_name, file_id
    return None

async def check_subscription(user_id: int) -> bool:
    """Проверяет, подписан ли пользователь на канал. Если CHANNEL_ID не задан - пускает всех."""
    if not CHANNEL_ID:
        return True
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        if member.status in ["creator", "administrator", "member"]:
            return True
    except TelegramBadRequest as e:
        logger.error(f"Ошибка проверки подписки (возможно, бот не админ в канале): {e}")
    return False

async def send_mod_file(chat_id: int, base_name: str):
    result = find_file_id(base_name)
    if not result:
        await bot.send_message(chat_id, "Файл пока недоступен. Попробуй позже.")
        return
    _, file_id = result
    await bot.send_document(chat_id, file_id)

async def forward_to_admins(message: Message, header: str):
    logger.info(f"Пытаюсь переслать сообщение. Список получателей: {TARGET_CHAT_IDS}")
    if not TARGET_CHAT_IDS:
        logger.error("ОШИБКА: Список TARGET_CHAT_IDS пуст! Проверь GROUP_ID.")
        return

    for chat_id in TARGET_CHAT_IDS:
        try:
            await bot.send_message(chat_id, header, parse_mode="HTML")
            await message.forward(chat_id)
            logger.info(f"Успешно отправлено в {chat_id}")
        except Exception as exc:
            logger.error(f"Не удалось отправить в {chat_id}. Ошибка: {exc}")

# --- ХЕНДЛЕРЫ ---

@dp.message(F.document)
async def group_document_handler(message: Message):
    if CHANNEL_ID and message.chat.id == CHANNEL_ID:
        doc = message.document
        if doc.file_name:
            FILE_IDS[doc.file_name] = doc.file_id
            save_file_ids()
            logger.info("Saved file from group: %s", doc.file_name)

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

# --- ОБРАБОТЧИКИ МОДОВ С ПРОВЕРКОЙ ПОДПИСКИ ---

@dp.callback_query(F.data == "mod_old_font")
async def cb_old_font(callback: CallbackQuery):
    await callback.answer()
    if not await check_subscription(callback.from_user.id):
        await callback.message.answer(
            "Чтобы скачать этот мод, пожалуйста, подпишись на наш канал!",
            reply_markup=subscribe_keyboard
        )
        return
    await callback.message.answer("Версия мода: v1.0")
    await send_mod_file(callback.from_user.id, "old_font")

@dp.callback_query(F.data == "mod_old_medals")
async def cb_old_medals(callback: CallbackQuery):
    await callback.answer()
    if not await check_subscription(callback.from_user.id):
        await callback.message.answer(
            "Чтобы скачать этот мод, пожалуйста, подпишись на наш канал!",
            reply_markup=subscribe_keyboard
        )
        return
    await callback.message.answer("Версия мода: v1.0")
    await send_mod_file(callback.from_user.id, "old_medals")

@dp.callback_query(F.data == "mod_old_ui")
async def cb_old_ui(callback: CallbackQuery):
    await callback.answer()
    if not await check_subscription(callback.from_user.id):
        await callback.message.answer(
            "Чтобы скачать этот мод, пожалуйста, подпишись на наш канал!",
            reply_markup=subscribe_keyboard
        )
        return
    await callback.message.answer(
        "Версия мода: v1.2\n\n"
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
    await send_mod_file(callback.from_user.id, "old_ui")

# --- ОСТАЛЬНОЕ МЕНЮ ---

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
        "Отправляй хоть видео, хоть фото, хоть текст",
        reply_markup=main_keyboard,
    )

MENU_BUTTONS = {
    "Моды", "Приколы", "Помощь", "Предложить мод",
    "В разработке", "Поддержать", "Сообщить об ошибке", "Разное",
}

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

@dp.message(F.text == "Предложить мод")
async def btn_suggest_mod(message: Message, state: FSMContext):
    await state.set_state(UserState.awaiting_mod_suggestion)
    await message.answer(
        "<b>Предложить идею для мода</b>\n\n"
        "Напиши описание мода и как что работает, фото/видео/голосовые/видеосообщения не принимаются.\n"
        "Переслано администратору.\n\n"
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
        "Опиши ошибку в моде. Напиши название мода и что именно не так, всё будет передано парням из дружного коллектива MOD_rak.rar.",
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
        parse_mode="HTML"
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

async def main():
    logger.info("Bot started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
