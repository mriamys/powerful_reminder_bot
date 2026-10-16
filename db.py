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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_completed_date TEXT,
                last_reminded_date TEXT
            )
        ''')
        # Ensure new columns exist for existing databases
        cursor = await db.execute("PRAGMA table_info(tasks)")
        columns = [row[1] for row in await cursor.fetchall()]
        if "last_completed_date" not in columns:
            await db.execute("ALTER TABLE tasks ADD COLUMN last_completed_date TEXT")
        if "last_reminded_date" not in columns:
            await db.execute("ALTER TABLE tasks ADD COLUMN last_reminded_date TEXT")
        await db.commit()

async def ensure_daily_reset(today_str: str):
    """
    Guarantees daily tasks are marked undone (is_done=0) if they were not
    completed today. Even if the bot was offline at midnight, this self-heals
    on the very next request or check.
    """
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            """
            UPDATE tasks 
            SET is_done = 0 
            WHERE is_daily = 1 
              AND (last_completed_date IS NULL OR last_completed_date != ?)
            """,
            (today_str,)
        )
        await db.commit()

async def add_task(user_id: int, title: str, is_daily: bool, reminder_time: str = None, last_reminded_date: str = None):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            """
            INSERT INTO tasks (user_id, title, is_daily, reminder_time, is_done, last_completed_date, last_reminded_date) 
            VALUES (?, ?, ?, ?, 0, NULL, ?)
            """,
            (user_id, title, is_daily, reminder_time, last_reminded_date)
        )
        await db.commit()

async def get_user_tasks(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT id, title, is_daily, reminder_time, is_done FROM tasks WHERE user_id = ? ORDER BY id ASC", 
            (user_id,)
        ) as cursor:
            return await cursor.fetchall()

async def mark_task_done(task_id: int, today_str: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE tasks SET is_done = 1, last_completed_date = ? WHERE id = ?", 
            (today_str, task_id)
        )
        await db.commit()

async def mark_task_undone(task_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE tasks SET is_done = 0, last_completed_date = NULL WHERE id = ?", 
            (task_id,)
        )
        await db.commit()

async def mark_task_reminded(task_id: int, today_str: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE tasks SET last_reminded_date = ? WHERE id = ?", 
            (today_str, task_id)
        )
        await db.commit()

async def delete_task(task_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        await db.commit()

async def get_all_tasks():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT id, user_id, title, is_daily, reminder_time, is_done, created_at, last_completed_date, last_reminded_date FROM tasks"
        ) as cursor:
            return await cursor.fetchall()

async def reset_daily_tasks(today_str: str = None):
    await ensure_daily_reset(today_str or datetime.date.today().strftime("%Y-%m-%d"))
