"""
The core event-driven, interactive monitoring session for dev_utils.
Includes network deduplication and a resilient, rate-limited UI click scanner.
"""
import asyncio
import json
from pathlib import Path
from datetime import datetime, timedelta
from collections import deque
from urllib.parse import urlparse
from deepdiff import DeepDiff
from .connection import CDPConnection
from typing import Optional, Dict

class EventDrivenMonitor:
    """Manages an interactive, event-driven monitoring session with a hard rate limit on UI events."""

    RATE_LIMIT_COUNT = 3
    RATE_LIMIT_WINDOW = timedelta(seconds=1)
    MICRO_DEBOUNCE_WINDOW = timedelta(milliseconds=200)

    def __init__(self, cdp_port: int):
        self.conn = CDPConnection(cdp_port=cdp_port)
        self.is_logging = False
        self.log_file_path: Optional[Path] = None
        self._event_queue = asyncio.Queue()
        self._log_writer_task: Optional[asyncio.Task] = None
        self.log_session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._network_deduplicator = NetworkDeduplicator()
        self._listeners_attached = False
        self._ui_click_timestamps = deque()
        self._last_log_time = datetime.min

    async def start(self):
        print(f"Connecting to browser on CDP port {self.conn.cdp_port}...")
        if not await self.conn.connect(): return
        print(f"✅ Successfully connected to: {await self.conn.page.title()}")
        try:
            await self._interactive_loop()
        finally:
            print("🔌 Disconnecting from browser...")
            if self._log_writer_task: self._log_writer_task.cancel()
            await self.conn.disconnect()

    async def _interactive_loop(self):
        print("\nCommands:\n  run [prefix] - Start or resume logging.\n  wait         - Pause logging.\n  new [prefix] - Create a new log file and start.\n  quit         - Exit.")
        while True:
            command_str = await asyncio.to_thread(input, "\n> ")
            parts = command_str.lower().strip().split()
            if not parts: continue
            command, args = parts[0], parts[1:]
            prefix = args[0] if args else None

            if command == "run":
                if not self.log_file_path: self._start_new_log_file(prefix)
                self.is_logging = True
                await self._ensure_listeners()
                print(f"🚀 Logging is active. Saving to: {self.log_file_path}")
            elif command == "wait":
                self.is_logging = False
                print("⏸️ Logging paused.")
            elif command == "new":
                self._start_new_log_file(prefix)
                await self._ensure_listeners()
                print(f"📝 New log file created. Saving to: {self.log_file_path}")
            elif command == "quit":
                break
            else:
                print("❓ Unknown command.")

    def _start_new_log_file(self, prefix: str = None):
        self.log_file_path = self._get_log_path(prefix)
        self.log_file_path.parent.mkdir(parents=True, exist_ok=True)
        self.is_logging = True
        
        if self._log_writer_task: self._log_writer_task.cancel()
        self._log_writer_task = asyncio.create_task(self._log_writer())
        self._log_event("SESSION_START", {"log_file": str(self.log_file_path)})

    async def _ensure_listeners(self):
        if self._listeners_attached: return
        self.conn.client.on('Network.requestWillBeSent', self._handle_network_request)
        await self.conn.client.send('Network.enable')
        self.conn.client.on('Runtime.consoleAPICalled', self._handle_console_api)
        await self.conn.page.evaluate(self._get_click_scanner_script())
        await self.conn.client.send('Runtime.enable')
        self._listeners_attached = True
        print("✅ Event listeners attached.")

    def _log_event(self, event_type: str, data: dict):
        if not self.is_logging: return
        self._event_queue.put_nowait({
            "timestamp": datetime.now().isoformat(),
            "type": event_type,
            "data": data
        })
    
    def _handle_network_request(self, event: dict):
        event_type, processed_data = self._network_deduplicator.process(event)
        self._log_event(event_type, processed_data)

    def _handle_console_api(self, event):
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
        except (KeyError, IndexError, json.JSONDecodeError): pass

    async def _log_writer(self):
        while True:
            try:
                event = await self._event_queue.get()
                with open(self.log_file_path, 'a') as f:
                    f.write(json.dumps(event) + '\n')
                self._event_queue.task_done()
            except asyncio.CancelledError:
                break

    def _get_log_path(self, prefix: str = None) -> Path:
        filename = f"{self.log_session_id}.jsonl"
        if not prefix: return Path.home() / "Documents" / "dev_utils_logs" / filename
        prefix_path = Path(prefix)
        return (prefix_path / filename) if prefix.endswith('/') else prefix_path.parent / f"{prefix_path.name}_{filename}"

    def _get_click_scanner_script(self) -> str:
        # Includes a resilient try/catch block for content extraction.
        return """
        (() => {
            let lastExecutionTime = 0;
            const debounceInterval = 300;

            const getSelector = (el) => {
                if (!el || !el.tagName) return '';
                let selector = el.tagName.toLowerCase();
                if (el.id) selector += `#${el.id.trim()}`;
                if (el.className && typeof el.className === 'string') {
                    selector += `.${el.className.trim().split(/\\s+/).join('.')}`;
                }
                return selector;
            };

            const extractInnerContent = (startNode) => {
                // This function is now wrapped in a try/catch by the caller
                const findings = [];
                const nodesToVisit = [startNode];
                let count = 0;
                while (nodesToVisit.length > 0 && findings.length < 5 && count < 10) {
                    const node = nodesToVisit.shift();
                    count++;
                    if (!node) continue;
                    const tagName = (node.tagName || '').toLowerCase();
                    if (tagName === 'a' && node.href) {
                        findings.push({ type: 'link', href: node.href, text: (node.innerText || '').trim().slice(0, 150) });
                    }
                    if (node.children) {
                        nodesToVisit.push(...node.children);
                    }
                }
                return findings;
            };

            document.body.addEventListener('click', (event) => {
                if (!event.isTrusted) return;
                const currentTime = performance.now();
                if (currentTime - lastExecutionTime < debounceInterval) return;
                lastExecutionTime = currentTime;

                const target = document.elementFromPoint(event.clientX, event.clientY);
                if (!target) return;

                const result = {};

                try {
                    const path = [];
                    let current = target;
                    for (let i = 0; i < 5 && current && current.parentElement; i++) {
                        path.unshift(getSelector(current));
                        if (['main', 'section', 'nav'].includes(current.tagName.toLowerCase())) break;
                        current = current.parentElement;
                    }
                    result.element_path = path.join(' > ');
                    result.target_text = (target.innerText || '').trim().slice(0, 150);
                    
                    // --- Resilient Content Extraction ---
                    try {
                        result.inner_content = extractInnerContent(target);
                    } catch (e) {
                        result.inner_content_error = e.message;
                    }

                } catch (e) {
                    // Main catch block for core data gathering
                    result.error = e.message;
                }
                
                console.log('__UI_SCANNER_DATA__' + JSON.stringify(result));
            }, true);
        })();
        """

class NetworkDeduplicator:
    """A class to identify and diff similar network requests."""
    def __init__(self):
        self._reference_requests: Dict[str, dict] = {}

    def process(self, event: dict) -> tuple[str, dict]:
        request_info = event.get('request', {})
        url = request_info.get('url', '')
        method = request_info.get('method', '')
        
        parsed_url = urlparse(url)
        fingerprint = f"{method}::{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}"

        if fingerprint not in self._reference_requests:
            self._reference_requests[fingerprint] = event
            return "NETWORK_REFERENCE", event

        reference_event = self._reference_requests[fingerprint]
        diff = DeepDiff(reference_event, event, ignore_order=True)
        
        changes = {
            path: change.get('new_value', change) 
            for path, change in diff.get('values_changed', {}).items()
        }

        diff_data = {
            "fingerprint": fingerprint,
            "requestId": event.get("requestId"),
            "url_params": parsed_url.query,
            "changes": changes
        }
        return "NETWORK_DIFF", diff_data