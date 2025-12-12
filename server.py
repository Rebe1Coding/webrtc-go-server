"""
WebRTC Signaling Server
Использует aiohttp для WebSocket соединений
"""

from aiohttp import web
import json
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Хранилище активных пользователей
users = {}  # {username: websocket}


async def websocket_handler(request):
    """Обработчик WebSocket соединений"""
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    
    username = None
    
    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    message_type = data.get('type')
                    
                    # Регистрация пользователя
                    if message_type == 'login':
                        username = data.get('username')
                        if username in users:
                            await ws.send_json({
                                'type': 'error',
                                'message': 'Username already taken'
                            })
                            await ws.close()
                            return
                        
                        users[username] = ws
                        await ws.send_json({
                            'type': 'login_success',
                            'username': username
                        })
                        logger.info(f"User {username} connected. Total users: {len(users)}")
                    
                    # Инициация звонка
                    elif message_type == 'call':
                        target = data.get('target')
                        call_type = data.get('callType')
                        
                        if target not in users:
                            await ws.send_json({
                                'type': 'error',
                                'message': f'User {target} not found'
                            })
                        else:
                            target_ws = users[target]
                            await target_ws.send_json({
                                'type': 'incoming_call',
                                'from': username,
                                'callType': call_type
                            })
                            logger.info(f"Call from {username} to {target} ({call_type})")
                    
                    # WebRTC сигнализация - Offer
                    elif message_type == 'offer':
                        target = data.get('target')
                        offer = data.get('offer')
                        
                        if target in users:
                            target_ws = users[target]
                            await target_ws.send_json({
                                'type': 'offer',
                                'from': username,
                                'offer': offer
                            })
                            logger.info(f"Offer from {username} to {target}")
                    
                    # WebRTC сигнализация - Answer
                    elif message_type == 'answer':
                        target = data.get('target')
                        answer = data.get('answer')
                        
                        if target in users:
                            target_ws = users[target]
                            await target_ws.send_json({
                                'type': 'answer',
                                'from': username,
                                'answer': answer
                            })
                            logger.info(f"Answer from {username} to {target}")
                    
                    # WebRTC сигнализация - ICE Candidate
                    elif message_type == 'ice-candidate':
                        target = data.get('target')
                        candidate = data.get('candidate')
                        
                        if target in users:
                            target_ws = users[target]
                            await target_ws.send_json({
                                'type': 'ice-candidate',
                                'from': username,
                                'candidate': candidate
                            })
                    
                    # Отклонение звонка
                    elif message_type == 'decline':
                        target = data.get('target')
                        
                        if target in users:
                            target_ws = users[target]
                            await target_ws.send_json({
                                'type': 'call_declined',
                                'from': username
                            })
                            logger.info(f"Call declined by {username}")
                    
                    # Завершение звонка
                    elif message_type == 'end_call':
                        target = data.get('target')
                        
                        if target in users:
                            target_ws = users[target]
                            await target_ws.send_json({
                                'type': 'call_ended',
                                'from': username
                            })
                            logger.info(f"Call ended by {username}")
                
                except json.JSONDecodeError:
                    logger.error("Invalid JSON received")
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
            
            elif msg.type == web.WSMsgType.ERROR:
                logger.error(f'WebSocket error: {ws.exception()}')
    
    finally:
        # Удаление пользователя при отключении
        if username and username in users:
            del users[username]
            logger.info(f"User {username} disconnected. Total users: {len(users)}")
    
    return ws


async def index_handler(request):
    """Возвращает HTML страницу"""
    with open('index.html', 'r', encoding='utf-8') as f:
        return web.Response(text=f.read(), content_type='text/html')


def main():
    """Запуск сервера"""
    app = web.Application()
    
    # Роуты
    app.router.add_get('/', index_handler)
    app.router.add_get('/ws', websocket_handler)
    
    # CORS для разработки
    async def cors_middleware(app, handler):
        async def middleware_handler(request):
            response = await handler(request)
            response.headers['Access-Control-Allow-Origin'] = '*'
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = '*'
            return response
        return middleware_handler
    
    app.middlewares.append(cors_middleware)
    
    # Запуск
    logger.info("Starting WebRTC Signaling Server on http://localhost:8000")
    web.run_app(app, host='0.0.0.0', port=8000)


if __name__ == '__main__':
    main()