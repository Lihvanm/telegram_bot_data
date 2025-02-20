-- Таблица для хранения информации о пользователях
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,       -- ID пользователя
    username TEXT,                     -- Логин пользователя (если есть)
    is_spammer BOOLEAN DEFAULT FALSE, -- Флаг: является ли пользователь спамером
    is_flooder BOOLEAN DEFAULT FALSE, -- Флаг: является ли пользователь флудером
    is_matreeshnik BOOLEAN DEFAULT FALSE, -- Флаг: использовал ли пользователь мат
    total_zch_messages INTEGER DEFAULT 0, -- Количество сообщений с "зч"
    first_zch_message_time TIMESTAMP, -- Время первого сообщения с "зч"
    total_stars INTEGER DEFAULT 0     -- Количество звёзд в закрепах
);

-- Таблица для хранения истории сообщений с "зч"
CREATE TABLE IF NOT EXISTS zch_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,                   -- ID пользователя
    chat_id INTEGER,                   -- ID чата
    message_id INTEGER,                -- ID сообщения
    message_text TEXT,                 -- Текст сообщения
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(user_id)
);

-- Таблица для хранения закреплённых сообщений
CREATE TABLE IF NOT EXISTS pinned_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,                   -- ID пользователя
    chat_id INTEGER,                   -- ID чата
    message_id INTEGER,                -- ID сообщения
    message_text TEXT,                 -- Текст сообщения
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(user_id)
);
