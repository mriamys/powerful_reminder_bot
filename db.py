import aiosqlite
import datetime

DB_NAME = "tasks.db"

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                is_daily BOOLEAN DEFAULT 0,
                reminder_time TEXT,
                is_done BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.commit()

async def add_task(user_id: int, title: str, is_daily: bool, reminder_time: str = None):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO tasks (user_id, title, is_daily, reminder_time, is_done) VALUES (?, ?, ?, ?, 0)",
            (user_id, title, is_daily, reminder_time)
        )
        await db.commit()

async def get_user_tasks(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT id, title, is_daily, reminder_time, is_done FROM tasks WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchall()

async def mark_task_done(task_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE tasks SET is_done = 1 WHERE id = ?", (task_id,))
        await db.commit()

async def mark_task_undone(task_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE tasks SET is_done = 0 WHERE id = ?", (task_id,))
        await db.commit()

async def delete_task(task_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        await db.commit()

async def get_all_tasks():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT id, user_id, title, is_daily, reminder_time, is_done FROM tasks") as cursor:
            return await cursor.fetchall()

async def reset_daily_tasks():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE tasks SET is_done = 0 WHERE is_daily = 1")
        await db.commit()
