from telegram import Update, ChatPermissions
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    JobQueue,
)
import logging
import time
import re
from datetime import datetime, timedelta, time as dt_time
import os
import psycopg2
from psycopg2.extras import DictCursor

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Токен вашего бота
BOT_TOKEN = '8095859951:AAFGrYc5flFZk2EU8NNnsqpVWRJTGn009D4'

# ID целевой группы (если нужно пересылать сообщения)
TARGET_GROUP_ID = -1002437528572  # Замените на правильный ID группы

# Время в секундах (45 минут = 2700 секунд)
PINNED_DURATION = 2700  # Изменено на 45 минут

# Разрешенный пользователь для сброса таймера
ALLOWED_USER = "@Muzikant1429"

# Список запрещенных слов (антимат)
BANNED_WORDS = ["бляд", "хуй", "пизд", "наху", "гандон", "пидр", "пидорас", "пидар", "шалав", "шлюх", "мразь", "мразо", "ебат"]

# Ключевые слова для мессенджеров и ссылок
MESSENGER_KEYWORDS = [
    "t.me", "telegram", "whatsapp", "viber", "discord", "vk.com", "instagram",
    "facebook", "twitter", "youtube", "http", "www", ".com", ".ru", ".net", "tiktok"
]

# Лимиты для антиспама
SPAM_LIMIT = 4  # Максимальное количество сообщений
SPAM_INTERVAL = 30  # Интервал в секундах
MUTE_DURATION = 360  # Время мута в секундах (5 минут)

# Глобальные переменные
last_pinned_times = {}  # {chat_id: timestamp}
last_user_username = {}  # {chat_id: username}
last_zch_times = {}  # {user_id: timestamp}
last_thanks_times = {}  # {chat_id: timestamp}
pinned_messages = {}  # {chat_id: message_id}
is_bot_active = True  # Флаг активности бота

# Бан-лист
banned_users = set()

# Подключение к PostgreSQL
def get_db_connection():
    try:
        conn = psycopg2.connect(
            database=os.environ.get("PGDATABASE", "railway"),
            user=os.environ.get("PGUSER", "postgres"),
            password=os.environ.get("PGPASSWORD", "your_password"),
            host=os.environ.get("PGHOST", "postgres.railway.internal"),
            port=os.environ.get("PGPORT", "5432")
        )
        return conn
    except Exception as e:
        logger.error(f"Ошибка подключения к PostgreSQL: {e}")
        raise


# Инициализация базы данных
def init_db():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=DictCursor)

        # Создание таблиц
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pinned_messages (
                id SERIAL PRIMARY KEY,
                chat_id INTEGER,
                user_id INTEGER,
                username TEXT,
                message_text TEXT,
                timestamp INTEGER
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS active_users (
                id SERIAL PRIMARY KEY,
                user_id INTEGER,
                username TEXT,
                delete_count INTEGER,
                timestamp INTEGER
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS birthdays (
                id SERIAL PRIMARY KEY,
                user_id INTEGER UNIQUE,
                username TEXT,
                birth_date TEXT,
                last_congratulated_year INTEGER
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ban_list (
                id SERIAL PRIMARY KEY,
                user_id INTEGER,
                username TEXT,
                ban_time INTEGER
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ban_history (
                id SERIAL PRIMARY KEY,
                user_id INTEGER,
                username TEXT,
                reason TEXT,
                timestamp INTEGER
            )
        ''')
        conn.commit()
        logger.info("Таблицы успешно созданы.")
    except Exception as e:
        logger.error(f"Ошибка при создании таблиц: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()


init_db()


# Проверка прав администратора или музыканта
async def is_admin_or_musician(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.message.from_user
    chat_id = update.message.chat.id

    try:
        chat_member = await context.bot.get_chat_member(chat_id, user.id)
        if chat_member.status in ["administrator", "creator"]:
            return True
    except Exception as e:
        logger.error(f"Ошибка при проверке прав пользователя {user.id}: {e}")

    if user.username == ALLOWED_USER[1:]:
        return True

    return False


# Удаление системных сообщений через указанное время
async def delete_system_message(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    try:
        await context.bot.delete_message(chat_id=job.chat_id, message_id=job.data)
    except Exception as e:
        logger.error(f"Ошибка при удалении системного сообщения: {e}")


# Команда /reset_pin_timer
async def reset_pin_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat.id
    user = update.message.from_user

    if not await is_admin_or_musician(update, context):
        response = await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=chat_id)
        await update.message.delete()  # Удаляем команду
        return

    last_pinned_times[chat_id] = 0

    try:
        await context.bot.unpin_all_chat_messages(chat_id=chat_id)
        logger.info(f"Откреплены все сообщения в группе {chat_id}.")
    except Exception as e:
        logger.error(f"Ошибка при откреплении сообщений в группе {chat_id}: {e}")

    success_message = await update.message.reply_text("Таймер закрепа успешно сброшен.")
    context.job_queue.run_once(delete_system_message, 10, data=success_message.message_id, chat_id=chat_id)
    await update.message.delete()  # Удаляем команду


# Функция для добавления нарушителей в историю банов
async def add_to_ban_history(user_id: int, username: str, reason: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO ban_history (user_id, username, reason, timestamp)
        VALUES (%s, %s, %s, %s)
    ''', (user_id, username, reason, int(time.time())))
    conn.commit()
    conn.close()


# Команда /ban_history
async def ban_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat.id
    if not await is_admin_or_musician(update, context):
        response = await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=chat_id)
        await update.message.delete()  # Удаляем команду
        return

    days = int(context.args[0]) if context.args else 1

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    cursor.execute('''
        SELECT user_id, username, reason, timestamp 
        FROM ban_history 
        WHERE timestamp >= %s
    ''', (int(time.time()) - days * 86400,))
    results = cursor.fetchall()
    conn.close()

    if not results:
        response = await update.message.reply_text(f"Нет нарушителей за последние {days} дней.")
        context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=chat_id)
        await update.message.delete()  # Удаляем команду
        return

    text = f"Нарушители за последние {days} дней:\n"
    for idx, row in enumerate(results, start=1):
        text += (
            f"{idx}. ID: {row['user_id']} | "
            f"Имя: {row['username']} | "
            f"Причина: {row['reason']} | "
            f"Дата: {datetime.fromtimestamp(row['timestamp']).strftime('%d.%m.%Y %H:%M')}\n"
        )

    await update.message.reply_text(text)
    context.job_queue.run_once(delete_system_message, 60, data=response.message_id, chat_id=chat_id)
    await update.message.delete()  # Удаляем команду


# Команда /del
async def delete_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat.id
    user = update.message.from_user

    if not await is_admin_or_musician(update, context):
        response = await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=chat_id)
        await update.message.delete()  # Удаляем команду
        return

    if not update.message.reply_to_message:
        response = await update.message.reply_text("Ответьте на сообщение, которое нужно удалить.")
        context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=chat_id)
        await update.message.delete()  # Удаляем команду
        return

    try:
        await update.message.reply_to_message.delete()
        logger.info(f"Сообщение удалено пользователем {user.username} в чате {chat_id}.")
        await update.message.delete()  # Удаляем команду
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения: {e}")
        response = await update.message.reply_text("Не удалось удалить сообщение. Проверьте права бота.")
        context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=chat_id)
        await update.message.delete()  # Удаляем команду


# Обработчик новых сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_bot_active

    if not is_bot_active:
        logger.info("Бот неактивен. Сообщение игнорируется.")
        return

    message = update.message
    user = message.from_user
    chat_id = message.chat.id
    text = message.text
    current_time = int(time.time())

    # Проверка на бан в базе бота
    if user.id in banned_users:
        try:
            await message.delete()
        except Exception as e:
            logger.error(f"Ошибка удаления: {e}")
        return

    if message.chat.type not in ['group', 'supergroup']:
        return

    if not text.lower().startswith(("звезда", "зч")) and "🌟" not in text:
        return

    # Антимат, антиреклама, антиспам
    if not await is_admin_or_musician(update, context):
        if any(word in text.lower() for word in BANNED_WORDS):
            await message.delete()
            warning_message = await context.bot.send_message(
                chat_id=chat_id,
                text="Использование нецензурных выражений недопустимо!"
            )
            context.job_queue.run_once(delete_system_message, 10, data=warning_message.message_id, chat_id=chat_id)
            await add_to_ban_history(user.id, user.username or user.first_name, "Мат")
            return

        if any(re.search(rf"\b{re.escape(keyword)}\b", text.lower()) for keyword in MESSENGER_KEYWORDS):
            await message.delete()
            warning_message = await context.bot.send_message(
                chat_id=chat_id,
                text="Отправка ссылок и упоминаний мессенджеров недопустима!"
            )
            context.job_queue.run_once(delete_system_message, 10, data=warning_message.message_id, chat_id=chat_id)
            await add_to_ban_history(user.id, user.username or user.first_name, "Реклама")
            return

        if user.id in last_zch_times:
            if current_time - last_zch_times[user.id] < SPAM_INTERVAL:
                await message.delete()
                warning_message = await context.bot.send_message(
                    chat_id=chat_id,
                    text="Слишком частое отправление сообщений! Вы замьючены на 5 минут."
                )
                context.job_queue.run_once(delete_system_message, 10, data=warning_message.message_id, chat_id=chat_id)

                try:
                    await context.bot.restrict_chat_member(
                        chat_id=chat_id,
                        user_id=user.id,
                        permissions=ChatPermissions(can_send_messages=False),
                        until_date=int(time.time()) + MUTE_DURATION
                    )
                    logger.info(f"Пользователь {user.id} замьючен на {MUTE_DURATION} секунд.")
                except Exception as e:
                    logger.error(f"Ошибка при мьюте пользователя {user.id}: {e}")

                await add_to_ban_history(user.id, user.username or user.first_name, "Спам")
                return
        last_zch_times[user.id] = current_time

    # Проверка наличия закрепленного сообщения в группе
    try:
        chat = await context.bot.get_chat(chat_id)
        pinned_message = chat.pinned_message
    except Exception as e:
        logger.error(f"Ошибка при получении информации о закрепленном сообщении: {e}")
        pinned_message = None

    if pinned_message is None:
        try:
            await message.pin()
            last_pinned_times[chat_id] = current_time
            last_user_username[chat_id] = user.username if user.username else None

            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO pinned_messages (chat_id, user_id, username, message_text, timestamp)
                VALUES (%s, %s, %s, %s, %s)
            ''', (chat_id, user.id, user.username, text, current_time))
            conn.commit()
            conn.close()

            # Автопоздравление именинников
            await auto_birthdays(context, chat_id)
            context.job_queue.run_once(unpin_last_message, PINNED_DURATION, chat_id=chat_id)

            # Пересылка сообщения в целевую группу
            if chat_id != TARGET_GROUP_ID:
                new_text = text.replace("🌟 ", "").strip()
                forwarded_message = await context.bot.send_message(chat_id=TARGET_GROUP_ID, text=new_text)
                await forwarded_message.pin()
        except Exception as e:
            logger.error(f"Ошибка при закреплении сообщения: {e}")
        return

    last_pinned_time = last_pinned_times.get(chat_id, 0)
    if current_time - last_pinned_time < PINNED_DURATION:
        if not await is_admin_or_musician(update, context):
            await message.delete()
            return

    try:
        await message.pin()
        last_pinned_times[chat_id] = current_time
        last_user_username[chat_id] = user.username if user.username else None

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO pinned_messages (chat_id, user_id, username, message_text, timestamp)
            VALUES (%s, %s, %s, %s, %s)
        ''', (chat_id, user.id, user.username, text, current_time))
        conn.commit()
        conn.close()

        # Пересылка сообщения в целевую группу
        if chat_id != TARGET_GROUP_ID:
            new_text = text.replace("🌟 ", "").strip()
            forwarded_message = await context.bot.send_message(chat_id=TARGET_GROUP_ID, text=new_text)
            await forwarded_message.pin()

        # Автопоздравление именинников
        await auto_birthdays(context, chat_id)
        context.job_queue.run_once(unpin_last_message, PINNED_DURATION, chat_id=chat_id)
    except Exception as e:
        logger.error(f"Ошибка при закреплении сообщения: {e}")


# Автопоздравление именинников
async def auto_birthdays(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    today = datetime.now().strftime("%d.%m")
    current_year = datetime.now().year

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    cursor.execute('''
        SELECT user_id, username 
        FROM birthdays 
        WHERE substr(birth_date, 1, 5) = %s AND (last_congratulated_year IS NULL OR last_congratulated_year < %s)
    ''', (today, current_year))
    results = cursor.fetchall()
    conn.close()

    for row in results:
        user_id = row['user_id']
        username = row['username']

        try:
            user = await context.bot.get_chat_member(chat_id, user_id)
            user_name = user.user.first_name or user.user.username or f"ID: {user.user.id}"
        except Exception as e:
            logger.error(f"Ошибка при получении информации о пользователе {user_id}: {e}")
            user_name = f"ID: {user_id}"

        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🎉{user_name} 🎊 - Поздравляю тебя с днем рождения! 🍀Желаю умножить свой cash🎁back x10 раз 🎉"
        )

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE birthdays SET last_congratulated_year = %s WHERE user_id = %s', (current_year, user_id))
        conn.commit()
        conn.close()


# Основная функция
def main():
    global banned_users

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    cursor.execute('SELECT user_id FROM ban_list')
    banned_users = {row['user_id'] for row in cursor.fetchall()}
    conn.close()

    application = Application.builder().token(BOT_TOKEN).build()
    job_queue = application.job_queue

    # Расписание для временного пробуждения каждые 25 минут с 21:00 до 7:00
    for hour in range(21, 24):  # С 21:00 до 23:59
        for minute in range(0, 60, 25):  # Каждые 25 минут
            job_queue.run_daily(temporary_activation, time=dt_time(hour=hour, minute=minute, second=0))
            logger.info(f"Запланировано временное пробуждение бота в {hour:02d}:{minute:02d}.")

    for hour in range(0, 7):  # С 00:00 до 6:59
        for minute in range(0, 60, 25):  # Каждые 25 минут
            job_queue.run_daily(temporary_activation, time=dt_time(hour=hour, minute=minute, second=0))
            logger.info(f"Запланировано временное пробуждение бота в {hour:02d}:{minute:02d}.")

    # Расписание для выключения бота в 21:00
    job_queue.run_daily(deactivate_bot, time=dt_time(hour=21, minute=0, second=0))
    logger.info("Запланировано выключение бота в 21:00.")

    # Расписание для включения бота в 7:00
    job_queue.run_daily(activate_bot, time=dt_time(hour=7, minute=0, second=0))
    logger.info("Запланировано включение бота в 07:00.")

    # Добавление обработчиков команд и сообщений
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("timer", reset_pin_timer))
    application.add_handler(CommandHandler("del", delete_message))
    application.add_handler(CommandHandler("lider", lider))
    application.add_handler(CommandHandler("zh", zh))
    application.add_handler(CommandHandler("active", active))
    application.add_handler(CommandHandler("dr", dr))
    application.add_handler(CommandHandler("druser", druser))  # Добавляем команду /druser
    application.add_handler(CommandHandler("id", get_user_id))  # Добавляем команду /id
    application.add_handler(CommandHandler("birthday", birthday))
    application.add_handler(CommandHandler("check_birthdays", check_all_birthdays))
    application.add_handler(CommandHandler("ban_list", ban_list))
    application.add_handler(CommandHandler("ban", ban_user))
    application.add_handler(CommandHandler("deban", deban_user))
    application.add_handler(CommandHandler("ban_history", ban_history))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Настройка вебхука
    PORT = int(os.environ.get('PORT', '8443'))
    WEBHOOK_URL = f"https://{os.environ.get('RAILWAY_HOST')}/telegram/webhook"

    try:
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path="/telegram/webhook",
            webhook_url=WEBHOOK_URL,
            secret_token=os.environ.get('TELEGRAM_SECRET_TOKEN', '')
        )
        logger.info("Бот запущен через вебхук. Ожидание сообщений...")
    except Exception as e:
        logger.error(f"Ошибка при запуске бота через вебхук: {e}")
    finally:
        logger.info("Бот остановлен.")


# Функция для временного включения бота
async def temporary_activation(context: ContextTypes.DEFAULT_TYPE):
    global is_bot_active
    logger.info("Бот временно активирован на 2 минуты.")
    is_bot_active = True
    await asyncio.sleep(120)  # Бот активен 2 минуты
    is_bot_active = False
    logger.info("Бот вернулся в спящий режим.")


# Функция для выключения бота
async def deactivate_bot(context: ContextTypes.DEFAULT_TYPE):
    global is_bot_active
    is_bot_active = False
    logger.info("Бот деактивирован.")


# Функция для включения бота
async def activate_bot(context: ContextTypes.DEFAULT_TYPE):
    global is_bot_active
    is_bot_active = True
    logger.info("Бот активирован.")


if __name__ == '__main__':
    main()
