import asyncio
import os
import logging
from datetime import datetime
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import CommandStart, Command
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
            [KeyboardButton(text="📝 Мои задачи"), KeyboardButton(text="➕ Добавить задачу")]
        ],
        resize_keyboard=True
    )

def task_action_kb(task_id, is_done):
    status_text = "✅ Отметить как выполненное" if not is_done else "❌ Вернуть в невыполненные"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=status_text, callback_data=f"toggle_{task_id}_{int(not is_done)}")],
        [InlineKeyboardButton(text="🗑 Удалить задачу", callback_data=f"delete_{task_id}")],
        [InlineKeyboardButton(text="🔙 Назад к списку", callback_data="back_tasks_list")]
    ])

@router.message(CommandStart())
async def cmd_start(message: Message):
    user_name = message.from_user.first_name
    await message.answer(
        f"Привет, {user_name}! 👋\n\n"
        "Я твой личный бот-напоминалка.\n"
        "Твои задачи полностью приватны и отделены от других пользователей.\n\n"
        "Управляй задачами с помощью кнопок внизу 👇",
        reply_markup=get_reply_kb()
    )

@router.message(Command("help"))
async def cmd_help(message: Message):
    help_text = (
        "💡 **Подсказка:**\n"
        "• «➕ Добавить задачу» — создать новую задачу (разовую или ежедневную).\n"
        "• «📝 Мои задачи» — посмотреть список, отметить выполненными или удалить.\n"
        "• Одноразовые задачи удаляются сразу при выполнении!\n"
        "• Ежедневные задачи обновляются каждую полночь."
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

    await message.answer("Твой личный список задач (нажми на задачу):", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data == "back_tasks_list")
async def cq_back_tasks_list(callback: CallbackQuery):
    user_id = callback.from_user.id
    tasks = await db.get_user_tasks(user_id)
    
    if not tasks:
        await callback.message.edit_text("У тебя пока нет задач. Нажми «➕ Добавить задачу» на клавиатуре!")
        return

    kb = []
    for t_id, title, is_daily, rem_time, is_done in tasks:
        status = "✅" if is_done else "⏳"
        daily_icon = "🔁" if is_daily else "📝"
        time_str = f" (в {rem_time})" if rem_time else ""
        btn_text = f"{status} {daily_icon} {title}{time_str}"
        kb.append([InlineKeyboardButton(text=btn_text, callback_data=f"view_{t_id}")])

    await callback.message.edit_text("Твой личный список задач (нажми на задачу):", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data.startswith("view_"))
async def cq_view_task(callback: CallbackQuery):
    task_id = int(callback.data.split("_")[1])
    tasks = await db.get_user_tasks(callback.from_user.id)
    task = next((t for t in tasks if t[0] == task_id), None)
    
    if not task:
        await callback.answer("Задача не найдена или уже удалена!", show_alert=True)
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
    
    tasks = await db.get_user_tasks(callback.from_user.id)
    task = next((t for t in tasks if t[0] == task_id), None)
    
    if not task:
        await callback.answer("Задача не найдена!", show_alert=True)
        return

    t_id, title, is_daily, rem_time, is_done = task
    
    if new_status:
        if not is_daily:
            # Одноразовая задача выполнена -> удаляем из списка
            await db.delete_task(task_id)
            await callback.answer("Задача выполнена и удалена из списка! 🎉")
            await callback.message.delete()
            
            remaining = await db.get_user_tasks(callback.from_user.id)
            if remaining:
                kb = []
                for tid, t_title, t_daily, t_rem, t_done in remaining:
                    status = "✅" if t_done else "⏳"
                    daily_icon = "🔁" if t_daily else "📝"
                    time_str = f" (в {t_rem})" if t_rem else ""
                    btn_text = f"{status} {daily_icon} {t_title}{time_str}"
                    kb.append([InlineKeyboardButton(text=btn_text, callback_data=f"view_{tid}")])
                await callback.message.answer(
                    f"✅ Одноразовая задача **«{title}»** выполнена и удалена!\n\nТвой список задач:",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=kb),
                    parse_mode="Markdown"
                )
            else:
                await callback.message.answer(
                    f"✅ Одноразовая задача **«{title}»** выполнена и удалена!\n\nСписок пуст 🎉",
                    parse_mode="Markdown"
                )
            return
        else:
            await db.mark_task_done(task_id)
            await callback.answer("Молодец! Ежедневная задача выполнена ✅")
    else:
        await db.mark_task_undone(task_id)
        await callback.answer("Задача снова в процессе ⏳")
        
    tasks = await db.get_user_tasks(callback.from_user.id)
    task = next((t for t in tasks if t[0] == task_id), None)
    if task:
        t_id, title, is_daily, rem_time, is_done = task
        text = f"📌 **Задача:** {title}\n"
        text += f"Тип: {'Ежедневная 🔁' if is_daily else 'На один раз 📝'}\n"
        if rem_time:
            text += f"Время напоминания: {rem_time}\n"
        text += f"Статус: **{'Выполнена ✅' if is_done else 'В процессе ⏳'}**"
        await callback.message.edit_text(text, reply_markup=task_action_kb(t_id, is_done), parse_mode="Markdown")

@router.callback_query(F.data.startswith("remtoggle_"))
async def cq_remtoggle_task(callback: CallbackQuery):
    _, task_id, new_status = callback.data.split("_")
    task_id = int(task_id)
    new_status = bool(int(new_status))
    
    tasks = await db.get_user_tasks(callback.from_user.id)
    task = next((t for t in tasks if t[0] == task_id), None)
    
    if not task:
        await callback.answer("Задача уже удалена или выполнена!", show_alert=True)
        return

    t_id, title, is_daily, rem_time, is_done = task
    
    if new_status:
        if not is_daily:
            # Одноразовая задача выполнена -> удаляем из списка
            await db.delete_task(task_id)
            await callback.answer("Задача выполнена и удалена! 🎉")
            await callback.message.edit_text(
                f"🔔 **НАПОМИНАНИЕ**\n\n📌 Задача: **{title}**\n\n✅ **Выполнена и удалена из списка!**",
                reply_markup=None,
                parse_mode="Markdown"
            )
            return
        else:
            await db.mark_task_done(task_id)
            await callback.answer("Молодец! Задача выполнена ✅")
            status_label = "Выполнена ✅"
            next_btn = InlineKeyboardButton(text="❌ Вернуть в невыполненные", callback_data=f"remtoggle_{task_id}_0")
            await callback.message.edit_text(
                f"🔔 **НАПОМИНАНИЕ!**\nПора сделать: **{title}**\n\nСтатус: **{status_label}**",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[next_btn]]),
                parse_mode="Markdown"
            )
    else:
        await db.mark_task_undone(task_id)
        await callback.answer("Задача снова в процессе ⏳")
        status_label = "В процессе ⏳"
        next_btn = InlineKeyboardButton(text="✅ Отметить выполненным", callback_data=f"remtoggle_{task_id}_1")
        await callback.message.edit_text(
            f"🔔 **НАПОМИНАНИЕ!**\nПора сделать: **{title}**\n\nСтатус: **{status_label}**",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[next_btn]]),
            parse_mode="Markdown"
        )

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
            daily_icon = "🔁" if is_daily else "📝"
            time_str = f" (в {rem_time})" if rem_time else ""
            btn_text = f"{status} {daily_icon} {title}{time_str}"
            kb.append([InlineKeyboardButton(text=btn_text, callback_data=f"view_{t_id}")])
        await callback.message.answer("Оставшиеся задачи:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    else:
        await callback.message.answer("Список задач пуст.")

# --- Add Task Flow ---
@router.message(F.text == "➕ Добавить задачу")
async def cmd_tasks_add(message: Message, state: FSMContext):
    await message.answer("Напиши текст задачи (например: *Купить молоко* или *Позвонить врачу*):", parse_mode="Markdown")
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
                        [InlineKeyboardButton(text="✅ Отметить выполненным", callback_data=f"remtoggle_{t_id}_1")]
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
