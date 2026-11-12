import asyncio
import sys
import os

# Добавляем папку tg_bot в системный путь
sys.path.append(os.path.join(os.path.dirname(__file__), "tg_bot"))

# Импортируем объекты бота из твоего файла
from bot import dp, bot

if __name__ == "__main__":
    asyncio.run(dp.start_polling(bot))
