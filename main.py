import asyncio
from datetime import datetime
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from data.database import new_session, setup_database
from data.bot_messages import MESSAGES
from data.config import BOT_TOKEN
from data.models import TaskModel

form_router = Router()
dp = Dispatcher()


async def main():
    # await setup_database()
    bot = Bot(token=BOT_TOKEN)
    await dp.start_polling(bot)


@dp.message(Command("start"))
async def process_start_command(message: Message):
    await message.reply(MESSAGES["greeting text"])


class TaskStates(StatesGroup):
    title = State()
    due_date = State()


@dp.message(Command("add_task"))
async def add_task(message: Message, state: FSMContext):
    await state.set_state(TaskStates.title)
    await message.answer("Введите название задачи:")


@dp.message(Command("stop"))
@dp.message(F.text.casefold() == "stop")
async def cancel_handler(message: Message, state: FSMContext) -> None:
    curr_state = await state.get_state()
    if curr_state is None:
        return
    await state.clear()
    await message.answer(
        "Всего доброго!",
    )


@dp.message(TaskStates.title)
async def process_task_title(message: Message, state: FSMContext):
    title = message.text
    await state.update_data(title=title)
    await state.set_state(TaskStates.due_date)
    await message.answer("Теперь укажите дату выполнения (ДД-ММ-ГГГГ):")


@dp.message(TaskStates.due_date)
async def process_due_date(message: Message, state: FSMContext):
    try:
        due_date = datetime.strptime(message.text, "%d-%m-%Y").date()
    except ValueError:
        await message.answer("Неверный формат даты! Используйте ДД-ММ-ГГГГ")
        return

    data = await state.get_data()
    async with new_session() as session:
        try:
            task = TaskModel(
                user_id=message.from_user.id,
                title=data["title"],
                due_date=due_date,
            )
            session.add(task)
            await session.commit()
            await message.answer(f"Задача добавлена!\nНазвание: {data['title']}\nДедлайн: {due_date}")
        except Exception as e:
            print(e)
            await message.answer("Ошибка при сохранении задачи!")
        finally:
            await state.clear()


if __name__ == "__main__":
    asyncio.run(main())
