import asyncio
import sqlalchemy
from datetime import datetime

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery

from data.bot_messages import MESSAGES
from data.config import BOT_TOKEN
from data.database import new_session
from data.models import TaskModel, TagModel

form_router = Router()
dp = Dispatcher()


async def main():
    # await setup_database()
    bot = Bot(token=BOT_TOKEN)
    await dp.start_polling(bot)


@dp.message(Command("start"))
async def process_start_command(message: Message):
    await message.reply(MESSAGES["greeting text"])


@dp.message(Command("stop"))
@dp.message(F.text.casefold() == "stop")
async def cancel_handler(message: Message, state: FSMContext) -> None:
    curr_state = await state.get_state()
    if curr_state is None:
        return
    await state.clear()
    await message.answer("Сброс действий")


class TaskStates(StatesGroup):
    title_tag = State()
    due_date = State()
    delete_number = State()
    edit_task = State()
    add_tag = State()


@dp.message(Command("add_task"))
async def add_task(message: Message, state: FSMContext):
    await state.set_state(TaskStates.title_tag)
    await message.answer("Введите название задачи и #тег_задачи:")


@dp.message(TaskStates.title_tag)
async def process_task_title_tag(message: Message, state: FSMContext):
    text = message.text
    if "#" in text:
        title, tag = text.rsplit("#", 1)
        await state.update_data(title=title.strip())
        await state.update_data(tag=tag.strip())
    else:
        await state.update_data(title=text.strip())
        await state.update_data(tag=None)
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
            if data["tag"]:
                query = sqlalchemy.select(TagModel).where(TagModel.title == data["tag"])
                result = await session.execute(query)
                tag = result.scalars().first()
                if not tag:
                    await message.answer("Тег не найден! Добавьте его через команду /add_tag")
                    return
                task = TaskModel(
                    user_id=message.from_user.id,
                    title=data["title"],
                    tag_id=tag.id,
                    due_date=due_date,
                )
                session.add(task)
                await session.commit()
                await message.answer(
                    f"Задача добавлена!\nНазвание: {data['title']}\nДедлайн: {due_date}\nТег: {data['tag']}")
            else:
                task = TaskModel(
                    user_id=message.from_user.id,
                    title=data["title"],
                    due_date=due_date,
                )
                session.add(task)
                await session.commit()
                await message.answer(
                    f"Задача добавлена!\nНазвание: {data['title']}\nДедлайн: {due_date}\n")

        except Exception as e:
            print(e)
            await message.answer("Ошибка при сохранении задачи!")
        finally:
            await state.clear()


@dp.message(Command("add_tag"))
async def add_tag(message: Message, state: FSMContext):
    await state.set_state(TaskStates.add_tag)
    await message.answer("Введите название тега:")


@dp.message(TaskStates.add_tag)
async def process_task_add_tag(message: Message, state: FSMContext):
    title = message.text
    async with new_session() as session:
        try:
            new_tag = TagModel(
                title=title,
            )
            session.add(new_tag)
            await session.commit()
            await message.answer(f"Тег '{title}' добавлен!")
        except Exception as e:
            print(e)
            await message.answer("Ошибка при сохранении тега!")
        finally:
            await state.clear()


async def get_tasks(status, message):
    async with new_session() as session:
        result = await session.execute(sqlalchemy.select(TaskModel).where(
            TaskModel.user_id == message.from_user.id,
            TaskModel.is_done == status,
        ))
        data = list()
        for el in result.scalars().all():
            data.append(f"{el.id}. {el.title}")
        return data


async def get_task(data, message):
    async with new_session() as session:
        try:
            data = int(data)
            result = await session.execute(sqlalchemy.select(TaskModel).where(
                TaskModel.user_id == message.from_user.id,
                TaskModel.id == data,
            ))
            task = result.scalars().first()
            return task, session

        except ValueError:
            await message.answer("Введите корректный номер задачи (целое, положительное число)")
            return


@dp.message(Command("delete_task"))
async def delete_message(message: Message, state: FSMContext):
    data = await get_tasks(False, message)
    if data:
        await message.answer(f"Выберите номер задачи для удаления:\n{'\n'.join(data)}")
        await state.set_state(TaskStates.delete_number)
    else:
        await message.answer(f"Активных задач нет")


@dp.message(TaskStates.delete_number)
async def delete_task(message: Message, state: FSMContext):
    data = message.text
    task, session = await get_task(data, message)
    answer = f"№{data}"
    if task:
        await session.delete(task)
        await session.commit()
        await message.reply(f'Задача {answer} удалена!')
        await state.clear()
    else:
        await message.reply(f'Задача с {answer} не найдена.')


@dp.message(Command("tasks"))
async def task_buttons(message: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Активные", callback_data="active"),
            InlineKeyboardButton(text="Завершенные", callback_data="done"),
        ],
    ])

    await message.answer("Выберите тип задач", reply_markup=keyboard)


@dp.callback_query(lambda c: c.data == "done")
async def choose_done(callback: CallbackQuery):
    data = await get_tasks(True, callback)
    if data:
        await callback.message.answer(f"Выполненные задачи:\n{'\n'.join(data)}")
    else:
        await callback.message.answer("Завершенных задач нет")


@dp.callback_query(lambda c: c.data == "active")
async def choose_active(callback: CallbackQuery):
    data = await get_tasks(False, callback)
    if data:
        await callback.message.answer(f"Активные задачи:\n{'\n'.join(data)}")
    else:
        await callback.message.answer("Активных задач нет")


@dp.message(Command("edit_task"))
async def start_edit(message: Message, state: FSMContext):
    data = await get_tasks(False, message)
    if data:
        await message.answer(f"Выберите номер задачи, которую хотите отредактировать:\n{'\n'.join(data)}")
        await state.set_state(TaskStates.edit_task)
    else:
        await message.answer(f"Активных задач нет")


@dp.message(TaskStates.edit_task)
async def delete(message: Message):
    data = message.text
    task, session = await get_task(data, message)
    answer = f"№{data}"
    if task:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Удалить", callback_data="delete"),
                InlineKeyboardButton(text="Изменить название", callback_data="change_text"),
            ],
            [
                InlineKeyboardButton(text="Изменить дедлайн", callback_data="change_date"),
                InlineKeyboardButton(text="Поменять тег", callback_data="change_tag"),
            ],
            [
                InlineKeyboardButton(text="Завершить", callback_data="is_done"),
            ],
        ])

        await message.answer("Выберите действие", reply_markup=keyboard)
    else:
        await message.answer(f"Задача с {answer} не найдена.")


if __name__ == "__main__":
    asyncio.run(main())