from telegram import Update
from telegram import ChatPermissions
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    JobQueue,
)
import logging
import re
import sqlite3
import time
from datetime import datetime, time as dt_time  # Используйте alias для избежания конфликта
import psycopg2
from psycopg2.extras import DictCursor
import asyncio

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
BANNED_WORDS = ["бляд", "хуй", "пизд", "наху", "гандон", "пидр", "пидорас","пидар", "шалав", "шлюх", "мразь", "мразо", "ебат"]

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
last_zch_times = {}  # {chat_id: timestamp}
last_thanks_times = {}  # {chat_id: timestamp}
pinned_messages = {}  # {chat_id: message_id}  # Добавлено
# Глобальная переменная для управления состоянием бота
is_bot_active = True

# Бан-лист
banned_users = set()


def get_db_connection():
    try:
        conn = psycopg2.connect(
            database="railway",  # Имя вашей БД
            user="postgres",          # Пользователь БД
            password="NSHWEgFYGUgAmGtRvPxhNbIVHNhdNacT",      # Пароль
            host="postgres.railway.internal",              # Хост (например, localhost)
            port="5432"                    # Порт PostgreSQL
        )
        return conn
    except Exception as e:
        logger.error(f"Ошибка подключения к PostgreSQL: {e}")
        raise

def init_db():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
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
        conn.execute('''
            CREATE TABLE IF NOT EXISTS birthdays (
                id SERIAL PRIMARY KEY,
                user_id INTEGER UNIQUE,
                username TEXT,
                birth_date TEXT,
                last_congratulated_year INTEGER
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS ban_history (
                id SERIAL PRIMARY KEY,
                user_id INTEGER,
                username TEXT,
                reason TEXT,
                timestamp INTEGER
            )
        ''')
        conn.commit()
        logger.info("Таблицы успешно созданы")
    
    except Exception as e:
        logger.error(f"Ошибка при создании таблиц: {e}")
        if conn:
            conn.rollback()  # Откатываем транзакцию при ошибке
    
    finally:
        if conn:
            conn.close()

init_db()
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Я ваш бот. Введите /help для получения списка команд.")

async def activate_bot(context: ContextTypes.DEFAULT_TYPE):
    try:
        global is_bot_active
        is_bot_active = True
        logger.info("Бот активирован.")
    except Exception as e:
        logger.error(f"Ошибка при активации бота: {e}")

# функция, которая будет выключать бота (делать его неактивным).
async def deactivate_bot(context: ContextTypes.DEFAULT_TYPE):
    global is_bot_active
    is_bot_active = False
    logger.info("Бот деактивирован.")

# функцию, которая будет временно включать бота на 2 минуты, а затем снова выключать его.
async def temporary_activation(context: ContextTypes.DEFAULT_TYPE):
    try:
        global is_bot_active
        logger.info("Бот временно активирован на 2 минуты.")
        is_bot_active = True
        await asyncio.sleep(120)  # Бот активен 2 минуты
        is_bot_active = False
        logger.info("Бот вернулся в спящий режим.")
    except Exception as e:
        logger.error(f"Ошибка при временном пробуждении бота: {e}")

# Проверяет, является ли пользователь администратором или музыкантом
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

# Функция для добавления нарушителей в банлист_ХИСТОРИ:
async def add_to_ban_history(user_id: int, username: str, reason: str):
    conn = get_db_connection()
    conn.execute('''
        INSERT INTO ban_history (user_id, username, reason, timestamp)
        VALUES (?, ?, ?, ?)
    ''', (user_id, username, reason, int(time.time())))
    conn.commit()
    conn.close()

# Команда /ban_history:
async def ban_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat.id
    user = update.message.from_user

    # Проверка прав администратора или музыканта
    if not await is_admin_or_musician(update, context):
        response = await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=chat_id)
        await update.message.delete()  # Удаляем команду
        return

    # Получаем период из аргументов команды
    days = int(context.args[0]) if context.args else 1

    # Получаем данные из базы
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id, username, reason, timestamp 
        FROM ban_history 
        WHERE timestamp >= ?
    ''', (int(time.time()) - days * 86400,))
    results = cursor.fetchall()
    conn.close()

    if not results:
        response = await update.message.reply_text(f"Нет нарушителей за последние {days} дней.")
        context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=chat_id)
        await update.message.delete()  # Удаляем команду
        return

    # Формируем сообщение
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
        success_message = await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        context.job_queue.run_once(delete_system_message, 10, data=success_message.message_id, chat_id=chat_id)
        await update.message.delete()  # Удаляем команду
        return

    if not update.message.reply_to_message:
        success_message = await update.message.reply_text("Ответьте на сообщение, которое нужно удалить.")
        context.job_queue.run_once(delete_system_message, 10, data=success_message.message_id, chat_id=chat_id)
        await update.message.delete()  # Удаляем команду
        return

    try:
        await update.message.reply_to_message.delete()
        logger.info(f"Сообщение удалено пользователем {user.username} в чате {chat_id}.")
        await update.message.delete()  # Удаляем команду
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения: {e}")
        success_message = await update.message.reply_text("Не удалось удалить сообщение. Проверьте права бота.")
        context.job_queue.run_once(delete_system_message, 10, data=success_message.message_id, chat_id=chat_id)
        await update.message.delete()  # Удаляем команду


# Обработчик новых сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    # Игнорируем сообщения не из групп/супергрупп
    if message.chat.type not in ['group', 'supergroup']:
        return

    # Проверка на маркер "зч" или "🌟"
    if not text.lower().startswith(("звезда", "зч")) and "🌟" not in text:
        return

    # Проверка на антимат и антирекламу
    if not await is_admin_or_musician(update, context): # Исключаем администраторов и музыкантов из ограничений
        # Антимат
        if any(word in text.lower() for word in BANNED_WORDS):
            await message.delete()
            warning_message = await context.bot.send_message(
                chat_id=chat_id,
                text="Использование нецензурных выражений недопустимо!"
            )
            context.job_queue.run_once(delete_system_message, 10, data=warning_message.message_id, chat_id=chat_id)
            await add_to_ban_history(user.id, user.username or user.first_name, "Использование нецензурных выражений")
            return

        # Антиреклама
        if any(re.search(rf"\b{re.escape(keyword)}\b", text.lower()) for keyword in MESSENGER_KEYWORDS):
            await message.delete()
            warning_message = await context.bot.send_message(
                chat_id=chat_id,
                text="Отправка ссылок и упоминаний мессенджеров недопустима!"
            )
            context.job_queue.run_once(delete_system_message, 10, data=warning_message.message_id, chat_id=chat_id)
            await add_to_ban_history(user.id, user.username or user.first_name, "Отправка ссылок или упоминание мессенджеров")
            return

        # Антиспам
        user_id = user.id
        if user_id in last_zch_times:
            if current_time - last_zch_times[user_id] < SPAM_INTERVAL:
                await message.delete()
                warning_message = await context.bot.send_message(
                    chat_id=chat_id,
                    text="Слишком частое отправление сообщений! Вы замьючены на 5 минут."
                )
                context.job_queue.run_once(delete_system_message, 10, data=warning_message.message_id, chat_id=chat_id)

                # Мут пользователя на 5 минут
                try:
                    await context.bot.restrict_chat_member(
                        chat_id=chat_id,
                        user_id=user_id,
                        permissions=ChatPermissions(can_send_messages=False),
                        until_date=int(time.time()) + MUTE_DURATION
                    )
                    logger.info(f"Пользователь {user_id} замьючен на {MUTE_DURATION} секунд.")
                except Exception as e:
                    logger.error(f"Ошибка при мьюте пользователя {user_id}: {e}")

                # Добавляем нарушителя в историю
                await add_to_ban_history(user_id, user.username or user.first_name, "Спам")
                return
        last_zch_times[user_id] = current_time

    # Проверка наличия закрепленного сообщения в группе
    try:
        chat = await context.bot.get_chat(chat_id)
        pinned_message = chat.pinned_message
    except Exception as e:
        logger.error(f"Ошибка при получении информации о закрепленном сообщении: {e}")
        pinned_message = None

    # Если закрепленного сообщения нет, разрешаем закрепление
    if pinned_message is None:
        try:
            await message.pin()
            last_pinned_times[chat_id] = current_time
            last_user_username[chat_id] = user.username if user.username else None

            conn = get_db_connection()
            conn.execute('''
                INSERT INTO pinned_messages (chat_id, user_id, username, message_text, timestamp)
                VALUES (%s, %s, %s, %s, %s)
            ''', (chat_id, user.id, user.username, text, current_time))
            conn.commit()
            conn.close()

            # Автопоздравление именинников
            await auto_birthdays(context, chat_id)
            context.job_queue.run_once(unpin_last_message, PINNED_DURATION, chat_id=chat_id)

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

            # Сохраняем информацию о удаленном сообщении
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT id FROM active_users WHERE user_id = ?', (user.id,))
            result = cursor.fetchone()

            if result:
                cursor.execute('UPDATE active_users SET delete_count = delete_count + 1 WHERE user_id = ?', (user.id,))
            else:
                cursor.execute('INSERT INTO active_users (user_id, username, delete_count, timestamp) VALUES (?, ?, ?, ?)',
                               (user.id, user.username, 1, current_time))
            conn.commit()
            conn.close()

            # Отправляем благодарность за повторное сообщение
            if current_time - last_pinned_time < 180:
                last_thanks_time = last_thanks_times.get(chat_id, 0)
                if current_time - last_thanks_time >= 180:
                    thanks_message = await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"Спасибо за вашу бдительность! Звезда часа уже замечена пользователем "
                             f"{'@' + last_user_username.get(chat_id, 'неизвестным')} и закреплена в группе. "
                             f"Надеюсь, в следующий раз именно Вы станете нашей 🌟 !!!"
                    )
                    context.job_queue.run_once(delete_system_message, 180, data=thanks_message.message_id, chat_id=chat_id)
                    last_thanks_times[chat_id] = current_time
            return
        else:
            try:
                await message.pin()
                last_pinned_times[chat_id] = current_time
                last_user_username[chat_id] = user.username if user.username else None

                conn = get_db_connection()
                conn.execute('''
                    INSERT INTO pinned_messages (chat_id, user_id, username, message_text, timestamp)
                    VALUES (%s, %s, %s, %s, %s)
                ''', (chat_id, user.id, user.username, text, current_time))
                conn.commit()
                conn.close()

                correction_message = await context.bot.send_message(
                    chat_id=chat_id,
                    text="Корректировка звезды часа от Админа."
                )
                context.job_queue.run_once(delete_system_message, 10, data=correction_message.message_id, chat_id=chat_id)
            except Exception as e:
                logger.error(f"Ошибка при закреплении сообщения: {e}")
            return

    # Если время закрепления истекло, закрепляем сообщение
    try:
        await message.pin()
        last_pinned_times[chat_id] = current_time
        last_user_username[chat_id] = user.username if user.username else None

        conn = get_db_connection()
        conn.execute('''
            INSERT INTO pinned_messages (chat_id, user_id, username, message_text, timestamp)
            VALUES (%s, %s, %s, %s, %s)
        ''', (chat_id, user.id, user.username, text, current_time))
        conn.commit()
        conn.close()

        # Автопоздравление именинников
        await auto_birthdays(context, chat_id)

        context.job_queue.run_once(unpin_last_message, PINNED_DURATION, chat_id=chat_id)

        if chat_id != TARGET_GROUP_ID:
            new_text = text.replace("🌟 ", "").strip()
            forwarded_message = await context.bot.send_message(chat_id=TARGET_GROUP_ID, text=new_text)
            await forwarded_message.pin()
    except Exception as e:
        logger.error(f"Ошибка при закреплении сообщения: {e}")

    # Если время закрепления истекло, закрепляем новое сообщение
    try:
        await message.pin()
        last_pinned_times[chat_id] = current_time
        last_user_username[chat_id] = user.username if user.username else None

        conn = get_db_connection()
        conn.execute('''
            INSERT INTO pinned_messages (chat_id, user_id, username, message_text, timestamp)
            VALUES (?, ?, ?, ?, ?)
        ''', (chat_id, user.id, user.username, text, current_time))
        conn.commit()
        conn.close()

        # Пересылка сообщения в целевую группу
        if chat_id != TARGET_GROUP_ID:
            try:
                new_text = text.replace("🌟 ", "").strip()
                forwarded_message = await context.bot.send_message(chat_id=TARGET_GROUP_ID, text=new_text)
                await forwarded_message.pin()
            except Exception as e:
                logger.error(f"Ошибка при пересылке сообщения в целевую группу: {e}")

        # Автопоздравление именинников
        await auto_birthdays(context, chat_id)
        context.job_queue.run_once(unpin_last_message, PINNED_DURATION, chat_id=chat_id)
        
    except Exception as e:
        logger.error(f"Ошибка при закреплении сообщения: {e}")
    
async def check_all_birthdays(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, username, birth_date FROM birthdays')
    results = cursor.fetchall()
    conn.close()

    if not results:
        response = await update.message.reply_text("В базе данных нет записей о днях рождения.")
        context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=update.message.chat.id)
        await update.message.delete()
        return

    text = "Все дни рождения:\n"
    for row in results:
        text += f"• @{row['username']} — {row['birth_date']}\n"

    await update.message.reply_text(text)
    await update.message.delete()

# Команда /liderX
async def lider(update: Update, context: ContextTypes.DEFAULT_TYPE):
    days = int(context.args[0]) if context.args else 1
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id, username, COUNT(*) as count
        FROM pinned_messages
        WHERE timestamp >= ?
        GROUP BY user_id
        ORDER BY count DESC
        LIMIT 3
    ''', (int(time.time()) - days * 86400,))
    results = cursor.fetchall()
    conn.close()

    if not results:
        response = await update.message.reply_text("Нет данных за указанный период.")
        context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=update.message.chat.id)
        await update.message.delete()  # Удаляем команду
        return

    text = f"ТОП участников по закрепам за - {days} д.:\n"
    for i, row in enumerate(results, start=1):
        text += f"{i}. @{row['username']} — {row['count']} 🌟\n"

    await update.message.reply_text(text)
    await update.message.delete()  # Удаляем команду


# Команда /zhX
async def zh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count = int(context.args[0]) if context.args else 10
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id, username, message_text
        FROM pinned_messages
        ORDER BY timestamp DESC
        LIMIT ?
    ''', (count,))
    results = cursor.fetchall()
    conn.close()

    if not results:
        await update.message.reply_text("Нет закрепленных сообщений.")
        await update.message.delete()  # Удаляем команду
        return

    text = f"Последние {count} ⭐️🕐:\n"
    for i, row in enumerate(results, start=1):
        text += f"{i}. @{row['username']}: {row['message_text']}\n"

    await update.message.reply_text(text)
    await update.message.delete()  # Удаляем команду


# Команда /activeX
async def active(update: Update, context: ContextTypes.DEFAULT_TYPE):
    days = int(context.args[0]) if context.args else 1
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id, username, SUM(delete_count) as total_deletes
        FROM active_users
        WHERE timestamp >= ?
        GROUP BY user_id
        ORDER BY total_deletes DESC
        LIMIT 3
    ''', (int(time.time()) - days * 86400,))
    results = cursor.fetchall()
    conn.close()

    if not results:
        response = await update.message.reply_text("Нет активных пользователей за указанный период.")
        context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=update.message.chat.id)
        await update.message.delete()  # Удаляем команду
        return

    text = f"Самые активные пользователи за период - {days} д.:\n"
    for i, row in enumerate(results, start=1):
        text += f"{i}. @{row['username']} — {row['total_deletes']} раз(а) написал(а)⭐🕐\n"

    await update.message.reply_text(text)
    await update.message.delete()  # Удаляем команду


# Команда /dr
async def dr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    if context.args:
        birth_date = context.args[0]
        if re.match(r"\d{2}\.\d{2}\.\d{4}", birth_date):
            conn = get_db_connection()
            conn.execute('''
                INSERT OR REPLACE INTO birthdays (user_id, username, birth_date, last_congratulated_year)
                VALUES (?, ?, ?, ?)
            ''', (user.id, user.username, birth_date, 0))  # 0 означает, что пользователь еще не был поздравлен
            conn.commit()
            conn.close()
            response = await update.message.reply_text(f"Дата рождения сохранена: {birth_date}")
            context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=update.message.chat.id)
            await update.message.delete()  # Удаляем команду
        else:
            response = await update.message.reply_text("Неверный формат даты. Напишите одним сообщением  /dr ДД.ММ.ГГГГ")
            context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=update.message.chat.id)
            await update.message.delete()  # Удаляем команду
    else:
        response = await update.message.reply_text("Напишите свою дату рождения в формате ДД.ММ.ГГГГ")
        context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=update.message.chat.id)
        await update.message.delete()  # Удаляем команду


async def birthday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Получаем сегодняшнюю дату в формате ДД.ММ
    today = datetime.now().strftime("%d.%m")
    
    # Подключаемся к базе данных
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Логируем запрос и данные
    logger.info(f"Ищем именинников на дату: {today}")
    
    # Выполняем запрос к базе данных для поиска сегодняшних именинников
    cursor.execute('SELECT user_id, username FROM birthdays WHERE substr(birth_date, 1, 5) = ?', (today,))
    results = cursor.fetchall()
    conn.close()

    # Если именинников нет
    if not results:
        response = await update.message.reply_text(f"Сегодня ({today}) нет именинников. Чтобы добавить свою дату рождения, напишите /dr и дату рождения одним сообщением в формате /dr ДД.ММ.ГГГГ")
        context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=update.message.chat.id)
        await update.message.delete()
        return

    # Формируем сообщение с именинниками
    text = f"Сегодня ({today}) день рождения у:\n"
    for row in results:
        text += f"• @{row['username']}\n"

    # Отправляем сообщение
    await update.message.reply_text(text)
    await update.message.delete()

# Автопоздравление именинников
async def auto_birthdays(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    today = time.strftime("%d.%m")  # Сегодняшняя дата в формате ДД.ММ
    current_year = datetime.now().year  # Текущий год
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id, username 
        FROM birthdays 
        WHERE substr(birth_date, 1, 5) = ? AND (last_congratulated_year IS NULL OR last_congratulated_year < ?)
    ''', (today, current_year))
    results = cursor.fetchall()

    for row in results:
        user_id = row['user_id']
        username = row['username']

        # Получаем информацию о пользователе
        try:
            user = await context.bot.get_chat_member(chat_id, user_id)
            user_name = user.user.first_name or user.user.username or f"ID: {user.user.id}"
        except Exception as e:
            logger.error(f"Ошибка при получении информации о пользователе {user_id}: {e}")
            user_name = f"ID: {user_id}"

        # Поздравляем пользователя
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🎉{user_name} 🎊 - Поздравляю тебя с днем рождения! 🍀Желаю умножить свой cash🎁back x10 раз 🎉. _\_/_\_/_\_/_\_/_\_/_\_/_\_/_ Чтобы добавить свою дату рождения в базу, напишите команду с датой в формате /dr ДД.ММ.ГГГГ"
        )

        # Обновляем год последнего поздравления
        cursor.execute('UPDATE birthdays SET last_congratulated_year = ? WHERE user_id = ?', (current_year, user_id))
        conn.commit()

    conn.close()

async def druser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat.id
    user = update.message.from_user

    # Проверка прав администратора или музыканта
    if not await is_admin_or_musician(update, context):
        response = await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=chat_id)
        await update.message.delete()  # Удаляем команду
        return

    # Проверка, является ли команда ответом на сообщение
    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
        user_id = target_user.id
        username = target_user.username or f"ID: {target_user.id}"
        birth_date = " ".join(context.args) if context.args else None
    else:
        # Если команда не является ответом на сообщение, обрабатываем как обычно
        if not context.args or len(context.args) < 2:
            response = await update.message.reply_text(
                "Используйте команду в формате: /druser @username dd.mm.yyyy, /druser ID dd.mm.yyyy или ответьте на сообщение пользователя с командой /druser dd.mm.yyyy"
            )
            context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=chat_id)
            await update.message.delete()  # Удаляем команду
            return

        user_identifier = context.args[0]  # @username или ID
        birth_date = context.args[1]  # Дата рождения

        # Получаем user_id
        user_id = None
        username = None

        if user_identifier.startswith("@"):  # Если указан @username
            username = user_identifier[1:]  # Убираем @
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT user_id FROM birthdays WHERE username = ?', (username,))
            result = cursor.fetchone()
            if result:
                user_id = result['user_id']
            conn.close()

            # Если user_id не найден в базе, пытаемся получить его через get_chat_member
            if not user_id:
                try:
                    chat_member = await context.bot.get_chat_member(chat_id, username)
                    user_id = chat_member.user.id
                    username = chat_member.user.username or username
                except Exception as e:
                    logger.error(f"Ошибка при получении информации о пользователе {username}: {e}")
                    response = await update.message.reply_text(f"Пользователь @{username} не найден.")
                    context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=chat_id)
                    await update.message.delete()  # Удаляем команду
                    return
        else:  # Если указан ID
            try:
                user_id = int(user_identifier)
            except ValueError:
                response = await update.message.reply_text("Неверный формат ID. Используйте числовой ID.")
                context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=chat_id)
                await update.message.delete()  # Удаляем команду
                return

    # Проверка формата даты
    if not birth_date or not re.match(r"\d{2}\.\d{2}\.\d{4}", birth_date):
        response = await update.message.reply_text("Неверный формат даты. Используйте ДД.ММ.ГГГГ.")
        context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=chat_id)
        await update.message.delete()  # Удаляем команду
        return

    # Сохраняем дату рождения в базу данных
    conn = get_db_connection()
    conn.execute('''
        INSERT OR REPLACE INTO birthdays (user_id, username, birth_date, last_congratulated_year)
        VALUES (?, ?, ?, ?)
    ''', (user_id, username, birth_date, 0))  # 0 означает, что пользователь еще не был поздравлен
    conn.commit()
    conn.close()

    response = await update.message.reply_text(f"Дата рождения для пользователя {username or f'ID: {user_id}'} сохранена: {birth_date}")
    context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=chat_id)
    await update.message.delete()  # Удаляем команду

async def get_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat.id
    user = update.message.from_user

    # Проверка прав администратора или музыканта
    if not await is_admin_or_musician(update, context):
        response = await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=chat_id)
        await update.message.delete()  # Удаляем команду
        return

    # Проверка, является ли команда ответом на сообщение
    if not update.message.reply_to_message:
        response = await update.message.reply_text("Ответьте на сообщение пользователя, чтобы узнать его ID.")
        context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=chat_id)
        await update.message.delete()  # Удаляем команду
        return

    # Получаем информацию о пользователе
    target_user = update.message.reply_to_message.from_user
    user_id = target_user.id
    username = target_user.username or "без username"
    first_name = target_user.first_name or "без имени"

    # Отправляем ID пользователя
    response = await update.message.reply_text(
        f"ID пользователя {first_name} (@{username}): {user_id}"
    )
    context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=chat_id)
    await update.message.delete()  # Удаляем команду

# Команда /ban_list
async def ban_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, username FROM ban_list')
    results = cursor.fetchall()
    conn.close()

    if not results:
        response = await update.message.reply_text("Бан-лист пуст.")
        context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=update.message.chat.id)
        await update.message.delete()  # Удаляем команду
        return

    text = "Бан-лист:\n"
    for idx, row in enumerate(results, start=1):
        text += f"{idx}. ID: {row['user_id']} | Username: @{row['username']}\n"

    
    response = await update.message.reply_text(text)
    context.job_queue.run_once(delete_system_message, 60, data=response.message_id, chat_id=update.message.chat.id)
    await update.message.delete()  # Удаляем команду


# Команда /ban
async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_musician(update, context):
        response = await update.message.reply_text("❌ Только админы могут банить!")
        context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=update.message.chat.id)
        await update.message.delete()  # Удаляем команду
        return
    
    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
        
        try:
            await update.message.delete()  # Удаляем команду
        except Exception as e:
            logger.error(f"Ошибка при удалении сообщения пользователя {target_user.id}: {e}")

        if target_user.id in banned_users:
            response = await update.message.reply_text(f"@{target_user.username} уже забанен.")
            context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=update.message.chat.id)
            await update.message.delete()  # Удаляем команду
            return

        conn = get_db_connection()
        conn.execute('INSERT INTO ban_list (user_id, username, ban_time) VALUES (?, ?, ?)', 
                     (target_user.id, target_user.username, int(time.time())))
        conn.commit()
        conn.close()

        banned_users.add(target_user.id)

        try:
            await context.bot.ban_chat_member(chat_id=update.message.chat.id, user_id=target_user.id)
        except Exception as e:
            logger.error(f"Ошибка при бане пользователя {target_user.id}: {e}")     
            response = await update.message.reply_text("Не удалось забанить пользователя. Проверьте права бота.")
            context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=update.message.chat.id)
            await update.message.delete()  # Удаляем команду
            return

        
        response = await update.message.reply_text(f"@{target_user.username} забанен.")
        context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=update.message.chat.id)
        await update.message.delete()  # Удаляем команду
    elif context.args:
        user_id = context.args[0]
        try:
            user_id = int(user_id)
        except ValueError:
            response = await update.message.reply_text("Введите корректный ID пользователя.")
            context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=update.message.chat.id)
            await update.message.delete()  # Удаляем команду
            return

        conn = get_db_connection()
        conn.execute('INSERT INTO ban_list (user_id, username, ban_time) VALUES (?, ?, ?)', 
                     (user_id, "Unknown", int(time.time())))
        conn.commit()
        conn.close()

        banned_users.add(user_id) # Обновляем кэш

        try:
            await context.bot.ban_chat_member(chat_id=update.message.chat.id, user_id=user_id)
        except Exception as e:
            logger.error(f"Ошибка при бане пользователя {user_id}: {e}")
            response = await update.message.reply_text("Не удалось забанить пользователя. Проверьте права бота.")
            context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=update.message.chat.id)
            await update.message.delete()  # Удаляем команду
            return

        response = await update.message.reply_text(f"Пользователь с ID {user_id} забанен.")
        context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=update.message.chat.id)
        await update.message.delete()  # Удаляем команду
    else:
        response = await update.message.reply_text("Ответьте на сообщение пользователя или укажите его ID.")
        context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=update.message.chat.id)
        await update.message.delete()  # Удаляем команду


# Команда /deban
async def deban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_musician(update, context):
        response = await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=update.message.chat.id)
        await update.message.delete()  # Удаляем команду
        return
    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
        if target_user.id not in banned_users:
            response = await update.message.reply_text(f"@{target_user.username} не находится в бане.")
            context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=update.message.chat.id)
            await update.message.delete()  # Удаляем команду
            return

        conn = get_db_connection()
        conn.execute('DELETE FROM ban_list WHERE user_id = ?', (target_user.id,))
        conn.commit()
        conn.close()

        banned_users.discard(target_user.id)

        try:
            await context.bot.unban_chat_member(chat_id=update.message.chat.id, user_id=target_user.id)
        except Exception as e:
            logger.error(f"Ошибка при разбане пользователя {target_user.id}: {e}")
            response = await update.message.reply_text("Не удалось разбанить пользователя. Проверьте права бота.")
            context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=update.message.chat.id)
            await update.message.delete()  # Удаляем команду
            return

        response = await update.message.reply_text(f"@{target_user.username} разбанен.")
        context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=update.message.chat.id)
        await update.message.delete()  # Удаляем команду
    elif context.args:
        user_id = context.args[0]
        try:
            user_id = int(user_id)
        except ValueError:
            response = await update.message.reply_text("Введите корректный ID пользователя.")
            context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=update.message.chat.id)
            await update.message.delete()  # Удаляем команду
            return

        if user_id not in banned_users:
            response = await update.message.reply_text(f"Пользователь с ID {user_id} не находится в бане.")
            context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=update.message.chat.id)
            await update.message.delete()  # Удаляем команду
            return

        conn = get_db_connection()
        conn.execute('DELETE FROM ban_list WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()

        banned_users.discard(user_id)

        try:
            await context.bot.unban_chat_member(chat_id=update.message.chat.id, user_id=user_id)
        except Exception as e:
            logger.error(f"Ошибка при разбане пользователя {user_id}: {e}")
            response = await update.message.reply_text("Не удалось разбанить пользователя. Проверьте права бота.")
            context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=update.message.chat.id)
            await update.message.delete()  # Удаляем команду
            return

        response = await update.message.reply_text(f"Пользователь с ID {user_id} разбанен.")
        context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=update.message.chat.id)
        await update.message.delete()  # Удаляем команду
    else:
        response = await update.message.reply_text("Ответьте на сообщение пользователя или укажите его ID.")
        context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=update.message.chat.id)
        await update.message.delete()  # Удаляем команду


# Основная функция
def main():
    logger.info("Запуск бота...")
    init_db() 

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM ban_list')
    global banned_users
    banned_users = {row['user_id'] for row in cursor.fetchall()}
    conn.close()

    # Инициализация JobQueue
    application = Application.builder().token(BOT_TOKEN).build()
    job_queue = application.job_queue

    # Расписание для временного пробуждения каждые 25 минут с 21:00 до 7:00
    for hour in range(21, 24):
        for minute in range(0, 60, 25):
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
    application.add_error_handler(error_handler)
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

    try:
        application.run_polling()
        logger.info("Бот запущен. Ожидание сообщений...")
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")
    finally:
        logger.info("Бот остановлен.")


if __name__ == '__main__':
    main()
