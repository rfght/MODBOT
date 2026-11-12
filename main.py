import asyncio
import sys
import os

# Добавляем папку tg_bot в системный путь, чтобы бот мог найти свои модули
sys.path.append(os.path.join(os.path.dirname(__file__), "tg_bot"))

# Импортируем твоего бота
from bot import dp, bot

if __name__ == "__main__":
    # Запускаем опрос сообщений
    asyncio.run(dp.start_polling(bot))
