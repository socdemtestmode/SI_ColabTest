import asyncio
import logging
import requests
import json
from signalrcore.hub_connection_builder import HubConnectionBuilder
from signalrcore.protocol.messagepack_protocol import MessagePackHubProtocol
import time

class SIGameBot:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'SIGameBot/1.0'})
        self.server_api_base_uri = None
        self.sihost_connection = None
        self.game_name = f"bot-game-{int(time.time())}"
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger("SIGameBot")

    async def run(self):
        self.logger.info("Bot starting...")
        if not self.discover_server():
            return

        game_response = self.create_game()
        if not game_response:
            return

        host_uri = game_response.get('hostUri')
        game_id = game_response.get('gameId')

        if not host_uri or game_id is None:
            self.logger.error("Could not find hostUri or gameId in response.")
            return

        await self.connect_and_host_game(host_uri, game_id)

    def discover_server(self):
        self.logger.info("Discovering game server...")
        try:
            response = self.session.get("https://vladimirkhil.com/api/si/servers")
            response.raise_for_status()
            servers = response.json()
            if servers:
                self.server_api_base_uri = servers[0]['uri']
                self.logger.info(f"Server API base URI: {self.server_api_base_uri}")
                return True
        except requests.RequestException as e:
            self.logger.error(f"Server discovery failed: {e}")
        return False

    def create_game(self):
        create_game_url = f"{self.server_api_base_uri}/api/v1/games"
        self.logger.info(f"Creating game via POST to: {create_game_url}")

        # Payload meticulously crafted based on the .ts contract files
        game_request = {
            "gameSettings": {
                "networkGameName": self.game_name,
                "humanPlayerName": "Jules_Host",
                "networkGamePassword": "",
                "isPrivate": False,
                "allowViewers": True,
                "showman": {"name": "Jules_Host", "isHuman": True, "isReady": True},
                "players": [],
                "viewers": [],
                "appSettings": {
                    "gameMode": "Tv", # Classic
                    "randomSpecials": True,
                    "timeSettings": {
                        "timeForChoosingQuestion": 30, "timeForThinkingOnQuestion": 60,
                        "timeForPrintingAnswer": 0, "timeForGivingACat": 30,
                        "timeForMakingStake": 30, "timeForThinkingOnSpecial": 60,
                        "timeOfRound": 0, "timeForChoosingFinalTheme": 30,
                        "timeForFinalThinking": 60, "timeForShowmanDecisions": 60,
                        "timeForRightAnswer": 3, "timeForMediaDelay": 0,
                        "timeForBlockingButton": 2, "partialImageTime": 0, "imageTime": 0
                    }
                }
            },
            "packageInfo": {
                "type": 1, # LibraryItem
                "uri": "@{random}",
                "contentServiceUri": None, "secret": None, "source": None
            },
            "computerAccounts": []
        }

        try:
            response = self.session.post(create_game_url, json=game_request)
            response.raise_for_status()
            game_data = response.json()
            self.logger.info(f"Game created successfully! Response: {game_data}")
            return game_data
        except requests.RequestException as e:
            self.logger.error(f"Game creation failed: {e}")
            if e.response: self.logger.error(f"Response: {e.response.status_code}, {e.response.text}")
        return None

    async def connect_and_host_game(self, host_uri, game_id):
        negotiate_url = f"{host_uri}/sihost/negotiate?negotiateVersion=1"
        self.logger.info(f"Negotiating with sihost: {negotiate_url}")
        try:
            response = self.session.post(negotiate_url)
            response.raise_for_status()
            connection_id = response.json().get('connectionId')
            if not connection_id:
                self.logger.error("Could not get connectionId from sihost.")
                return

            self.logger.info(f"SIHost negotiation successful. ID: {connection_id}")
            ws_url = f"{host_uri.replace('https', 'wss')}/sihost?id={connection_id}"

            self.sihost_connection = HubConnectionBuilder().with_url(ws_url, {"cookies": self.session.cookies}).with_hub_protocol(MessagePackHubProtocol()).build()
            self.sihost_connection.on("Receive", lambda msg: self.logger.info(f"<-- RECV: {msg}"))
            self.sihost_connection.on_error(lambda err: self.logger.error(f"ERROR: {err}"))

            self.sihost_connection.start()
            await asyncio.sleep(2)

            self.logger.info("--> SEND: Init")
            await self.sihost_connection.send("Init", [])
            await asyncio.sleep(1)

            self.logger.info(f"--> SEND: JoinGame as Showman")
            await self.sihost_connection.send("JoinGame", [{"GameId": game_id, "Role": "Showman", "UserName": "Jules_Host"}])
            await asyncio.sleep(5)

            self.logger.info("--> SEND: START message")
            await self.sihost_connection.send("SendMessage", [{"Text": "START"}])

            self.logger.info("Game started. Logging all events.")
            await asyncio.Event().wait()
        except Exception as e:
            self.logger.error(f"SIHost connection/hosting error: {e}", exc_info=True)
        finally:
            if self.sihost_connection: self.sihost_connection.stop()

if __name__ == "__main__":
    try:
        asyncio.run(SIGameBot().run())
    except KeyboardInterrupt:
        print("\nBot stopped.")
