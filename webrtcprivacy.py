"""
WebRTC Privacy Module - Configure WebRTC IP handling policy (Brave browser only).
Usage: await configure_webrtc_privacy(page)
"""
import asyncio
import logging
from playwright.async_api import Page, Error as PWError, TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger("devpipe.webrtcprivacy")

SETTINGS_URL_SEARCH = "brave://settings/?search=webrtc"
WEBRTC_POLICY_TEXT_LABEL = "WebRTC IP handling policy"
TARGET_OPTION_VALUE = "disable_non_proxied_udp"


async def detect_browser_type(page: Page) -> str:
    """
    Detect browser type using multiple methods.
    
    Brave detection is tricky because:
    - User agent contains "Chrome" (built on Chromium)
    - User agent may or may not contain "Brave"
    - Best detection: navigator.brave API (Brave-specific)
    
    Returns:
        str: 'brave', 'chrome', 'firefox', or 'unknown'
    """
    try:
        # Method 1: Check for Brave-specific API (most reliable)
        is_brave = await page.evaluate("""
            () => {
                // Brave has a navigator.brave object
                if (navigator.brave && typeof navigator.brave.isBrave === 'function') {
                    return navigator.brave.isBrave();
                }
                return false;
            }
        """)
        
        if is_brave:
            logger.debug("Detected Brave via navigator.brave API")
            return "brave"
        
        # Method 2: Check user agent as fallback
        user_agent = await page.evaluate("navigator.userAgent")
        logger.debug(f"User agent: {user_agent}")
        
        # Check for explicit "Brave" in user agent
        if "Brave" in user_agent or "brave" in user_agent.lower():
            logger.debug("Detected Brave via user agent string")
            return "brave"
        
        # Firefox detection
        if "Firefox" in user_agent:
            logger.debug("Detected Firefox via user agent")
            return "firefox"
        
        # Chrome/Chromium detection (after Brave check)
        if "Chrome" in user_agent or "Chromium" in user_agent:
            logger.debug("Detected Chrome/Chromium via user agent")
            return "chrome"
        
        logger.debug("Browser type unknown")
        return "unknown"
        
    except Exception as e:
        logger.error(f"Browser detection error: {e}")
        return "unknown"


async def configure_webrtc_privacy(page: Page, restore_url: bool = True, force: bool = False) -> bool:
    """
    Configure Brave browser to use 'disable_non_proxied_udp' for WebRTC IP handling.
    This prevents WebRTC from leaking your real IP when using a proxy.
    
    **Brave Browser Only** - Chrome and Firefox not currently supported.
    
    Args:
        page: Playwright Page object (must be Brave browser)
        restore_url: Whether to navigate back to original URL after configuration (default: True)
        force: Skip browser detection and attempt configuration anyway (default: False)
    
    Returns:
        bool: True if successfully configured or already set, False on failure
    
    Example:
        await configure_webrtc_privacy(page)
        
        # Force configuration even if browser detection fails
        await configure_webrtc_privacy(page, force=True)
    """
    original_url = page.url
    
    # Browser detection (skip if forced)
    if not force:
        browser_type = await detect_browser_type(page)
        
        if browser_type != "brave":
            logger.warning(
                f"WebRTC privacy configuration is Brave-only. "
                f"Detected browser: {browser_type}. "
                f"Chrome requires extensions, Firefox uses about:config (not yet supported). "
                f"Use force=True to attempt configuration anyway."
            )
            return False
    else:
        logger.info("Forcing WebRTC configuration (skipping browser detection)")
    
    try:
        logger.info("Configuring Brave WebRTC IP handling policy...")
        
        # Navigate to settings
        logger.debug(f"Navigating to {SETTINGS_URL_SEARCH}")
        await page.goto(SETTINGS_URL_SEARCH, timeout=30_000, wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle", timeout=20_000)
        await asyncio.sleep(1.5)
        
        # Find the dropdown
        logger.debug(f"Looking for settings box with text: {WEBRTC_POLICY_TEXT_LABEL}")
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
            logger.info(f"✅ Already set to '{TARGET_OPTION_VALUE}'")
            return True
        
        # Set new value
        logger.info(f"Setting WebRTC policy to '{TARGET_OPTION_VALUE}'...")
        await dropdown.select_option(TARGET_OPTION_VALUE, timeout=10_000)
        await asyncio.sleep(0.75)
        
        # Verify
        new_value = await dropdown.evaluate("el => el.value")
        if new_value == TARGET_OPTION_VALUE:
            logger.info(f"✅ Successfully set to '{TARGET_OPTION_VALUE}'")
            return True
        else:
            logger.error(f"❌ Verification failed: expected '{TARGET_OPTION_VALUE}', got '{new_value}'")
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
                logger.debug(f"Restoring original URL: {original_url}")
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
    original_url = page.url
    
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
            logger.info(f"✅ TEST PASSED: WebRTC policy is set to '{TARGET_OPTION_VALUE}'")
            return True
        else:
            logger.warning(f"❌ TEST FAILED: WebRTC policy is '{current_value}', expected '{TARGET_OPTION_VALUE}'")
            return False
            
    except Exception as e:
        logger.error(f"Test failed with error: {e}")
        return False
    finally:
        # Restore original page
        if not page.is_closed() and page.url.startswith("brave://settings"):
            try:
                await page.goto(original_url if original_url else "about:blank", 
                               timeout=10_000, wait_until="domcontentloaded")
            except Exception as e:
                logger.warning(f"Failed to restore original URL: {e}")


# Convenience alias for the main function
configure = configure_webrtc_privacy
test = test_webrtc_privacy
