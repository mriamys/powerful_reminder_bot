import asyncio
import os
import logging
from datetime import datetime
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
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

def main_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Мои задачи", callback_data="tasks_list")],
        [InlineKeyboardButton(text="➕ Добавить задачу", callback_data="tasks_add")]
    ])

def task_action_kb(task_id, is_done):
    status_text = "✅ Выполнено" if is_done else "❌ Не выполнено (нажать для выполнения)"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=status_text, callback_data=f"toggle_{task_id}_{int(not is_done)}")],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete_{task_id}")],
        [InlineKeyboardButton(text="🔙 Назад к списку", callback_data="tasks_list")]
    ])

@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "Привет! Я мощный бот-напоминалка 🤖\n"
        "Здесь ты можешь создавать задачи (в том числе ежедневные) и управлять ими.",
        reply_markup=main_menu_kb()
    )

@router.callback_query(F.data == "main_menu")
async def cq_main_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "Главное меню:",
        reply_markup=main_menu_kb()
    )

@router.callback_query(F.data == "tasks_list")
async def cq_tasks_list(callback: CallbackQuery):
    tasks = await db.get_user_tasks(callback.from_user.id)
    if not tasks:
        await callback.message.edit_text(
            "У тебя пока нет задач.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Добавить", callback_data="tasks_add")],
                [InlineKeyboardButton(text="🔙 В главное меню", callback_data="main_menu")]
            ])
        )
        return

    kb = []
    for t_id, title, is_daily, rem_time, is_done in tasks:
        status = "✅" if is_done else "⏳"
        daily_icon = "🔁" if is_daily else "📝"
        time_str = f" ({rem_time})" if rem_time else ""
        btn_text = f"{status} {daily_icon} {title}{time_str}"
        kb.append([InlineKeyboardButton(text=btn_text, callback_data=f"view_{t_id}")])
    
    kb.append([InlineKeyboardButton(text="➕ Добавить", callback_data="tasks_add")])
    kb.append([InlineKeyboardButton(text="🔙 В главное меню", callback_data="main_menu")])

    await callback.message.edit_text("Список твоих задач:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data.startswith("view_"))
async def cq_view_task(callback: CallbackQuery):
    task_id = int(callback.data.split("_")[1])
    tasks = await db.get_user_tasks(callback.from_user.id)
    task = next((t for t in tasks if t[0] == task_id), None)
    
    if not task:
        await callback.answer("Задача не найдена!", show_alert=True)
        return
        
    t_id, title, is_daily, rem_time, is_done = task
    text = f"📌 **Задача:** {title}\n"
    text += f"Тип: {'Ежедневная 🔁' if is_daily else 'Обычная 📝'}\n"
    if rem_time:
        text += f"Напоминание в: {rem_time}\n"
    text += f"Статус: {'Выполнена ✅' if is_done else 'В процессе ⏳'}"

    await callback.message.edit_text(text, reply_markup=task_action_kb(t_id, is_done), parse_mode="Markdown")

@router.callback_query(F.data.startswith("toggle_"))
async def cq_toggle_task(callback: CallbackQuery):
    _, task_id, new_status = callback.data.split("_")
    task_id = int(task_id)
    new_status = bool(int(new_status))
    
    if new_status:
        await db.mark_task_done(task_id)
    else:
        await db.mark_task_undone(task_id)
        
    # Refresh view
    await cq_view_task(callback)
    await callback.answer("Статус обновлен!")

@router.callback_query(F.data.startswith("delete_"))
async def cq_delete_task(callback: CallbackQuery):
    task_id = int(callback.data.split("_")[1])
    await db.delete_task(task_id)
    await callback.answer("Задача удалена!")
    await cq_tasks_list(callback)

# --- Add Task Flow ---
@router.callback_query(F.data == "tasks_add")
async def cq_tasks_add(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введи текст задачи:")
    await state.set_state(TaskForm.title)

@router.message(TaskForm.title)
async def process_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Да, ежедневная 🔁", callback_data="daily_yes")],
        [InlineKeyboardButton(text="Нет, на один раз 📝", callback_data="daily_no")]
    ])
    await message.answer("Эта задача ежедневная?", reply_markup=kb)
    await state.set_state(TaskForm.is_daily)

@router.callback_query(TaskForm.is_daily, F.data.in_(["daily_yes", "daily_no"]))
async def process_is_daily(callback: CallbackQuery, state: FSMContext):
    is_daily = callback.data == "daily_yes"
    await state.update_data(is_daily=is_daily)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пропустить", callback_data="time_skip")]
    ])
    await callback.message.edit_text("В какое время напоминать? (Введи в формате ЧЧ:ММ, например 09:30). Или нажми Пропустить.", reply_markup=kb)
    await state.set_state(TaskForm.reminder_time)

@router.message(TaskForm.reminder_time)
async def process_time_msg(message: Message, state: FSMContext):
    # Basic validation (could be improved)
    time_str = message.text.strip()
    if len(time_str) == 5 and ":" in time_str:
        await finalize_task(message, state, time_str)
    else:
        await message.answer("Неверный формат. Введи в формате ЧЧ:ММ (например 09:30) или используй кнопку Пропустить.")

@router.callback_query(TaskForm.reminder_time, F.data == "time_skip")
async def process_time_skip(callback: CallbackQuery, state: FSMContext):
    await finalize_task(callback.message, state, None)
    await callback.message.delete()

async def finalize_task(message: Message, state: FSMContext, time_str: str | None):
    data = await state.get_data()
    user_id = message.chat.id
    await db.add_task(user_id, data['title'], data['is_daily'], time_str)
    await state.clear()
    
    await message.answer("✅ Задача успешно добавлена!", reply_markup=main_menu_kb())

# --- Scheduler Jobs ---
async def check_reminders():
    now_str = datetime.now().strftime("%H:%M")
    tasks = await db.get_all_tasks()
    for t_id, user_id, title, is_daily, rem_time, is_done in tasks:
        if not is_done and rem_time == now_str:
            try:
                await bot.send_message(user_id, f"🔔 Напоминание: **{title}**", parse_mode="Markdown")
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
