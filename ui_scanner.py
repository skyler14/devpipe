"""
This module provides a dedicated, resilient UI Click Scanner.
It receives console events from the main monitor and processes them.
"""
import json
from datetime import datetime, timedelta
from collections import deque
import asyncio
from typing import Dict

class UIScanner:
    """A dedicated class to handle all UI click scanning logic."""
    RATE_LIMIT_COUNT = 3
    RATE_LIMIT_WINDOW = timedelta(seconds=1)
    MICRO_DEBOUNCE_WINDOW = timedelta(milliseconds=200)

    def __init__(self, event_queue: asyncio.Queue):
        self._event_queue = event_queue
        self._ui_click_timestamps = deque()
        self._last_log_time = datetime.min
        self._page = None

    async def attach_to_page(self, page):
        """Injects the scanner script into the page."""
        self._page = page
        await self._page.evaluate(self._get_click_scanner_script())

    def process_event(self, event: Dict):
        """Receives a console event from the monitor and processes it."""
        try:
            if event['args'][0]['value'].startswith('__UI_SCANNER_DATA__'):
                now = datetime.now()
                if now - self._last_log_time < self.MICRO_DEBOUNCE_WINDOW: return
                while self._ui_click_timestamps and self._ui_click_timestamps[0] < now - self.RATE_LIMIT_WINDOW:
                    self._ui_click_timestamps.popleft()
                if len(self._ui_click_timestamps) >= self.RATE_LIMIT_COUNT: return
                
                self._ui_click_timestamps.append(now)
                self._last_log_time = now
                data = json.loads(event['args'][0]['value'].replace('__UI_SCANNER_DATA__', ''))
                self._log_event('UI_CLICK', data)
        except (KeyError, IndexError, json.JSONDecodeError):
            pass

    def _log_event(self, event_type: str, data: dict):
        self._event_queue.put_nowait({
            "timestamp": datetime.now().isoformat(),
            "type": event_type,
            "data": data
        })

    def _get_click_scanner_script(self) -> str:
        # This is the stable, recursive scanner logic.
        return """
        (() => {
            // This entire scanner is designed to be re-injected on page loads.
            let lastExecutionTime = 0;
            const debounceInterval = 300;

            const getSelector = (el) => {
                if (!el || !el.tagName) return ''; let selector = el.tagName.toLowerCase();
                if (el.id) selector += `#${el.id.trim()}`;
                if (el.className && typeof el.className === 'string') selector += `.${el.className.trim().split(/\\s+/).join('.')}`;
                return selector;
            };

            const clickHandler = (event) => {
                if (!event.isTrusted) return;
                const currentTime = performance.now();
                if (currentTime - lastExecutionTime < debounceInterval) return;
                lastExecutionTime = currentTime;
                
                const target = event.composedPath()[0] || event.target;
                if (!target) return;

                const path = []; let current = target;
                for (let i = 0; i < 5 && current && current.parentElement; i++) {
                    path.unshift(getSelector(current));
                    if (['main', 'section', 'nav'].includes(current.tagName.toLowerCase())) break;
                    current = current.parentElement;
                }
                console.log('__UI_SCANNER_DATA__', JSON.stringify({
                    target_text: (target.innerText || '').trim().slice(0, 150),
                    element_path: path.join(' > '),
                    document_url: (target.ownerDocument || document).location.href
                }));
            };

            const attachedRoots = new WeakSet();
            const attachScanner = (rootNode) => {
                if (!rootNode || attachedRoots.has(rootNode)) return;
                try {
                    rootNode.addEventListener('click', clickHandler, true);
                    attachedRoots.add(rootNode);
                    const observer = new MutationObserver((mutations) => {
                        mutations.forEach(m => m.addedNodes.forEach(n => scanForRoots(n)));
                    });
                    observer.observe(rootNode, { childList: true, subtree: true });
                } catch (e) {}
            };
            
            const scanForRoots = (element) => {
                if (element.nodeType !== Node.ELEMENT_NODE) return;
                if (element.shadowRoot) attachScanner(element.shadowRoot);
                if (element.tagName === 'IFRAME') { try { attachScanner(element.contentDocument); } catch (e) {} }
                element.querySelectorAll('*').forEach(child => {
                    if (child.shadowRoot) attachScanner(child.shadowRoot);
                    if (child.tagName === 'IFRAME') { try { attachScanner(child.contentDocument); } catch (e) {} }
                });
            };

            attachScanner(document);
            scanForRoots(document.body);
        })();
        """