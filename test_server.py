"""
Автоматические тесты для WebRTC Signaling Server
Использует pytest и pytest-aiohttp
"""

import pytest
import json
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop
import asyncio
from server import websocket_handler, index_handler, users


class TestWebRTCServer(AioHTTPTestCase):
    """Тесты для WebRTC сигнального сервера"""
    
    async def get_application(self):
        """Создание тестового приложения"""
        app = web.Application()
        app.router.add_get('/', index_handler)
        app.router.add_get('/ws', websocket_handler)
        return app
    
    async def setUp(self):
        """Очистка перед каждым тестом"""
        await super().setUp()
        users.clear()
    
    @unittest_run_loop
    async def test_index_page(self):
        """Тест загрузки главной страницы"""
        async with self.client.request("GET", "/") as resp:
            assert resp.status == 200
            text = await resp.text()
            assert "WebRTC Caller" in text
    
    @unittest_run_loop
    async def test_websocket_connection(self):
        """Тест установки WebSocket соединения"""
        async with self.client.ws_connect('/ws') as ws:
            assert not ws.closed
    
    @unittest_run_loop
    async def test_user_login_success(self):
        """Тест успешной регистрации пользователя"""
        async with self.client.ws_connect('/ws') as ws:
            # Отправка login запроса
            await ws.send_json({
                'type': 'login',
                'username': 'test_user'
            })
            
            # Получение ответа
            msg = await ws.receive_json()
            
            assert msg['type'] == 'login_success'
            assert msg['username'] == 'test_user'
            assert 'test_user' in users
    
    @unittest_run_loop
    async def test_duplicate_username(self):
        """Тест регистрации с занятым username"""
        # Первый пользователь
        async with self.client.ws_connect('/ws') as ws1:
            await ws1.send_json({
                'type': 'login',
                'username': 'duplicate_user'
            })
            await ws1.receive_json()
            
            # Второй пользователь с тем же username
            async with self.client.ws_connect('/ws') as ws2:
                await ws2.send_json({
                    'type': 'login',
                    'username': 'duplicate_user'
                })
                
                msg = await ws2.receive_json()
                assert msg['type'] == 'error'
                assert 'already taken' in msg['message']
    
    @unittest_run_loop
    async def test_call_initiation(self):
        """Тест инициации звонка"""
        # Создаем двух пользователей
        async with self.client.ws_connect('/ws') as ws_caller:
            await ws_caller.send_json({
                'type': 'login',
                'username': 'caller'
            })
            await ws_caller.receive_json()
            
            async with self.client.ws_connect('/ws') as ws_callee:
                await ws_callee.send_json({
                    'type': 'login',
                    'username': 'callee'
                })
                await ws_callee.receive_json()
                
                # Инициация звонка
                await ws_caller.send_json({
                    'type': 'call',
                    'target': 'callee',
                    'callType': 'video'
                })
                
                # Получение уведомления о входящем звонке
                msg = await ws_callee.receive_json()
                assert msg['type'] == 'incoming_call'
                assert msg['from'] == 'caller'
                assert msg['callType'] == 'video'
    
    @unittest_run_loop
    async def test_call_to_nonexistent_user(self):
        """Тест звонка несуществующему пользователю"""
        async with self.client.ws_connect('/ws') as ws:
            await ws.send_json({
                'type': 'login',
                'username': 'caller'
            })
            await ws.receive_json()
            
            await ws.send_json({
                'type': 'call',
                'target': 'nonexistent',
                'callType': 'audio'
            })
            
            msg = await ws.receive_json()
            assert msg['type'] == 'error'
            assert 'not found' in msg['message']
    
    @unittest_run_loop
    async def test_offer_exchange(self):
        """Тест обмена WebRTC offer"""
        async with self.client.ws_connect('/ws') as ws_caller:
            await ws_caller.send_json({
                'type': 'login',
                'username': 'caller'
            })
            await ws_caller.receive_json()
            
            async with self.client.ws_connect('/ws') as ws_callee:
                await ws_callee.send_json({
                    'type': 'login',
                    'username': 'callee'
                })
                await ws_callee.receive_json()
                
                # Отправка offer
                test_offer = {
                    'type': 'offer',
                    'sdp': 'fake_sdp_data'
                }
                
                await ws_caller.send_json({
                    'type': 'offer',
                    'target': 'callee',
                    'offer': test_offer
                })
                
                # Получение offer
                msg = await ws_callee.receive_json()
                assert msg['type'] == 'offer'
                assert msg['from'] == 'caller'
                assert msg['offer'] == test_offer
    
    @unittest_run_loop
    async def test_answer_exchange(self):
        """Тест обмена WebRTC answer"""
        async with self.client.ws_connect('/ws') as ws_caller:
            await ws_caller.send_json({
                'type': 'login',
                'username': 'caller'
            })
            await ws_caller.receive_json()
            
            async with self.client.ws_connect('/ws') as ws_callee:
                await ws_callee.send_json({
                    'type': 'login',
                    'username': 'callee'
                })
                await ws_callee.receive_json()
                
                # Отправка answer
                test_answer = {
                    'type': 'answer',
                    'sdp': 'fake_answer_sdp'
                }
                
                await ws_callee.send_json({
                    'type': 'answer',
                    'target': 'caller',
                    'answer': test_answer
                })
                
                # Получение answer
                msg = await ws_caller.receive_json()
                assert msg['type'] == 'answer'
                assert msg['from'] == 'callee'
                assert msg['answer'] == test_answer
    
    @unittest_run_loop
    async def test_ice_candidate_exchange(self):
        """Тест обмена ICE candidates"""
        async with self.client.ws_connect('/ws') as ws1:
            await ws1.send_json({
                'type': 'login',
                'username': 'user1'
            })
            await ws1.receive_json()
            
            async with self.client.ws_connect('/ws') as ws2:
                await ws2.send_json({
                    'type': 'login',
                    'username': 'user2'
                })
                await ws2.receive_json()
                
                # Отправка ICE candidate
                test_candidate = {
                    'candidate': 'candidate:1 1 UDP 2130706431 192.168.1.1 54321 typ host',
                    'sdpMLineIndex': 0,
                    'sdpMid': 'audio'
                }
                
                await ws1.send_json({
                    'type': 'ice-candidate',
                    'target': 'user2',
                    'candidate': test_candidate
                })
                
                # Получение ICE candidate
                msg = await ws2.receive_json()
                assert msg['type'] == 'ice-candidate'
                assert msg['from'] == 'user1'
                assert msg['candidate'] == test_candidate
    
    @unittest_run_loop
    async def test_call_decline(self):
        """Тест отклонения звонка"""
        async with self.client.ws_connect('/ws') as ws_caller:
            await ws_caller.send_json({
                'type': 'login',
                'username': 'caller'
            })
            await ws_caller.receive_json()
            
            async with self.client.ws_connect('/ws') as ws_callee:
                await ws_callee.send_json({
                    'type': 'login',
                    'username': 'callee'
                })
                await ws_callee.receive_json()
                
                # Отклонение звонка
                await ws_callee.send_json({
                    'type': 'decline',
                    'target': 'caller'
                })
                
                # Получение уведомления об отклонении
                msg = await ws_caller.receive_json()
                assert msg['type'] == 'call_declined'
                assert msg['from'] == 'callee'
    
    @unittest_run_loop
    async def test_call_end(self):
        """Тест завершения звонка"""
        async with self.client.ws_connect('/ws') as ws1:
            await ws1.send_json({
                'type': 'login',
                'username': 'user1'
            })
            await ws1.receive_json()
            
            async with self.client.ws_connect('/ws') as ws2:
                await ws2.send_json({
                    'type': 'login',
                    'username': 'user2'
                })
                await ws2.receive_json()
                
                # Завершение звонка
                await ws1.send_json({
                    'type': 'end_call',
                    'target': 'user2'
                })
                
                # Получение уведомления о завершении
                msg = await ws2.receive_json()
                assert msg['type'] == 'call_ended'
                assert msg['from'] == 'user1'
    
    @unittest_run_loop
    async def test_user_disconnect(self):
        """Тест отключения пользователя"""
        async with self.client.ws_connect('/ws') as ws:
            await ws.send_json({
                'type': 'login',
                'username': 'disconnect_test'
            })
            await ws.receive_json()
            
            assert 'disconnect_test' in users
        
        # После закрытия соединения
        await asyncio.sleep(0.1)  # Даем время на cleanup
        assert 'disconnect_test' not in users
    
    @unittest_run_loop
    async def test_multiple_users(self):
        """Тест работы с несколькими пользователями"""
        connections = []
        usernames = ['user1', 'user2', 'user3']
        
        try:
            for username in usernames:
                ws = await self.client.ws_connect('/ws')
                await ws.send_json({
                    'type': 'login',
                    'username': username
                })
                await ws.receive_json()
                connections.append(ws)
            
            # Проверка, что все пользователи зарегистрированы
            assert len(users) == 3
            for username in usernames:
                assert username in users
        finally:
            # Закрытие всех соединений
            for ws in connections:
                await ws.close()
    
    @unittest_run_loop
    async def test_invalid_json(self):
        """Тест обработки невалидного JSON"""
        async with self.client.ws_connect('/ws') as ws:
            await ws.send_str('invalid json data')
            # Сервер должен продолжать работать
            await ws.send_json({
                'type': 'login',
                'username': 'test_user'
            })
            msg = await ws.receive_json()
            assert msg['type'] == 'login_success'
    
    @unittest_run_loop
    async def test_full_call_flow(self):
        """Тест полного потока звонка: инициация -> offer -> answer -> ICE -> завершение"""
        async with self.client.ws_connect('/ws') as ws_caller:
            # Регистрация caller
            await ws_caller.send_json({
                'type': 'login',
                'username': 'caller'
            })
            await ws_caller.receive_json()
            
            async with self.client.ws_connect('/ws') as ws_callee:
                # Регистрация callee
                await ws_callee.send_json({
                    'type': 'login',
                    'username': 'callee'
                })
                await ws_callee.receive_json()
                
                # 1. Инициация звонка
                await ws_caller.send_json({
                    'type': 'call',
                    'target': 'callee',
                    'callType': 'video'
                })
                
                incoming = await ws_callee.receive_json()
                assert incoming['type'] == 'incoming_call'
                
                # 2. Отправка offer
                await ws_caller.send_json({
                    'type': 'offer',
                    'target': 'callee',
                    'offer': {'sdp': 'offer_sdp'}
                })
                
                offer = await ws_callee.receive_json()
                assert offer['type'] == 'offer'
                
                # 3. Отправка answer
                await ws_callee.send_json({
                    'type': 'answer',
                    'target': 'caller',
                    'answer': {'sdp': 'answer_sdp'}
                })
                
                answer = await ws_caller.receive_json()
                assert answer['type'] == 'answer'
                
                # 4. Обмен ICE candidates
                await ws_caller.send_json({
                    'type': 'ice-candidate',
                    'target': 'callee',
                    'candidate': {'candidate': 'ice_data'}
                })
                
                ice = await ws_callee.receive_json()
                assert ice['type'] == 'ice-candidate'
                
                # 5. Завершение звонка
                await ws_caller.send_json({
                    'type': 'end_call',
                    'target': 'callee'
                })
                
                end = await ws_callee.receive_json()
                assert end['type'] == 'call_ended'


# Дополнительные unit тесты
class TestServerComponents:
    """Unit тесты для отдельных компонентов"""
    
    def test_users_dict_initialization(self):
        """Тест инициализации словаря пользователей"""
        assert isinstance(users, dict)
    
    def test_users_dict_operations(self):
        """Тест операций со словарем пользователей"""
        users.clear()
        
        # Добавление пользователя
        users['test'] = 'mock_ws'
        assert 'test' in users
        assert len(users) == 1
        
        # Удаление пользователя
        del users['test']
        assert 'test' not in users
        assert len(users) == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])