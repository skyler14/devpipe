"""
WebRTC Privacy Module - Simple one-liner to configure Brave WebRTC IP handling policy.
Usage: await configure_webrtc_privacy(page)
"""
import asyncio
import logging
from playwright.async_api import Page, Error as PWError, TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger("dev_utils.webrtcprivacy")

SETTINGS_URL_SEARCH = "brave://settings/?search=webrtc"
WEBRTC_POLICY_TEXT_LABEL = "WebRTC IP handling policy"
TARGET_OPTION_VALUE = "disable_non_proxied_udp"


async def configure_webrtc_privacy(page: Page, restore_url: bool = True) -> bool:
    """
    Configure Brave browser to use 'disable_non_proxied_udp' for WebRTC IP handling.
    This prevents WebRTC from leaking your real IP when using a proxy.
    
    Args:
        page: Playwright Page object (must be Brave browser)
        restore_url: Whether to navigate back to original URL after configuration (default: True)
    
    Returns:
        bool: True if successfully configured or already set, False on failure
    
    Example:
        await configure_webrtc_privacy(page)
    """
    original_url = page.url
    
    try:
        logger.info("Configuring Brave WebRTC IP handling policy...")
        
        # Navigate to settings
        await page.goto(SETTINGS_URL_SEARCH, timeout=30_000, wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle", timeout=20_000)
        await asyncio.sleep(1.5)
        
        # Find the dropdown
        settings_box = page.locator(f'div.settings-box:has-text("{WEBRTC_POLICY_TEXT_LABEL}")')
        await settings_box.wait_for(state="visible", timeout=15_000)
        
        dropdown = settings_box.locator('settings-dropdown-menu').locator('select#dropdownMenu')
        await dropdown.wait_for(state="visible", timeout=7_000)
        
        if not await dropdown.is_enabled():
            logger.error("WebRTC dropdown found but not enabled")
            return False
        
        # Check current value
        current_value = await dropdown.evaluate("el => el.value")
        logger.info(f"Current WebRTC policy: {current_value}")
        
        if current_value == TARGET_OPTION_VALUE:
            logger.info(f"Already set to '{TARGET_OPTION_VALUE}'")
            return True
        
        # Set new value
        await dropdown.select_option(TARGET_OPTION_VALUE, timeout=10_000)
        await asyncio.sleep(0.75)
        
        # Verify
        new_value = await dropdown.evaluate("el => el.value")
        if new_value == TARGET_OPTION_VALUE:
            logger.info(f"Successfully set to '{TARGET_OPTION_VALUE}'")
            return True
        else:
            logger.error(f"Verification failed: expected '{TARGET_OPTION_VALUE}', got '{new_value}'")
            return False
            
    except (PlaywrightTimeoutError, PWError) as e:
        logger.error(f"Failed to configure WebRTC privacy: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return False
    finally:
        # Restore original page
        if restore_url and not page.is_closed() and page.url.startswith("brave://settings"):
            try:
                await page.goto(original_url if original_url else "about:blank", 
                               timeout=10_000, wait_until="domcontentloaded")
            except Exception as e:
                logger.warning(f"Failed to restore original URL: {e}")


async def test_webrtc_privacy(page: Page) -> bool:
    """
    Test function to verify WebRTC privacy configuration.
    
    Returns:
        bool: True if test passed, False otherwise
    
    Example:
        success = await test_webrtc_privacy(page)
        print(f"Test {'passed' if success else 'failed'}")
    """
    try:
        logger.info("Testing WebRTC privacy configuration...")
        
        # Navigate to settings
        await page.goto(SETTINGS_URL_SEARCH, timeout=30_000, wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle", timeout=20_000)
        await asyncio.sleep(1.5)
        
        # Find and check dropdown
        settings_box = page.locator(f'div.settings-box:has-text("{WEBRTC_POLICY_TEXT_LABEL}")')
        await settings_box.wait_for(state="visible", timeout=15_000)
        
        dropdown = settings_box.locator('settings-dropdown-menu').locator('select#dropdownMenu')
        await dropdown.wait_for(state="visible", timeout=7_000)
        
        current_value = await dropdown.evaluate("el => el.value")
        
        if current_value == TARGET_OPTION_VALUE:
            logger.info(f"TEST PASSED: WebRTC policy is set to '{TARGET_OPTION_VALUE}'")
            return True
        else:
            logger.warning(f"TEST FAILED: WebRTC policy is '{current_value}', expected '{TARGET_OPTION_VALUE}'")
            return False
            
    except Exception as e:
        logger.error(f"Test failed with error: {e}")
        return False


# Convenience alias for the main function
configure = configure_webrtc_privacy
test = test_webrtc_privacy
