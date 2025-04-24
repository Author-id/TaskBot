import asyncio
from datetime import datetime

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from data.database import get_session
from data.bot_messages import MESSAGES
from data.config import BOT_TOKEN
from data.models import TaskModel, UserModel

dp = Dispatcher()


async def main():
    bot = Bot(token=BOT_TOKEN)
    await dp.start_polling(bot)


@dp.message(Command("start"))
async def process_start_command(message: types.Message):
    await message.reply(MESSAGES["greeting text"])


class TaskStates(StatesGroup):
    waiting_for_title = State()
    waiting_for_due_date = State()


@dp.message(Command("add_task"))
async def add_task(message: types.Message, state: FSMContext):
    await state.set_state(TaskStates.waiting_for_title)
    await message.answer("Введите название задачи:")


@dp.message(TaskStates.waiting_for_title)
async def process_task_title(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        data["title"] = message.text
    await state.set_state(TaskStates.waiting_for_due_date)
    await message.answer("Теперь укажите дату выполнения (ГГГГ-ММ-ДД):")


@dp.message(TaskStates.waiting_for_due_date)
async def process_due_date(message: types.Message, state: FSMContext):
    try:
        due_date = datetime.strptime(message.text, "%Y-%m-%d").date()
    except ValueError:
        await message.answer("Неверный формат даты! Используйте ГГГГ-ММ-ДД.")
        return

    async with state.proxy() as data:
        session = get_session()
        try:
            task = TaskModel(
                user_id=message.from_user.id,
                title=data["title"],
                due_date=due_date,
            )
            session.add(task)
            session.commit()
            await message.answer(f"Задача добавлена!\nНазвание: {data['title']}\nСрок: {due_date}")
        except Exception as e:
            session.rollback()
            await message.answer("Ошибка при сохранении задачи!")
        finally:
            session.close()

    await state.clear()


if __name__ == "__main__":
    asyncio.run(main())
