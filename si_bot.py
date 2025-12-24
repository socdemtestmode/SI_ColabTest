# @title 🤖 Запуск SIGame бота
# @markdown Нажмите на кнопку ▶️ слева, чтобы запустить бота. Он создаст игру и выведет ссылку-приглашение.

import sys
import subprocess
import asyncio
import json
import logging
import random
import traceback
import time

# --- Установка зависимостей ---
def install_libs():
    """Проверяет и устанавливает необходимые библиотеки."""
    try:
        import aiohttp
        import websockets
        # print("✅ Библиотеки уже установлены.")
    except ImportError:
        print("📥 Установка aiohttp и websockets...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "aiohttp", "websockets"])
        print("✅ Библиотеки успешно установлены.")

install_libs()
import aiohttp
import websockets

# --- Настройки логгирования ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
    stream=sys.stdout,
    force=True
)
logger = logging.getLogger("SIGameBot")

# --- Конфигурация бота ---
# API для поиска серверов
SERVERS_API = "https://vladimirkhil.com/api/si/servers"
# Прямой адрес сервера (используется в приоритете)
DIRECT_SERVER = "https://vladimirkhil.com/sigameserver-0"

# Имя бота будет сгенерировано случайно, чтобы избежать конфликтов
BOT_NAME = f"ColabBot_{random.randint(1000, 9999)}"
# Имя игры будет содержать случайное число
GAME_NAME = f"testcolabgame{random.randint(1, 99):03}"
# Пароль для входа в игру
GAME_PASSWORD = "1212"

# Технический разделитель сообщений SignalR
DELIMITER = '\x1e'

class SIGameBot:
    """
    Класс для управления ботом: подключение к лобби, создание игры и ожидание игроков.
    """
    def __init__(self):
        self.ws = None
        self.token = None
        self.connection_url = None
        self.protocol_version = 1
        self.game_id = None
        self.player_count = 0

    async def find_best_server(self):
        """
        Определяет лучший сервер для подключения.
        Сначала пытается подключиться к прямому адресу, если не удается - ищет через API.
        """
        logger.info("🔍 [1/5] Поиск доступного сервера...")
        try:
            # Проверяем доступность прямого сервера
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                async with session.get(f"{DIRECT_SERVER}/sionline/negotiate?negotiateVersion=1") as resp:
                    if resp.status == 200:
                        logger.info(f"✅ Прямой сервер {DIRECT_SERVER} доступен.")
                        return DIRECT_SERVER
        except Exception:
            logger.warning("⚠️ Прямой сервер не ответил, ищу через API...")

        # Если прямой сервер недоступен, ищем через официальный API
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(SERVERS_API) as resp:
                    servers = await resp.json()
                    if servers:
                        server = servers[0]
                        uri = server.get('uri') or server.get('Uri')
                        self.protocol_version = server.get('protocolVersion', 1)
                        logger.info(f"✅ Найден сервер через API: {uri}")
                        return uri
        except Exception as e:
            logger.error(f"❌ Не удалось получить список серверов через API: {e}")
            return None

    async def negotiate(self, server_uri):
        """
        Получает `connectionToken` для установки WebSocket-соединения с лобби.
        """
        logger.info(f"🔑 [2/5] Получение токена (negotiate)...")
        # SignalR хаб для лобби называется 'sionline'
        negotiate_url = f"{server_uri.rstrip('/')}/sionline/negotiate"
        try:
            async with aiohttp.ClientSession() as session:
                params = {"negotiateVersion": "1"}
                headers = {"Content-Type": "application/json"}
                async with session.post(negotiate_url, params=params, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self.token = data.get("connectionToken")
                        if self.token:
                            ws_base = server_uri.replace("https://", "wss://").replace("http://", "ws://")
                            self.connection_url = f"{ws_base.rstrip('/')}/sionline?id={self.token}"
                            logger.info("✅ Токен успешно получен.")
                            return True
                    else:
                         logger.error(f"❌ Ошибка negotiate: {resp.status} - {await resp.text()}")
        except Exception as e:
            logger.error(f"❌ Критическая ошибка при negotiate: {e}")
        return False

    async def run(self):
        """
        Основной цикл работы бота.
        """
        server = await self.find_best_server()
        if not server or not await self.negotiate(server):
            logger.error("❌ Не удалось подключиться к серверу. Попробуйте перезапустить ячейку.")
            return

        logger.info(f"🔌 [3/5] Подключение к WebSocket...")
        try:
            async with websockets.connect(self.connection_url) as ws:
                self.ws = ws
                asyncio.create_task(self.pinger()) # Запускаем "пингер" для поддержки соединения

                # 1. Рукопожатие (Handshake)
                logger.info("🤝 [4/5] Рукопожатие с сервером...")
                await ws.send(json.dumps({"protocol": "json", "version": 1}) + DELIMITER)
                await ws.recv() # Сервер должен ответить пустым объектом {}

                # 2. Вход в лобби
                logger.info(f"👤 [5/5] Вход в лобби под именем {BOT_NAME}...")
                login_command = [
                    "LOGIN", str(self.protocol_version), BOT_NAME,
                    "", "0", "", "0", "", "" # Остальные параметры оставляем пустыми
                ]
                await self.send_command(*login_command)

                # 3. Цикл прослушивания сообщений
                logger.info("⏳ Ожидание ответа от сервера...")
                async for message in ws:
                    # Сообщения могут приходить "пачками", разделенными DELIMITER
                    for part in message.strip().split(DELIMITER):
                        if not part: continue
                        try:
                            msg_data = json.loads(part)
                            # Игровые сообщения приходят с типом 1 и целью 'OnMessage'
                            if msg_data.get("type") == 1 and msg_data.get("target") == "OnMessage":
                                await self.handle_server_message(msg_data["arguments"][0])
                        except json.JSONDecodeError:
                            # Игнорируем сообщения, которые не являются JSON (например, пинги)
                            pass
        except Exception as e:
            logger.error(f"💥 Произошла критическая ошибка: {e}")
            traceback.print_exc()

    async def handle_server_message(self, message_text):
        """
        Обрабатывает сообщения, полученные от игрового сервера.
        """
        args = message_text.split('\n')
        command = args[0]

        logger.info(f"📬 Получено сообщение: {command} {args[1:] if len(args) > 1 else ''}")

        if command == "LOGGEDIN":
            logger.info("✅ Успешный вход в лобби!")
            logger.info(f"🛠 Создание игры '{GAME_NAME}'...")

            # Команда для создания игры со стандартным (пустым) пакетом
            # Формат: CREATE Имя_игры Пароль URI_пакета Тип_игры ...
            create_command_args = [
                "CREATE", GAME_NAME, GAME_PASSWORD,
                "", "Classic", "0", "3", "false"
            ]
            await self.send_command(*create_command_args)

        elif command == "GAMECREATED":
            self.game_id = args[1]
            logger.info(f"🎉 ИГРА СОЗДАНА! ID: {self.game_id}")
            self.print_invite_link()

        elif command == "JOINED":
            self.player_count += 1
            logger.info(f"👍 К игре присоединился игрок! Всего игроков: {self.player_count}/2")
            if self.player_count >= 2:
                logger.info("▶️ В игре достаточно игроков. Запускаю матч!")
                await self.send_command("START")

        elif command == "DISCONNECTED":
            # Уменьшаем счетчик, если кто-то вышел до начала игры
            if self.player_count > 0:
                self.player_count -= 1
            logger.info(f"👎 Игрок отключился. Всего игроков: {self.player_count}/2")

        elif command == "NOTICE":
            # Серверные уведомления, часто содержат сообщения об ошибках
            logger.warning(f"🔔 Уведомление от сервера: {args[1]}")

    def print_invite_link(self):
        """
        Генерирует и выводит в консоль ссылку для приглашения в игру.
        """
        try:
            if self.game_id.isdigit():
                # Конвертируем ID в HEX для стандартной ссылки
                hex_id = hex(int(self.game_id))[2:]
                link = f"https://sigame.vladimirkhil.com/?_b{hex_id}"
            else:
                # Для нечисловых ID используем прямую ссылку
                link = f"https://sigame.vladimirkhil.com/?id={self.game_id}"

            print("\n" + "="*50)
            print(" " * 15 + "🎉 ИГРА ГОТОВА 🎉")
            print(" " * 8 + "Отправьте эту ссылку друзьям!")
            print(f"🔗 Ссылка: {link}")
            print(f"🔑 Пароль: {GAME_PASSWORD}")
            print(" " * 5 + "Бот автоматически начнет игру,")
            print(" " * 7 + "когда зайдут два человека.")
            print("="*50 + "\n")
        except Exception as e:
            logger.error(f"Не удалось сгенерировать ссылку: {e}")

    async def send_command(self, *args):
        """
        Отправляет команду на сервер в формате, который ожидает SIGame.
        """
        if not self.ws or self.ws.closed: return

        # Команды - это строки, разделенные символом \n
        command_text = "\n".join(map(str, args))

        message = {
            "type": 1,
            "target": "SendMessage",
            "arguments": [command_text],
            "invocationId": str(random.randint(1, 10000))
        }
        await self.ws.send(json.dumps(message) + DELIMITER)
        logger.info(f"📤 Отправлена команда: {command_text.splitlines()[0]}")

    async def pinger(self):
        """
        Каждые 15 секунд отправляет "пинг" на сервер, чтобы соединение не разрывалось.
        """
        while True:
            await asyncio.sleep(15)
            try:
                if self.ws and not self.ws.closed:
                    await self.ws.send(json.dumps({"type": 6}) + DELIMITER)
            except websockets.exceptions.ConnectionClosed:
                logger.warning("Соединение разорвано, пингер остановлен.")
                break

# --- Точка входа ---
async def main():
    """Асинхронная функция для запуска бота."""
    bot = SIGameBot()
    await bot.run()

if __name__ == "__main__":
    try:
        # Запускаем асинхронный цикл
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🤖 Бот остановлен вручную.")
