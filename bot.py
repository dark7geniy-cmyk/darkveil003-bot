# -*- coding: utf-8 -*-
"""
DARKVEIL 0.03 | BOT - v1.0
LAST UPDATE - 14:51
"""

import asyncio
import logging
import os
import re
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple, Any
from enum import Enum

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputFile, FSInputFile
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

import aiohttp
import config
import texts
from database import Database

# Настройка логирования без эмодзи для консоли Windows
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(config.LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Инициализация
bot = Bot(token=config.BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

db = Database()

# Состояния FSM
class UserStates(StatesGroup):
    main_menu = State()
    activate_key = State()
    
    # Скрипт
    script_main = State()
    script_settings = State()
    
    # Координаты
    coordinates_main = State()
    coordinates_group = State()
    coordinates_edit = State()
    coordinates_input = State()
    
    # Задержки
    delays_main = State()
    delay_edit = State()
    delay_input = State()
    
    # Перебив
    work_settings = State()
    work_platform = State()
    work_inpord = State()
    
    # Режимы
    modes_main = State()
    modes_list = State()
    mode_select = State()
    mode_param_input = State()
    
    # Функции
    functions_main = State()
    function_toggle = State()
    function_param_input = State()
    
    # Параметры
    parameters_main = State()
    parameter_edit = State()
    
    # Команды
    commands_main = State()
    saleskin_input = State()
    
    # Админ
    admin_main = State()
    admin_keys = State()
    admin_key_detail = State()
    admin_statistics = State()
    admin_loot = State()
    
    # Настройки пользователя
    user_settings = State()
    
    # Цвета координат
    color_input = State()

# Глобальные переменные
user_current_message_id = {}
active_users_in_script_control = {}
script_status_cache = {}
last_status_update = {}

# ====================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ====================

def make_keyboard(buttons: List[tuple], row_width: int = 2, last_row_full: bool = False) -> InlineKeyboardMarkup:
    """Создать клавиатуру с кнопками"""
    keyboard = []
    current_row = []
    
    for button_data in buttons:
        text, callback = button_data
        current_row.append(InlineKeyboardButton(text=text, callback_data=callback))
        
        if len(current_row) >= row_width:
            keyboard.append(current_row)
            current_row = []
    
    if current_row:
        keyboard.append(current_row)
    
    if last_row_full and keyboard:
        last_row = keyboard[-1]
        if len(last_row) > 1:
            keyboard.pop()
            for button in last_row:
                keyboard.append([button])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

async def edit_or_send_message(user_id: int, text: str, keyboard: InlineKeyboardMarkup = None):
    """Редактирует существующее сообщение или отправляет новое"""
    if user_id in user_current_message_id:
        try:
            await bot.edit_message_text(
                chat_id=user_id,
                message_id=user_current_message_id[user_id],
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            return True
        except Exception as e:
            logger.warning(f"Не удалось редактировать сообщение: {e}")
            try:
                await bot.delete_message(user_id, user_current_message_id[user_id])
            except Exception as e2:
                logger.warning(f"Не удалось удалить сообщение: {e2}")
            if user_id in user_current_message_id:
                del user_current_message_id[user_id]
    
    # Отправляем новое сообщение
    try:
        msg = await bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        user_current_message_id[user_id] = msg.message_id
        return True
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение: {e}")
        return False

async def send_toast_notification(callback: CallbackQuery, text: str, duration: int = 2):
    """Отправить всплывающее уведомление (toast) - ТОЛЬКО ДЛЯ КОМАНД"""
    try:
        # Отправляем временное сообщение
        temp_msg = await callback.message.answer(f"ℹ️ {text}")
        # Удаляем через указанное время
        await asyncio.sleep(duration)
        await bot.delete_message(callback.message.chat.id, temp_msg.message_id)
    except Exception as e:
        logger.error(f"Error sending toast: {e}")

def get_script_status_text(user_id: int) -> tuple:
    """Получить текст статуса скрипта"""
    status = db.get_script_status(user_id)
    
    if status['is_paused']:
        return (
            texts.get_text("SCRIPT_SECTION.paused.title"),
            texts.get_text("SCRIPT_SECTION.paused.status"),
            texts.get_text("SCRIPT_SECTION.paused.description")
        )
    elif status['is_running']:
        return (
            texts.get_text("SCRIPT_SECTION.running.title"),
            texts.get_text("SCRIPT_SECTION.running.status"),
            texts.get_text("SCRIPT_SECTION.running.description")
        )
    else:
        return (
            texts.get_text("SCRIPT_SECTION.offline.title"),
            texts.get_text("SCRIPT_SECTION.offline.status"),
            texts.get_text("SCRIPT_SECTION.offline.description")
        )

async def get_script_status_from_api(user_id: int, force_refresh: bool = False) -> dict:
    """Получает актуальный статус скрипта из API"""
    if not force_refresh and user_id in last_status_update:
        time_diff = (datetime.now() - last_status_update[user_id]).total_seconds()
        if time_diff < 1 and user_id in script_status_cache:
            return script_status_cache[user_id]
    
    try:
        async with aiohttp.ClientSession() as session:
            url = f"http://{config.API_HOST}:{config.API_PORT}/api/check_commands/{user_id}"
            headers = {"api-key": config.API_SECRET_KEY}
            
            async with session.get(url, headers=headers, timeout=2) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    script_status_cache[user_id] = {
                        'is_running': data.get('is_running', False),
                        'is_paused': data.get('is_paused', False),
                        'pause_until': data.get('pause_until'),
                        'last_update': datetime.now(),
                        'has_commands': data.get('has_commands', False)
                    }
                    
                    last_status_update[user_id] = datetime.now()
                    return script_status_cache[user_id]
    except Exception as e:
        logger.debug(f"API недоступно, используем кэш: {e}")
    
    if user_id in script_status_cache:
        return script_status_cache[user_id]
    
    return {
        'is_running': False,
        'is_paused': False,
        'pause_until': None,
        'last_update': datetime.now()
    }

async def send_photo_message(user_id: int, photo_path: str, caption: str, keyboard: InlineKeyboardMarkup = None):
    """Отправить сообщение с фото"""
    try:
        if os.path.exists(photo_path):
            photo = FSInputFile(photo_path)
            msg = await bot.send_photo(
                chat_id=user_id,
                photo=photo,
                caption=caption,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        else:
            msg = await bot.send_message(
                chat_id=user_id,
                text=caption,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        
        if user_id in user_current_message_id:
            try:
                await bot.delete_message(user_id, user_current_message_id[user_id])
            except:
                pass
        
        user_current_message_id[user_id] = msg.message_id
        return True
    except Exception as e:
        logger.error(f"Error sending photo message: {e}")
        return False

def resolve_user_view_state(user: dict, user_key: dict | None) -> str:
    """Определяет состояние пользователя для отображения"""
    if user.get("is_admin"):
        if user_key and user_key.get("is_frozen"):
            return "ADMIN_FROZEN"
        return "ADMIN_ACTIVE"

    if not user_key or user_key.get("activated_by") != user["user_id"]:
        return "USER_NO_KEY"

    if user_key.get("is_frozen"):
        return "USER_FROZEN"

    return "USER_ACTIVE"

async def update_user_menu_if_active(user_id: int, action_text: str = None):
    """Обновить меню пользователя если оно активно"""
    try:
        if user_id in user_current_message_id:
            user = db.get_user(user_id)
            key_info = db.get_user_key_info(user_id)
            
            state_str = resolve_user_view_state(user, key_info)
            
            if state_str == "USER_FROZEN":
                text = texts.get_text("MAIN_MENU.frozen.text")
                if action_text:
                    text = f"{action_text}\n\n{text}"
                buttons = texts.get_text("MAIN_MENU.frozen.buttons")
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=buttons['support'], url='https://t.me/piimpkin')]
                ])
            elif state_str == "USER_ACTIVE":
                text = texts.get_text("MAIN_MENU.active.text")
                if action_text:
                    text = f"{action_text}\n\n{text}"
                buttons = texts.get_text("MAIN_MENU.active.buttons")
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(text=buttons['script'], callback_data='script_main'),
                        InlineKeyboardButton(text=buttons['settings'], callback_data='user_settings')
                    ],
                    [InlineKeyboardButton(text=buttons['support'], url='https://t.me/piimpkin')]
                ])
            else:
                return
            
            await edit_or_send_message(user_id, text, keyboard)
    except Exception as e:
        logger.error(f"Error updating user menu: {e}")

# ====================
# ГЛАВНОЕ МЕНЮ
# ====================

@router.message(CommandStart())
async def start_command(message: Message, state: FSMContext):
    """Обработчик команды /start"""
    user_id = message.from_user.id
    username = message.from_user.username
    
    db.get_or_create_user(user_id, username)
    
    if user_id in config.ADMIN_IDS:
        key_info = db.get_user_key_info(user_id)
        if not key_info:
            key = db.create_key(user_id)
            db.activate_key(key['key_value'], user_id)
            logger.info(f"Auto-created key for admin {user_id}: {key['key_value']}")
    
    await show_main_menu(user_id, state)

async def show_main_menu(user_id: int, state: FSMContext):
    """Показать главное меню"""
    try:
        user = db.get_user(user_id)
        key_info = db.get_user_key_info(user_id)
        
        state_str = resolve_user_view_state(user, key_info)
        
        if state_str == "ADMIN_ACTIVE":
            text = texts.get_text("MAIN_MENU.admin.text")
            buttons = texts.get_text("MAIN_MENU.admin.buttons")
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text=buttons['script'], callback_data='script_main'),
                    InlineKeyboardButton(text=buttons['settings'], callback_data='user_settings')
                ],
                [InlineKeyboardButton(text=buttons['admin'], callback_data='admin_main')]
            ])
        elif state_str == "USER_NO_KEY":
            text = texts.get_text("MAIN_MENU.no_key.text")
            buttons = texts.get_text("MAIN_MENU.no_key.buttons")
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text=buttons['activate'], callback_data='activate_key'),
                    InlineKeyboardButton(text=buttons['support'], url='https://t.me/piimpkin')
                ]
            ])
        elif state_str == "USER_FROZEN":
            text = texts.get_text("MAIN_MENU.frozen.text")
            buttons = texts.get_text("MAIN_MENU.frozen.buttons")
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=buttons['support'], url='https://t.me/piimpkin')]
            ])
        else:  # USER_ACTIVE
            text = texts.get_text("MAIN_MENU.active.text")
            buttons = texts.get_text("MAIN_MENU.active.buttons")
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text=buttons['script'], callback_data='script_main'),
                    InlineKeyboardButton(text=buttons['settings'], callback_data='user_settings')
                ],
                [InlineKeyboardButton(text=buttons['support'], url='https://t.me/piimpkin')]
            ])
        
        await edit_or_send_message(user_id, text, keyboard)
        await state.set_state(UserStates.main_menu)
            
    except Exception as e:
        logger.error(f"Error in show_main_menu: {e}")

# ====================
# АКТИВАЦИЯ КЛЮЧА
# ====================

@router.callback_query(F.data == "activate_key")
async def activate_key_start(callback: CallbackQuery, state: FSMContext):
    """Начало активации ключа"""
    user_id = callback.from_user.id
    
    text = texts.get_text("KEYS.activate.prompt")
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data='activate_key_back')]
    ])
    
    await edit_or_send_message(user_id, text, keyboard)
    await state.set_state(UserStates.activate_key)

@router.callback_query(F.data == "activate_key_back")
async def activate_key_back_handler(callback: CallbackQuery, state: FSMContext):
    """Возврат в меню активации ключа"""
    await activate_key_start(callback, state)

@router.message(UserStates.activate_key)
async def activate_key_process(message: Message, state: FSMContext):
    """Обработка введённого ключа"""
    user_id = message.from_user.id
    key_value = message.text.strip().upper()
    
    try:
        await message.delete()
    except:
        pass
    
    # Проверка формата
    if not key_value.startswith(config.KEY_PREFIX):
        text = texts.get_text("KEYS.activate.error.invalid_format", key_prefix=config.KEY_PREFIX)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data='activate_key')]
        ])
        
        await edit_or_send_message(user_id, text, keyboard)
        return
    
    key = db.get_key_by_value(key_value)
    
    if not key:
        text = texts.get_text("KEYS.activate.error.not_found")
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data='activate_key')]
        ])
        
        await edit_or_send_message(user_id, text, keyboard)
        return
    
    if key['is_frozen']:
        text = texts.get_text("KEYS.activate.error.frozen")
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data='activate_key')]
        ])
        
        await edit_or_send_message(user_id, text, keyboard)
        return
        
    if key['activated_by']:
        text = texts.get_text("KEYS.activate.error.already_used")
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data='activate_key')]
        ])
        
        await edit_or_send_message(user_id, text, keyboard)
        return
    
    # Активация ключа
    if db.activate_key(key_value, user_id):
        text = texts.get_text("KEYS.activate.success.text")
        await edit_or_send_message(user_id, text)
        
        await asyncio.sleep(1)
        await show_main_menu(user_id, state)
    else:
        text = texts.get_text("KEYS.activate.error.activation_error")
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data='activate_key')]
        ])
        
        await edit_or_send_message(user_id, text, keyboard)

# ====================
# РАЗДЕЛ СКРИПТА
# ====================

@router.callback_query(F.data == "script_main")
async def script_main_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик раздела Скрипт"""
    user_id = callback.from_user.id
    user = db.get_user(user_id)
    
    if not user.get('is_admin'):
        user_key = db.get_user_key_info(user_id)
        if not user_key or user_key.get('activated_by') != user_id:
            return
        
        if user_key.get('is_frozen'):
            return
    
    await show_script_main_panel(callback, state)

async def show_script_main_panel(callback: CallbackQuery, state: FSMContext):
    """Показывает основную панель скрипта с исправленной кнопкой Параметры"""
    user_id = callback.from_user.id
    
    active_users_in_script_control[user_id] = datetime.now()
    
    status_data = await get_script_status_from_api(user_id, force_refresh=True)
    
    title, status_text, description = get_script_status_text(user_id)
    text = f"{title}\n{status_text}\n\n{description}"
    
    # Определяем кнопки в зависимости от статуса
    keyboard_buttons = []
    
    if status_data['is_running']:
        if status_data['is_paused']:
            keyboard_buttons.append([
                InlineKeyboardButton(text=texts.get_text("SCRIPT_SECTION.buttons.resume"), callback_data='script_resume'),
                InlineKeyboardButton(text=texts.get_text("SCRIPT_SECTION.buttons.stop"), callback_data='script_stop')
            ])
        else:
            keyboard_buttons.append([
                InlineKeyboardButton(text=texts.get_text("SCRIPT_SECTION.buttons.pause"), callback_data='script_pause'),
                InlineKeyboardButton(text=texts.get_text("SCRIPT_SECTION.buttons.stop"), callback_data='script_stop')
            ])
        keyboard_buttons.append([InlineKeyboardButton(text=texts.get_text("SCRIPT_SECTION.buttons.commands"), callback_data='menu_commands')])
    else:
        keyboard_buttons.append([InlineKeyboardButton(text=texts.get_text("SCRIPT_SECTION.buttons.coordinates"), callback_data='coordinates_main')])
    
    # Общие кнопки настроек
    if not status_data['is_running'] or status_data['is_paused']:
        keyboard_buttons.extend([
            [
                InlineKeyboardButton(text=texts.get_text("SCRIPT_SECTION.buttons.delays"), callback_data='delays_main'),
                InlineKeyboardButton(text=texts.get_text("SCRIPT_SECTION.buttons.work_settings"), callback_data='work_settings')
            ],
            [
                InlineKeyboardButton(text=texts.get_text("SCRIPT_SECTION.buttons.modes"), callback_data='modes_main'),
                InlineKeyboardButton(text=texts.get_text("SCRIPT_SECTION.buttons.functions"), callback_data='functions_main')
            ],
            [InlineKeyboardButton(text=texts.get_text("SCRIPT_SECTION.buttons.parameters"), callback_data='parameters_main')]
        ])
    else:
        # При включенном скрипте кнопка Параметры на всю строку
        keyboard_buttons.extend([
            [
                InlineKeyboardButton(text=texts.get_text("SCRIPT_SECTION.buttons.delays"), callback_data='delays_main'),
                InlineKeyboardButton(text=texts.get_text("SCRIPT_SECTION.buttons.work_settings"), callback_data='work_settings')
            ],
            [
                InlineKeyboardButton(text=texts.get_text("SCRIPT_SECTION.buttons.modes"), callback_data='modes_main'),
                InlineKeyboardButton(text=texts.get_text("SCRIPT_SECTION.buttons.functions"), callback_data='functions_main')
            ],
            [InlineKeyboardButton(text=texts.get_text("SCRIPT_SECTION.buttons.parameters"), callback_data='parameters_main')]
        ])
    
    keyboard_buttons.append([InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data='menu_main')])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    await edit_or_send_message(user_id, text, keyboard)
    await state.set_state(UserStates.script_main)

@router.callback_query(F.data == "script_pause")
async def script_pause_handler(callback: CallbackQuery, state: FSMContext):
    """Постановка скрипта на паузу"""
    user_id = callback.from_user.id
    
    try:
        async with aiohttp.ClientSession() as session:
            url = f"http://{config.API_HOST}:{config.API_PORT}/api/pause"
            headers = {"api-key": config.API_SECRET_KEY}
            data = {"user_id": user_id, "seconds": 86400}
            
            async with session.post(url, headers=headers, json=data) as response:
                if response.status == 200:
                    await show_script_main_panel(callback, state)
                else:
                    pass
    except Exception as e:
        logger.error(f"Ошибка установки паузы: {e}")

@router.callback_query(F.data == "script_resume")
async def script_resume_handler(callback: CallbackQuery, state: FSMContext):
    """Снятие скрипта с паузы"""
    user_id = callback.from_user.id
    
    try:
        async with aiohttp.ClientSession() as session:
            url = f"http://{config.API_HOST}:{config.API_PORT}/api/pause"
            headers = {"api-key": config.API_SECRET_KEY}
            data = {"user_id": user_id, "seconds": 0}
            
            async with session.post(url, headers=headers, json=data) as response:
                if response.status == 200:
                    await show_script_main_panel(callback, state)
                else:
                    pass
    except Exception as e:
        logger.error(f"Ошибка снятия паузы: {e}")

@router.callback_query(F.data == "script_stop")
async def script_stop_handler(callback: CallbackQuery, state: FSMContext):
    """Остановка скрипта"""
    user_id = callback.from_user.id
    
    try:
        async with aiohttp.ClientSession() as session:
            url = f"http://{config.API_HOST}:{config.API_PORT}/api/command"
            headers = {"api-key": config.API_SECRET_KEY}
            data = {"user_id": user_id, "command": "stop"}
            
            async with session.post(url, headers=headers, json=data) as response:
                if response.status == 200:
                    await show_script_main_panel(callback, state)
                else:
                    pass
    except Exception as e:
        logger.error(f"Ошибка остановки скрипта: {e}")

# ====================
# КООРДИНАТЫ (ОБНОВЛЕННЫЙ РАЗДЕЛ)
# ====================

@router.callback_query(F.data == "coordinates_main")
async def coordinates_main_handler(callback: CallbackQuery, state: FSMContext):
    """Главное меню координат"""
    user_id = callback.from_user.id
    
    # Проверяем статус скрипта
    status_data = await get_script_status_from_api(user_id)
    if status_data.get('is_running') and not status_data.get('is_paused'):
        text = texts.get_text("COORDINATES.error.only_offline")
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data='script_main')]
        ])
        await edit_or_send_message(user_id, text, keyboard)
        return
    
    coord_status = db.get_coordinate_status(user_id)
    
    text = texts.get_text("COORDINATES.main_screen",
                         total=coord_status['total'],
                         configured=coord_status['configured'],
                         percentage=coord_status['percentage'])
    
    keyboard_buttons = []
    row = []
    groups = list(config.COORDINATE_GROUPS.items())
    
    for i, (group_key, group_data) in enumerate(groups):
        emoji = group_data['emoji']
        name = group_data['name']
        row.append(InlineKeyboardButton(text=f"{emoji} {name}", callback_data=f'coord_group_{group_key}'))
        
        if len(row) == 2 or i == len(groups) - 1:
            keyboard_buttons.append(row)
            row = []
    
    keyboard_buttons.append([InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data='script_main')])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    await edit_or_send_message(user_id, text, keyboard)
    await state.set_state(UserStates.coordinates_main)

@router.callback_query(F.data.startswith("coord_group_"))
async def coordinates_group_handler(callback: CallbackQuery, state: FSMContext):
    """Показать группу координат"""
    user_id = callback.from_user.id
    group_key = callback.data.replace('coord_group_', '')
    
    if group_key not in config.COORDINATE_GROUPS:
        return
    
    group = config.COORDINATE_GROUPS[group_key]
    coords = db.get_user_coordinates(user_id)
    
    # Формируем красивый статус
    status_lines = []
    for coord_name in group['coords']:
        coord = coords.get(coord_name, {'x': 0, 'y': 0})
        status = "🟢" if (coord['x'] > 0 and coord['y'] > 0) else "🔴"
        status_lines.append(f"{status} {coord_name}: ({coord['x']}, {coord['y']})")
    
    # Разделяем на колонки для лучшего отображения
    if group_key == 'main':
        # Для основных координат - 2 колонки
        col1 = status_lines[:4]
        col2 = status_lines[4:]
        status_text = ""
        for i in range(max(len(col1), len(col2))):
            if i < len(col1):
                status_text += col1[i].ljust(40)
            if i < len(col2):
                status_text += col2[i]
            status_text += "\n"
    else:
        # Для остальных - обычный список
        status_text = '\n'.join(status_lines)
    
    text = texts.get_text("COORDINATES.group_screen",
                         emoji=group['emoji'],
                         name=group['name'],
                         status_text=status_text)
    
    keyboard_buttons = []
    row = []
    for i, coord_name in enumerate(group['coords']):
        coord = coords.get(coord_name, {'x': 0, 'y': 0})
        status = "🟢" if (coord['x'] > 0 and coord['y'] > 0) else "🔴"
        
        row.append(InlineKeyboardButton(text=f"{status} {coord_name}", callback_data=f'coord_edit_{coord_name}'))
        
        if len(row) == 2 or i == len(group['coords']) - 1:
            keyboard_buttons.append(row)
            row = []
    
    keyboard_buttons.append([InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data='coordinates_main')])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    await edit_or_send_message(user_id, text, keyboard)
    await state.update_data(current_coord_group=group_key)
    await state.set_state(UserStates.coordinates_group)

@router.callback_query(F.data.startswith("coord_edit_"))
async def coordinate_edit_handler(callback: CallbackQuery, state: FSMContext):
    """Редактирование конкретной координаты"""
    user_id = callback.from_user.id
    coord_name = callback.data.replace('coord_edit_', '')
    
    if coord_name not in config.DEFAULT_COORDINATES:
        return
    
    coords = db.get_user_coordinates(user_id)
    coord = coords.get(coord_name, {'x': 0, 'y': 0, 'description': ''})
    
    # Получаем настройки для цвета
    settings = db.get_script_settings(user_id)
    
    # Используем новый шаблон из texts.py
    current_value_text = texts.get_text("COORDINATES.edit.labels.current_value")
    text = texts.get_text("COORDINATES.edit.screen",
                         coord_name=coord_name,
                         current_value=f"({coord['x']}, {coord['y']})")
    
    # Если это back, ok, arrow - показываем цвет
    if coord_name in ['back', 'ok', 'arrow']:
        color_param = f"{coord_name}C"
        color_value = settings.get(color_param, 0)
        text += texts.get_text("COORDINATES.color_info", 
                             color_value=color_value, 
                             hex_value=f"0x{color_value:06X}")
    
    # Сохраняем информацию о редактируемой координате
    await state.update_data(
        editing_coord=coord_name,
        current_coord_group=(await state.get_data()).get('current_coord_group', 'main')
    )
    
    keyboard_buttons = []
    
    # Кнопка сброса
    keyboard_buttons.append([InlineKeyboardButton(text=texts.get_text("BUTTONS.reset"), callback_data=f'coord_reset_{coord_name}')])
    
    # Для back, ok, arrow - добавляем кнопку изменения цвета
    if coord_name in ['back', 'ok', 'arrow']:
        keyboard_buttons.append([InlineKeyboardButton(
            text=texts.get_text("COORDINATES.buttons.change_color"), 
            callback_data=f'coord_color_{coord_name}'
        )])
    
    keyboard_buttons.append([InlineKeyboardButton(
        text=texts.get_text("BUTTONS.back"), 
        callback_data=f'coord_group_{(await state.get_data()).get("current_coord_group", "main")}'
    )])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    image_path = os.path.join(config.IMAGE_PATH, f"{coord_name}.png")
    
    if os.path.exists(image_path):
        await send_photo_message(user_id, image_path, text, keyboard)
    else:
        await edit_or_send_message(user_id, text, keyboard)
    
    await state.set_state(UserStates.coordinates_input)

@router.message(UserStates.coordinates_input)
async def coordinate_input_process(message: Message, state: FSMContext):
    """Обработка ввода координат"""
    user_id = message.from_user.id
    data = await state.get_data()
    coord_name = data.get('editing_coord')
    
    if not coord_name:
        await state.set_state(UserStates.coordinates_main)
        await coordinates_main_handler(FakeCallback(user_id, 'coordinates_main'), state)
        return
    
    input_text = message.text.strip()
    
    try:
        await message.delete()
    except:
        pass
    
    # Валидация формата
    if ',' not in input_text:
        text = texts.get_text("COORDINATES.error.invalid_format")
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data=f'coord_edit_{coord_name}')]
        ])
        await edit_or_send_message(user_id, text, keyboard)
        return
    
    try:
        parts = input_text.split(',')
        if len(parts) != 2:
            raise ValueError
        
        x = int(parts[0].strip())
        y = int(parts[1].strip())
        
        if x < 0 or y < 0:
            text = texts.get_text("COORDINATES.error.negative")
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data=f'coord_edit_{coord_name}')]
            ])
            await edit_or_send_message(user_id, text, keyboard)
            return
        
        if x > 5000 or y > 5000:
            text = texts.get_text("COORDINATES.error.too_large")
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data=f'coord_edit_{coord_name}')]
            ])
            await edit_or_send_message(user_id, text, keyboard)
            return
        
    except ValueError:
        text = texts.get_text("COORDINATES.error.not_numbers")
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data=f'coord_edit_{coord_name}')]
        ])
        await edit_or_send_message(user_id, text, keyboard)
        return
    
    # Сохранение координаты
    db.save_user_coordinate(user_id, coord_name, x, y)
    
    # Возвращаемся к редактированию координаты
    await coordinate_edit_handler(FakeCallback(user_id, f'coord_edit_{coord_name}'), state)

@router.callback_query(F.data.startswith("coord_reset_"))
async def coordinate_reset_handler(callback: CallbackQuery, state: FSMContext):
    """Сброс координаты"""
    user_id = callback.from_user.id
    coord_name = callback.data.replace('coord_reset_', '')
    
    if db.delete_user_coordinate(user_id, coord_name):
        # Возвращаемся к редактированию координаты
        await coordinate_edit_handler(callback, state)

@router.callback_query(F.data.startswith("coord_color_"))
async def coordinate_color_handler(callback: CallbackQuery, state: FSMContext):
    """Настройка цвета координаты"""
    user_id = callback.from_user.id
    coord_name = callback.data.replace('coord_color_', '')
    
    if coord_name not in ['back', 'ok', 'arrow']:
        return
    
    settings = db.get_script_settings(user_id)
    color_param = f"{coord_name}C"
    color_value = settings.get(color_param, 0)
    
    text = texts.get_text("COORDINATES.color_screen",
                         coord_name=coord_name,
                         color_value=color_value,
                         hex_value=f"0x{color_value:06X}")
    
    await state.update_data(
        editing_color_coord=coord_name,
        editing_color_param=color_param
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data=f'coord_edit_{coord_name}')]
    ])
    
    await edit_or_send_message(user_id, text, keyboard)
    await state.set_state(UserStates.color_input)

@router.message(UserStates.color_input)
async def color_input_process(message: Message, state: FSMContext):
    """Обработка ввода цвета"""
    user_id = message.from_user.id
    data = await state.get_data()
    coord_name = data.get('editing_color_coord')
    color_param = data.get('editing_color_param')
    
    if not coord_name or not color_param:
        await state.set_state(UserStates.coordinates_main)
        await coordinates_main_handler(FakeCallback(user_id, 'coordinates_main'), state)
        return
    
    input_text = message.text.strip()
    
    try:
        await message.delete()
    except:
        pass
    
    try:
        color_value = int(input_text)
        
        if color_value < 0 or color_value > 16777215:
            text = texts.get_text("COORDINATES.error.color_range")
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data=f'coord_edit_{coord_name}')]
            ])
            await edit_or_send_message(user_id, text, keyboard)
            return
        
        # Сохраняем цвет в настройках
        settings = db.get_script_settings(user_id)
        settings[color_param] = color_value
        db.save_script_settings(user_id, settings)
        
        # Возвращаемся к редактированию координаты
        await coordinate_edit_handler(FakeCallback(user_id, f'coord_edit_{coord_name}'), state)
        
    except ValueError:
        text = texts.get_text("COORDINATES.error.color_number")
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data=f'coord_edit_{coord_name}')]
        ])
        await edit_or_send_message(user_id, text, keyboard)

# ====================
# ЗАДЕРЖКИ (ОБНОВЛЕННЫЙ РАЗДЕЛ)
# ====================

@router.callback_query(F.data == "delays_main")
async def delays_main_handler(callback: CallbackQuery, state: FSMContext):
    """Главное меню задержек - только основные задержки"""
    user_id = callback.from_user.id
    settings = db.get_script_settings(user_id)
    
    # Формируем красивое отображение только основных задержек
    delay_params = ['dbclickS', 'opkeyS', 'befordS', 'aftordS', 'actreqS', 
                    'reslotS', 'aftpasteS', 'clkeyS']
    
    # Группируем задержки по категориям
    delay_groups = {
        "Основные": ['dbclickS', 'opkeyS', 'befordS', 'aftordS'],
        "Действия": ['actreqS', 'reslotS', 'aftpasteS', 'clkeyS']
    }
    
    delay_lines = []
    for group_name, params in delay_groups.items():
        delay_lines.append(f"<b>▫️ {group_name}:</b>")
        for param in params:
            value = settings.get(param, 0)
            description = config.DELAY_DESCRIPTIONS.get(param, "")
            delay_lines.append(f"   • <code>{param}</code>: <b>{value} мс</b>")
        delay_lines.append("")
    
    current_values = '\n'.join(delay_lines)
    
    text = texts.get_text("DELAYS.main_screen", current_values=current_values)
    
    # Создаем клавиатуру только с основными задержками
    keyboard_buttons = []
    
    # Первая строка: основные задержки
    row1 = []
    for param in ['dbclickS', 'opkeyS', 'befordS', 'aftordS']:
        value = settings.get(param, 0)
        row1.append(InlineKeyboardButton(
            text=f"⏱ {param}\n{value} мс", 
            callback_data=f'delay_edit_{param}'
        ))
        if len(row1) == 2:
            keyboard_buttons.append(row1)
            row1 = []
    if row1:
        keyboard_buttons.append(row1)
    
    # Вторая строка: действия
    row2 = []
    for param in ['actreqS', 'reslotS', 'aftpasteS', 'clkeyS']:
        value = settings.get(param, 0)
        row2.append(InlineKeyboardButton(
            text=f"⚡ {param}\n{value} мс", 
            callback_data=f'delay_edit_{param}'
        ))
        if len(row2) == 2:
            keyboard_buttons.append(row2)
            row2 = []
    if row2:
        keyboard_buttons.append(row2)
    
    keyboard_buttons.append([InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data='script_main')])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    await edit_or_send_message(user_id, text, keyboard)
    await state.set_state(UserStates.delays_main)

@router.callback_query(F.data.startswith("delay_edit_"))
async def delay_edit_handler(callback: CallbackQuery, state: FSMContext):
    """Редактирование задержки"""
    user_id = callback.from_user.id
    param = callback.data.replace('delay_edit_', '')
    
    settings = db.get_script_settings(user_id)
    value = settings.get(param, 0)
    description = config.DELAY_DESCRIPTIONS.get(param, "")
    
    text = texts.get_text("DELAYS.edit_screen",
                         param=param,
                         description=description,
                         value=value)
    
    await state.update_data(
        editing_param=param,
        editing_type='delay'
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data='delays_main')]
    ])
    
    await edit_or_send_message(user_id, text, keyboard)
    await state.set_state(UserStates.delay_input)

# ====================
# УНИВЕРСАЛЬНАЯ ОБРАБОТКА ВВОДА
# ====================

@router.message(UserStates.delay_input)
async def delay_input_process(message: Message, state: FSMContext):
    """Обработка ввода задержки"""
    await universal_input_process(message, state, 'delay')

@router.message(UserStates.mode_param_input)
async def mode_param_input_process(message: Message, state: FSMContext):
    """Обработка ввода параметра режима"""
    await universal_input_process(message, state, 'mode')

@router.message(UserStates.function_param_input)
async def function_param_input_process(message: Message, state: FSMContext):
    """Обработка ввода параметра функции - с возвратом в меню функции"""
    user_id = message.from_user.id
    input_text = message.text.strip()
    data = await state.get_data()
    
    func_key = data.get('editing_func')
    param = data.get('editing_param')
    
    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except:
        pass
    
    if not func_key or not param:
        await functions_main_handler(FakeCallback(user_id, 'functions_main'), state)
        return
    
    try:
        # Определяем тип значения
        settings = db.get_script_settings(user_id)
        
        if param in ['doubcust', 'waitcust', 'fullcust', 'rskincust', 'multincust']:
            value = int(input_text)
        else:
            value = float(input_text.replace(',', '.'))
        
        if value < 0:
            raise ValueError("Значение не может быть отрицательным")
        
        # Сохраняем значение
        settings[param] = value
        db.save_script_settings(user_id, settings)
        
        # Возвращаемся к меню настройки конкретной функции
        await function_view_handler(FakeCallback(user_id, f'function_view_{func_key}'), state)
        
    except ValueError as e:
        # Показываем ошибку и предлагаем повторить ввод
        error_text = f"❌ Ошибка: {str(e)}\n\nВведите правильное значение:"
        
        # Получаем данные функции для повторного отображения
        func_data = texts.get_text(f"FUNCTIONS.functions.{func_key}")
        func_name = func_data['name']
        
        # Получаем описание параметра
        param_description = ""
        if 'param' in func_data and func_data['param'] == param:
            param_description = func_data.get('param_description', '')
        elif 'params' in func_data and param in func_data['params']:
            param_descriptions = func_data.get('param_descriptions', {})
            param_description = param_descriptions.get(param, '')
        
        # Формируем полный текст с ошибкой
        text = f"{error_text}\n\n"
        text += texts.get_text("FUNCTIONS.edit_param_screen",
                             func_name=func_name,
                             param=param,
                             param_description=param_description,
                             value=input_text)
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data=f'function_view_{func_key}')]
        ])
        
        await edit_or_send_message(user_id, text, keyboard)
    except Exception as e:
        logger.error(f"Ошибка в function_param_input_process: {e}")
        await function_view_handler(FakeCallback(user_id, f'function_view_{func_key}'), state)

@router.message(UserStates.saleskin_input)
async def saleskin_input_process(message: Message, state: FSMContext):
    """Обработка ввода цены продажи"""
    await universal_input_process(message, state, 'sale')

async def universal_input_process(message: Message, state: FSMContext, input_type: str):
    """Универсальная обработка ввода"""
    user_id = message.from_user.id
    input_text = message.text.strip()
    data = await state.get_data()
    
    try:
        await message.delete()
    except:
        pass
    
    param_name = data.get('editing_param')
    
    # Валидация в зависимости от типа
    try:
        if input_type == 'delay':
            value = int(input_text)
            if value <= 0:
                raise ValueError(texts.get_text("DELAYS.edit.error.invalid"))
            if value > 10000:
                raise ValueError(texts.get_text("DELAYS.edit.error.too_large"))
            
            settings = db.get_script_settings(user_id)
            settings[param_name] = value
            db.save_script_settings(user_id, settings)
            
            # Возвращаемся в меню редактирования задержки
            await delays_main_handler(FakeCallback(user_id, 'delays_main'), state)
            
        elif input_type == 'mode':
            if '.' in input_text or ',' in input_text:
                value = float(input_text.replace(',', '.'))
            else:
                value = int(input_text)
            
            if value <= 0:
                raise ValueError(texts.get_text("MODES.edit_param.error.invalid"))
            
            if param_name == 'percust' and (value > 100 or value < 0):
                raise ValueError(texts.get_text("MODES.edit_param.error.percent_range"))
            
            settings = db.get_script_settings(user_id)
            settings[param_name] = value
            db.save_script_settings(user_id, settings)
            
            # Возвращаемся в меню редактирования параметра режима
            mode_key = data.get('editing_mode')
            if mode_key:
                await mode_param_handler(FakeCallback(user_id, f'mode_param_{mode_key}'), state)
            else:
                await modes_main_handler(FakeCallback(user_id, 'modes_main'), state)
            
        elif input_type == 'function':
            if param_name in ['doubcust', 'waitcust', 'fullcust', 'rskincust']:
                value = int(input_text)
            else:
                value = float(input_text.replace(',', '.'))
            
            if value < 0:
                raise ValueError(texts.get_text("MESSAGES.invalid_input"))
            
            settings = db.get_script_settings(user_id)
            settings[param_name] = value
            db.save_script_settings(user_id, settings)
            
            # Возвращаемся в меню редактирования параметра функции
            func_key = data.get('editing_func')
            if func_key:
                await function_toggle_handler(FakeCallback(user_id, f'function_{func_key}'), state)
            else:
                await functions_main_handler(FakeCallback(user_id, 'functions_main'), state)
            
        elif input_type == 'sale':
            value = float(input_text.replace(',', '.'))
            if value <= 0:
                raise ValueError(texts.get_text("COMMANDS.error.positive"))
            
            db.create_command(user_id, 'saleskin', {'salePrice': value})
            await commands_main_handler(FakeCallback(user_id, 'commands_main'), state)
        
        else:
            await edit_or_send_message(user_id, texts.get_text("MESSAGES.error"))
            return
            
    except ValueError as e:
        error_text = f"❌ {str(e)}"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data='cancel_input')]
        ])
        await edit_or_send_message(user_id, error_text, keyboard)
    except Exception as e:
        logger.error(f"Ошибка в universal_input_process: {e}")
        error_text = texts.get_text("MESSAGES.error")
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data='cancel_input')]
        ])
        await edit_or_send_message(user_id, error_text, keyboard)

# ====================
# НАСТРОЙКА ПЕРЕБИВА
# ====================

@router.callback_query(F.data == "work_settings")
async def work_settings_handler(callback: CallbackQuery, state: FSMContext):
    """Главное меню настройки перебива"""
    user_id = callback.from_user.id
    settings = db.get_script_settings(user_id)
    
    dcpaste = settings.get('dcpaste', False)
    keypaste = settings.get('keypaste', False)
    inpord = settings.get('inpord', False)
    
    if not dcpaste and not keypaste:
        text = texts.get_text("WORK_SETTINGS.no_platform_screen")
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=texts.get_text("WORK_SETTINGS.no_platform.buttons.pc"), callback_data='work_platform_pc'),
                InlineKeyboardButton(text=texts.get_text("WORK_SETTINGS.no_platform.buttons.phone"), callback_data='work_platform_phone')
            ],
            [InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data='script_main')]
        ])
    elif dcpaste:
        inpord_status = texts.get_text("WORK_SETTINGS.inpord_status.enabled") if inpord else texts.get_text("WORK_SETTINGS.inpord_status.disabled")
        dcpasteS = settings.get('dcpasteS', 30)
        prinpS = settings.get('prinpS', 350)
        
        text = texts.get_text("WORK_SETTINGS.pc_mode_screen",
                             inpord_status=inpord_status,
                             dcpasteS=dcpasteS,
                             prinpS=prinpS)
        
        keyboard_buttons = [
            [InlineKeyboardButton(text=f"inpord ({inpord_status})", callback_data='work_inpord')],
            [
                InlineKeyboardButton(text=f"dcpasteS ({dcpasteS} мс)", callback_data='delay_edit_dcpasteS'),
                InlineKeyboardButton(text=f"prinpS ({prinpS} мс)", callback_data='delay_edit_prinpS')
            ],
            [InlineKeyboardButton(text=texts.get_text("WORK_SETTINGS.buttons.change_platform"), callback_data='work_change_platform')],
            [InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data='script_main')]
        ]
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    else:
        inpord_status = texts.get_text("WORK_SETTINGS.inpord_status.enabled") if inpord else texts.get_text("WORK_SETTINGS.inpord_status.disabled")
        
        text = texts.get_text("WORK_SETTINGS.phone_mode_screen", inpord_status=inpord_status)
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"inpord ({inpord_status})", callback_data='work_inpord')],
            [InlineKeyboardButton(text=texts.get_text("WORK_SETTINGS.buttons.change_platform"), callback_data='work_change_platform')],
            [InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data='script_main')]
        ])
    
    await edit_or_send_message(user_id, text, keyboard)
    await state.set_state(UserStates.work_settings)

@router.callback_query(F.data.startswith("work_platform_"))
async def work_platform_handler(callback: CallbackQuery, state: FSMContext):
    """Выбор платформы - без уведомлений"""
    user_id = callback.from_user.id
    platform = callback.data.replace('work_platform_', '')
    
    settings = db.get_script_settings(user_id)
    
    if platform == 'pc':
        settings['dcpaste'] = True
        settings['keypaste'] = False
        settings['inpord'] = False
    else:
        settings['dcpaste'] = False
        settings['keypaste'] = True
        settings['inpord'] = False
    
    db.save_script_settings(user_id, settings)
    
    # Просто обновляем меню без уведомлений
    await work_settings_handler(callback, state)

@router.callback_query(F.data == "work_change_platform")
async def work_change_platform_handler(callback: CallbackQuery, state: FSMContext):
    """Смена платформы - без уведомлений"""
    user_id = callback.from_user.id
    settings = db.get_script_settings(user_id)
    
    settings['dcpaste'] = False
    settings['keypaste'] = False
    
    db.save_script_settings(user_id, settings)
    
    # Просто обновляем меню без уведомлений
    await work_settings_handler(callback, state)

@router.callback_query(F.data == "work_inpord")
async def work_inpord_handler(callback: CallbackQuery, state: FSMContext):
    """Настройки inpord"""
    user_id = callback.from_user.id
    settings = db.get_script_settings(user_id)
    
    inpord = settings.get('inpord', False)
    inpordS = settings.get('inpordS', 200)
    
    status = texts.get_text("WORK_SETTINGS.inpord_status.enabled") if inpord else texts.get_text("WORK_SETTINGS.inpord_status.disabled")
    
    text = texts.get_text("WORK_SETTINGS.inpord_screen",
                         status=status,
                         inpordS=inpordS)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts.get_text("WORK_SETTINGS.inpord.buttons.edit"), callback_data='delay_edit_inpordS')],
        [InlineKeyboardButton(text="✅ Включить" if not inpord else "❌ Выключить", callback_data='work_inpord_toggle')],
        [InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data='work_settings')]
    ])
    
    await edit_or_send_message(user_id, text, keyboard)
    await state.set_state(UserStates.work_inpord)

@router.callback_query(F.data == "work_inpord_toggle")
async def work_inpord_toggle_handler(callback: CallbackQuery, state: FSMContext):
    """Переключение inpord"""
    user_id = callback.from_user.id
    settings = db.get_script_settings(user_id)
    
    new_state = not settings.get('inpord', False)
    settings['inpord'] = new_state
    db.save_script_settings(user_id, settings)
    
    await work_inpord_handler(callback, state)

# ====================
# РЕЖИМЫ
# ====================

@router.callback_query(F.data == "modes_main")
async def modes_main_handler(callback: CallbackQuery, state: FSMContext):
    """Главное меню режимов"""
    user_id = callback.from_user.id
    settings = db.get_script_settings(user_id)
    
    # Определяем текущий активный режим
    current_mode_key = None
    mode_list = ['defM', 'pfullM', 'percentM', 'tenthM', 'integerM', 'halfM', 'randomM']
    for mode in mode_list:
        if settings.get(mode, False):
            current_mode_key = mode
            break
    
    if not current_mode_key:
        current_mode_key = 'defM'
        settings['defM'] = True
        db.save_script_settings(user_id, settings)
    
    mode_data = texts.get_text(f"MODES.modes.{current_mode_key}")
    emoji = mode_data['name'][0]
    name = mode_data['name']
    
    text = texts.get_text("MODES.current_mode_screen",
                         emoji=emoji,
                         name=name)
    
    if 'param' in mode_data:
        param = mode_data['param']
        value = settings.get(param, 0)
        text += texts.get_text("MODES.param_info", param=param, value=value)
    
    text += texts.get_text("MODES.select_action")
    
    keyboard_buttons = []
    
    if 'param' in mode_data:
        keyboard_buttons.append([InlineKeyboardButton(
            text=texts.get_text("MODES.buttons.edit_param"), 
            callback_data=f'mode_param_{current_mode_key}'
        )])
    
    keyboard_buttons.append([InlineKeyboardButton(
        text=texts.get_text("MODES.buttons.change_mode"), 
        callback_data='modes_list'
    )])
    keyboard_buttons.append([InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data='script_main')])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    await edit_or_send_message(user_id, text, keyboard)
    await state.set_state(UserStates.modes_main)

@router.callback_query(F.data == "modes_list")
async def modes_list_handler(callback: CallbackQuery, state: FSMContext):
    """Список всех режимов"""
    user_id = callback.from_user.id
    
    text = texts.get_text("MODES.list_screen")
    
    keyboard_buttons = []
    modes = [
        ('defM', texts.get_text("MODES.modes.defM.name")),
        ('pfullM', texts.get_text("MODES.modes.pfullM.name")),
        ('percentM', texts.get_text("MODES.modes.percentM.name")),
        ('tenthM', texts.get_text("MODES.modes.tenthM.name")),
        ('integerM', texts.get_text("MODES.modes.integerM.name")),
        ('halfM', texts.get_text("MODES.modes.halfM.name")),
        ('randomM', texts.get_text("MODES.modes.randomM.name")),
    ]
    
    row = []
    for i, (mode_key, mode_name) in enumerate(modes):
        row.append(InlineKeyboardButton(text=mode_name, callback_data=f'mode_select_{mode_key}'))
        
        if len(row) == 2 or i == len(modes) - 1:
            keyboard_buttons.append(row)
            row = []
    
    keyboard_buttons.append([InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data='modes_main')])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    await edit_or_send_message(user_id, text, keyboard)
    await state.set_state(UserStates.modes_list)

@router.callback_query(F.data.startswith("mode_select_"))
async def mode_select_handler(callback: CallbackQuery, state: FSMContext):
    """Выбор режима"""
    user_id = callback.from_user.id
    mode_key = callback.data.replace('mode_select_', '')
    
    mode_data = texts.get_text(f"MODES.modes.{mode_key}")
    emoji = mode_data['name'][0]
    name = mode_data['name']
    description = mode_data['description']
    
    text = texts.get_text("MODES.select_confirm_screen",
                         emoji=emoji,
                         name=name,
                         description=description)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts.get_text("MODES.select_confirm.buttons.activate"), callback_data=f'mode_activate_{mode_key}')],
        [InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data='modes_list')]
    ])
    
    await edit_or_send_message(user_id, text, keyboard)
    await state.set_state(UserStates.mode_select)

@router.callback_query(F.data.startswith("mode_activate_"))
async def mode_activate_handler(callback: CallbackQuery, state: FSMContext):
    """Активация режима"""
    user_id = callback.from_user.id
    mode_key = callback.data.replace('mode_activate_', '')
    
    settings = db.get_script_settings(user_id)
    
    # Отключаем все режимы
    mode_list = ['defM', 'pfullM', 'percentM', 'tenthM', 'integerM', 'halfM', 'randomM']
    for mode in mode_list:
        settings[mode] = False
    
    # Включаем выбранный режим
    settings[mode_key] = True
    db.save_script_settings(user_id, settings)
    
    text = texts.get_text("MODES.activated", mode_name=texts.get_text(f"MODES.modes.{mode_key}.name"))
    await send_toast_notification(callback, text)
    
    await modes_main_handler(callback, state)

@router.callback_query(F.data.startswith("mode_param_"))
async def mode_param_handler(callback: CallbackQuery, state: FSMContext):
    """Ввод параметра режима"""
    user_id = callback.from_user.id
    mode_key = callback.data.replace('mode_param_', '')
    
    mode_data = texts.get_text(f"MODES.modes.{mode_key}")
    param = mode_data['param']
    
    settings = db.get_script_settings(user_id)
    value = settings.get(param, 0)
    
    text = texts.get_text("MODES.edit_param_screen",
                         mode_name=mode_data['name'],
                         param=param,
                         value=value)
    
    await state.update_data(
        editing_param=param,
        editing_mode=mode_key,
        editing_type='mode'
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data='modes_main')]
    ])
    
    await edit_or_send_message(user_id, text, keyboard)
    await state.set_state(UserStates.mode_param_input)

# ====================
# ФУНКЦИИ (ИСПРАВЛЕННАЯ ВЕРСИЯ - МГНОВЕННОЕ ОБНОВЛЕНИЕ)
# ====================

@router.callback_query(F.data == "functions_main")
async def functions_main_handler(callback: CallbackQuery, state: FSMContext):
    """Главное меню функций"""
    user_id = callback.from_user.id
    settings = db.get_script_settings(user_id)
    
    text = texts.get_text("FUNCTIONS.main_screen")
    
    # Список включённых функций
    enabled = []
    func_list = ['barrierF', 'blimitF', 'asellF', 'restskinF', 'multintF', 'flimitF', 'waitF']
    
    for func in func_list:
        if settings.get(func, False):
            func_data = texts.get_text(f"FUNCTIONS.functions.{func}")
            name = func_data['name']
            
            if 'params' in func_data:
                params = func_data['params']
                values = [str(settings.get(p, 0)) for p in params]
                enabled.append(f"• {name}: {', '.join(values)}")
            elif 'param' in func_data:
                param = func_data['param']
                value = settings.get(param, 0)
                enabled.append(f"• {name}: {value}")
    
    if enabled:
        text += texts.get_text("FUNCTIONS.enabled_title") + "\n" + '\n'.join(enabled) + "\n\n"
    else:
        text += texts.get_text("FUNCTIONS.no_enabled") + "\n"
    
    text += texts.get_text("FUNCTIONS.select_function")
    
    keyboard_buttons = []
    functions = [
        ('barrierF', texts.get_text("FUNCTIONS.functions.barrierF.name")),
        ('blimitF', texts.get_text("FUNCTIONS.functions.blimitF.name")),
        ('asellF', texts.get_text("FUNCTIONS.functions.asellF.name")),
        ('restskinF', texts.get_text("FUNCTIONS.functions.restskinF.name")),
        ('multintF', texts.get_text("FUNCTIONS.functions.multintF.name")),
        ('flimitF', texts.get_text("FUNCTIONS.functions.flimitF.name")),
        ('waitF', texts.get_text("FUNCTIONS.functions.waitF.name")),
    ]
    
    row = []
    for i, (func_key, func_name) in enumerate(functions):
        is_enabled = settings.get(func_key, False)
        status_emoji = "🟢" if is_enabled else "🔴"
        row.append(InlineKeyboardButton(text=f"{status_emoji} {func_name}", callback_data=f'function_view_{func_key}'))
        
        if len(row) == 2 or i == len(functions) - 1:
            keyboard_buttons.append(row)
            row = []
    
    keyboard_buttons.append([InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data='script_main')])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    await edit_or_send_message(user_id, text, keyboard)
    await state.set_state(UserStates.functions_main)

@router.callback_query(F.data.startswith("function_view_"))
async def function_view_handler(callback: CallbackQuery, state: FSMContext):
    """Просмотр и управление конкретной функцией"""
    user_id = callback.from_user.id
    func_key = callback.data.replace('function_view_', '')
    
    if func_key not in ['barrierF', 'blimitF', 'asellF', 'restskinF', 'multintF', 'flimitF', 'waitF']:
        await functions_main_handler(callback, state)
        return
    
    settings = db.get_script_settings(user_id)
    is_enabled = settings.get(func_key, False)
    
    func_data = texts.get_text(f"FUNCTIONS.functions.{func_key}")
    name = func_data['name']
    description = func_data['description']
    
    status = texts.get_text("FUNCTIONS.status.enabled") if is_enabled else texts.get_text("FUNCTIONS.status.disabled")
    
    text = f"<b>⚙️ {name}</b>\n\n"
    text += f"<b>Описание:</b> {description}\n\n"
    text += f"<b>Статус:</b> {status}\n"
    
    # Показываем параметры если функция включена
    if is_enabled:
        if 'param' in func_data:
            param = func_data['param']
            value = settings.get(param, 0)
            param_description = func_data.get('param_description', '')
            text += f"\n<b>Параметр:</b>\n"
            text += f"• <code>{param}</code> = {value}\n"
            text += f"  <i>{param_description}</i>\n"
        elif 'params' in func_data:
            params = func_data['params']
            param_descriptions = func_data.get('param_descriptions', {})
            text += f"\n<b>Параметры:</b>\n"
            for param in params:
                value = settings.get(param, 0)
                description = param_descriptions.get(param, '')
                text += f"• <code>{param}</code> = {value}\n"
                text += f"  <i>{description}</i>\n"
    
    text += "\n⬇️ Выберите действие:"
    
    keyboard_buttons = []
    
    # Кнопка включения/выключения
    toggle_text = "❌ Выключить" if is_enabled else "✅ Включить"
    keyboard_buttons.append([InlineKeyboardButton(
        text=toggle_text, 
        callback_data=f'function_toggle_{func_key}'
    )])
    
    # Кнопки редактирования параметров если функция включена
    if is_enabled:
        if 'param' in func_data:
            param = func_data['param']
            value = settings.get(param, 0)
            keyboard_buttons.append([InlineKeyboardButton(
                text=f"✏️ Изменить {param} ({value})", 
                callback_data=f'function_edit_{func_key}_{param}'
            )])
        elif 'params' in func_data:
            params = func_data['params']
            for param in params:
                value = settings.get(param, 0)
                keyboard_buttons.append([InlineKeyboardButton(
                    text=f"✏️ Изменить {param} ({value})", 
                    callback_data=f'function_edit_{func_key}_{param}'
                )])
    
    keyboard_buttons.append([InlineKeyboardButton(
        text=texts.get_text("BUTTONS.back"), 
        callback_data='functions_main'
    )])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    # Обновляем сообщение мгновенно, не уходя в другие меню
    await edit_or_send_message(user_id, text, keyboard)
    await state.set_state(UserStates.function_toggle)

@router.callback_query(F.data.startswith("function_toggle_"))
async def function_toggle_handler(callback: CallbackQuery, state: FSMContext):
    """Включение/выключение функции - МГНОВЕННОЕ ОБНОВЛЕНИЕ В ТОМ ЖЕ МЕНЮ"""
    user_id = callback.from_user.id
    func_key = callback.data.replace('function_toggle_', '')
    
    if func_key not in ['barrierF', 'blimitF', 'asellF', 'restskinF', 'multintF', 'flimitF', 'waitF']:
        await functions_main_handler(callback, state)
        return
    
    settings = db.get_script_settings(user_id)
    current_state = settings.get(func_key, False)
    
    # Меняем состояние
    new_state = not current_state
    settings[func_key] = new_state
    db.save_script_settings(user_id, settings)
    
    # Немедленно обновляем текущее сообщение с новым статусом
    func_data = texts.get_text(f"FUNCTIONS.functions.{func_key}")
    name = func_data['name']
    description = func_data['description']
    
    status = texts.get_text("FUNCTIONS.status.enabled") if new_state else texts.get_text("FUNCTIONS.status.disabled")
    
    text = f"<b>⚙️ {name}</b>\n\n"
    text += f"<b>Описание:</b> {description}\n\n"
    text += f"<b>Статус:</b> {status}\n"
    
    # Показываем параметры если функция теперь включена
    if new_state:
        if 'param' in func_data:
            param = func_data['param']
            value = settings.get(param, 0)
            param_description = func_data.get('param_description', '')
            text += f"\n<b>Параметр:</b>\n"
            text += f"• <code>{param}</code> = {value}\n"
            text += f"  <i>{param_description}</i>\n"
        elif 'params' in func_data:
            params = func_data['params']
            param_descriptions = func_data.get('param_descriptions', {})
            text += f"\n<b>Параметры:</b>\n"
            for param in params:
                value = settings.get(param, 0)
                description_text = param_descriptions.get(param, '')
                text += f"• <code>{param}</code> = {value}\n"
                text += f"  <i>{description_text}</i>\n"
    
    text += "\n⬇️ Выберите действие:"
    
    keyboard_buttons = []
    
    # Кнопка включения/выключения (уже с новым состоянием)
    toggle_text = "❌ Выключить" if new_state else "✅ Включить"
    keyboard_buttons.append([InlineKeyboardButton(
        text=toggle_text, 
        callback_data=f'function_toggle_{func_key}'
    )])
    
    # Кнопки редактирования параметров если функция теперь включена
    if new_state:
        if 'param' in func_data:
            param = func_data['param']
            value = settings.get(param, 0)
            keyboard_buttons.append([InlineKeyboardButton(
                text=f"✏️ Изменить {param} ({value})", 
                callback_data=f'function_edit_{func_key}_{param}'
            )])
        elif 'params' in func_data:
            params = func_data['params']
            for param in params:
                value = settings.get(param, 0)
                keyboard_buttons.append([InlineKeyboardButton(
                    text=f"✏️ Изменить {param} ({value})", 
                    callback_data=f'function_edit_{func_key}_{param}'
                )])
    
    keyboard_buttons.append([InlineKeyboardButton(
        text=texts.get_text("BUTTONS.back"), 
        callback_data='functions_main'
    )])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    # Пытаемся отредактировать текущее сообщение
    try:
        await bot.edit_message_text(
            chat_id=user_id,
            message_id=callback.message.message_id,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        # Обновляем ID текущего сообщения
        if user_id in user_current_message_id:
            user_current_message_id[user_id] = callback.message.message_id
    except Exception as e:
        logger.debug(f"Не удалось редактировать сообщение, отправляем новое: {e}")
        # Если не удалось редактировать, отправляем новое сообщение
        await edit_or_send_message(user_id, text, keyboard)
    
    await state.set_state(UserStates.function_toggle)

@router.callback_query(F.data.startswith("function_edit_"))
async def function_edit_handler(callback: CallbackQuery, state: FSMContext):
    """Редактирование параметра функции"""
    user_id = callback.from_user.id
    data = callback.data
    
    # Парсим данные: function_edit_barrierF_barcust
    parts = data.split('_')
    if len(parts) < 4:
        await functions_main_handler(callback, state)
        return
    
    func_key = '_'.join(parts[2:3])  # barrierF
    param = parts[3]  # barcust
    
    settings = db.get_script_settings(user_id)
    value = settings.get(param, 0)
    
    func_data = texts.get_text(f"FUNCTIONS.functions.{func_key}")
    func_name = func_data['name']
    
    # Получаем описание параметра
    param_description = ""
    if 'param' in func_data and func_data['param'] == param:
        param_description = func_data.get('param_description', '')
    elif 'params' in func_data and param in func_data['params']:
        param_descriptions = func_data.get('param_descriptions', {})
        param_description = param_descriptions.get(param, '')
    
    text = texts.get_text("FUNCTIONS.edit_param_screen",
                         func_name=func_name,
                         param=param,
                         param_description=param_description,
                         value=value)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data=f'function_view_{func_key}')]
    ])
    
    await edit_or_send_message(user_id, text, keyboard)
    
    await state.update_data(
        editing_func=func_key,
        editing_param=param
    )
    await state.set_state(UserStates.function_param_input)

@router.message(UserStates.function_param_input)
async def function_param_input_process(message: Message, state: FSMContext):
    """Обработка ввода параметра функции - с мгновенным возвратом к меню функции"""
    user_id = message.from_user.id
    input_text = message.text.strip()
    data = await state.get_data()
    
    func_key = data.get('editing_func')
    param = data.get('editing_param')
    
    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except:
        pass
    
    if not func_key or not param:
        await functions_main_handler(FakeCallback(user_id, 'functions_main'), state)
        return
    
    try:
        # Определяем тип значения
        settings = db.get_script_settings(user_id)
        
        if param in ['doubcust', 'waitcust', 'fullcust', 'rskincust', 'multincust']:
            value = int(input_text)
        else:
            value = float(input_text.replace(',', '.'))
        
        if value < 0:
            raise ValueError("Значение не может быть отрицательным")
        
        # Сохраняем значение
        settings[param] = value
        db.save_script_settings(user_id, settings)
        
        # Немедленно возвращаемся к меню функции с обновленными данными
        await function_view_handler(FakeCallback(user_id, f'function_view_{func_key}'), state)
        
    except ValueError as e:
        # Показываем ошибку и остаемся в режиме редактирования
        error_text = f"❌ Ошибка: {str(e)}\n\nПопробуйте снова:"
        
        # Создаем клавиатуру для возврата
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data=f'function_view_{func_key}')]
        ])
        
        # Отправляем сообщение с ошибкой
        try:
            await bot.send_message(
                chat_id=user_id,
                text=error_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения об ошибке: {e}")
    except Exception as e:
        logger.error(f"Ошибка в function_param_input_process: {e}")
        await function_view_handler(FakeCallback(user_id, f'function_view_{func_key}'), state)

# ====================
# ПАРАМЕТРЫ
# ====================

@router.callback_query(F.data == "parameters_main")
async def parameters_main_handler(callback: CallbackQuery, state: FSMContext):
    """Главное меню параметров"""
    user_id = callback.from_user.id
    
    text = texts.get_text("PARAMETERS.main_screen")
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=texts.get_text("PARAMETERS.scanM.name"), callback_data='param_scanM'),
            InlineKeyboardButton(text=texts.get_text("PARAMETERS.sendcatch.name"), callback_data='param_sendcatch')
        ],
        [InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data='script_main')]
    ])
    
    await edit_or_send_message(user_id, text, keyboard)
    await state.set_state(UserStates.parameters_main)

@router.callback_query(F.data == "param_scanM")
async def param_scanM_handler(callback: CallbackQuery, state: FSMContext):
    """Настройка Scan Mode"""
    user_id = callback.from_user.id
    settings = db.get_script_settings(user_id)
    
    is_enabled = settings.get('scanM', False)
    status = texts.get_text("PARAMETERS.scanM.status.enabled") if is_enabled else texts.get_text("PARAMETERS.scanM.status.disabled")
    
    text = texts.get_text("PARAMETERS.scanM_screen", status=status)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Выключить" if is_enabled else "✅ Включить", callback_data='param_scanM_toggle')],
        [InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data='parameters_main')]
    ])
    
    await edit_or_send_message(user_id, text, keyboard)
    await state.set_state(UserStates.parameter_edit)

@router.callback_query(F.data == "param_scanM_toggle")
async def param_scanM_toggle_handler(callback: CallbackQuery, state: FSMContext):
    """Переключение Scan Mode"""
    user_id = callback.from_user.id
    settings = db.get_script_settings(user_id)
    
    new_state = not settings.get('scanM', False)
    settings['scanM'] = new_state
    db.save_script_settings(user_id, settings)
    
    await param_scanM_handler(callback, state)

@router.callback_query(F.data == "param_sendcatch")
async def param_sendcatch_handler(callback: CallbackQuery, state: FSMContext):
    """Настройка отправки уловов"""
    user_id = callback.from_user.id
    settings = db.get_script_settings(user_id)
    
    is_enabled = settings.get('sendcatch', False)
    status = texts.get_text("PARAMETERS.sendcatch.status.enabled") if is_enabled else texts.get_text("PARAMETERS.sendcatch.status.disabled")
    
    text = texts.get_text("PARAMETERS.sendcatch_screen", status=status)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Выключить" if is_enabled else "✅ Включить", callback_data='param_sendcatch_toggle')],
        [InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data='parameters_main')]
    ])
    
    await edit_or_send_message(user_id, text, keyboard)
    await state.set_state(UserStates.parameter_edit)

@router.callback_query(F.data == "param_sendcatch_toggle")
async def param_sendcatch_toggle_handler(callback: CallbackQuery, state: FSMContext):
    """Переключение отправки уловов"""
    user_id = callback.from_user.id
    settings = db.get_script_settings(user_id)
    
    new_state = not settings.get('sendcatch', False)
    settings['sendcatch'] = new_state
    db.save_script_settings(user_id, settings)
    
    await param_sendcatch_handler(callback, state)

# ====================
# КОМАНДЫ
# ====================

@router.callback_query(F.data == "menu_commands")
async def commands_main_handler(callback: CallbackQuery, state: FSMContext):
    """Меню команд"""
    user_id = callback.from_user.id
    
    text = texts.get_text("COMMANDS.main_screen")
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=texts.get_text("COMMANDS.restskin.name"), callback_data='cmd_restskin'),
            InlineKeyboardButton(text=texts.get_text("COMMANDS.saleskin.name"), callback_data='cmd_saleskin')
        ],
        [
            InlineKeyboardButton(text=texts.get_text("COMMANDS.compcheck.name"), callback_data='cmd_compcheck'),
            InlineKeyboardButton(text=texts.get_text("COMMANDS.device_info.name"), callback_data='cmd_device_info')
        ],
        [InlineKeyboardButton(text=texts.get_text("COMMANDS.script_info.name"), callback_data='cmd_script_info')],
        [InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data='script_main')]
    ])
    
    await edit_or_send_message(user_id, text, keyboard)
    await state.set_state(UserStates.commands_main)

@router.callback_query(F.data == "cmd_restskin")
async def cmd_restskin_handler(callback: CallbackQuery, state: FSMContext):
    """Команда перезайти на скин"""
    user_id = callback.from_user.id
    db.create_command(user_id, 'restskin')
    
    await send_toast_notification(callback, texts.get_text("COMMANDS.restskin.confirm"))

@router.callback_query(F.data == "cmd_saleskin")
async def cmd_saleskin_handler(callback: CallbackQuery, state: FSMContext):
    """Начало команды продать скин"""
    user_id = callback.from_user.id
    
    text = texts.get_text("COMMANDS.saleskin.input")
    
    await state.update_data(
        editing_type='sale'
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data='commands_main')]
    ])
    
    await edit_or_send_message(user_id, text, keyboard)
    await state.set_state(UserStates.saleskin_input)

@router.callback_query(F.data == "cmd_compcheck")
async def cmd_compcheck_handler(callback: CallbackQuery, state: FSMContext):
    """Проверка КК"""
    user_id = callback.from_user.id
    db.create_command(user_id, 'compcheck', {'compCheckVal': 1})
    
    await send_toast_notification(callback, texts.get_text("COMMANDS.compcheck.confirm"))

@router.callback_query(F.data == "cmd_device_info")
async def cmd_device_info_handler(callback: CallbackQuery, state: FSMContext):
    """Информация об устройстве"""
    user_id = callback.from_user.id
    db.create_command(user_id, 'get_device_info')
    
    await send_toast_notification(callback, texts.get_text("COMMANDS.device_info.confirm"))

@router.callback_query(F.data == "cmd_script_info")
async def cmd_script_info_handler(callback: CallbackQuery, state: FSMContext):
    """Информация о скрипте"""
    user_id = callback.from_user.id
    db.create_command(user_id, 'get_script_info')
    
    await send_toast_notification(callback, texts.get_text("COMMANDS.script_info.confirm"))

# ====================
# НАСТРОЙКИ ПОЛЬЗОВАТЕЛЯ
# ====================

@router.callback_query(F.data == "user_settings")
async def user_settings_handler(callback: CallbackQuery, state: FSMContext):
    """Настройки пользователя"""
    user_id = callback.from_user.id
    user = db.get_user(user_id)
    key_info = db.get_user_key_info(user_id)
    
    # Статус
    status_text = texts.get_text("USER_SETTINGS.status.admin") if user['is_admin'] else texts.get_text("USER_SETTINGS.status.regular")
    
    # Информация о ключе
    if key_info:
        key_status = texts.get_text("USER_SETTINGS.key_status.frozen") if key_info['is_frozen'] else texts.get_text("USER_SETTINGS.key_status.active")
        created_date = datetime.fromisoformat(key_info['created_at']).strftime("%d.%m.%Y %H:%M")
        
        creator = db.get_user(key_info['created_by'])
        creator_name = creator['username'] if creator and creator['username'] else f"ID: {key_info['created_by']}"
        
        text = texts.get_text("USER_SETTINGS.with_key_screen",
                             username=user.get('username', 'Пользователь'),
                             user_id=user_id,
                             status_text=status_text,
                             key_value=key_info['key_value'],
                             created_date=created_date,
                             creator_name=creator_name,
                             key_status=key_status)
    else:
        text = texts.get_text("USER_SETTINGS.without_key_screen",
                             username=user.get('username', 'Пользователь'),
                             user_id=user_id,
                             status_text=status_text)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data='menu_main')]
    ])
    
    await edit_or_send_message(user_id, text, keyboard)
    await state.set_state(UserStates.user_settings)

# ====================
# АДМИН-ПАНЕЛЬ
# ====================

@router.callback_query(F.data == "admin_main")
async def admin_main_handler(callback: CallbackQuery, state: FSMContext):
    """Админ-панель"""
    user_id = callback.from_user.id
    
    if user_id not in config.ADMIN_IDS:
        return
    
    text = texts.get_text("ADMIN.main_screen")
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts.get_text("ADMIN.buttons.keys"), callback_data='admin_keys')],
        [
            InlineKeyboardButton(text=texts.get_text("ADMIN.buttons.stats"), callback_data='admin_statistics'),
            InlineKeyboardButton(text=texts.get_text("ADMIN.buttons.loot"), callback_data='admin_loot')
        ],
        [InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data='menu_main')]
    ])
    
    await edit_or_send_message(user_id, text, keyboard)
    await state.set_state(UserStates.admin_main)

@router.callback_query(F.data == "admin_keys")
async def admin_keys_handler(callback: CallbackQuery, state: FSMContext):
    """Управление ключами"""
    user_id = callback.from_user.id
    
    if user_id not in config.ADMIN_IDS:
        return
    
    all_keys = db.get_all_keys()
    filtered_keys = []
    
    for key in all_keys:
        if key['activated_by'] and key['activated_by'] in config.ADMIN_IDS:
            continue
        filtered_keys.append(key)
    
    text = texts.get_text("KEYS.management.description", total=len(filtered_keys))
    
    # Создаем клавиатуру с ключами
    keyboard_buttons = []
    row = []
    
    for i, key in enumerate(filtered_keys[:15]):  # Показываем первые 15 ключей
        if key['activated_by']:
            user = db.get_user(key['activated_by'])
            username = user.get('username', '') if user else ''
            button_text = f"✅ @{username}" if username else f"✅ ID:{key['activated_by']}"
        else:
            button_text = "❌"
        
        row.append(InlineKeyboardButton(text=button_text, callback_data=f"key_view_{key['id']}"))
        
        if len(row) == 3 or i == len(filtered_keys[:15]) - 1:
            keyboard_buttons.append(row)
            row = []
    
    keyboard_buttons.append([InlineKeyboardButton(text=texts.get_text("KEYS.management.actions.create"), callback_data='admin_create_key')])
    keyboard_buttons.append([InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data='admin_main')])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    await edit_or_send_message(user_id, text, keyboard)
    await state.set_state(UserStates.admin_keys)

@router.callback_query(F.data.startswith("key_view_"))
async def admin_key_detail_handler(callback: CallbackQuery, state: FSMContext):
    """Детали ключа - с новым расположением кнопок"""
    user_id = callback.from_user.id
    
    if user_id not in config.ADMIN_IDS:
        return
    
    try:
        key_id = int(callback.data.replace('key_view_', ''))
    except ValueError:
        return
    
    key = db.get_key_by_id(key_id)
    
    if not key:
        return
    
    # Статус
    if key['activated_by']:
        status = texts.get_text("KEYS.management.status.active")
        owner = db.get_user(key['activated_by'])
        owner_text = f"@{owner['username']}" if owner and owner['username'] else f"ID: {key['activated_by']}"
        activated_date = datetime.fromisoformat(key['activated_at']).strftime("%d.%m.%Y %H:%M")
        owner_section = texts.get_text("KEYS.management.owner_section",
                                      owner_text=owner_text,
                                      activated_date=activated_date)
    else:
        status = texts.get_text("KEYS.management.status.inactive")
        owner_section = ""
        activated_date = "-"
    
    creator = db.get_user(key['created_by'])
    creator_text = f"@{creator['username']}" if creator and creator['username'] else f"ID: {key['created_by']}"
    created_date = datetime.fromisoformat(key['created_at']).strftime("%d.%m.%Y %H:%M")
    
    frozen_text = texts.get_text("KEYS.management.frozen.yes") if key['is_frozen'] else texts.get_text("KEYS.management.frozen.no")
    
    text = texts.get_text("KEYS.management.key_details",
                         key_value=key['key_value'],
                         status=status,
                         frozen_text=frozen_text,
                         created_date=created_date,
                         creator_text=creator_text,
                         owner_section=owner_section)
    
    keyboard_buttons = []
    
    if key['activated_by']:
        # Ключ активирован - новая структура кнопок
        if key['is_frozen']:
            keyboard_buttons.append([
                InlineKeyboardButton(
                    text=texts.get_text("KEYS.management.actions.unfreeze"), 
                    callback_data=f'key_unfreeze_{key_id}'
                ),
                InlineKeyboardButton(
                    text=texts.get_text("KEYS.management.actions.unbind"), 
                    callback_data=f'key_unbind_{key_id}'
                )
            ])
        else:
            keyboard_buttons.append([
                InlineKeyboardButton(
                    text=texts.get_text("KEYS.management.actions.freeze"), 
                    callback_data=f'key_freeze_{key_id}'
                ),
                InlineKeyboardButton(
                    text=texts.get_text("KEYS.management.actions.unbind"), 
                    callback_data=f'key_unbind_{key_id}'
                )
            ])
        
        # Вторая строка: одна кнопка
        keyboard_buttons.append([InlineKeyboardButton(
            text=texts.get_text("KEYS.management.actions.delete"), 
            callback_data=f'key_delete_{key_id}'
        )])
    else:
        # Ключ не активирован
        if key['is_frozen']:
            keyboard_buttons.append([
                InlineKeyboardButton(
                    text=texts.get_text("KEYS.management.actions.unfreeze"), 
                    callback_data=f'key_unfreeze_{key_id}'
                ),
                InlineKeyboardButton(
                    text=texts.get_text("KEYS.management.actions.delete"), 
                    callback_data=f'key_delete_{key_id}'
                )
            ])
        else:
            keyboard_buttons.append([
                InlineKeyboardButton(
                    text=texts.get_text("KEYS.management.actions.freeze"), 
                    callback_data=f'key_freeze_{key_id}'
                ),
                InlineKeyboardButton(
                    text=texts.get_text("KEYS.management.actions.delete"), 
                    callback_data=f'key_delete_{key_id}'
                )
            ])
    
    # Третья строка: одна кнопка Назад
    keyboard_buttons.append([InlineKeyboardButton(
        text=texts.get_text("BUTTONS.back"), 
        callback_data='admin_keys'
    )])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    await edit_or_send_message(user_id, text, keyboard)
    await state.set_state(UserStates.admin_key_detail)

@router.callback_query(F.data.startswith("key_freeze_"))
async def key_freeze_handler(callback: CallbackQuery, state: FSMContext):
    """Заморозить ключ - мгновенное обновление"""
    user_id = callback.from_user.id
    key_id = int(callback.data.replace('key_freeze_', ''))
    
    key = db.get_key_by_id(key_id)
    if not key:
        return
    
    if db.freeze_key(key_id):
        # Мгновенно обновляем меню ключа
        await admin_key_detail_handler(callback, state)

@router.callback_query(F.data.startswith("key_unfreeze_"))
async def key_unfreeze_handler(callback: CallbackQuery, state: FSMContext):
    """Разморозить ключ - мгновенное обновление"""
    user_id = callback.from_user.id
    key_id = int(callback.data.replace('key_unfreeze_', ''))
    
    key = db.get_key_by_id(key_id)
    if not key:
        return
    
    if db.unfreeze_key(key_id):
        # Мгновенно обновляем меню ключа
        await admin_key_detail_handler(callback, state)

@router.callback_query(F.data.startswith("key_unbind_"))
async def key_unbind_handler(callback: CallbackQuery, state: FSMContext):
    """Отвязать ключ - мгновенное обновление"""
    user_id = callback.from_user.id
    key_id = int(callback.data.replace('key_unbind_', ''))
    
    key = db.get_key_by_id(key_id)
    if not key:
        return
    
    if db.unbind_key(key_id):
        # Мгновенно обновляем меню ключа
        await admin_key_detail_handler(callback, state)

@router.callback_query(F.data.startswith("key_delete_"))
async def key_delete_handler(callback: CallbackQuery, state: FSMContext):
    """Удалить ключ - мгновенное обновление"""
    user_id = callback.from_user.id
    key_id = int(callback.data.replace('key_delete_', ''))
    
    key = db.get_key_by_id(key_id)
    if not key:
        return
    
    if db.delete_key(key_id):
        # Обновляем список ключей
        await admin_keys_handler(callback, state)

@router.callback_query(F.data == "admin_create_key")
async def admin_create_key_handler(callback: CallbackQuery, state: FSMContext):
    """Создать новый ключ"""
    user_id = callback.from_user.id
    
    key = db.create_key(user_id)
    text = texts.get_text("KEYS.management.created", key_value=key['key_value'])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data='admin_keys')]
    ])
    
    await edit_or_send_message(user_id, text, keyboard)

@router.callback_query(F.data == "admin_statistics")
async def admin_statistics_handler(callback: CallbackQuery, state: FSMContext):
    """Статистика системы"""
    user_id = callback.from_user.id
    
    stats = db.get_statistics()
    
    text = texts.get_text("STATISTICS.main_screen",
                         total=stats['users']['total'],
                         admins=stats['users']['admins'],
                         regular=stats['users']['regular'],
                         total_keys=stats['keys']['total'],
                         used=stats['keys']['used'],
                         free=stats['keys']['free'],
                         frozen=stats['keys']['frozen'],
                         running=stats['scripts']['running'],
                         paused=stats['scripts']['paused'],
                         offline=stats['scripts']['offline'])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data='admin_main')]
    ])
    
    await edit_or_send_message(user_id, text, keyboard)
    await state.set_state(UserStates.admin_statistics)

@router.callback_query(F.data == "admin_loot")
async def admin_loot_handler(callback: CallbackQuery, state: FSMContext):
    """Настройки приёма уловов"""
    user_id = callback.from_user.id
    
    if user_id not in config.ADMIN_IDS:
        return
    
    settings = db.get_script_settings(user_id)
    
    receive = texts.get_text("ADMIN_LOOT.status.receive.enabled") if settings.get('admin_receive_loot', False) else texts.get_text("ADMIN_LOOT.status.receive.disabled")
    from_all = texts.get_text("ADMIN_LOOT.status.source.all") if settings.get('admin_receive_all', True) else texts.get_text("ADMIN_LOOT.status.source.not_all")
    
    text = texts.get_text("ADMIN_LOOT.main_screen", receive=receive, from_all=from_all)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts.get_text("ADMIN_LOOT.buttons.toggle_receive"), callback_data='admin_loot_toggle_receive')],
        [InlineKeyboardButton(text=texts.get_text("ADMIN_LOOT.buttons.toggle_source"), callback_data='admin_loot_toggle_source')],
        [InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data='admin_main')]
    ])
    
    await edit_or_send_message(user_id, text, keyboard)
    await state.set_state(UserStates.admin_loot)

@router.callback_query(F.data == "admin_loot_toggle_receive")
async def admin_loot_toggle_receive_handler(callback: CallbackQuery, state: FSMContext):
    """Переключение приёма уловов"""
    user_id = callback.from_user.id
    settings = db.get_script_settings(user_id)
    
    new_state = not settings.get('admin_receive_loot', False)
    settings['admin_receive_loot'] = new_state
    db.save_script_settings(user_id, settings)
    
    await admin_loot_handler(callback, state)

@router.callback_query(F.data == "admin_loot_toggle_source")
async def admin_loot_toggle_source_handler(callback: CallbackQuery, state: FSMContext):
    """Переключение источника уловов"""
    user_id = callback.from_user.id
    settings = db.get_script_settings(user_id)
    
    new_state = not settings.get('admin_receive_all', True)
    settings['admin_receive_all'] = new_state
    db.save_script_settings(user_id, settings)
    
    await admin_loot_handler(callback, state)

# ====================
# ОТМЕНА ВВОДА И ВОЗВРАТ
# ====================

@router.callback_query(F.data == "cancel_input")
async def cancel_input_handler(callback: CallbackQuery, state: FSMContext):
    """Отмена ввода"""
    user_id = callback.from_user.id
    data = await state.get_data()
    return_to = data.get('return_to', 'script_main')
    
    # Создаем фейковый callback для возврата
    fake_callback = FakeCallback(user_id, return_to)
    
    if return_to == 'menu_main':
        await show_main_menu(user_id, state)
    elif return_to == 'script_main':
        await show_script_main_panel(fake_callback, state)
    elif return_to == 'coordinates_main':
        await coordinates_main_handler(fake_callback, state)
    elif return_to == 'delays_main':
        await delays_main_handler(fake_callback, state)
    elif return_to == 'work_settings':
        await work_settings_handler(fake_callback, state)
    elif return_to == 'modes_main':
        await modes_main_handler(fake_callback, state)
    elif return_to == 'functions_main':
        await functions_main_handler(fake_callback, state)
    elif return_to.startswith('function_'):
        await function_toggle_handler(fake_callback, state)
    elif return_to == 'parameters_main':
        await parameters_main_handler(fake_callback, state)
    elif return_to == 'commands_main':
        await commands_main_handler(fake_callback, state)
    elif return_to == 'admin_keys':
        await admin_keys_handler(fake_callback, state)
    else:
        await show_main_menu(user_id, state)

@router.callback_query(F.data == "menu_main")
async def back_to_main_handler(callback: CallbackQuery, state: FSMContext):
    """Возврат в главное меню"""
    user_id = callback.from_user.id
    
    if user_id in active_users_in_script_control:
        del active_users_in_script_control[user_id]
    
    await show_main_menu(user_id, state)

@router.callback_query(F.data == "empty")
async def empty_handler(callback: CallbackQuery):
    """Обработчик пустых кнопок"""
    pass

# ====================
# ВСПОМОГАТЕЛЬНЫЕ КЛАССЫ
# ====================

class FakeCallback:
    """Фейковый callback для возврата в меню"""
    def __init__(self, user_id, data):
        self.from_user = type('obj', (object,), {'id': user_id})()
        self.data = data
        self.message = type('obj', (object,), {'chat': type('obj', (object,), {'id': user_id})()})()
    
    async def answer(self, text=None, show_alert=False):
        pass

# ====================
# МОНИТОРИНГ СКРИПТОВ И ОЧИСТКА ЛОГОВ
# ====================

async def monitor_script_changes():
    """Мониторинг изменений статуса скриптов"""
    logger.info(texts.get_text("LOGS.monitor_start"))
    
    last_known_status = {}
    
    while True:
        try:
            active_user_ids = list(active_users_in_script_control.keys())
            
            for user_id in active_user_ids:
                try:
                    current_status = await get_script_status_from_api(user_id, force_refresh=False)
                    old_status = last_known_status.get(user_id)
                    
                    if old_status is None or (
                        old_status.get('is_running') != current_status.get('is_running') or
                        old_status.get('is_paused') != current_status.get('is_paused')
                    ):
                        if user_id in active_users_in_script_control:
                            await update_script_panel_for_user(user_id)
                    
                    last_known_status[user_id] = current_status
                    
                    # Удаляем неактивных пользователей (больше 5 минут)
                    last_active = active_users_in_script_control.get(user_id)
                    if last_active and (datetime.now() - last_active).total_seconds() > 300:
                        del active_users_in_script_control[user_id]
                        if user_id in last_known_status:
                            del last_known_status[user_id]
                            
                except Exception as e:
                    logger.debug(f"Ошибка обновления статуса для user_id={user_id}: {e}")
            
            await asyncio.sleep(3)
            
        except Exception as e:
            logger.error(texts.get_text("LOGS.error", error=e))
            await asyncio.sleep(10)

async def cleanup_old_logs():
    """Автоматическая очистка логов старше 3 дней"""
    while True:
        try:
            # Ждем 3 дня
            await asyncio.sleep(3 * 24 * 60 * 60)
            
            log_file = config.LOG_FILE
            if os.path.exists(log_file):
                # Получаем время последнего изменения файла
                file_mtime = os.path.getmtime(log_file)
                file_age_days = (time.time() - file_mtime) / (24 * 60 * 60)
                
                if file_age_days > 3:
                    # Создаем резервную копию
                    backup_name = f"{log_file}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                    with open(log_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # Сохраняем последние 1000 строк
                    lines = content.split('\n')
                    if len(lines) > 1000:
                        lines = lines[-1000:]
                    
                    # Очищаем файл
                    with open(log_file, 'w', encoding='utf-8') as f:
                        f.write('\n'.join(lines))
                    
                    # Сохраняем полную копию
                    with open(backup_name, 'w', encoding='utf-8') as f:
                        f.write(content)
                    
                    logger.info(f"Логи очищены. Создана резервная копия: {backup_name}")
                    
                    # Удаляем старые резервные копии (старше 7 дней)
                    for filename in os.listdir('.'):
                        if filename.startswith(f"{log_file}.backup_"):
                            backup_path = os.path.join('.', filename)
                            backup_mtime = os.path.getmtime(backup_path)
                            backup_age_days = (time.time() - backup_mtime) / (24 * 60 * 60)
                            
                            if backup_age_days > 7:
                                os.remove(backup_path)
                                logger.info(f"Удалена старая резервная копия: {filename}")
            
        except Exception as e:
            logger.error(f"Ошибка при очистке логов: {e}")
        
        # Проверяем раз в день
        await asyncio.sleep(24 * 60 * 60)

async def update_script_panel_for_user(user_id: int):
    """Обновление панели скрипта для пользователя"""
    try:
        status_data = await get_script_status_from_api(user_id, force_refresh=True)
        
        title, status_text, description = get_script_status_text(user_id)
        text = f"{title}\n{status_text}\n\n{description}"
        
        # Определяем кнопки в зависимости от статуса
        keyboard_buttons = []
        
        if status_data['is_running']:
            if status_data['is_paused']:
                keyboard_buttons.append([
                    InlineKeyboardButton(text=texts.get_text("SCRIPT_SECTION.buttons.resume"), callback_data='script_resume'),
                    InlineKeyboardButton(text=texts.get_text("SCRIPT_SECTION.buttons.stop"), callback_data='script_stop')
                ])
            else:
                keyboard_buttons.append([
                    InlineKeyboardButton(text=texts.get_text("SCRIPT_SECTION.buttons.pause"), callback_data='script_pause'),
                    InlineKeyboardButton(text=texts.get_text("SCRIPT_SECTION.buttons.stop"), callback_data='script_stop')
                ])
            keyboard_buttons.append([InlineKeyboardButton(text=texts.get_text("SCRIPT_SECTION.buttons.commands"), callback_data='menu_commands')])
        else:
            keyboard_buttons.append([InlineKeyboardButton(text=texts.get_text("SCRIPT_SECTION.buttons.coordinates"), callback_data='coordinates_main')])
        
        # Общие кнопки настроек
        if not status_data['is_running'] or status_data['is_paused']:
            keyboard_buttons.extend([
                [
                    InlineKeyboardButton(text=texts.get_text("SCRIPT_SECTION.buttons.delays"), callback_data='delays_main'),
                    InlineKeyboardButton(text=texts.get_text("SCRIPT_SECTION.buttons.work_settings"), callback_data='work_settings')
                ],
                [
                    InlineKeyboardButton(text=texts.get_text("SCRIPT_SECTION.buttons.modes"), callback_data='modes_main'),
                    InlineKeyboardButton(text=texts.get_text("SCRIPT_SECTION.buttons.functions"), callback_data='functions_main')
                ],
                [InlineKeyboardButton(text=texts.get_text("SCRIPT_SECTION.buttons.parameters"), callback_data='parameters_main')]
            ])
        else:
            keyboard_buttons.extend([
                [
                    InlineKeyboardButton(text=texts.get_text("SCRIPT_SECTION.buttons.delays"), callback_data='delays_main'),
                    InlineKeyboardButton(text=texts.get_text("SCRIPT_SECTION.buttons.work_settings"), callback_data='work_settings')
                ],
                [
                    InlineKeyboardButton(text=texts.get_text("SCRIPT_SECTION.buttons.modes"), callback_data='modes_main'),
                    InlineKeyboardButton(text=texts.get_text("SCRIPT_SECTION.buttons.functions"), callback_data='functions_main')
                ],
                [
                    InlineKeyboardButton(text=texts.get_text("SCRIPT_SECTION.buttons.parameters"), callback_data='parameters_main'),
                    InlineKeyboardButton(text=texts.get_text("MESSAGES.empty_button"), callback_data="empty")
                ]
            ])
        
        keyboard_buttons.append([InlineKeyboardButton(text=texts.get_text("BUTTONS.back"), callback_data='menu_main')])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        
        await bot.edit_message_text(
            chat_id=user_id,
            message_id=user_current_message_id.get(user_id),
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.debug(f"Не удалось обновить статус для user_id={user_id}: {e}")

# ====================
# ЗАПУСК БОТА
# ====================

async def main():
    """Основная функция запуска бота"""
    logger.info(texts.get_text("LOGS.bot_start"))
    
    # Запускаем мониторинг в фоне
    asyncio.create_task(monitor_script_changes())
    
    # Запускаем очистку логов
    asyncio.create_task(cleanup_old_logs())
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
