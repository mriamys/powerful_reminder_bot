import asyncio
import os
import html
import logging
from datetime import datetime
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import (
    Message, CallbackQuery, 
    InlineKeyboardMarkup, InlineKeyboardButton, 
    ReplyKeyboardMarkup, KeyboardButton
)
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

bot = Bot(
    token=BOT_TOKEN, 
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
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
    status_text = "✅ Отметить выполненным" if not is_done else "↩️ Вернуть в невыполненные"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=status_text, callback_data=f"toggle_{task_id}_{int(not is_done)}")],
        [InlineKeyboardButton(text="🗑 Удалить задачу", callback_data=f"delete_{task_id}")],
        [InlineKeyboardButton(text="🔙 Назад к списку", callback_data="back_tasks_list")]
    ])

def format_task_card(title: str, is_daily: bool, rem_time: str | None, is_done: bool) -> str:
    type_badge = "🔁 Ежедневная <i>(сброс в 00:00)</i>" if is_daily else "📝 Разовая <i>(удалится после выполнения)</i>"
    time_badge = f"⏰ <code>{html.escape(rem_time)}</code>" if rem_time else "<i>Не установлено</i>"
    status_badge = "✅ <b>Выполнена</b>" if is_done else "⏳ <b>В процессе</b>"
    
    title_escaped = html.escape(title)
    if is_done:
        title_formatted = f"<s>📌 <b>{title_escaped}</b></s>"
    else:
        title_formatted = f"📌 <b>{title_escaped}</b>"

    return (
        f"{title_formatted}\n\n"
        f"<blockquote>"
        f"<b>Тип:</b> {type_badge}\n"
        f"<b>Время напоминания:</b> {time_badge}\n"
        f"<b>Статус:</b> {status_badge}"
        f"</blockquote>"
    )

@router.message(CommandStart())
async def cmd_start(message: Message):
    user_name = html.escape(message.from_user.first_name or "друг")
    await message.answer(
        f"👋 <b>Привет, {user_name}!</b>\n\n"
        f"<blockquote>🤖 <b>Личный менеджер задач</b>\n"
        f"Твой список полностью приватный и надежно сохранен.</blockquote>\n\n"
        f"Выбирай нужное действие внизу 👇",
        reply_markup=get_reply_kb()
    )

@router.message(Command("help"))
async def cmd_help(message: Message):
    help_text = (
        "💡 <b>Быстрая подсказка:</b>\n\n"
        "<blockquote>"
        "• <b>➕ Добавить задачу</b> — создать разовую или повторяющуюся задачу\n"
        "• <b>📝 Мои задачи</b> — список активных задач и управление ими\n"
        "• Одноразовые задачи удаляются сразу после выполнения\n"
        "• Ежедневные задачи обновляются автоматически каждую полночь"
        "</blockquote>"
    )
    await message.answer(help_text)

@router.message(F.text == "📝 Мои задачи")
async def cmd_tasks_list(message: Message):
    user_id = message.from_user.id
    tasks = await db.get_user_tasks(user_id)
    
    if not tasks:
        await message.answer(
            "✨ <b>Список задач пуст!</b>\n\n"
            "<blockquote>Нажми <b>«➕ Добавить задачу»</b>, чтобы создать новую.</blockquote>"
        )
        return

    kb = []
    for t_id, title, is_daily, rem_time, is_done in tasks:
        status_icon = "✅" if is_done else "⏳"
        daily_icon = "🔁" if is_daily else "📝"
        time_str = f" [⏰ {rem_time}]" if rem_time else ""
        btn_text = f"{status_icon} {daily_icon} {title}{time_str}"
        kb.append([InlineKeyboardButton(text=btn_text, callback_data=f"view_{t_id}")])

    await message.answer(
        f"📋 <b>Твой список задач</b>\n\n"
        f"<blockquote>Всего задач: <b>{len(tasks)}</b> • Нажми на задачу для просмотра:</blockquote>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
    )

@router.callback_query(F.data == "back_tasks_list")
async def cq_back_tasks_list(callback: CallbackQuery):
    user_id = callback.from_user.id
    tasks = await db.get_user_tasks(user_id)
    
    if not tasks:
        await callback.message.edit_text(
            "✨ <b>Список задач пуст!</b>\n\n"
            "<blockquote>Нажми <b>«➕ Добавить задачу»</b> на клавиатуре, чтобы создать новую.</blockquote>"
        )
        return

    kb = []
    for t_id, title, is_daily, rem_time, is_done in tasks:
        status_icon = "✅" if is_done else "⏳"
        daily_icon = "🔁" if is_daily else "📝"
        time_str = f" [⏰ {rem_time}]" if rem_time else ""
        btn_text = f"{status_icon} {daily_icon} {title}{time_str}"
        kb.append([InlineKeyboardButton(text=btn_text, callback_data=f"view_{t_id}")])

    await callback.message.edit_text(
        f"📋 <b>Твой список задач</b>\n\n"
        f"<blockquote>Всего задач: <b>{len(tasks)}</b> • Нажми на задачу для просмотра:</blockquote>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
    )

@router.callback_query(F.data.startswith("view_"))
async def cq_view_task(callback: CallbackQuery):
    task_id = int(callback.data.split("_")[1])
    tasks = await db.get_user_tasks(callback.from_user.id)
    task = next((t for t in tasks if t[0] == task_id), None)
    
    if not task:
        await callback.answer("Задача не найдена или уже удалена!", show_alert=True)
        return
        
    t_id, title, is_daily, rem_time, is_done = task
    text = format_task_card(title, is_daily, rem_time, is_done)
    await callback.message.edit_text(text, reply_markup=task_action_kb(t_id, is_done))

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
            # Одноразовая задача -> сразу удаляем из базы
            await db.delete_task(task_id)
            await callback.answer("Задача выполнена и удалена! 🎉")
            await callback.message.delete()
            
            remaining = await db.get_user_tasks(callback.from_user.id)
            if remaining:
                kb = []
                for tid, t_title, t_daily, t_rem, t_done in remaining:
                    status_icon = "✅" if t_done else "⏳"
                    daily_icon = "🔁" if t_daily else "📝"
                    time_str = f" [⏰ {t_rem}]" if t_rem else ""
                    btn_text = f"{status_icon} {daily_icon} {t_title}{time_str}"
                    kb.append([InlineKeyboardButton(text=btn_text, callback_data=f"view_{tid}")])
                await callback.message.answer(
                    f"✅ <s><b>{html.escape(title)}</b></s> выполнена и удалена!\n\n"
                    f"<blockquote>📋 <b>Оставшиеся задачи:</b></blockquote>",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
                )
            else:
                await callback.message.answer(
                    f"✅ <s><b>{html.escape(title)}</b></s> выполнена и удалена!\n\n"
                    f"<blockquote>🎉 <b>Все задачи выполнены, список пуст!</b></blockquote>"
                )
            return
        else:
            await db.mark_task_done(task_id)
            await callback.answer("Ежедневная задача выполнена! ✅")
    else:
        await db.mark_task_undone(task_id)
        await callback.answer("Задача возвращена в работу ⏳")
        
    tasks = await db.get_user_tasks(callback.from_user.id)
    task = next((t for t in tasks if t[0] == task_id), None)
    if task:
        t_id, title, is_daily, rem_time, is_done = task
        text = format_task_card(title, is_daily, rem_time, is_done)
        await callback.message.edit_text(text, reply_markup=task_action_kb(t_id, is_done))

@router.callback_query(F.data.startswith("remtoggle_"))
async def cq_remtoggle_task(callback: CallbackQuery):
    _, task_id, new_status = callback.data.split("_")
    task_id = int(task_id)
    new_status = bool(int(new_status))
    
    tasks = await db.get_user_tasks(callback.from_user.id)
    task = next((t for t in tasks if t[0] == task_id), None)
    
    if not task:
        await callback.answer("Задача уже выполнена или удалена!", show_alert=True)
        return

    t_id, title, is_daily, rem_time, is_done = task
    title_escaped = html.escape(title)
    
    if new_status:
        if not is_daily:
            # Одноразовая задача завершена из уведомления -> удаляем
            await db.delete_task(task_id)
            await callback.answer("Выполнено и удалено! 🎉")
            await callback.message.edit_text(
                f"<s>📌 <b>{title_escaped}</b></s>\n\n"
                f"<blockquote>✅ <b>Задача выполнена и удалена из списка!</b></blockquote>",
                reply_markup=None
            )
            return
        else:
            await db.mark_task_done(task_id)
            await callback.answer("Отлично! Задача выполнена ✅")
            next_btn = InlineKeyboardButton(text="↩️ Вернуть в невыполненные", callback_data=f"remtoggle_{task_id}_0")
            await callback.message.edit_text(
                f"<s>📌 <b>{title_escaped}</b></s>\n\n"
                f"<blockquote>✅ <b>Выполнено на сегодня!</b>\n"
                f"🔁 <i>Сбросится в 00:00</i></blockquote>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[next_btn]])
            )
    else:
        await db.mark_task_undone(task_id)
        await callback.answer("Задача снова в работе ⏳")
        next_btn = InlineKeyboardButton(text="✅ Отметить выполненным", callback_data=f"remtoggle_{task_id}_1")
        await callback.message.edit_text(
            f"📌 <b>{title_escaped}</b>\n\n"
            f"<blockquote>⏰ <b>Напоминание • В процессе</b>\n"
            f"Не забудь выполнить задачу!</blockquote>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[next_btn]])
        )

@router.callback_query(F.data.startswith("delete_"))
async def cq_delete_task(callback: CallbackQuery):
    task_id = int(callback.data.split("_")[1])
    await db.delete_task(task_id)
    await callback.answer("Задача удалена 🗑")
    await callback.message.delete()
    
    tasks = await db.get_user_tasks(callback.from_user.id)
    if tasks:
        kb = []
        for t_id, title, is_daily, rem_time, is_done in tasks:
            status_icon = "✅" if is_done else "⏳"
            daily_icon = "🔁" if is_daily else "📝"
            time_str = f" [⏰ {rem_time}]" if rem_time else ""
            btn_text = f"{status_icon} {daily_icon} {title}{time_str}"
            kb.append([InlineKeyboardButton(text=btn_text, callback_data=f"view_{t_id}")])
        await callback.message.answer(
            f"🗑 <b>Задача удалена.</b>\n\n"
            f"<blockquote>📋 <b>Оставшиеся задачи:</b></blockquote>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
        )
    else:
        await callback.message.answer(
            "🗑 <b>Задача удалена.</b>\n\n"
            "<blockquote>Список задач теперь пуст.</blockquote>"
        )

# --- Add Task Flow ---
@router.message(F.text == "➕ Добавить задачу")
async def cmd_tasks_add(message: Message, state: FSMContext):
    await message.answer(
        "✍️ <b>Новая задача</b>\n\n"
        "Напиши название задачи:\n"
        "<i>Например: <code>Купить молоко</code> или <code>Выпить таблетки</code></i>"
    )
    await state.set_state(TaskForm.title)

@router.message(TaskForm.title)
async def process_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    title_escaped = html.escape(message.text)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔁 Каждый день", callback_data="daily_yes")],
        [InlineKeyboardButton(text="📝 Только один раз", callback_data="daily_no")]
    ])
    await message.answer(
        f"📌 <b>{title_escaped}</b>\n\n"
        f"Как часто нужно выполнять эту задачу?", 
        reply_markup=kb
    )
    await state.set_state(TaskForm.is_daily)

@router.callback_query(TaskForm.is_daily, F.data.in_(["daily_yes", "daily_no"]))
async def process_is_daily(callback: CallbackQuery, state: FSMContext):
    is_daily = callback.data == "daily_yes"
    await state.update_data(is_daily=is_daily)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Без напоминания", callback_data="time_skip")]
    ])
    await callback.message.edit_text(
        "⏰ <b>Время напоминания</b>\n\n"
        "Во сколько прислать уведомление?\n"
        "Напиши время в формате <code>ЧЧ:ММ</code> (например: <code>09:30</code> или <code>20:00</code>).\n\n"
        "<i>Или нажми кнопку ниже, если точное время не нужно:</i>", 
        reply_markup=kb
    )
    await state.set_state(TaskForm.reminder_time)

@router.message(TaskForm.reminder_time)
async def process_time_msg(message: Message, state: FSMContext):
    time_str = message.text.strip()
    if len(time_str) == 5 and ":" in time_str:
        await finalize_task(message, state, time_str)
    else:
        await message.answer(
            "⚠️ <b>Неверный формат времени!</b>\n\n"
            "Пожалуйста, укажи время в виде <code>09:30</code> или <code>18:00</code>, либо нажми кнопку <b>«Без напоминания»</b> выше."
        )

@router.callback_query(TaskForm.reminder_time, F.data == "time_skip")
async def process_time_skip(callback: CallbackQuery, state: FSMContext):
    await finalize_task(callback.message, state, None)
    await callback.message.delete()

async def finalize_task(message: Message, state: FSMContext, time_str: str | None):
    data = await state.get_data()
    uid = message.chat.id if hasattr(message, "chat") else message.from_user.id
    title = data['title']
    is_daily = data['is_daily']
        
    await db.add_task(uid, title, is_daily, time_str)
    await state.clear()
    
    type_badge = "🔁 Ежедневная" if is_daily else "📝 Разовая"
    time_badge = f"⏰ <code>{time_str}</code>" if time_str else "<i>без напоминания</i>"
    
    await bot.send_message(
        uid, 
        f"🎉 <b>Задача успешно создана!</b>\n\n"
        f"📌 <b>{html.escape(title)}</b>\n"
        f"<blockquote><b>Тип:</b> {type_badge}\n"
        f"<b>Время:</b> {time_badge}</blockquote>", 
        reply_markup=get_reply_kb()
    )

# --- Scheduler Jobs ---
async def check_reminders():
    now_str = datetime.now().strftime("%H:%M")
    tasks = await db.get_all_tasks()
    for t_id, user_id, title, is_daily, rem_time, is_done in tasks:
        if not is_done and rem_time == now_str:
            title_escaped = html.escape(title)
            # Задачу ставим в САМЫЙ верх, чтобы в пуш-уведомлении телефона сразу читалось название!
            text = (
                f"📌 <b>{title_escaped}</b>\n\n"
                f"<blockquote>⏰ <b>Напоминание • {rem_time}</b>\n"
                f"Пора выполнить запланированное дело!</blockquote>"
            )
            try:
                await bot.send_message(
                    user_id, 
                    text,
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
