import asyncio
import os
import logging
from datetime import datetime
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from apscheduler.schedulers.asyncio import AsyncIOScheduler

import db

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set in .env")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

class TaskForm(StatesGroup):
    title = State()
    is_daily = State()
    reminder_time = State()

def get_reply_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📝 Мои задачи"), KeyboardButton(text="➕ Добавить задачу")],
            [KeyboardButton(text="❓ Как пользоваться (Примеры)")]
        ],
        resize_keyboard=True
    )

def task_action_kb(task_id, is_done):
    status_text = "✅ Отметить как выполненное" if not is_done else "❌ Вернуть в невыполненные"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=status_text, callback_data=f"toggle_{task_id}_{int(not is_done)}")],
        [InlineKeyboardButton(text="🗑 Удалить задачу", callback_data=f"delete_{task_id}")]
    ])

@router.message(CommandStart())
async def cmd_start(message: Message):
    user_name = message.from_user.first_name
    await message.answer(
        f"Привет, {user_name}! 👋\n\n"
        "Я твой личный бот-напоминалка.\n"
        "Твои задачи полностью отделены от других пользователей, никто кроме тебя их не увидит!\n\n"
        "Используй кнопки внизу экрана, чтобы управлять задачами 👇",
        reply_markup=get_reply_kb()
    )

@router.message(F.text == "❓ Как пользоваться (Примеры)")
async def cmd_help(message: Message):
    help_text = (
        "💡 **Как это работает:**\n\n"
        "1️⃣ **Добавление задачи**\n"
        "Нажми «➕ Добавить задачу» и напиши, что нужно сделать. \n"
        "👉 *Пример:* Купить молоко\n"
        "👉 *Пример:* Выпить витамины\n\n"
        "2️⃣ **Типы задач**\n"
        "Бот спросит, повторять ли задачу каждый день. \n"
        "• *Ежедневная:* Каждый день в полночь она снова станет невыполненной.\n"
        "• *Разовая:* Выполнил один раз и забыл.\n\n"
        "3️⃣ **Напоминания**\n"
        "Можешь указать точное время в формате ЧЧ:ММ (например, 09:30 или 20:00), и бот пришлет сообщение!\n\n"
        "4️⃣ **Списки и Выполнение**\n"
        "Нажми «📝 Мои задачи». Там можно нажать на задачу и отметить её как выполненную ✅."
    )
    await message.answer(help_text, parse_mode="Markdown")

@router.message(F.text == "📝 Мои задачи")
async def cmd_tasks_list(message: Message):
    user_id = message.from_user.id
    tasks = await db.get_user_tasks(user_id)
    
    if not tasks:
        await message.answer("У тебя пока нет задач. Нажми «➕ Добавить задачу»!")
        return

    kb = []
    for t_id, title, is_daily, rem_time, is_done in tasks:
        status = "✅" if is_done else "⏳"
        daily_icon = "🔁" if is_daily else "📝"
        time_str = f" (в {rem_time})" if rem_time else ""
        btn_text = f"{status} {daily_icon} {title}{time_str}"
        kb.append([InlineKeyboardButton(text=btn_text, callback_data=f"view_{t_id}")])

    await message.answer(f"Твой личный список задач (нажми на задачу):", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data.startswith("view_"))
async def cq_view_task(callback: CallbackQuery):
    task_id = int(callback.data.split("_")[1])
    tasks = await db.get_user_tasks(callback.from_user.id)
    task = next((t for t in tasks if t[0] == task_id), None)
    
    if not task:
        await callback.answer("Задача не найдена или удалена!", show_alert=True)
        return
        
    t_id, title, is_daily, rem_time, is_done = task
    text = f"📌 **Задача:** {title}\n"
    text += f"Тип: {'Ежедневная 🔁' if is_daily else 'На один раз 📝'}\n"
    if rem_time:
        text += f"Время напоминания: {rem_time}\n"
    text += f"Статус: **{'Выполнена ✅' if is_done else 'В процессе ⏳'}**"

    await callback.message.edit_text(text, reply_markup=task_action_kb(t_id, is_done), parse_mode="Markdown")

@router.callback_query(F.data.startswith("toggle_"))
async def cq_toggle_task(callback: CallbackQuery):
    _, task_id, new_status = callback.data.split("_")
    task_id = int(task_id)
    new_status = bool(int(new_status))
    
    if new_status:
        await db.mark_task_done(task_id)
        await callback.answer("Молодец! Задача выполнена ✅")
    else:
        await db.mark_task_undone(task_id)
        await callback.answer("Задача снова в процессе ⏳")
        
    await cq_view_task(callback)

@router.callback_query(F.data.startswith("delete_"))
async def cq_delete_task(callback: CallbackQuery):
    task_id = int(callback.data.split("_")[1])
    await db.delete_task(task_id)
    await callback.answer("Задача удалена 🗑")
    await callback.message.delete()
    # Refresh list
    tasks = await db.get_user_tasks(callback.from_user.id)
    if tasks:
        kb = []
        for t_id, title, is_daily, rem_time, is_done in tasks:
            status = "✅" if is_done else "⏳"
            btn_text = f"{status} {title}"
            kb.append([InlineKeyboardButton(text=btn_text, callback_data=f"view_{t_id}")])
        await callback.message.answer("Оставшиеся задачи:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    else:
        await callback.message.answer("Список задач пуст.")

# --- Add Task Flow ---
@router.message(F.text == "➕ Добавить задачу")
async def cmd_tasks_add(message: Message, state: FSMContext):
    await message.answer("Напиши текст задачи (например: *Выпить стакан воды* или *Отправить отчет*):", parse_mode="Markdown")
    await state.set_state(TaskForm.title)

@router.message(TaskForm.title)
async def process_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Да, каждый день 🔁", callback_data="daily_yes")],
        [InlineKeyboardButton(text="Нет, только один раз 📝", callback_data="daily_no")]
    ])
    await message.answer("Эта задача будет повторяться каждый день?", reply_markup=kb)
    await state.set_state(TaskForm.is_daily)

@router.callback_query(TaskForm.is_daily, F.data.in_(["daily_yes", "daily_no"]))
async def process_is_daily(callback: CallbackQuery, state: FSMContext):
    is_daily = callback.data == "daily_yes"
    await state.update_data(is_daily=is_daily)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Без времени (Пропустить) ⏭", callback_data="time_skip")]
    ])
    await callback.message.edit_text(
        "В какое время прислать напоминание?\n"
        "Напиши время в формате **ЧЧ:ММ** (например: **09:00** или **18:30**).\n\n"
        "Если напоминание не нужно, нажми кнопку ниже.", 
        reply_markup=kb, parse_mode="Markdown"
    )
    await state.set_state(TaskForm.reminder_time)

@router.message(TaskForm.reminder_time)
async def process_time_msg(message: Message, state: FSMContext):
    time_str = message.text.strip()
    if len(time_str) == 5 and ":" in time_str:
        await finalize_task(message, state, time_str)
    else:
        await message.answer("Неверный формат ❌\nПожалуйста, напиши время как **09:30** или нажми «Без времени».", parse_mode="Markdown")

@router.callback_query(TaskForm.reminder_time, F.data == "time_skip")
async def process_time_skip(callback: CallbackQuery, state: FSMContext):
    await finalize_task(callback.message, state, None)
    await callback.message.delete()

async def finalize_task(message: Message, state: FSMContext, time_str: str | None):
    data = await state.get_data()
    user_id = message.chat.id
    
    # Optional context (for CallbackQuery message might be slightly different context)
    # user_id should be from the person doing it
    if hasattr(message, "chat"):
        uid = message.chat.id
    else:
        uid = message.from_user.id
        
    await db.add_task(uid, data['title'], data['is_daily'], time_str)
    await state.clear()
    
    await bot.send_message(uid, "✅ Ура! Задача успешно добавлена.", reply_markup=get_reply_kb())

# --- Scheduler Jobs ---
async def check_reminders():
    now_str = datetime.now().strftime("%H:%M")
    tasks = await db.get_all_tasks()
    for t_id, user_id, title, is_daily, rem_time, is_done in tasks:
        if not is_done and rem_time == now_str:
            try:
                await bot.send_message(
                    user_id, 
                    f"🔔 **НАПОМИНАНИЕ!**\nПора сделать: {title}", 
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="✅ Отметить выполненным", callback_data=f"toggle_{t_id}_1")]
                    ])
                )
            except Exception as e:
                logging.error(f"Failed to send reminder to {user_id}: {e}")

async def reset_daily():
    await db.reset_daily_tasks()
    logging.info("Daily tasks reset.")

async def main():
    await db.init_db()
    
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_reminders, 'cron', minute='*')
    scheduler.add_job(reset_daily, 'cron', hour=0, minute=0)
    scheduler.start()
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
