import sys
import subprocess
import asyncio
import json
import logging
import random
import traceback
import aiohttp
import websockets

# --- Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
    stream=sys.stdout,
    force=True
)
logger = logging.getLogger("SI_BOT")

SERVERS_API = "https://vladimirkhil.com/api/si/servers"
PACKAGE_API = "https://vladimirkhil.com/sistorage/api/v1/packages/random"
FALLBACK_URI = "https://vladimirkhil.com/sigameserver-0"
BOT_NAME = f"PyBot_{random.randint(1000, 9999)}"
GAME_NAME = f"testpygame_{random.randint(1, 111):02d}"
GAME_PASSWORD = "0101"
DELIMITER = '\x1e'

class SIGameBot:
    def __init__(self):
        self.ws = None
        self.conn_url = None
        self.token = None
        self.protocol_ver = 1
        self.package_uri = ""

    async def get_random_package(self):
        logger.info("📦 [1/7] Getting random package...")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(PACKAGE_API, timeout=8) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self.package_uri = data.get('directUri') or data.get('uri')
                        logger.info(f"✅ Package found: {data.get('name', 'Unknown')}")
                        return
        except Exception as e:
            logger.warning(f"⚠️ Package error: {e}")
        logger.info("⚠️ Package not received. Using standard themes.")

    async def find_server_and_negotiate(self):
        logger.info("🔍 [2/7] Finding server...")
        candidates = []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(SERVERS_API, timeout=5) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for srv in data:
                            uri = srv.get('proxyUri') or srv.get('uri') or srv.get('Uri')
                            if uri and "content" not in uri:
                                candidates.append((uri, srv.get('protocolVersion', 1)))
        except: pass
        candidates.append((FALLBACK_URI, 1))

        logger.info(f"🕵️ [3/7] Probing {len(candidates)} servers...")
        paths = ["/api/v1/sionline", "/sionline", "/sihub"]
        async with aiohttp.ClientSession() as session:
            for base_uri, ver in candidates:
                for path in paths:
                    negotiate_url = f"{base_uri.rstrip('/')}{path}/negotiate"
                    try:
                        async with session.post(negotiate_url, params={"negotiateVersion": "1"}, headers={"Content-Type": "application/json"}, timeout=3) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                token = data.get("connectionToken") or data.get("connectionId")
                                if token:
                                    logger.info(f"✅ Server found: {base_uri.rstrip('/')}")
                                    self.token = token
                                    self.protocol_ver = ver if ver > 1 else 17
                                    ws_host = base_uri.replace("https://", "wss://").replace("http://", "ws://")
                                    self.conn_url = f"{ws_host.rstrip('/')}{path}?id={token}"
                                    return True
                    except: continue
        return False

    async def run(self):
        await self.get_random_package()
        if not await self.find_server_and_negotiate():
            logger.error("❌ Could not connect to any server.")
            return

        logger.info(f"🔌 [4/7] WebSocket: {self.conn_url}")
        try:
            async with websockets.connect(self.conn_url) as ws:
                self.ws = ws
                asyncio.create_task(self.ping_loop())

                logger.info("🤝 [5/7] Handshake...")
                await ws.send(json.dumps({"protocol": "json", "version": 1}) + DELIMITER)
                await ws.recv()

                login_args = ["LOGIN", str(self.protocol_ver), BOT_NAME, "", "0", "", "0", "", ""]
                login_cmd = "\n".join(login_args)

                logger.info(f"📤 [6/7] Sending LOGIN (protocol ver. {self.protocol_ver})...")
                await self.send_command(login_cmd)

                logger.info("⏳ [7/7] Waiting for server response...")
                async for raw in ws:
                    for part in raw.split(DELIMITER):
                        if not part: continue
                        try:
                            await self.handle_signalr(json.loads(part))
                        except json.JSONDecodeError: pass
        except Exception as e:
            logger.error(f"❌ Error: {e}")
            traceback.print_exc()

    async def handle_signalr(self, data):
        if data.get("type") == 6:
            await self.ws.send(json.dumps({"type": 6}) + DELIMITER)
            return
        if data.get("type") == 1 and data.get("target") == "OnMessage":
            await self.process_si_message(data["arguments"][0])

    async def process_si_message(self, text):
        args = text.split('\n')
        cmd = args[0]

        if cmd == "LOGGEDIN":
            logger.info("🎉 LOGIN SUCCESSFUL!")
            pkg = self.package_uri or ""
            create_args = ["CREATE", GAME_NAME, GAME_PASSWORD, pkg, "Classic", "0", "3", "false"]
            await self.send_command("\n".join(create_args))
        elif cmd == "GAMECREATED":
            logger.info(f"🚀 GAME CREATED! Name: {GAME_NAME}, Password: {GAME_PASSWORD}")
            logger.info("🤖 Adding computer player...")
            await self.send_command("ADDCOMPUTER\n0")
            logger.info("▶️ Starting game...")
            await self.send_command("START")
        elif cmd in ["NOTICE", "BANNED"]: logger.info(f"📢 {cmd}: {args[1]}")
        elif cmd == "STAGE": logger.info(f"🎬 STAGE: {args[1]} {args[2] if len(args)>2 else ''}")
        elif cmd == "ROUNDTHEMES": logger.info(f"📚 THEMES: {', '.join(args[1:])}")
        elif cmd == "QTYPE": logger.info(f"❓ QTYPE: {args[1]}")
        elif cmd == "QUESTION": logger.info(f"💰 PRICE: {args[1]}")
        elif cmd == "ATOM": logger.info(f"📜 QUESTION ({args[1]}): {args[2] if len(args)>2 else '[No text]'}")
        elif cmd == "RIGHTANSWER": logger.info(f"✅ CORRECT ANSWER: {args[2] if len(args)>2 else args[1]}")
        elif cmd == "PERSON": logger.info(f"👤 Player {args[2]}: {'PLUS' if args[1] == '+' else 'MINUS'} {args[3]}")
        elif cmd == "WINNER": logger.info(f"🏆 WINNER INDEX: {args[1]}")

    async def send_command(self, si_command_text):
        if not self.ws: return
        msg = {"type": 1, "target": "SendMessage", "arguments": [si_command_text]}
        await self.ws.send(json.dumps(msg) + DELIMITER)

    async def ping_loop(self):
        while self.ws:
            try:
                await asyncio.sleep(5)
                await self.ws.send(json.dumps({"type": 6}) + DELIMITER)
            except: break

if __name__ == "__main__":
    try:
        asyncio.run(SIGameBot().run())
    except KeyboardInterrupt:
        print("\nBot stopped.")
