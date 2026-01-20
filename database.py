import sqlite3
import json
import secrets
import time
from datetime import datetime
from typing import Optional, Dict, Any, List
from contextlib import contextmanager
import config
import logging

# Настройка логирования
logger = logging.getLogger(__name__)

class CacheManager:
    """Менеджер кэша для оптимизации запросов"""
    def __init__(self):
        self.cache = {}
        self.cache_times = {}
    
    def get(self, key: str, ttl: int = 30) -> Optional[Any]:
        """Получить значение из кэша"""
        if key not in self.cache:
            return None
        
        # Проверяем время жизни
        if time.time() - self.cache_times.get(key, 0) > ttl:
            del self.cache[key]
            del self.cache_times[key]
            return None
        
        return self.cache[key]
    
    def set(self, key: str, value: Any):
        """Сохранить значение в кэш"""
        self.cache[key] = value
        self.cache_times[key] = time.time()
    
    def invalidate(self, pattern: str = None):
        """Инвалидировать кэш по паттерну"""
        if pattern is None:
            self.cache.clear()
            self.cache_times.clear()
        else:
            keys_to_delete = [k for k in self.cache.keys() if pattern in k]
            for key in keys_to_delete:
                del self.cache[key]
                if key in self.cache_times:
                    del self.cache_times[key]

class Database:
    def __init__(self, db_path: str = config.DATABASE_PATH):
        self.db_path = db_path
        self.cache = CacheManager()
        self.init_database()
    
    @contextmanager
    def get_connection(self):
        """Контекстный менеджер для работы с БД"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def init_database(self):
        """Инициализация структуры базы данных"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Таблица пользователей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    is_admin BOOLEAN DEFAULT 0,
                    last_message_id INTEGER,  -- ДОБАВЛЕНО
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица ключей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key_value TEXT UNIQUE NOT NULL,
                    created_by INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    activated_by INTEGER,
                    activated_at TIMESTAMP,
                    is_frozen BOOLEAN DEFAULT 0,
                    FOREIGN KEY (created_by) REFERENCES users(user_id),
                    FOREIGN KEY (activated_by) REFERENCES users(user_id)
                )
            ''')
            
            # Таблица настроек скрипта
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS script_settings (
                    user_id INTEGER PRIMARY KEY,
                    settings TEXT NOT NULL,
                    config_version INTEGER DEFAULT 1,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')
            
            # Таблица координат
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS coordinates (
                    user_id INTEGER,
                    coord_name TEXT,
                    x INTEGER NOT NULL,
                    y INTEGER NOT NULL,
                    description TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, coord_name),
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')
            
            # Таблица команд (очередь)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS commands (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    command_type TEXT NOT NULL,
                    params TEXT,
                    status TEXT DEFAULT 'pending',
                    result TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    executed_at TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')
            
            # Таблица статусов скриптов
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS script_status (
                    user_id INTEGER PRIMARY KEY,
                    is_running BOOLEAN DEFAULT 0,
                    is_paused BOOLEAN DEFAULT 0,
                    pause_until TIMESTAMP,
                    last_heartbeat TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')
            
            # Индексы для оптимизации
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_keys_activated ON keys(activated_by)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_keys_frozen ON keys(is_frozen)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_commands_status ON commands(user_id, status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_commands_created ON commands(created_at)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_script_status_running ON script_status(is_running)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_admin ON users(is_admin)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_settings_updated ON script_settings(updated_at)')
            
            conn.commit()
    
    # ===== ПОЛЬЗОВАТЕЛИ =====
    
    def get_or_create_user(self, user_id: int, username: str = None) -> Dict:
        """Получить или создать пользователя с кэшированием"""
        cache_key = f"user_{user_id}"
        cached = self.cache.get(cache_key, ttl=config.CACHE_TTL_STATUS)
        if cached:
            return cached
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            is_admin = user_id in config.ADMIN_IDS
            
            cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            user = cursor.fetchone()
            
            if user:
                cursor.execute(
                    'UPDATE users SET last_seen = CURRENT_TIMESTAMP, username = ?, is_admin = ? WHERE user_id = ?',
                    (username, is_admin, user_id)
                )
                result = dict(user)
                result['is_admin'] = is_admin
                # Убедимся, что last_message_id есть в результате
                if 'last_message_id' not in result:
                    result['last_message_id'] = None
            else:
                cursor.execute(
                    'INSERT INTO users (user_id, username, is_admin, last_message_id) VALUES (?, ?, ?, NULL)',
                    (user_id, username, is_admin)
                )
                
                self._create_default_settings(user_id, cursor)
                cursor.execute(
                    'INSERT INTO script_status (user_id) VALUES (?)',
                    (user_id,)
                )
                
                cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
                result = dict(cursor.fetchone())
                result['last_message_id'] = None
            
            self.cache.set(cache_key, result)
            return result
    
    def _create_default_settings(self, user_id: int, cursor):
        """Создать настройки по умолчанию для пользователя"""
        settings_json = json.dumps(config.DEFAULT_SETTINGS)
        cursor.execute(
            'INSERT INTO script_settings (user_id, settings) VALUES (?, ?)',
            (user_id, settings_json)
        )
    
    def get_user(self, user_id: int) -> Optional[Dict]:
        """Получить информацию о пользователе"""
        cache_key = f"user_{user_id}"
        cached = self.cache.get(cache_key, ttl=config.CACHE_TTL_STATUS)
        if cached:
            return cached
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            row = cursor.fetchone()
            if row:
                result = dict(row)
                self.cache.set(cache_key, result)
                return result
            return None
    
    def get_last_message_id(self, user_id: int) -> Optional[int]:
        """Получить последний message_id пользователя"""
        cache_key = f"user_{user_id}_last_msg"
        cached = self.cache.get(cache_key, ttl=config.CACHE_TTL_STATUS)
        if cached:
            return cached
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT last_message_id FROM users WHERE user_id = ?', (user_id,))
            row = cursor.fetchone()
            if row:
                result = row['last_message_id']
                self.cache.set(cache_key, result)
                return result
            return None
    
    def set_last_message_id(self, user_id: int, message_id: int) -> bool:
        """Установить последний message_id пользователя"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE users SET last_message_id = ? WHERE user_id = ?',
                (message_id, user_id)
            )
            
            cache_key = f"user_{user_id}_last_msg"
            self.cache.set(cache_key, message_id)
            # Инвалидируем кэш пользователя
            self.cache.invalidate(f"user_{user_id}")
            return cursor.rowcount > 0
    
    # ===== КЛЮЧИ =====
    
    def create_key(self, created_by: int) -> Dict:
        """Создать новый ключ"""
        key_value = f"{config.KEY_PREFIX}{secrets.token_hex(4).upper()}"
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO keys (key_value, created_by) VALUES (?, ?)',
                (key_value, created_by)
            )
            key_id = cursor.lastrowid
            cursor.execute('SELECT * FROM keys WHERE id = ?', (key_id,))
            
            self.cache.invalidate("keys_")
            return dict(cursor.fetchone())
    
    def activate_key(self, key_value: str, user_id: int) -> bool:
        """Активировать ключ"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute(
                'SELECT * FROM keys WHERE key_value = ? AND activated_by IS NULL AND is_frozen = 0',
                (key_value,)
            )
            key = cursor.fetchone()
            
            if not key:
                return False
            
            cursor.execute(
                'UPDATE keys SET activated_by = ?, activated_at = CURRENT_TIMESTAMP WHERE key_value = ?',
                (user_id, key_value)
            )
            
            self.cache.invalidate(f"user_{user_id}_key")
            self.cache.invalidate("keys_")
            return True
    
    def get_user_key_info(self, user_id: int) -> Optional[Dict]:
        """Получить информацию о ключе пользователя с кэшированием"""
        cache_key = f"user_{user_id}_key"
        cached = self.cache.get(cache_key, ttl=config.CACHE_TTL_STATUS)
        if cached:
            return cached
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM keys WHERE activated_by = ?',
                (user_id,)
            )
            row = cursor.fetchone()
            if row:
                result = dict(row)
                self.cache.set(cache_key, result)
                return result
            return None
    
    def freeze_key(self, key_id: int) -> bool:
        """Заморозить ключ"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE keys SET is_frozen = 1 WHERE id = ?', (key_id,))
            self.cache.invalidate("keys_")
            return cursor.rowcount > 0
    
    def unfreeze_key(self, key_id: int) -> bool:
        """Разморозить ключ"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE keys SET is_frozen = 0 WHERE id = ?', (key_id,))
            self.cache.invalidate("keys_")
            return cursor.rowcount > 0
    
    def unbind_key(self, key_id: int) -> bool:
        """Отвязать ключ от пользователя"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE keys SET activated_by = NULL, activated_at = NULL WHERE id = ?',
                (key_id,)
            )
            self.cache.invalidate("keys_")
            return cursor.rowcount > 0
    
    def delete_key(self, key_id: int) -> bool:
        """Удалить ключ"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM keys WHERE id = ?', (key_id,))
            self.cache.invalidate("keys_")
            return cursor.rowcount > 0
    
    def get_all_keys(self, limit: int = None, offset: int = 0) -> List[Dict]:
        """Получить все ключи с пагинацией"""
        cache_key = f"keys_list_{limit}_{offset}"
        cached = self.cache.get(cache_key, ttl=10)
        if cached:
            return cached
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if limit:
                cursor.execute(
                    'SELECT * FROM keys ORDER BY created_at DESC LIMIT ? OFFSET ?',
                    (limit, offset)
                )
            else:
                cursor.execute('SELECT * FROM keys ORDER BY created_at DESC')
            
            result = [dict(row) for row in cursor.fetchall()]
            self.cache.set(cache_key, result)
            return result
    
    def get_key_by_id(self, key_id: int) -> Optional[Dict]:
        """Получить ключ по ID"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM keys WHERE id = ?', (key_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_key_by_value(self, key_value: str) -> Optional[Dict]:
        """Получить ключ по значению"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM keys WHERE key_value = ?', (key_value,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    # ===== НАСТРОЙКИ СКРИПТА =====
    
    def get_script_settings(self, user_id: int) -> Dict:
        """Получить настройки скрипта пользователя с кэшированием"""
        cache_key = f"settings_{user_id}"
        cached = self.cache.get(cache_key, ttl=config.CACHE_TTL_SETTINGS)
        if cached:
            return cached
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT settings FROM script_settings WHERE user_id = ?', (user_id,))
            row = cursor.fetchone()
            
            if row:
                result = json.loads(row['settings'])
            else:
                self._create_default_settings(user_id, cursor)
                result = config.DEFAULT_SETTINGS.copy()
            
            self.cache.set(cache_key, result)
            return result
    
    def save_script_settings(self, user_id: int, settings: Dict) -> bool:
        """Сохранить настройки скрипта"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            settings_json = json.dumps(settings)
            cursor.execute(
                '''UPDATE script_settings 
                   SET settings = ?, config_version = config_version + 1, updated_at = CURRENT_TIMESTAMP 
                   WHERE user_id = ?''',
                (settings_json, user_id)
            )
            
            self.cache.invalidate(f"settings_{user_id}")
            return cursor.rowcount > 0
    
    def get_config_version(self, user_id: int) -> int:
        """Получить версию конфигурации"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT config_version FROM script_settings WHERE user_id = ?', (user_id,))
            row = cursor.fetchone()
            return row['config_version'] if row else 1
    
    # ===== КООРДИНАТЫ =====
    
    def get_user_coordinates(self, user_id: int) -> Dict:
        """Получить все координаты пользователя с кэшированием"""
        cache_key = f"coords_{user_id}"
        cached = self.cache.get(cache_key, ttl=config.CACHE_TTL_SETTINGS)
        if cached:
            return cached
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM coordinates WHERE user_id = ?', (user_id,))
            rows = cursor.fetchall()
            
            coords = {}
            for row in rows:
                coords[row['coord_name']] = {
                    'x': row['x'],
                    'y': row['y'],
                    'description': row['description']
                }
            
            # Добавляем координаты по умолчанию
            for name, default in config.DEFAULT_COORDINATES.items():
                if name not in coords:
                    coords[name] = default.copy()
            
            self.cache.set(cache_key, coords)
            return coords
    
    def save_user_coordinate(self, user_id: int, coord_name: str, x: int, y: int) -> bool:
        """Сохранить координату пользователя"""
        if coord_name not in config.DEFAULT_COORDINATES:
            return False
        
        description = config.DEFAULT_COORDINATES[coord_name].get('description', '')
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''INSERT OR REPLACE INTO coordinates (user_id, coord_name, x, y, description, updated_at)
                   VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)''',
                (user_id, coord_name, x, y, description)
            )
            
            cursor.execute(
                'UPDATE script_settings SET config_version = config_version + 1 WHERE user_id = ?',
                (user_id,)
            )
            
            self.cache.invalidate(f"coords_{user_id}")
            return True
    
    def delete_user_coordinate(self, user_id: int, coord_name: str) -> bool:
        """Удалить координату пользователя"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'DELETE FROM coordinates WHERE user_id = ? AND coord_name = ?',
                (user_id, coord_name)
            )
            
            cursor.execute(
                'UPDATE script_settings SET config_version = config_version + 1 WHERE user_id = ?',
                (user_id,)
            )
            
            self.cache.invalidate(f"coords_{user_id}")
            return cursor.rowcount > 0
    
    def get_coordinate_status(self, user_id: int) -> Dict:
        """Получить статус настройки координат"""
        coords = self.get_user_coordinates(user_id)
        total = len(coords)
        configured = sum(1 for c in coords.values() if c['x'] > 0 and c['y'] > 0)
        
        return {
            'total': total,
            'configured': configured,
            'percentage': (configured / total * 100) if total > 0 else 0
        }
    
    # ===== КОМАНДЫ =====
    
    def create_command(self, user_id: int, command_type: str, params: Dict = None) -> int:
        """Создать команду в очереди"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            params_json = json.dumps(params) if params else None
            cursor.execute(
                'INSERT INTO commands (user_id, command_type, params) VALUES (?, ?, ?)',
                (user_id, command_type, params_json)
            )
            return cursor.lastrowid
    
    def get_pending_commands(self, user_id: int) -> List[Dict]:
        """Получить ожидающие команды пользователя"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''SELECT * FROM commands 
                   WHERE user_id = ? AND status = 'pending' 
                   ORDER BY created_at ASC''',
                (user_id,)
            )
            return [dict(row) for row in cursor.fetchall()]
    
    def complete_command(self, command_id: int, result: str = None) -> bool:
        """Отметить команду как выполненную"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''UPDATE commands 
                   SET status = 'completed', result = ?, executed_at = CURRENT_TIMESTAMP 
                   WHERE id = ?''',
                (result, command_id)
            )
            return cursor.rowcount > 0
    
    def cleanup_old_commands(self, days: int = 7):
        """Очистить старые команды"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''DELETE FROM commands 
                   WHERE created_at < datetime('now', '-' || ? || ' days')''',
                (days,)
            )
    
    # ===== СТАТУС СКРИПТА =====
    
    def update_script_status(self, user_id: int, is_running: bool, is_paused: bool = False):
        """Обновить статус скрипта"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''INSERT OR REPLACE INTO script_status (user_id, is_running, is_paused, last_heartbeat)
                   VALUES (?, ?, ?, CURRENT_TIMESTAMP)''',
                (user_id, is_running, is_paused)
            )
        
        self.cache.invalidate(f"status_{user_id}")
    
    def update_heartbeat(self, user_id: int):
        """Обновить heartbeat"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE script_status SET last_heartbeat = CURRENT_TIMESTAMP WHERE user_id = ?',
                (user_id,)
            )
        
        self.cache.invalidate(f"status_{user_id}")
    
    def get_script_status(self, user_id: int) -> Dict:
        """Получить статус скрипта с кэшированием"""
        cache_key = f"status_{user_id}"
        cached = self.cache.get(cache_key, ttl=config.CACHE_TTL_STATUS)
        if cached:
            return cached
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM script_status WHERE user_id = ?', (user_id,))
            row = cursor.fetchone()
            
            if row:
                result = dict(row)
            else:
                result = {
                    'user_id': user_id,
                    'is_running': False,
                    'is_paused': False,
                    'pause_until': None,
                    'last_heartbeat': None
                }
            
            self.cache.set(cache_key, result)
            return result
    
    def set_pause(self, user_id: int, seconds: int):
        """Установить паузу скрипта"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if seconds > 0:
                cursor.execute(
                    '''UPDATE script_status 
                       SET is_paused = 1, pause_until = datetime('now', '+' || ? || ' seconds')
                       WHERE user_id = ?''',
                    (seconds, user_id)
                )
            else:
                cursor.execute(
                    'UPDATE script_status SET is_paused = 0, pause_until = NULL WHERE user_id = ?',
                    (user_id,)
                )
        
        self.cache.invalidate(f"status_{user_id}")
    
    # ===== СТАТИСТИКА =====
    
    def get_statistics(self) -> Dict:
        """Получить статистику системы"""
        cache_key = "statistics"
        cached = self.cache.get(cache_key, ttl=30)
        if cached:
            return cached
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT COUNT(*) as total FROM users')
            total_users = cursor.fetchone()['total']
            
            cursor.execute('SELECT COUNT(*) as admins FROM users WHERE is_admin = 1')
            admin_users = cursor.fetchone()['admins']
            
            cursor.execute('SELECT COUNT(*) as total FROM keys')
            total_keys = cursor.fetchone()['total']
            
            cursor.execute('SELECT COUNT(*) as used FROM keys WHERE activated_by IS NOT NULL')
            used_keys = cursor.fetchone()['used']
            
            cursor.execute('SELECT COUNT(*) as frozen FROM keys WHERE is_frozen = 1')
            frozen_keys = cursor.fetchone()['frozen']
            
            cursor.execute('SELECT COUNT(*) as running FROM script_status WHERE is_running = 1 AND is_paused = 0')
            running_scripts = cursor.fetchone()['running']
            
            cursor.execute('SELECT COUNT(*) as paused FROM script_status WHERE is_paused = 1')
            paused_scripts = cursor.fetchone()['paused']
            
            cursor.execute('SELECT COUNT(*) as offline FROM script_status WHERE is_running = 0')
            offline_scripts = cursor.fetchone()['offline']
            
            result = {
                'users': {
                    'total': total_users,
                    'admins': admin_users,
                    'regular': total_users - admin_users
                },
                'keys': {
                    'total': total_keys,
                    'used': used_keys,
                    'free': total_keys - used_keys,
                    'frozen': frozen_keys
                },
                'scripts': {
                    'running': running_scripts,
                    'paused': paused_scripts,
                    'offline': offline_scripts
                }
            }
            
            self.cache.set(cache_key, result)
            return result
    
    # ===== МЕТОДЫ ДЛЯ УДАЛЕНИЯ СООБЩЕНИЙ (ASYNC) =====
    
    async def delete_last_bot_message(self, user_id: int, bot) -> bool:
        """Удалить последнее сообщение бота у пользователя (async)"""
        try:
            last_message_id = self.get_last_message_id(user_id)
            if last_message_id:
                await bot.delete_message(chat_id=user_id, message_id=last_message_id)
                self.set_last_message_id(user_id, None)
                logger.info(f"Deleted last message {last_message_id} for user {user_id}")
                return True
        except Exception as e:
            # Если сообщение уже удалено или другая ошибка
            if "message to delete not found" in str(e).lower():
                # Просто очищаем ID
                self.set_last_message_id(user_id, None)
                return True
            logger.error(f"Error deleting last message for user {user_id}: {e}")
        return False
