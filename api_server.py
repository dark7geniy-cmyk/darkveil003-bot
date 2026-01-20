from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime
import uvicorn
import asyncio
import logging

import config
from database import Database

# Настройка логирования
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(config.LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Инициализация
app = FastAPI(title="DARKVEIL API", version="0.03")
db = Database()

# Хранилище для отправки сообщений боту
message_queue = asyncio.Queue()

# ===== МОДЕЛИ ДАННЫХ =====

class ValidateRequest(BaseModel):
    user_id: str
    user_key: str

class HeartbeatRequest(BaseModel):
    user_id: str
    user_key: str
    status: str = "running"

class CommandRequest(BaseModel):
    user_id: int
    command: str

class PauseRequest(BaseModel):
    user_id: int
    seconds: int = 86400

class NotificationRequest(BaseModel):
    user_id: str
    user_key: str
    message: str

class CatchNotificationRequest(BaseModel):
    user_id: str
    user_key: str
    catch_type: str
    username: str
    message: str

class CommandCompleteRequest(BaseModel):
    command_id: int
    result: Optional[str] = None

class DeviceInfoRequest(BaseModel):
    user_id: str
    user_key: str
    message: str

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====

def verify_api_key(api_key: Optional[str] = Header(None)) -> bool:
    """Проверка API ключа"""
    return api_key == config.API_SECRET_KEY

def verify_user_key(user_id: str, user_key: str) -> bool:
    """Проверка ключа пользователя"""
    try:
        uid = int(user_id)
        key_info = db.get_user_key_info(uid)
        
        if not key_info:
            return False
        
        return (key_info['key_value'] == user_key and 
                key_info['activated_by'] == uid and 
                not key_info['is_frozen'])
    except Exception as e:
        logger.error(f"Error verifying user key: {e}")
        return False

async def send_to_bot(user_id: int, message: str, message_type: str = "notification"):
    """Отправить сообщение боту"""
    await message_queue.put({
        'user_id': user_id,
        'message': message,
        'type': message_type,
        'timestamp': datetime.now().isoformat()
    })

# ===== ЭНДПОИНТЫ API =====

@app.get("/")
async def root():
    """Проверка работоспособности API"""
    return {"status": "ok", "version": "0.03", "service": "DARKVEIL API"}

@app.get("/api/validate")
async def validate_auth(
    user_id: str,
    key: str,
    api_key: str,
    request: Request
):
    """
    Валидация авторизации скрипта
    
    Query params:
        user_id: Telegram ID пользователя
        key: Ключ доступа
        api_key: API ключ
    """
    if api_key != config.API_SECRET_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    if not verify_user_key(user_id, key):
        return JSONResponse(
            status_code=401,
            content={"status": "error", "message": "Invalid credentials"}
        )
    
    try:
        uid = int(user_id)
        user = db.get_user(uid)
        
        return {
            "status": "ok",
            "username": user.get('username', '') if user else ''
        }
    except Exception as e:
        logger.error(f"Validation error: {e}")
        raise HTTPException(status_code=500, detail="Internal error")

@app.post("/api/heartbeat")
async def heartbeat(request: HeartbeatRequest, api_key: str = Header(None)):
    """
    Heartbeat от скрипта
    
    Body:
        user_id: Telegram ID
        user_key: Ключ доступа
        status: Статус (running/stopped)
    """
    if not verify_api_key(api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    if not verify_user_key(request.user_id, request.user_key):
        return {"valid": False, "message": "Invalid credentials"}
    
    try:
        uid = int(request.user_id)
        
        # Обновляем heartbeat
        db.update_heartbeat(uid)
        
        # Обновляем статус
        is_running = request.status == "running"
        status = db.get_script_status(uid)
        db.update_script_status(uid, is_running, status.get('is_paused', False))
        
        return {"valid": True, "message": "Heartbeat received"}
    except Exception as e:
        logger.error(f"Heartbeat error: {e}")
        return {"valid": False, "message": "Error processing heartbeat"}

@app.get("/api/config")
async def get_config(
    user_id: str,
    key: str,
    api_key: str
):
    """
    Получить полную конфигурацию для скрипта
    
    Query params:
        user_id: Telegram ID
        key: Ключ доступа
        api_key: API ключ
    """
    if api_key != config.API_SECRET_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    if not verify_user_key(user_id, key):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    try:
        uid = int(user_id)
        
        # Получаем настройки
        settings = db.get_script_settings(uid)
        
        # Получаем координаты
        coordinates = db.get_user_coordinates(uid)
        
        # Формируем конфигурацию
        config_data = {}
        
        # Добавляем настройки
        config_data.update(settings)
        
        # Добавляем координаты
        for coord_name, coord_data in coordinates.items():
            config_data[f"{coord_name}_x"] = coord_data['x']
            config_data[f"{coord_name}_y"] = coord_data['y']
        
        return config_data
        
    except Exception as e:
        logger.error(f"Config error: {e}")
        raise HTTPException(status_code=500, detail="Error loading config")

@app.get("/api/runtime_config")
async def get_runtime_config(
    user_id: str,
    key: str,
    api_key: str
):
    """
    Получить конфигурацию, которую можно менять во время работы
    
    Query params:
        user_id: Telegram ID
        key: Ключ доступа
        api_key: API ключ
    """
    if api_key != config.API_SECRET_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    if not verify_user_key(user_id, key):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    try:
        uid = int(user_id)
        settings = db.get_script_settings(uid)
        
        # Возвращаем только параметры, которые можно менять в runtime
        runtime_config = {
            key: value for key, value in settings.items()
            if key in config.RUNTIME_EDITABLE_PARAMS
        }
        
        return runtime_config
        
    except Exception as e:
        logger.error(f"Runtime config error: {e}")
        raise HTTPException(status_code=500, detail="Error loading runtime config")

@app.get("/api/commands")
async def get_commands(
    user_id: str,
    key: str,
    api_key: str
):
    """
    Получить ожидающие команды для скрипта
    
    Query params:
        user_id: Telegram ID
        key: Ключ доступа
        api_key: API ключ
    
    Returns:
        JSON с командами и флагами
    """
    if api_key != config.API_SECRET_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    if not verify_user_key(user_id, key):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    try:
        uid = int(user_id)
        
        # Получаем ожидающие команды
        commands = db.get_pending_commands(uid)
        
        # Формируем ответ
        response = {}
        
        for cmd in commands:
            cmd_type = cmd['command_type']
            
            if cmd_type == 'restskin':
                response['restskin'] = True
            elif cmd_type == 'saleskin':
                import json
                params = json.loads(cmd['params']) if cmd['params'] else {}
                response['saleskin'] = params.get('salePrice', 0)
            elif cmd_type == 'compcheck':
                import json
                params = json.loads(cmd['params']) if cmd['params'] else {}
                response['compcheck'] = params.get('compCheckVal', 0)
            elif cmd_type == 'get_device_info':
                response['get_device_info'] = True
            elif cmd_type == 'get_script_info':
                response['get_script_info'] = True
        
        # Проверяем, обновилась ли конфигурация
        config_version = db.get_config_version(uid)
        response['config_version'] = config_version
        
        # Если есть команды, помечаем что они были получены
        if commands:
            response['config_updated'] = True
        
        return response
        
    except Exception as e:
        logger.error(f"Commands error: {e}")
        raise HTTPException(status_code=500, detail="Error getting commands")

@app.get("/api/check_commands/{user_id}")
async def check_commands(user_id: int, api_key: str = Header(None)):
    """Проверить наличие команд и статус скрипта (для бота)"""
    if not verify_api_key(api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    try:
        # Получаем статус
        status = db.get_script_status(user_id)
        
        # Получаем команды
        commands = db.get_pending_commands(user_id)
        
        return {
            "is_running": status.get('is_running', False),
            "is_paused": status.get('is_paused', False),
            "pause_until": status.get('pause_until'),
            "has_commands": len(commands) > 0
        }
    except Exception as e:
        logger.error(f"Check commands error: {e}")
        raise HTTPException(status_code=500, detail="Error checking commands")

@app.post("/api/command")
async def create_command(request: CommandRequest, api_key: str = Header(None)):
    """
    Создать команду для скрипта (от бота)
    
    Body:
        user_id: Telegram ID
        command: stop/pause/resume
    """
    if not verify_api_key(api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    try:
        if request.command == "stop":
            db.update_script_status(request.user_id, False, False)
            return {"status": "ok", "message": "Stop command sent"}
        
        return {"status": "ok", "message": "Command created"}
        
    except Exception as e:
        logger.error(f"Create command error: {e}")
        raise HTTPException(status_code=500, detail="Error creating command")

@app.post("/api/pause")
async def set_pause(request: PauseRequest, api_key: str = Header(None)):
    """
    Установить/снять паузу скрипта
    
    Body:
        user_id: Telegram ID
        seconds: Длительность паузы (0 = снять паузу)
    """
    if not verify_api_key(api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    try:
        db.set_pause(request.user_id, request.seconds)
        
        if request.seconds > 0:
            return {"status": "ok", "message": "Pause set"}
        else:
            return {"status": "ok", "message": "Pause removed"}
            
    except Exception as e:
        logger.error(f"Pause error: {e}")
        raise HTTPException(status_code=500, detail="Error setting pause")

@app.post("/api/notify")
async def send_notification(request: NotificationRequest, api_key: str = Header(None)):
    """
    Отправить уведомление пользователю от скрипта
    
    Body:
        user_id: Telegram ID
        user_key: Ключ доступа
        message: Текст сообщения
    """
    if not verify_user_key(request.user_id, request.user_key):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    try:
        uid = int(request.user_id)
        await send_to_bot(uid, request.message, "notification")
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Notification error: {e}")
        raise HTTPException(status_code=500, detail="Error sending notification")

@app.post("/api/catch_notify")
async def send_catch_notification(request: CatchNotificationRequest):
    """
    Отправить уведомление об улове администраторам (без фильтра lowLootOnly)
    
    Body:
        user_id: Telegram ID отправителя
        user_key: Ключ доступа
        catch_type: Тип улова (FULL, HALF-LOW, LOW)
        username: Username отправителя
        message: Текст сообщения
    """
    if not verify_user_key(request.user_id, request.user_key):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    try:
        uid = int(request.user_id)
        
        # Отправляем пользователю
        await send_to_bot(uid, request.message, "catch")
        
        # Получаем список админов с включённым приёмом уловов
        for admin_id in config.ADMIN_IDS:
            admin_settings = db.get_script_settings(admin_id)
            
            # Проверяем, включён ли приём уловов
            if not admin_settings.get('admin_receive_loot', False):
                continue
            
            # Проверяем, от всех ли принимаем
            if not admin_settings.get('admin_receive_all', True):
                continue
            
            # Добавляем username в сообщение
            admin_message = f"👤 От: @{request.username}\n\n{request.message}"
            await send_to_bot(admin_id, admin_message, "admin_catch")
        
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Catch notification error: {e}")
        raise HTTPException(status_code=500, detail="Error sending catch notification")

@app.post("/api/script_stopped")
async def script_stopped(request: NotificationRequest):
    """Уведомление об остановке скрипта"""
    if not verify_user_key(request.user_id, request.user_key):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    try:
        uid = int(request.user_id)
        
        # Обновляем статус
        db.update_script_status(uid, False, False)
        
        # Отправляем уведомление
        message = f"🛑 Скрипт остановлен\nПричина: {request.message}"
        await send_to_bot(uid, message, "notification")
        
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Script stopped error: {e}")
        raise HTTPException(status_code=500, detail="Error processing stop")

@app.post("/api/device_info")
async def device_info(request: DeviceInfoRequest):
    """Получить информацию об устройстве"""
    if not verify_user_key(request.user_id, request.user_key):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    try:
        uid = int(request.user_id)
        await send_to_bot(uid, request.message, "device_info")
        
        # Удаляем команду из очереди
        commands = db.get_pending_commands(uid)
        for cmd in commands:
            if cmd['command_type'] == 'get_device_info':
                db.complete_command(cmd['id'])
        
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Device info error: {e}")
        raise HTTPException(status_code=500, detail="Error processing device info")

@app.post("/api/script_info")
async def script_info(request: DeviceInfoRequest):
    """Получить информацию о скрипте"""
    if not verify_user_key(request.user_id, request.user_key):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    try:
        uid = int(request.user_id)
        await send_to_bot(uid, request.message, "script_info")
        
        # Удаляем команду из очереди
        commands = db.get_pending_commands(uid)
        for cmd in commands:
            if cmd['command_type'] == 'get_script_info':
                db.complete_command(cmd['id'])
        
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Script info error: {e}")
        raise HTTPException(status_code=500, detail="Error processing script info")

# ===== ЗАПУСК СЕРВЕРА =====

if __name__ == "__main__":
    logger.info(f"Starting DARKVEIL API server on {config.API_HOST}:{config.API_PORT}")
    uvicorn.run(
        app,
        host=config.API_HOST,
        port=config.API_PORT,
        log_level=config.LOG_LEVEL.lower()
    )
