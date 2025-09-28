"""
Manages a minimal and robust connection to an existing browser via CDP.
Inspiration from example_cdp_connector.py
"""
import requests
from playwright.async_api import async_playwright, Browser, Page, Playwright
from typing import Optional
import logging

logger = logging.getLogger("dev_utils.connection")

class CDPConnection:
    """Manages a connection to an existing browser instance."""

    def __init__(self, cdp_port: int):
        self.cdp_port = cdp_port
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.client = None

    async def connect(self) -> bool:
        """
        Connects to an existing browser instance after verifying it's accessible.
        Returns True on success, False on failure.
        """
        # 1. Pre-Connection Check (inspired by example)
        try:
            response = requests.get(f"http://localhost:{self.cdp_port}/json/version")
            if response.status_code != 200:
                logger.error(f"Browser on port {self.cdp_port} is not accessible. (HTTP Status: {response.status_code})")
                logger.error("Please ensure a browser is running with --remote-debugging-port=<port>")
                return False
            browser_info = response.json().get('Browser', 'Unknown Version')
            logger.info(f"Successfully located browser: {browser_info}")
        except requests.ConnectionError:
            logger.error(f"[Connection] Connection refused on port {self.cdp_port}.")
            logger.error("[Tip] Is the launcher.py script running? Or did you start a browser manually with the --remote-debugging-port flag?")
            return False
        except Exception as e:
            logger.error(f"[Connection] An unexpected error occurred during the pre-connection HTTP check: {e}")
            logger.error("[Tip] This could be a network issue or a problem with the browser's debugging service.")
            return False

        # 2. Connect using Playwright
        try:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.connect_over_cdp(
                f"http://localhost:{self.cdp_port}"
            )
            
            # Find a suitable page to use
            if self.browser.contexts and self.browser.contexts[0].pages:
                self.page = self.browser.contexts[0].pages[0]
            else: # If no pages exist, create one
                self.page = await self.browser.contexts[0].new_page()

            self.client = await self.page.context.new_cdp_session(self.page)
            return True
        except Exception as e:
            logger.error(f"[Connection] Playwright failed to establish the CDP connection: {e}")
            logger.error("[Tip] This can happen if the browser is closing or if there's a version mismatch between Playwright and the browser.")
            await self.disconnect()
            return False

    async def disconnect(self):
        """Stops the Playwright instance gracefully."""
        if self.playwright:
            await self.playwright.stop()
            logger.info("Playwright connection stopped.")
