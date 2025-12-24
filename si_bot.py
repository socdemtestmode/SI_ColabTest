
import asyncio
import aiohttp
import websockets
import json
import random
import sys
import subprocess
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def install_libs():
    """Installs required libraries if they are not already installed."""
    try:
        import aiohttp
        import websockets
    except ImportError:
        logging.info("Installing required libraries...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "aiohttp", "websockets"])
        logging.info("Libraries installed successfully.")

async def discover_server():
    """Discovers an available SIGame server."""
    url = "https://vladimirkhil.com/api/si/servers"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url) as response:
                response.raise_for_status()
                servers = await response.json()
                if servers:
                    server_address = servers[0]['uri']
                    logging.info(f"Found server: {server_address}")
                    return server_address
                else:
                    logging.error("No servers found.")
                    return None
        except aiohttp.ClientError as e:
            logging.error(f"Error discovering server: {e}")
            return None

async def connect_to_sionline(server_address):
    """Connects to the sionline hub and returns the WebSocket connection."""
    negotiate_url = f"{server_address}/sionline/negotiate?negotiateVersion=1"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36",
        "Origin": "https://sigame.vladimirkhil.com",
        "Referer": "https://sigame.vladimirkhil.com/",
        "X-SIGame-Client-Version": "8.1.0"
    }
    async with aiohttp.ClientSession(headers=headers) as session:
        try:
            async with session.post(negotiate_url) as response:
                response.raise_for_status()
                neg_res = await response.json()
                token = neg_res['connectionToken']
                ws_url = f"{server_address.replace('https', 'wss')}/sionline?token={token}"

                logging.info(f"Connecting to sionline: {ws_url}")
                websocket = await websockets.connect(ws_url)

                # SignalR handshake
                await websocket.send(json.dumps({"protocol": "json", "version": 1}) + '\x1e')
                await websocket.recv()
                logging.info("WebSocket connection to sionline established.")
                return websocket
        except aiohttp.ClientError as e:
            logging.error(f"Error connecting to sionline: {e}")
            return None

async def connect_to_sihost(host_uri):
    """Connects to the sihost hub and returns the WebSocket connection."""
    negotiate_url = f"{host_uri}/sihost/negotiate?negotiateVersion=1"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36",
        "Origin": "https://sigame.vladimirkhil.com",
        "Referer": "https://sigame.vladimirkhil.com/",
    }
    async with aiohttp.ClientSession(headers=headers) as session:
        try:
            async with session.post(negotiate_url) as response:
                response.raise_for_status()
                neg_res = await response.json()
                token = neg_res['connectionToken']
                ws_url = f"{host_uri.replace('https', 'wss')}/sihost?id={token}"

                logging.info(f"Connecting to sihost: {ws_url}")
                websocket = await websockets.connect(ws_url)

                # SignalR handshake
                await websocket.send(json.dumps({"protocol": "json", "version": 1}) + '\x1e')
                await websocket.recv()
                logging.info("WebSocket connection to sihost established.")
                return websocket
        except aiohttp.ClientError as e:
            logging.error(f"Error connecting to sihost: {e}")
            return None

async def send_signalr_message(websocket, target, arguments, invocation_id):
    """Sends a SignalR invocation message."""
    message = {
        "type": 1,
        "invocationId": str(invocation_id),
        "target": target,
        "arguments": arguments
    }
    await websocket.send(json.dumps(message) + '\x1e')

async def receive_signalr_message(websocket, invocation_id):
    """Receives a SignalR message and matches it to the invocationId."""
    while True:
        try:
            message = await websocket.recv()
            messages = message.split('\x1e')
            for msg in messages:
                if msg:
                    data = json.loads(msg)
                    if data.get("invocationId") == str(invocation_id):
                        return data
        except websockets.exceptions.ConnectionClosed:
            logging.error("Connection closed.")
            return None

async def create_game(websocket, invocation_id):
    """Creates a new game room."""
    game_name = f"testcolabgame_{random.randint(1000, 9999)}"
    password = "1212"

    game_settings = {
        "GameName": game_name,
        "Password": password,
        "PackageName": "Standard empty package",
        "Showman": {"Name": "BotHost"},
        "Players": [],
        "Viewers": []
    }

    package_key = {
        "Type": "LibraryItem",
        "Name": "Standard empty package",
        "Uri": "https://vladimirkhil.com/sistorage/packages/d8faa1a4-2a6f-4103-b298-fd15c6ee3ea6.siq"
    }

    logging.info(f"Creating game '{game_name}'...")
    await send_signalr_message(websocket, "CreateAndJoinGameNew", [game_settings, package_key, [], True], invocation_id)
    response = await receive_signalr_message(websocket, invocation_id)
    logging.info(f"Game creation response: {response}")
    return response

async def join_game(websocket, game_id, password, invocation_id):
    """Joins the game as the host."""
    logging.info(f"Joining game {game_id}...")
    await send_signalr_message(websocket, "JoinGameNew", [game_id, "Host", True, password], invocation_id)
    response = await receive_signalr_message(websocket, invocation_id)
    logging.info(f"Join game response: {response}")

async def listen_for_players(websocket):
    """Listens for players joining the lobby."""
    while True:
        try:
            message = await websocket.recv()
            messages = message.split('\x1e')
            for msg in messages:
                if msg:
                    data = json.loads(msg)
                    if data.get("target") == "GamePersonsChanged":
                        persons = data["arguments"][1]
                        logging.info(f"Players in lobby: {persons}")
                        # Check if two players have joined
                        if len([p for p in persons if p.get("role") == "Player"]) >= 2:
                            return
        except websockets.exceptions.ConnectionClosed:
            logging.error("Connection to sihost closed.")
            break

async def start_game(websocket, invocation_id):
    """Starts the game."""
    logging.info("Starting game...")
    await send_signalr_message(websocket, "SendMessage", ["START"], invocation_id)

async def log_game_events(websocket):
    """Logs all game events."""
    while True:
        try:
            message = await websocket.recv()
            messages = message.split('\x1e')
            for msg in messages:
                if msg:
                    logging.info(f"Game event: {msg}")
        except websockets.exceptions.ConnectionClosed:
            logging.error("Connection to sihost closed.")
            break

async def main():
    install_libs()
    server_address = await discover_server()
    if not server_address:
        return

    sionline_ws = None
    sihost_ws = None
    try:
        sionline_ws = await connect_to_sionline(server_address)
        if not sionline_ws:
            return

        invocation_id = 1
        game_creation_response = await create_game(sionline_ws, invocation_id)

        if not (game_creation_response and game_creation_response.get("result", {}).get("isSuccess")):
            logging.error(f"Game creation failed: {game_creation_response.get('result', {}).get('errorMessage')}")
            return

        host_uri = game_creation_response["result"]["hostUri"]
        game_id = game_creation_response["result"]["gameId"]
        password = "1212"
        logging.info(f"Connecting to game host: {host_uri}")
        sihost_ws = await connect_to_sihost(host_uri)
        if not sihost_ws:
            return

        invocation_id += 1
        await join_game(sihost_ws, game_id, password, invocation_id)
        await listen_for_players(sihost_ws)
        invocation_id += 1
        await start_game(sihost_ws, invocation_id)
        await log_game_events(sihost_ws)

    finally:
        if sionline_ws:
            await sionline_ws.close()
        if sihost_ws:
            await sihost_ws.close()

if __name__ == "__main__":
    asyncio.run(main())
