import re
import asyncio
import sqlalchemy
from datetime import datetime, date, time, timedelta

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from data.bot_messages import MESSAGES
from data.config import BOT_TOKEN
from data.database import new_session, setup_database
from data.models import TaskModel, TagModel, UserModel

form_router = Router()
dp = Dispatcher()


async def main():
    # await setup_database()
    bot = Bot(token=BOT_TOKEN)
    await on_startup(bot)
    await dp.start_polling(bot)


@dp.message(Command("start"))
async def process_start_command(message: Message):
    async with new_session() as session:
        query = sqlalchemy.select(UserModel).where(
            UserModel.tg_id == message.from_user.id
        )
        result = await session.execute(query)
        user_id_list = [user.tg_id for user in result.scalars().all()]
        if not user_id_list:
            user = UserModel(
                tg_id=message.from_user.id,
                username=message.from_user.username
            )
            session.add(user)
            await session.commit()
        await message.reply(MESSAGES["start text"])


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
    add_tag = State()
    delete_tag = State()
    set_remind = State()
    delete_number = State()
    edit_task = State()
    change_title = State()
    change_deadline = State()
    change_tag = State()
    type_to_edit = State()
    type_to = State()
    filter = State()
    filter_edit = State()


def setup_scheduler(bot: Bot):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        send_reminders,
        "interval",
        minutes=1,
        args=[bot]
    )
    scheduler.start()


async def on_startup(bot: Bot):
    setup_scheduler(bot)


async def send_reminders(bot: Bot):
    async with new_session() as session:
        now = datetime.now()
        start_time = now - timedelta(minutes=1)
        end_time = now + timedelta(minutes=1)
        task_query = (
            sqlalchemy.select(TaskModel).where(
                TaskModel.notify_time.between(start_time, end_time),
                TaskModel.is_done == 0,
                TaskModel.send_remind == 0
            )
        )
        tasks = (await session.execute(task_query)).scalars().all()

        for task in tasks:
            try:
                tag_query = sqlalchemy.select(TagModel).where(
                    TagModel.id == task.tag_id
                )
                tag_result = await session.execute(tag_query)
                tag = tag_result.scalars().first()
                if tag:
                    await bot.send_message(
                        chat_id=task.user_id,
                        text=f"ЗАВТРА ({task.due_date.strftime('%d-%m-%Y')})\n"
                             f"ДЕДЛАЙН ЗАДАЧИ '{task.title}' с тегом #{tag.title}\n"
                             f"Перейдите в /edit_task если хотите перенести дедлайн!"
                    )
                else:
                    await bot.send_message(
                        chat_id=task.user_id,
                        text=f"ЗАВТРА ({task.due_date.strftime('%d-%m-%Y')})\n"
                             f"ДЕДЛАЙН ЗАДАЧИ '{task.title}'\n"
                             f"Перейдите в /edit_task если хотите перенести дедлайн!"
                    )
                task.send_remind = True
                await session.commit()
            except Exception as error:
                print(error)


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
    await message.answer("Укажите дату выполнения (ДД-ММ-ГГГГ):")


async def date_validation(input_date, message):
    try:
        due_date = datetime.strptime(input_date, "%d-%m-%Y").date()
        today = date.today()
        if due_date < today:
            await message.answer("Дата в прошлом!!")
            return
        return due_date
    except ValueError:
        await message.answer("Неверный формат даты! Используйте ДД-ММ-ГГГГ")
        return


@dp.message(TaskStates.due_date)
async def process_due_date(message: Message, state: FSMContext):
    now = datetime.now()
    due_date = await date_validation(message.text, message)
    if now.time().hour >= 18 and due_date == now.date() + timedelta(days=1):
        notify_hour = now.time().hour + 2
    else:
        notify_hour = 18
    notify_date = due_date - timedelta(days=1)
    notify_time = datetime.combine(notify_date, time(notify_hour, 00))
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
                    notify_time=notify_time
                )
                session.add(task)
                await session.commit()
                await message.answer(
                    f"Задача успешно добавлена!\nНазвание: {data['title']}\nДедлайн: {due_date.strftime('%d-%m-%Y')}\nТег: #{data['tag']}")
            else:
                task = TaskModel(
                    user_id=message.from_user.id,
                    title=data["title"],
                    due_date=due_date,
                    notify_time=notify_time
                )
                session.add(task)
                await session.commit()
                await message.answer(
                    f"Задача успешно добавлена!\nНазвание: {data['title']}\nДедлайн: {due_date.strftime('%d-%m-%Y')}\n")

        except Exception as e:
            print(e)
            await message.answer("Ошибка при сохранении задачи!")
        finally:
            await state.clear()


async def get_tags(message):
    async with new_session() as session:
        query = sqlalchemy.select(TagModel).where(
            TagModel.user_id == message.from_user.id
        )
        result = await session.execute(query)
        return [(tag.id, tag.title) for tag in result.scalars().all()]


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
                user_id=message.from_user.id,
                title=title,
            )
            session.add(new_tag)
            await session.commit()
            await message.answer(f"Тег #{title} успешно добавлен!")
        except Exception as error:
            print(error)
            user_tags = await get_tags(message)
            if title in [tag[1] for tag in user_tags]:
                await message.answer("Тег уже существует!")
            else:
                await message.answer("Ошибка при сохранении тега!")
        finally:
            await state.clear()


@dp.message(Command("delete_tag"))
async def delete_tag(message: Message, state: FSMContext):
    user_tags = await get_tags(message)
    if not user_tags:
        await message.answer("У вас нет активных тегов!")
        return

    tags_list = "\n".join([f"{tag_id}. {tag_title}" for tag_id, tag_title in user_tags])
    await message.answer(
        "Введите ID тега:\n"
        f"{tags_list}\n\n",
    )
    await state.update_data(user_tags=user_tags)
    await state.set_state(TaskStates.delete_tag)


@dp.message(TaskStates.delete_tag)
async def process_task_delete_tag(message: Message, state: FSMContext):
    try:
        tag_id = int(message.text)
        data = await state.get_data()
        user_tags = data["user_tags"]
        if tag_id not in [tag[0] for tag in user_tags]:
            await message.answer("Тег с таким ID не найден среди ваших тегов.")
            return

        async with new_session() as session:
            tag = await session.get(TagModel, tag_id)
            await session.delete(tag)
            await session.commit()
            await message.answer(f"Тег #{tag.title} успешно удалён!")
    except ValueError:
        await message.answer("Введите число (ID тега)!!!")
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
                        f"\nЗадача №{el.id} \n{el.title}\nДедлайн: {el.due_date.strftime('%d-%m-%Y')}\nТег: #{tag.title}\n")
                else:
                    data[el.due_date].append(
                        f"\nЗадача №{el.id} \n{el.title}\nДедлайн: {el.due_date.strftime('%d-%m-%Y')}\n")
            else:
                if tag:
                    data[
                        el.due_date] = [
                        f"\nЗадача №{el.id} \n{el.title}\nДедлайн: {el.due_date.strftime('%d-%m-%Y')}\nТег: #{tag.title}\n"]
                else:
                    data[
                        el.due_date] = [
                        f"\nЗадача №{el.id} \n{el.title}\nДедлайн: {el.due_date.strftime('%d-%m-%Y')}\n"]
        data = sorted(data.items())
        ans = list()
        for el in data:
            for i in el[1]:
                ans.append(i)
        return ans


async def get_task(data, message, nums):
    async with new_session() as session:
        try:
            data = int(data)
            data = nums[data]
            result = await session.execute(sqlalchemy.select(TaskModel).where(
                TaskModel.user_id == message.from_user.id,
                TaskModel.id == data,
            ))
            task = result.scalars().first()
            return task, session

        except ValueError:
            await message.answer("Введите номер задачи! (число)")
            return


async def task_buttons(message, text1, text2, text3, text4):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Активные", callback_data=text1),
            InlineKeyboardButton(text="Завершенные", callback_data=text2),
        ],
        [
            InlineKeyboardButton(text="Отфильтровать по тегу", callback_data=text3),
        ]
    ])

    await message.answer(text4, reply_markup=keyboard)


async def choose_status(callback, state, arg, text1, text2):
    data = await get_tasks(arg, callback)
    if data:
        count = 1
        ans = list()
        for i in data:
            i = i.replace(re.search(r"(№\d+)[^\n]*", i).group(1).strip(), f"<b>№{count}</b> ", 1)
            ans.append(i)
            count += 1
        await callback.message.answer(text1 + f"{''.join(ans)}", parse_mode="html")
        await state.clear()
        if text1 == "Выберите номер задачи:\n":
            count = 1
            answer = dict()
            nums = list(map(int, [re.search(r"(№\d+)[^\n]*", el).group(1).strip().strip("№") for el in data]))
            for el in nums:
                answer[count] = el
                count += 1
            await state.set_state(TaskStates.edit_task)
            await state.update_data(nums=answer)
    else:
        await callback.message.answer(text2)


@dp.message(Command("tasks"))
async def tasks_buttons(message: Message, state: FSMContext):
    await task_buttons(message, "active", "done", "filter", "Выберите тип задач: ")
    await state.set_state(TaskStates.type_to)


@dp.callback_query(
    F.data == "active",
    StateFilter(TaskStates.type_to)
)
async def choose_active(callback: CallbackQuery, state: FSMContext):
    await choose_status(callback, state, False, "Активные задачи:\n", "Активных задач нет")


@dp.callback_query(
    F.data == "done",
    StateFilter(TaskStates.type_to)
)
async def choose_done(callback: CallbackQuery, state: FSMContext):
    await choose_status(callback, state, True, "Завершенные задачи:\n", "Завершенных задач нет")


@dp.callback_query(
    F.data == "filter",
)
async def view_filter(callback: CallbackQuery, state: FSMContext):
    await choose_filter(callback, state, False)


async def choose_filter(callback: CallbackQuery, state: FSMContext, arg):
    tags = dict()
    async with new_session() as session:
        query = await session.execute(
            sqlalchemy.select(TagModel).where(
                UserModel.tg_id == TagModel.user_id
            )
        )
        query = query.scalars().all()
        for el in query:
            tags[el.id] = el.title

    keyboard = list()
    current_row = list()

    for tag_id, tag_title in tags.items():
        current_row.append(
            InlineKeyboardButton(text=tag_title, callback_data=f"tag_{tag_id}")
        )

        if len(current_row) == 3 or tag_id == list(tags.keys())[-1]:
            keyboard.append(current_row)
            current_row = list()

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard)

    await callback.message.answer(
        "Выберите тег для фильтра:",
        reply_markup=keyboard
    )
    await state.set_state(TaskStates.filter)
    await state.update_data(arg=arg)


@dp.callback_query(
    StateFilter(TaskStates.filter)
)
async def process_filter(callback: CallbackQuery, state: FSMContext):
    args = await state.get_data()
    arg = args.get("arg")
    tag_id = int(callback.data.split("_")[1])
    async with new_session() as session:
        tag = await session.execute(sqlalchemy.select(TagModel).where(
            TagModel.id == tag_id,
        ))
        tag = tag.scalars().first()
        result = await session.execute(sqlalchemy.select(TaskModel).where(
            TaskModel.user_id == callback.from_user.id,
            TaskModel.tag_id == tag_id,
            TaskModel.is_done == False,
        ))
        result = result.scalars().all()
        if result:
            data = dict()
            for el in result:
                if el.due_date in data:
                    data[
                        el.due_date].append(
                        f"\nЗадача №{el.id} \n{el.title}\nДедлайн: {el.due_date.strftime('%d-%m-%Y')}\nТег: #{tag.title}\n")
                else:
                    data[
                        el.due_date] = [
                        f"\nЗадача №{el.id} \n{el.title}\nДедлайн: {el.due_date.strftime('%d-%m-%Y')}\nТег: #{tag.title}\n"]
            data = sorted(data.items())
            ans = list()
            for el in data:
                for i in el[1]:
                    ans.append(i)
            count = 1
            data = ans
            nums = dict()
            ans = list()
            for i in data:
                nums[count] = int(re.search(r"(\d+)[^\n]*", i).group(1))
                i = i.replace(re.search(r"(№\d+)[^\n]*", i).group(1).strip(), f"<b>№{count}</b> ", 1)
                ans.append(i)
                count += 1
            await callback.message.answer(f"Активные задачи с тегом #{tag.title} : \n" + f"{''.join(ans)}", parse_mode="html")
            if arg:
                await state.set_state(TaskStates.edit_task)
                await state.update_data(nums=nums)
            else:
                await state.clear()
        else:
            await callback.message.answer(f"Активных задач с тегом #{tag.title} нет")


@dp.message(Command("edit_task"))
async def edit_tasks_buttons(message: Message, state: FSMContext):
    await task_buttons(message, "edit_active", "edit_done", "filter_edit", "Выберите тип задачи:")
    await state.set_state(TaskStates.type_to_edit)


@dp.callback_query(
    F.data == "edit_active",
    StateFilter(TaskStates.type_to_edit)
)
async def edit_choose_active(callback: CallbackQuery, state: FSMContext):
    await choose_status(callback, state, False, "Выберите номер задачи:\n",
                        "Активных задач нет")


@dp.callback_query(
    F.data == "edit_done",
    StateFilter(TaskStates.type_to_edit)
)
async def edit_choose_done(callback: CallbackQuery, state: FSMContext):
    await choose_status(callback, state, True, "Выберите номер задачи:\n", "Завершенных задач нет")


@dp.callback_query(
    F.data == "filter_edit",
    StateFilter(TaskStates.type_to_edit)
)
async def view_filter_edit(callback: CallbackQuery, state: FSMContext):
    await choose_filter(callback, state, True)


@dp.message(TaskStates.edit_task)
async def choose_edit(message: Message, state: FSMContext):
    data = message.text
    nums = await state.get_data()
    nums = nums.get("nums")
    answer = f"№{data}"
    if not (int(data) in nums):
        await message.answer(f"Задача с {answer} не найдена.")
    else:
        task, session = await get_task(data, message, nums)
        nums = [nums[i] for i in nums]
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
                        InlineKeyboardButton(text="Напомнить", callback_data="set_remind"),
                    ],
                    [
                        InlineKeyboardButton(text="Завершить", callback_data="is_done"),
                        InlineKeyboardButton(text="Удалить", callback_data="delete"),
                    ],
                ])
                await state.update_data(task=task, session=session, answer=answer)
                await message.answer("Выберите действие", reply_markup=keyboard)


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


@dp.callback_query(
    F.data == "delete",
    StateFilter(TaskStates.edit_task),
)
async def delete(callback: CallbackQuery, state: FSMContext):
    task, session, answer = await get_state(state)
    await session.delete(task)
    await session.commit()
    await callback.message.answer(f'Задача {answer} успешно удалена!')
    await state.clear()
    return


@dp.callback_query(
    F.data == "change_text",
    StateFilter(TaskStates.edit_task),
)
async def change_text(callback: CallbackQuery, state: FSMContext, ):
    await change_smth(callback, state, "Введите новое название", TaskStates.change_title)
    return


@dp.message(TaskStates.change_title)
async def title_is_changed(message: Message, state: FSMContext):
    new_title = message.text
    task, session, answer = await get_state(state)
    old_title = task.title
    task.title = new_title
    session.add(task)
    await session.commit()
    await message.answer(f'Название задачи {answer} изменено с "{old_title}" на "{task.title}"')
    await state.clear()
    return


@dp.callback_query(
    F.data == "change_deadline",
    StateFilter(TaskStates.edit_task),
)
async def change_deadline(callback: CallbackQuery, state: FSMContext):
    await change_smth(callback, state, "Введите новую дату выполнения (ДД-ММ-ГГГГ):", TaskStates.change_deadline)
    return


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
        f"Дедлайн задачи {answer} перенесён с {old_deadline.strftime('%d-%m-%Y')} на {task.due_date.strftime('%d-%m-%Y')}")
    await state.clear()
    return


@dp.callback_query(
    F.data == "change_tag",
    StateFilter(TaskStates.edit_task),
)
async def change_tag(callback: CallbackQuery, state: FSMContext):
    await change_smth(callback, state, "Введите новый тег (без #):", TaskStates.change_tag)
    return


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
    await state.clear()
    return


@dp.callback_query(
    F.data == "set_remind",
    StateFilter(TaskStates.edit_task),
)
async def notification_time(callback: CallbackQuery, state: FSMContext):
    await change_smth(callback, state,
                      "Введите дату и время для получения уведомления в формате (ДД-ММ-ГГГГ ЧЧ:ММ)",
        TaskStates.set_remind)


@dp.message(TaskStates.set_remind)
async def set_remind(message: Message, state: FSMContext):
    try:
        notify_time = datetime.strptime(message.text, "%d-%m-%Y %H:%M")
        if notify_time <= datetime.now():
            await message.answer("Дата в прошлом!")
            return

        task, session, answer = await get_state(state)
        task.notify_time = notify_time
        task.send_remind = False
        session.add(task)
        await session.commit()
        formatted_time = notify_time.strftime("%d.%m.%Y в %H:%M")
        await message.answer(f"Напоминание о дедлайне задачи {answer} установлено на {formatted_time}!!!")
        await state.clear()
        return

    except ValueError:
        await message.answer("Неверный формат даты! Используйте ДД-ММ-ГГГГ ЧЧ:ММ")
        return


async def change_status(callback, state, arg, text):
    task, session, answer = await get_state(state)
    task.is_done = arg
    session.add(task)
    await session.commit()
    await callback.message.answer(f"Задача {answer} " + text)
    await state.clear()
    return


@dp.callback_query(
    F.data == "is_done",
    StateFilter(TaskStates.edit_task),
)
async def date_update(callback: CallbackQuery, state: FSMContext):
    await change_status(callback, state, True, "завершена")
    return


@dp.callback_query(
    F.data == "to_active",
    StateFilter(TaskStates.edit_task),
)
async def to_active(callback: CallbackQuery, state: FSMContext):
    await change_status(callback, state, False, "снова активна")
    return


if __name__ == "__main__":
    asyncio.run(main())
