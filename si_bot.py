# @title 🚀 Запуск SIGame бота
# @markdown Нажмите ▶️, чтобы запустить бота. Он создаст игру и выведет ссылку-приглашение.

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
    """Проверяет и обновляет необходимые библиотеки."""
    try:
        import aiohttp
        import websockets
    except ImportError:
        print("📥 Установка aiohttp и websockets...")
        # Обновляем до последней версии, чтобы избежать проблем совместимости
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "aiohttp", "websockets"])
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
SERVERS_API = "https://vladimirkhil.com/api/si/servers"
DIRECT_SERVER = "https://vladimirkhil.com/sigameserver-0"

BOT_NAME = f"ColabBot_{random.randint(1000, 9999)}"
GAME_NAME = f"testcolabgame{random.randint(1, 99):03}"
GAME_PASSWORD = "1212"

DELIMITER = '\x1e'

class SIGameBot:
    """
    Класс для управления ботом: подключение, создание игры и автостарт.
    """
    def __init__(self):
        self.ws = None
        self.token = None
        self.connection_url = None
        self.protocol_version = 1
        self.game_id = None
        self.player_count = 0

    async def find_best_server(self):
        """Определяет лучший сервер для подключения."""
        logger.info("🔍 [1/4] Поиск сервера...")
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                async with session.get(f"{DIRECT_SERVER}/sionline/negotiate?negotiateVersion=1") as resp:
                    if resp.status == 200:
                        logger.info(f"✅ Прямой сервер {DIRECT_SERVER} доступен.")
                        return DIRECT_SERVER
        except Exception:
            logger.warning("⚠️ Прямой сервер не ответил, ищу через API...")

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
            logger.error(f"❌ Не удалось получить список серверов: {e}")
            return None

    async def negotiate(self, server_uri):
        """Получает токен для WebSocket-соединения."""
        logger.info(f"🔑 [2/4] Получение токена...")
        negotiate_url = f"{server_uri.rstrip('/')}/sionline/negotiate"
        try:
            async with aiohttp.ClientSession() as session:
                params = {"negotiateVersion": "1"}
                async with session.post(negotiate_url, params=params) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    self.token = data.get("connectionToken")
                    if self.token:
                        ws_base = server_uri.replace("https://", "wss://").replace("http://", "ws://")
                        self.connection_url = f"{ws_base.rstrip('/')}/sionline?id={self.token}"
                        logger.info("✅ Токен успешно получен.")
                        return True
        except Exception as e:
            logger.error(f"❌ Ошибка при negotiate: {e}")
        return False

    async def run(self):
        """Основной цикл работы бота."""
        server = await self.find_best_server()
        if not server or not await self.negotiate(server):
            logger.error("❌ Не удалось подключиться. Попробуйте перезапустить ячейку.")
            return

        logger.info(f"🔌 [3/4] Подключение к WebSocket...")
        try:
            async with websockets.connect(self.connection_url) as ws:
                self.ws = ws
                asyncio.create_task(self.pinger())

                logger.info("🤝 [4/4] Рукопожатие с сервером...")
                await ws.send(json.dumps({"protocol": "json", "version": 1}) + DELIMITER)
                await ws.recv()

                # Вместо текстового LOGIN, сервер ожидает вызов метода CreateAndJoinGameNew,
                # но перед этим нужно войти, чтобы сервер нас "узнал".
                # Для этого используется текстовый LOGIN.
                login_command = [ "LOGIN", str(self.protocol_version), BOT_NAME, "", "0", "", "0", "", "" ]
                await self.send_text_message(*login_command)
                logger.info(f"👤 Вход в лобби под именем {BOT_NAME}...")

                async for message in ws:
                    for part in message.strip().split(DELIMITER):
                        if not part: continue
                        try:
                            msg_data = json.loads(part)
                            if msg_data.get("type") == 1: # Это вызов от сервера
                                target = msg_data.get("target")
                                if target == "OnMessage": # Текстовые сообщения лобби
                                    await self.handle_lobby_message(msg_data["arguments"][0])
                                elif target == "Receive": # Внутриигровые сообщения
                                    await self.handle_game_message(msg_data["arguments"][0])
                        except json.JSONDecodeError:
                            pass # Игнорируем не-JSON сообщения
        except Exception as e:
            logger.error(f"💥 Критическая ошибка: {e}")
            traceback.print_exc()

    async def handle_lobby_message(self, text):
        """Обрабатывает текстовые сообщения из лобби."""
        args = text.split('\n')
        command = args[0]

        if command == "LOGGEDIN":
            logger.info("✅ Успешный вход в лобби!")
            logger.info(f"🛠 Создание игры '{GAME_NAME}'...")

            game_settings = {
                "Name": GAME_NAME, "Password": GAME_PASSWORD,
                "Role": "host", "PlayerCount": 3, "GameMode": "Classic",
            }

            await self.invoke_hub_method("CreateAndJoinGameNew", game_settings, "", [], True)

    async def handle_game_message(self, text):
        """Обрабатывает внутриигровые сообщения."""
        args = text.split('\n')
        command = args[0]

        logger.info(f"🎮 Внутриигровое сообщение: {command}")

        if command == "INFO2":
            # GameID находится в 4-м аргументе (индекс 3)
            self.game_id = args[3]
            logger.info(f"ℹ️ Получена информация об игре. ID: {self.game_id}")
            self.print_invite_link()

        elif command == "CONNECTED":
            # Параметры: role, index, name
            if args[1] == "player":
                self.player_count += 1
                logger.info(f"👍 К игре присоединился игрок! Всего игроков: {self.player_count}/2")
                if self.player_count >= 2:
                    logger.info("▶️ В игре достаточно игроков. Запускаю матч!")
                    await self.send_text_message("START")

    def print_invite_link(self):
        """Генерирует и выводит ссылку-приглашение."""
        if not self.game_id: return
        try:
            link = f"https://sigame.vladimirkhil.com/?id={self.game_id}"
            if self.game_id.isdigit():
                link = f"https://sigame.vladimirkhil.com/?_b{hex(int(self.game_id))[2:]}"

            print("\n" + "="*50)
            print(" " * 15 + "🎉 ИГРА ГОТОВА 🎉")
            print(f"🔗 Ссылка: {link}")
            print(f"🔑 Пароль: {GAME_PASSWORD}")
            print(" " * 5 + "Бот начнет игру, когда зайдут 2 человека.")
            print("="*50 + "\n")
        except Exception as e:
            logger.error(f"Не удалось сгенерировать ссылку: {e}")

    async def invoke_hub_method(self, target, *args):
        """Вызывает метод хаба SignalR."""
        if not self.ws: return
        message = {"type": 1, "target": target, "arguments": list(args), "invocationId": str(random.randint(1, 10000))}
        await self.ws.send(json.dumps(message) + DELIMITER)
        logger.info(f"📤 Вызван метод: {target}")

    async def send_text_message(self, *args):
        """Отправляет текстовое сообщение (в лобби или в игре)."""
        await self.invoke_hub_method("SendMessage", "\n".join(map(str, args)))

    async def pinger(self):
        """Поддерживает WebSocket-соединение активным."""
        while True:
            await asyncio.sleep(15)
            try:
                await self.ws.send(json.dumps({"type": 6}) + DELIMITER)
            except Exception:
                logger.warning("Соединение разорвано.")
                break

# --- Точка входа ---
async def main():
    bot = SIGameBot()
    await bot.run()

if __name__ == "__main__":
    try:
        install_libs()
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🤖 Бот остановлен.")
