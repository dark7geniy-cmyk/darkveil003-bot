import os
from typing import Dict, List

# ===== ОСНОВНЫЕ НАСТРОЙКИ =====
BOT_TOKEN = os.getenv("BOT_TOKEN", "8591051415:AAGyuueeJGXl5nbhJPbTcRNXS3PXbepNk3k")
API_SECRET_KEY = os.getenv("API_SECRET_KEY", "DV_12345")
KEY_PREFIX = "DV_"

# API настройки
API_HOST = "0.0.0.0"
API_PORT = 8080

# База данных
DATABASE_PATH = "darkveil.db"

# Админы (Telegram ID)
ADMIN_IDS = [1581297002, 8385568563, 8414792453]

# Ограничения
MAX_COMMANDS_PER_MINUTE = 10
COMMAND_TIMEOUT_SECONDS = 90
HEARTBEAT_INTERVAL_SECONDS = 30
HEARTBEAT_TIMEOUT_SECONDS = 120

# Оптимизация для 150+ пользователей
CACHE_TTL_STATUS = 3  # секунды
CACHE_TTL_SETTINGS = 30  # секунды
BATCH_SIZE = 50  # размер пакета для обработки
MAX_CONCURRENT_REQUESTS = 100

# Координаты по умолчанию
DEFAULT_COORDINATES = {
    # Основные
    "rleftT": {"x": 0, "y": 0, "description": "Верхняя левая точка цены запроса", "group": "main"},
    "rrightB": {"x": 0, "y": 0, "description": "Нижняя правая точка цены запроса", "group": "main"},
    "pleftT": {"x": 0, "y": 0, "description": "Верхняя левая точка цены лота", "group": "main"},
    "prightB": {"x": 0, "y": 0, "description": "Нижняя правая точка цены лота", "group": "main"},
    "bleftT": {"x": 0, "y": 0, "description": "Верхняя левая точка баланса", "group": "main"},
    "brightB": {"x": 0, "y": 0, "description": "Нижняя правая точка баланса", "group": "main"},
    "paste": {"x": 0, "y": 0, "description": "Точка кнопки вставить", "group": "main"},
    "inpClose": {"x": 0, "y": 0, "description": "Точка кнопки OK для закрытия поля ввода", "group": "main"},
    
    # ПК
    "prinp": {"x": 0, "y": 0, "description": "Точка цены на поле ввода (ПК)", "group": "pc"},
    
    # Уведомления
    "nleftT": {"x": 0, "y": 0, "description": "Верхняя левая точка названия скина", "group": "notifications"},
    "nrightB": {"x": 0, "y": 0, "description": "Нижняя правая точка названия скина", "group": "notifications"},
    
    # Автопродажа
    "sell": {"x": 0, "y": 0, "description": "Кнопка продать", "group": "autosell"},
    "chskin": {"x": 0, "y": 0, "description": "Выбор скина", "group": "autosell"},
    "select": {"x": 0, "y": 0, "description": "Выбрать скин", "group": "autosell"},
    "inprice": {"x": 0, "y": 0, "description": "Открыть поле ввода для вставки цены", "group": "autosell"},
    
    # Перезаход
    "invent": {"x": 0, "y": 0, "description": "Инвентарь", "group": "restskin"},
    "market": {"x": 0, "y": 0, "description": "Рынок", "group": "restskin"},
    "myreq": {"x": 0, "y": 0, "description": "Мои запросы", "group": "restskin"},
    "reqbuy": {"x": 0, "y": 0, "description": "Запросы на покупку", "group": "restskin"},
    "tenskin": {"x": 0, "y": 0, "description": "10 скин для перезахода", "group": "restskin"},
    "findmark": {"x": 0, "y": 0, "description": "Найти на рынке", "group": "restskin"},
    
    # Дополнительные
    "back": {"x": 0, "y": 0, "description": "Точка кнопки назад при осмотре скина", "group": "additional"},
    "ok": {"x": 0, "y": 0, "description": "Точка кнопки ОК при ошибке", "group": "additional"},
    "arrow": {"x": 0, "y": 0, "description": "Точка стрелочки назад", "group": "additional"},
}

# Группы координат для UI
COORDINATE_GROUPS = {
    "main": {
        "name": "Основные",
        "emoji": "📍",
        "coords": ["rleftT", "rrightB", "pleftT", "prightB", "bleftT", "brightB", "paste", "inpClose"]
    },
    "pc": {
        "name": "ПК",
        "emoji": "💻",
        "coords": ["prinp"]
    },
    "notifications": {
        "name": "Уведомления",
        "emoji": "🏷️",
        "coords": ["nleftT", "nrightB"]
    },
    "autosell": {
        "name": "Автопродажа",
        "emoji": "💰",
        "coords": ["sell", "chskin", "select", "inprice"]
    },
    "restskin": {
        "name": "Перезаход",
        "emoji": "🔄",
        "coords": ["invent", "market", "myreq", "reqbuy", "tenskin", "findmark"]
    },
    "additional": {
        "name": "Дополнительные",
        "emoji": "🎯",
        "coords": ["back", "ok", "arrow"]
    }
}

# Настройки по умолчанию (без lowLootOnly)
DEFAULT_SETTINGS = {
    # Задержки
    "dbclickS": 1000,
    "opkeyS": 800,
    "befordS": 250,
    "aftordS": 400,
    "actreqS": 1000,
    "reslotS": 4000,
    "aftpasteS": 100,
    "clkeyS": 125,
    
    # Настройка перебива
    "inpord": False,
    "inpordS": 200,
    "dcpaste": False,
    "dcpasteS": 30,
    "prinpS": 350,
    "keypaste": False,
    
    # Режимы
    "defM": True,
    "defcust": 0.01,
    "pfullM": False,
    "pfcust": 0.01,
    "percentM": False,
    "percust": 10.0,
    "tenthM": False,
    "integerM": False,
    "halfM": False,
    "randomM": False,
    
    # Функции
    "barrierF": False,
    "barcust": 0.1,
    "blimitF": False,
    "balcust": 100.0,
    "asellF": False,
    "aslcust": 0.01,
    "restskinF": False,
    "rskincust": 30,
    "multintF": False,
    "multincust": 2.0,
    "doubcust": 300,
    "flimitF": False,
    "fullcust": 3,
    "waitF": False,
    "waitcust": 1000,
    
    # Параметры (без lowLootOnly)
    "scanM": True,
    "sendcatch": True,
    
    # Дополнительные
    "backC": 0,
    "okC": 0,
    "arrowC": 0,
    
    # Админские настройки приема уловов (без admin_low_only)
    "admin_receive_loot": False,
    "admin_receive_all": True,
    
    # Статистика
    "_fulls_count": 0,
    "_last_balance": 0,
}

# Параметры, которые можно менять в RUNNING (без lowLootOnly и admin_low_only)
RUNTIME_EDITABLE_PARAMS = [
    "dbclickS", "opkeyS", "befordS", "aftordS", "actreqS", "reslotS",
    "aftpasteS", "clkeyS", "inpordS", "dcpasteS", "prinpS", "doubcust",
    "waitcust", "rskincust",
    "inpord", "dcpaste", "keypaste",
    "defM", "pfullM", "percentM", "tenthM", "integerM", "halfM", "randomM",
    "barrierF", "blimitF", "asellF", "multintF", "flimitF", "waitF", "restskinF",
    "sendcatch",
    "defcust", "pfcust", "percust", "barcust", "balcust", "aslcust",
    "multincust", "fullcust",
    "backC", "okC", "arrowC",
    "admin_receive_loot", "admin_receive_all",
]

# Описания задержек
DELAY_DESCRIPTIONS = {
    "dbclickS": "Время между кликами",
    "opkeyS": "Время на открытие клавиатуры",
    "befordS": "Время до открытия окна запроса",
    "aftordS": "Время после открытия окна запроса",
    "actreqS": "Время активного запроса",
    "reslotS": "Время на перезаход лота",
    "aftpasteS": "Время после нажатия на «вставить»",
    "clkeyS": "Время после нажатия на «ок» в поле ввода",
    "inpordS": "Время после «вставить» до быстрого клика",
    "dcpasteS": "Время между нажатиями на цену для выделения",
    "prinpS": "Время на выделение цены для появления «вставить»",
    "doubcust": "Время между мульти-перебивами",
    "waitcust": "Время ожидания перед выставлением запроса",
}

# Логирование
LOG_LEVEL = "INFO"
LOG_FILE = "darkveil.log"

# Пути к изображениям координат
IMAGE_PATH = "images/coords"

# Настройки для корректной работы alert
MAX_MESSAGE_LENGTH = 200
