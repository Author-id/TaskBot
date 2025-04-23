import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from data.bot_messages import MESSAGES
from data.config import BOT_TOKEN


dp = Dispatcher()


async def main():
    bot = Bot(token=BOT_TOKEN)
    await dp.start_polling(bot)


@dp.message(Command("start"))
async def start_command(message: types.Message):
    await message.reply(MESSAGES["greeting text"])


if __name__ == "__main__":
    asyncio.run(main())