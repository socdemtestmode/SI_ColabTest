import asyncio
import logging
from playwright.async_api import async_playwright
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("SpyClient")

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        log_file = open("network_log_final.txt", "w")

        def log_network_event(event_type, data):
            log_file.write(f"[{event_type}] {data}\n")
            log_file.flush()
            logger.info(f"[{event_type}] {data}")

        # Enhanced request logging to include POST data
        def log_request(request):
            post_data = request.post_data or ""
            log_network_event("REQUEST", f"{request.method} {request.url} BODY: {post_data}")

        page.on("request", log_request)
        page.on("response", lambda response: log_network_event("RESPONSE", f"{response.status} {response.url}"))

        page.on("websocket", lambda ws: {
            log_network_event("WEBSOCKET_CREATED", f"URL: {ws.url}"),
            ws.on("framereceived", lambda payload: log_network_event("WS_RECV", f"{payload}")),
            ws.on("framesent", lambda payload: log_network_event("WS_SENT", f"{payload}")),
            ws.on("close", lambda: log_network_event("WEBSOCKET_CLOSED", f"URL: {ws.url}"))
        })

        try:
            logger.info("Navigating...")
            await page.goto("https://sigame.vladimirkhil.com/", wait_until="networkidle")

            cookie_button_selector = "button:has-text('Accept cookies')"
            if await page.is_visible(cookie_button_selector):
                await page.click(cookie_button_selector)

            await page.fill('input.login_name', "spy_bot")
            await page.click('button.enter:has-text("Sign in")')

            await page.wait_for_selector('.newGame', timeout=20000)
            logger.info("Logged in. Clicking 'New Game'...")
            await page.click('.newGame')

            await page.wait_for_selector('.gameName', timeout=10000)
            game_name = f"spy-game-{int(time.time())}"
            await page.fill('.gameName', game_name)

            await page.click('.packageButton')
            await page.wait_for_selector('.randomPackage', timeout=10000)
            await page.click('.randomPackage')

            logger.info("Finalizing game creation...")
            # This is the click that should trigger the POST request we need
            await page.click('input[type="button"][value="Создать"]')

            await page.wait_for_selector('.gameHostView', timeout=20000)
            logger.info("Game created. Monitoring for 10 seconds.")
            await asyncio.sleep(10)

            logger.info("Spy session finished successfully.")

        except Exception as e:
            logger.error(f"Spy session error: {e}", exc_info=True)
        finally:
            await browser.close()
            log_file.close()
            logger.info("Browser closed, log saved.")

if __name__ == "__main__":
    asyncio.run(main())
