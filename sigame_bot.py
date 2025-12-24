import sys
import subprocess
import asyncio
import json
import logging
import random
import traceback
import aiohttp
import websockets

# --- 1. SETTINGS ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
    stream=sys.stdout,
    force=True
)
logger = logging.getLogger("SIGameBot")

# --- 2. BOT IMPLEMENTATION ---
class SIGameBot:
    """
    A bot for creating and managing SIGame rooms automatically.
    """
    DELIMITER = '\x1e'

    def __init__(self):
        self.ws = None
        self.token = None
        self.connection_url = None
        self.server_url = None
        self.game_id = None
        self.bot_name = f"Bot_{random.randint(100, 999)}"
        self.players = set()
        self.game_started = False

    def install_libs(self):
        """Checks for and installs required libraries."""
        try:
            import aiohttp
            import websockets
        except ImportError:
            logger.info("📥 Installing required libraries...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", "aiohttp", "websockets"])
            logger.info("✅ Libraries installed.")

    async def find_server(self):
        """Finds a V1 protocol server to connect to."""
        url = "https://vladimirkhil.com/api/si/servers"
        logger.info("🔍 [1/5] Finding a game server...")
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        servers = await resp.json()
                        for server in servers:
                            if server.get("protocolVersion") == 1:
                                self.server_url = server.get("uri")
                                logger.info(f"✅ Server found: {self.server_url}")
                                return True
                        logger.error("❌ No server with protocol version 1 found.")
                    else:
                        logger.error(f"❌ Failed to get server list: {resp.status}")
            except Exception as e:
                logger.error(f"❌ HTTP Error while finding server: {e}")
        return False

    async def negotiate(self):
        """Gets a SignalR connection token."""
        negotiate_url = f"{self.server_url}/sionline/negotiate"
        logger.info(f"🔑 [2/5] Negotiating connection: {negotiate_url}")
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(negotiate_url, params={"negotiateVersion": "1"}) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self.token = data.get("connectionToken")
                        if self.token:
                            ws_base = self.server_url.replace("https://", "wss://").replace("http://", "ws://")
                            self.connection_url = f"{ws_base}/sionline?id={self.token}"
                            logger.info("✅ Connection token received.")
                            return True
                        else:
                            logger.error(f"❌ Connection token not found in negotiate response: {data}")
                    else:
                        logger.error(f"❌ Negotiate failed with status: {resp.status}")
                        logger.error(f"Response: {await resp.text()}")
            except Exception as e:
                logger.error(f"❌ HTTP Error during negotiation: {e}")
        return False

    async def pinger(self):
        """Sends a ping every 5 seconds to keep the connection alive."""
        while self.ws and self.ws.open:
            try:
                await self.ws.send(json.dumps({"type": 6}) + self.DELIMITER)
                await asyncio.sleep(5)
            except websockets.exceptions.ConnectionClosed:
                logger.warning("Connection closed. Pinger stopping.")
                break

    async def send_si_command(self, command_text):
        """Sends a text-based command using the SIGame protocol via SendMessage."""
        if not self.ws or not self.ws.open:
            logger.warning("Cannot send command, WebSocket is not connected.")
            return

        invocation_id = str(random.randint(1000, 9999))
        command_req = {
            "type": 1,
            "target": "SendMessage",
            "arguments": [command_text],
            "invocationId": invocation_id
        }
        await self.ws.send(json.dumps(command_req) + self.DELIMITER)

    async def create_game(self):
        """Constructs and sends the game creation request."""
        game_name = f"testcolabgame_{random.randint(1, 999):03d}"
        logger.info(f"📝 [5/5] Creating game '{game_name}'...")

        game_settings = {
            "Name": game_name,
            "Password": "1212",
            "PlayerCount": 3,
            "Showman": self.bot_name,
            "GameMode": "Classic"
        }

        package_key = ""
        invocation_id = str(random.randint(1000, 9999))
        create_game_req = {
            "type": 1,
            "target": "CreateAndJoinGameNew",
            "arguments": [game_settings, package_key, [], True],
            "invocationId": invocation_id
        }
        await self.ws.send(json.dumps(create_game_req) + self.DELIMITER)
        logger.info("✉️ Game creation request sent.")

    async def handle_si_message(self, text_message):
        """Parses and reacts to internal SIGame protocol messages."""
        args = text_message.split('\n')
        command = args[0]

        if command == "CONNECTED":
            role, _, name, _ = args[1:]
            # We only care about players joining
            if role == "player":
                if name not in self.players:
                    self.players.add(name)
                    logger.info(f"👤 Player '{name}' has joined. Total players: {len(self.players)}/2")

                    # Check if it's time to start the game
                    if len(self.players) >= 2 and not self.game_started:
                        self.game_started = True
                        logger.info("🏁 Reached 2 players! Starting game...")
                        await self.send_si_command("START")

        elif command == "DISCONNECTED":
            name = args[1]
            if name in self.players:
                self.players.remove(name)
                logger.info(f"👋 Player '{name}' has left. Total players: {len(self.players)}/2")

        elif command == "STAGE":
            stage_name = args[1]
            logger.info(f"🎬 Game stage changed to: {stage_name}")


    async def message_loop(self):
        """Handles all incoming messages from the server."""
        logger.info("🎧 Listening for server messages...")
        async for raw_message in self.ws:
            messages = raw_message.strip(self.DELIMITER).split(self.DELIMITER)
            for message in messages:
                if not message:
                    continue
                try:
                    msg_data = json.loads(message)

                    # Type 1: Server-to-client invocation
                    if msg_data.get("type") == 1:
                        target = msg_data.get("target")
                        if target == "GameCreated":
                            self.game_id = msg_data['arguments'][0]['ID']
                            logger.info(f"🎉 Game created successfully! Game ID: {self.game_id}")
                            print("\n" + "="*40)
                            print(f"🔗 Game Link: https://sigame.vladimirkhil.com/?id={self.game_id}")
                            print("🔑 Password: 1212")
                            print("="*40 + "\n")

                        elif target == "Receive": # This is a SIGame protocol message
                            await self.handle_si_message(msg_data['arguments'][0])

                    # Type 3: Result of our invocation (e.g., result of CreateGame)
                    elif msg_data.get("type") == 3:
                        if "error" in msg_data:
                            logger.error(f"❌ Server returned an error for invocation {msg_data.get('invocationId')}: {msg_data['error']}")
                        else:
                            logger.info(f"✅ Invocation {msg_data.get('invocationId')} completed successfully.")


                except json.JSONDecodeError:
                    logger.warning(f"Could not decode JSON: {message}")
                except Exception as e:
                    logger.error(f"Error processing message: {e}\n{traceback.format_exc()}")

    async def run(self):
        """Main execution loop for the bot."""
        self.install_libs()
        if not await self.find_server():
            return
        if not await self.negotiate():
            return

        logger.info(f"🔌 [3/5] Connecting to WebSocket: {self.connection_url}")
        try:
            async with websockets.connect(self.connection_url) as ws:
                self.ws = ws

                logger.info("🤝 [4/5] Sending handshake...")
                await ws.send(json.dumps({"protocol": "json", "version": 1}) + self.DELIMITER)
                await ws.recv()
                logger.info("✅ Handshake complete.")

                asyncio.create_task(self.pinger())
                await self.create_game()
                await self.message_loop()

        except Exception as e:
            logger.error(f"💥 Critical WebSocket error: {e}")
            traceback.print_exc()

# --- 3. SCRIPT EXECUTION ---
if __name__ == "__main__":
    bot = SIGameBot()
    try:
        if asyncio.get_event_loop().is_running():
            asyncio.create_task(bot.run())
        else:
            asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("🤖 Bot manually stopped.")
