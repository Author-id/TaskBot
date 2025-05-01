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
from data.database import new_session, setup_database
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
    change_title = State()
    change_deadline = State()
    change_tag = State()


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


async def date_validation(date, message):
    try:
        due_date = datetime.strptime(date, "%d-%m-%Y").date()
        return due_date
    except ValueError:
        await message.answer("Неверный формат даты! Используйте ДД-ММ-ГГГГ")
        return


@dp.message(TaskStates.due_date)
async def process_due_date(message: Message, state: FSMContext):
    due_date = await date_validation(message.text, message)
    if not due_date:
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
                    f"Задача добавлена!\nНазвание: {data['title']}\nДедлайн: {due_date.strftime("%d-%m-%Y")}\nТег: {data['tag']}")
            else:
                task = TaskModel(
                    user_id=message.from_user.id,
                    title=data["title"],
                    due_date=due_date,
                )
                session.add(task)
                await session.commit()
                await message.answer(
                    f"Задача добавлена!\nНазвание: {data['title']}\nДедлайн: {due_date.strftime("%d-%m-%Y")}\n")

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
        data = dict()
        for el in result.scalars().all():
            tag = await session.execute(sqlalchemy.select(TagModel).where(
                TagModel.id == el.tag_id,
            ))
            tag = tag.scalars().first()
            if el.due_date in data:
                if tag:
                    data[
                        el.due_date].append(
                        f"\nЗадача №{el.id} \n{el.title}\nДедлайн: {el.due_date.strftime("%d-%m-%Y")}\nТег: #{tag.title}\n")
                else:
                    data[el.due_date].append(
                        f"\nЗадача №{el.id} \n{el.title}\nДедлайн: {el.due_date.strftime("%d-%m-%Y")}\n")
            else:
                if tag:
                    data[
                        el.due_date] = [
                        f"\nЗадача №{el.id} \n{el.title}\nДедлайн: {el.due_date.strftime("%d-%m-%Y")}\nТег: #{tag.title}\n"]
                else:
                    data[
                        el.due_date] = [
                        f"\nЗадача №{el.id} \n{el.title}\nДедлайн: {el.due_date.strftime("%d-%m-%Y")}\n"]
        data = sorted(data.items())
        ans = list()
        for el in data:
            for i in el[1]:
                ans.append(i)
        return ans


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


async def task_buttons(message, text1, text2, text3):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Активные", callback_data=text1),
            InlineKeyboardButton(text="Завершенные", callback_data=text2),
        ],
    ])

    await message.answer(text3, reply_markup=keyboard)


async def choose_status(callback, state, arg, text1, text2):
    data = await get_tasks(arg, callback)
    if data:
        await callback.message.answer(text1 + f"{"".join(data)}")
        if text1 == "Выберите номер задачи:\n":
            nums = list(map(int, [el[9] for el in data]))
            await state.set_state(TaskStates.edit_task)
            await state.update_data(nums=nums)
    else:
        await callback.message.answer(text2)


@dp.message(Command("tasks"))
async def tasks_buttons(message: Message):
    await task_buttons(message, "active", "done", "Выберите тип задач")


@dp.callback_query(lambda c: c.data == "active")
async def choose_active(callback: CallbackQuery, state: FSMContext):
    await choose_status(callback, state, False, "Активные задачи:\n", "Активных задач нет")


@dp.callback_query(lambda c: c.data == "done")
async def choose_active(callback: CallbackQuery, state: FSMContext):
    await choose_status(callback, state, True, "Завершенные задачи:\n", "Завершенных задач нет")


@dp.message(Command("edit_task"))
async def edit_tasks_buttons(message: Message):
    await task_buttons(message, "edit_active", "edit_done", "Выберите тип задачи")


@dp.callback_query(lambda c: c.data == "edit_active")
async def edit_choose_active(callback: CallbackQuery, state: FSMContext):
    await choose_status(callback, state, False, "Выберите номер задачи:\n",
                        "Активных задач нет")


@dp.callback_query(lambda c: c.data == "edit_done")
async def edit_choose_active(callback: CallbackQuery, state: FSMContext):
    await choose_status(callback, state, True, "Выберите номер задачи:\n", "Завершенных задач нет")


@dp.message(TaskStates.edit_task)
async def choose_edit(message: Message, state: FSMContext):
    data = message.text
    nums = await state.get_data()
    nums = nums.get("nums")
    task, session = await get_task(data, message)
    answer = f"№{data}"
    if task:
        if not (task.id in nums):
            if task.is_done:
                text = "активной"
            else:
                text = "завершенной"
            await message.answer(f"Задача с {answer} не является {text}.")
        elif task.is_done:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="Сделать активной", callback_data="to_active"),
                    InlineKeyboardButton(text="Удалить", callback_data="delete"),
                ],
            ])
            await state.update_data(task=task, session=session, answer=answer)
            await message.answer("Выберите действие", reply_markup=keyboard)
        else:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="Название", callback_data="change_text"),
                    InlineKeyboardButton(text="Дедлайн", callback_data="change_deadline"),
                ],
                [
                    InlineKeyboardButton(text="Тег", callback_data="change_tag"),
                    InlineKeyboardButton(text="Завершить", callback_data="is_done"),
                ],
                [
                    InlineKeyboardButton(text="Удалить", callback_data="delete"),
                ],
            ])
            await state.update_data(task=task, session=session, answer=answer)
            await message.answer("Выберите действие", reply_markup=keyboard)
    else:
        await message.answer(f"Задача с {answer} не найдена.")


async def get_state(state):
    data = await state.get_data()
    task = data.get("task")
    session = data.get("session")
    answer = data.get("answer")
    return task, session, answer


async def change_smth(callback, state, text, to_update):
    task, session, answer = await get_state(state)
    await callback.message.answer(text)
    await state.set_state(to_update)
    await state.update_data(task=task, session=session, answer=answer)


@dp.callback_query(lambda c: c.data == "delete")
async def delete(callback: CallbackQuery, state: FSMContext):
    task, session, answer = await get_state(state)
    await session.delete(task)
    await session.commit()
    await callback.message.answer(f'Задача {answer} удалена!')
    await state.clear()


@dp.callback_query(lambda c: c.data == "change_text")
async def change_text(callback: CallbackQuery, state: FSMContext, ):
    await change_smth(callback, state, "Введите новое название", TaskStates.change_title)


@dp.message(TaskStates.change_title)
async def title_is_changed(message: Message, state: FSMContext):
    new_title = message.text
    task, session, answer = await get_state(state)
    old_title = task.title
    task.title = new_title
    session.add(task)
    await session.commit()
    await message.answer(f'Название задачи {answer} изменено с "{old_title}" на "{task.title}"')
    await state.set_state(TaskStates.edit_task)


@dp.callback_query(lambda c: c.data == "change_deadline")
async def change_deadline(callback: CallbackQuery, state: FSMContext):
    await change_smth(callback, state, "Введите новую дату выполнения (ДД-ММ-ГГГГ):", TaskStates.change_deadline)


@dp.message(TaskStates.change_deadline)
async def date_update(message: Message, state: FSMContext):
    due_date = await date_validation(message.text, message)
    if not due_date:
        return
    task, session, answer = await get_state(state)
    old_deadline = task.due_date
    task.due_date = due_date
    session.add(task)
    await session.commit()
    await message.answer(
        f"Дедлайн задачи {answer} перенесён с {old_deadline.strftime("%d-%m-%Y")} на {task.due_date.strftime("%d-%m-%Y")}")
    await state.set_state(TaskStates.edit_task)


@dp.callback_query(lambda c: c.data == "change_tag")
async def change_tag(callback: CallbackQuery, state: FSMContext):
    await change_smth(callback, state, "Введите новый тег (без #):", TaskStates.change_tag)


@dp.message(TaskStates.change_tag)
async def tag_update(message: Message, state: FSMContext):
    title = message.text
    task, session, answer = await get_state(state)
    query = sqlalchemy.select(TagModel).where(TagModel.title == title)
    tag_result = await session.execute(query)
    tag = tag_result.scalars().first()
    if not tag:
        await message.answer("Тег не найден! Добавьте его через команду /add_tag")
        return
    new_tag = await session.execute(sqlalchemy.select(TagModel).where(
        TagModel.title == title,
    ))
    new_tag = new_tag.scalars().first()
    result = await session.execute(sqlalchemy.select(TagModel).where(
        TagModel.id == task.tag_id,
    ))
    tag = result.scalars().first()
    if tag:
        old_tag = tag.title
    else:
        old_tag = None
    task.tag_id = new_tag.id
    session.add(task)
    await session.commit()
    if old_tag:
        await message.answer(f'Тег задачи {answer} изменён с #{old_tag} на #{title}')
    else:
        await message.answer(f'К задаче {answer} добавлен тег #{title}')
    await state.set_state(TaskStates.edit_task)


async def change_status(callback, state, arg, text):
    task, session, answer = await get_state(state)
    task.is_done = arg
    session.add(task)
    await session.commit()
    await callback.message.answer(f"Задача {answer} " + text)
    await state.clear()


@dp.callback_query(lambda c: c.data == "is_done")
async def date_update(callback: CallbackQuery, state: FSMContext):
    await change_status(callback, state, True, "завершена")


@dp.callback_query(lambda c: c.data == "to_active")
async def to_active(callback: CallbackQuery, state: FSMContext):
    await change_status(callback, state, False, "снова активна")


if __name__ == "__main__":
    asyncio.run(main())
