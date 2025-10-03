"""
The core event-driven, interactive monitoring session for dev_utils.
Includes network deduplication and a resilient, rate-limited UI click scanner.
"""
import asyncio
import json
from pathlib import Path
from datetime import datetime, timedelta
from collections import deque, defaultdict
from urllib.parse import urlparse
from deepdiff import DeepDiff
from .connection import CDPConnection
from typing import Optional, Dict, Any, List

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
        self._network_deduplicator = NetworkDeduplicator(self._log_event)
        self._listeners_attached = False
        self._ui_click_timestamps = deque()
        self._last_log_time = datetime.min
        self._navigation_listener_active = False
        self._main_frame_id = None

    async def start(self):
        print(f"Connecting to browser on CDP port {self.conn.cdp_port}...")
        if not await self.conn.connect(): return
        page_title = await self.conn.page.title()
        page_url = self.conn.page.url
        print(f"Successfully connected to: {page_title}")
        print(f"Current URL: {page_url}")
        try:
            await self._interactive_loop()
        finally:
            print("Disconnecting from browser...")
            if self._log_writer_task: self._log_writer_task.cancel()
            await self._network_deduplicator.shutdown()
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
                print(f"Logging is active. Saving to: {self.log_file_path}")
            elif command == "wait":
                self.is_logging = False
                print("Logging paused.")
            elif command == "new":
                self._start_new_log_file(prefix)
                await self._ensure_listeners()
                print(f"New log file created. Saving to: {self.log_file_path}")
            elif command == "quit":
                break
            else:
                print("Unknown command.")

    def _start_new_log_file(self, prefix: str = None):
        self.log_file_path = self._get_log_path(prefix)
        self.log_file_path.parent.mkdir(parents=True, exist_ok=True)
        self.is_logging = True
        
        if self._log_writer_task: self._log_writer_task.cancel()
        self._log_writer_task = asyncio.create_task(self._log_writer())
        self._log_event("SESSION_START", {"log_file": str(self.log_file_path)})

    async def _ensure_listeners(self):
        if self._listeners_attached: return
        
        # Enable Runtime FIRST so console listener is ready
        await self.conn.client.send('Runtime.enable')
        self.conn.client.on('Runtime.consoleAPICalled', self._handle_console_api)
        
        # Enable Network monitoring
        self.conn.client.on('Network.requestWillBeSent', self._handle_network_request)
        await self.conn.client.send('Network.enable')
        
        # Enable Page domain for navigation events
        await self.conn.client.send('Page.enable')
        
        # Get the main frame ID
        frame_tree = await self.conn.client.send('Page.getFrameTree')
        self._main_frame_id = frame_tree.get('frameTree', {}).get('frame', {}).get('id')
        
        # Set up navigation listener to re-inject script
        if not self._navigation_listener_active:
            self.conn.client.on('Page.frameNavigated', self._handle_navigation)
            self._navigation_listener_active = True
        
        # Check current page URL
        current_url = self.conn.page.url
        if current_url.startswith('chrome://') or current_url.startswith('chrome-extension://'):
            print(f"\nWARNING: Current page is '{current_url}'")
            print("Chrome internal pages (chrome://) block script injection for security.")
            print("Click detection will NOT work on this page.")
            print("Please navigate to a regular website (e.g., https://google.com) to test click detection.\n")
            self._listeners_attached = True
            return
        
        # Inject click scanner script
        await self._inject_scanner()
        
        self._listeners_attached = True
        print("Event listeners attached and ready.")

    async def _inject_scanner(self):
        """Inject the click scanner script into the current page."""
        try:
            print("Injecting click scanner script...")
            await self.conn.page.evaluate(self._get_click_scanner_script())
            
            # Send a test message to verify the script is running
            test_result = await self.conn.page.evaluate("""
                (() => {
                    console.log('__UI_SCANNER_TEST__');
                    return 'Script injected successfully';
                })()
            """)
            print(f"Script injection: {test_result}")
            
        except Exception as e:
            print(f"ERROR: Failed to inject click scanner script: {e}")
            print("Click detection will not work.")

    async def _handle_navigation(self, event: dict):
        """Re-inject the scanner script when the page navigates."""
        frame_id = event.get('frame', {}).get('id')
        parent_id = event.get('frame', {}).get('parentId')
        url = event.get('frame', {}).get('url', '')
        
        # Only re-inject on main frame navigation (frames without a parent)
        # or if it matches our stored main frame ID
        is_main_frame = (parent_id is None) or (frame_id == self._main_frame_id)
        
        if is_main_frame:
            print(f"\nPage navigated to: {url}")
            
            if not url.startswith('chrome://') and not url.startswith('chrome-extension://'):
                # Wait a bit for the page to settle
                await asyncio.sleep(0.5)
                await self._inject_scanner()
                self._log_event("PAGE_NAVIGATION", {"url": url})

    def _log_event(self, event_type: str, data: dict):
        if not self.is_logging: return
        self._event_queue.put_nowait({
            "timestamp": datetime.now().isoformat(),
            "type": event_type,
            "data": data
        })
    
    def _handle_network_request(self, event: dict):
        self._network_deduplicator.process(event)

    def _handle_console_api(self, event):
        try:
            # Check for test message
            if 'args' in event and len(event['args']) > 0:
                first_arg = event['args'][0]
                if 'value' in first_arg:
                    value = first_arg['value']
                    
                    # Debug: log the test message
                    if value == '__UI_SCANNER_TEST__':
                        print("Click scanner script is running and console.log is working!")
                        return
                    
                    # Handle actual click data
                    if value.startswith('__UI_SCANNER_DATA__'):
                        now = datetime.now()
                        if now - self._last_log_time < self.MICRO_DEBOUNCE_WINDOW: return
                        while self._ui_click_timestamps and self._ui_click_timestamps[0] < now - self.RATE_LIMIT_WINDOW:
                            self._ui_click_timestamps.popleft()
                        if len(self._ui_click_timestamps) >= self.RATE_LIMIT_COUNT: return
                        self._ui_click_timestamps.append(now)
                        self._last_log_time = now
                        data = json.loads(value.replace('__UI_SCANNER_DATA__', ''))
                        self._log_event('UI_CLICK', data)
                        print(f"Click detected: {data.get('element_path', 'unknown')}")
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            pass  # Silently ignore malformed events

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
        """
        Returns a Shadow DOM-aware click scanner script with improved selectors.
        Supports: Shadow DOM, iframes, dynamic content, and detached UI elements.
        """
        return """
        (() => {
            console.log('__UI_SCANNER_INIT__');
            
            let lastExecutionTime = 0;
            const debounceInterval = 300;

            const getSelector = (el) => {
                if (!el || !el.tagName) return '';
                
                let selector = el.tagName.toLowerCase();
                
                // Prioritize ID - most unique
                if (el.id) {
                    return selector + `#${el.id}`;
                }
                
                // Check for common test identifiers
                const testAttrs = ['data-testid', 'data-test', 'data-qa', 'data-cy'];
                for (const attr of testAttrs) {
                    if (el.hasAttribute(attr)) {
                        return selector + `[${attr}="${el.getAttribute(attr)}"]`;
                    }
                }
                
                // Check for name attribute (forms)
                if (el.name) {
                    selector += `[name="${el.name}"]`;
                }
                
                // Add classes (filter out dynamic/obfuscated ones)
                if (el.className && typeof el.className === 'string') {
                    const classes = el.className.trim().split(/\\s+/).filter(c => 
                        c && 
                        !c.startsWith('*') && 
                        !c.match(/^[a-z0-9]{6,}$/i) && // Skip hash-like classes
                        !c.match(/^_[a-zA-Z0-9]+$/) // Skip _hash patterns
                    );
                    if (classes.length > 0) {
                        selector += '.' + classes.slice(0, 2).join('.');
                    }
                }
                
                // Add nth-of-type for positional uniqueness
                if (el.parentElement) {
                    const siblings = Array.from(el.parentElement.children).filter(
                        child => child.tagName === el.tagName
                    );
                    if (siblings.length > 1) {
                        const index = siblings.indexOf(el) + 1;
                        selector += `:nth-of-type(${index})`;
                    }
                }
                
                return selector;
            };

            const extractInnerContent = (startNode) => {
                const findings = [];
                const nodesToVisit = [startNode];
                let count = 0;
                
                while (nodesToVisit.length > 0 && findings.length < 15 && count < 30) {
                    const node = nodesToVisit.shift();
                    count++;
                    if (!node) continue;
                    
                    const tagName = (node.tagName || '').toLowerCase();
                    
                    // Extract links
                    if (tagName === 'a' && node.href) {
                        findings.push({ 
                            type: 'link', 
                            href: node.href, 
                            text: (node.innerText || '').trim().slice(0, 128) 
                        });
                    }
                    // Extract images
                    else if (tagName === 'img' && node.src) {
                        findings.push({
                            type: 'image',
                            src: node.src,
                            alt: (node.alt || '').slice(0, 128)
                        });
                    }
                    // Extract select dropdowns with options
                    else if (tagName === 'select') {
                        const options = Array.from(node.options || []).map(opt => ({
                            value: opt.value,
                            text: opt.text.slice(0, 64)
                        })).slice(0, 20); // Max 20 options
                        findings.push({
                            type: 'select',
                            name: node.name || '',
                            options: options,
                            selected: node.selectedIndex
                        });
                    }
                    // Extract checkboxes and radios with labels
                    else if (tagName === 'input' && (node.type === 'checkbox' || node.type === 'radio')) {
                        let label = '';
                        // Try to find associated label
                        if (node.id) {
                            const labelEl = document.querySelector(`label[for="${node.id}"]`);
                            if (labelEl) label = labelEl.innerText.trim().slice(0, 128);
                        }
                        // Or check if wrapped in label
                        if (!label && node.parentElement && node.parentElement.tagName === 'LABEL') {
                            label = node.parentElement.innerText.trim().slice(0, 128);
                        }
                        findings.push({
                            type: node.type,
                            name: node.name || '',
                            value: node.value || '',
                            label: label,
                            checked: node.checked
                        });
                    }
                    // Extract text inputs with placeholders
                    else if (tagName === 'input' && ['text', 'email', 'password', 'search', 'tel', 'url'].includes(node.type)) {
                        findings.push({
                            type: 'input',
                            input_type: node.type,
                            name: node.name || '',
                            placeholder: (node.placeholder || '').slice(0, 128),
                            value: (node.value || '').slice(0, 128)
                        });
                    }
                    // Extract textareas
                    else if (tagName === 'textarea') {
                        findings.push({
                            type: 'textarea',
                            name: node.name || '',
                            placeholder: (node.placeholder || '').slice(0, 128),
                            preview: (node.value || '').slice(0, 128)
                        });
                    }
                    // Extract buttons
                    else if (tagName === 'button' || (tagName === 'input' && ['button', 'submit'].includes(node.type))) {
                        findings.push({
                            type: 'button',
                            button_type: node.type || 'button',
                            text: (node.innerText || node.value || '').trim().slice(0, 128)
                        });
                    }
                    // Extract plain text from text nodes
                    else if (node.nodeType === Node.TEXT_NODE) {
                        const text = (node.textContent || '').trim();
                        if (text && text.length > 0) {
                            findings.push({
                                type: 'text',
                                content: text.slice(0, 128)
                            });
                        }
                    }
                    
                    // Continue traversing children
                    if (node.childNodes) {
                        nodesToVisit.push(...node.childNodes);
                    }
                }
                return findings;
            };

            const clickHandler = (event) => {
                if (!event.isTrusted) return;
                
                const currentTime = performance.now();
                if (currentTime - lastExecutionTime < debounceInterval) return;
                lastExecutionTime = currentTime;
                
                // Use composedPath to handle Shadow DOM correctly
                const target = event.composedPath()[0] || event.target;
                if (!target) return;

                const result = {};

                try {
                    // Build element path
                    const path = [];
                    let current = target;
                    for (let i = 0; i < 5 && current && current.parentElement; i++) {
                        path.unshift(getSelector(current));
                        if (['main', 'section', 'nav', 'form'].includes(current.tagName.toLowerCase())) break;
                        current = current.parentElement;
                    }
                    result.element_path = path.join(' > ');
                    result.target_text = (target.innerText || target.textContent || target.value || '').trim().slice(0, 150);
                    result.document_url = (target.ownerDocument || document).location.href;
                    
                    // Add element type information
                    result.tag_name = target.tagName.toLowerCase();
                    if (target.type) result.input_type = target.type;
                    if (target.name) result.element_name = target.name;
                    
                    // Extract inner content with error handling
                    try {
                        result.inner_content = extractInnerContent(target);
                    } catch (e) {
                        result.inner_content_error = e.message;
                    }

                } catch (e) {
                    result.error = e.message;
                }
                
                // CRITICAL: Must concatenate for proper parsing in Python handler
                console.log('__UI_SCANNER_DATA__' + JSON.stringify(result));
            };

            // Track which roots have been instrumented
            const attachedRoots = new WeakSet();
            
            const attachScanner = (rootNode) => {
                if (!rootNode || attachedRoots.has(rootNode)) return;
                
                try {
                    // Use capture phase on window/root to catch events early, before they can be stopped
                    const eventTarget = rootNode === document ? window : rootNode;
                    eventTarget.addEventListener('click', clickHandler, true);
                    eventTarget.addEventListener('mousedown', clickHandler, true);
                    attachedRoots.add(rootNode);
                    
                    // Watch for dynamic content additions
                    if (rootNode.nodeType === Node.DOCUMENT_NODE || rootNode.nodeType === Node.DOCUMENT_FRAGMENT_NODE) {
                        const observer = new MutationObserver((mutations) => {
                            mutations.forEach(m => {
                                m.addedNodes.forEach(n => scanForRoots(n));
                            });
                        });
                        observer.observe(rootNode.body || rootNode, { childList: true, subtree: true });
                    }
                } catch (e) {
                    // Silently fail for inaccessible contexts
                }
            };
            
            const scanForRoots = (element) => {
                if (!element || element.nodeType !== Node.ELEMENT_NODE) return;
                
                // Attach to shadow roots
                if (element.shadowRoot) {
                    attachScanner(element.shadowRoot);
                }
                
                // Attach to iframe documents
                if (element.tagName === 'IFRAME') {
                    try {
                        attachScanner(element.contentDocument);
                    } catch (e) {
                        // Cross-origin iframes will throw - expected
                    }
                }
                
                // Recursively scan children for shadow roots and iframes
                try {
                    element.querySelectorAll('*').forEach(child => {
                        if (child.shadowRoot) {
                            attachScanner(child.shadowRoot);
                        }
                        if (child.tagName === 'IFRAME') {
                            try {
                                attachScanner(child.contentDocument);
                            } catch (e) {
                                // Cross-origin iframe - expected
                            }
                        }
                    });
                } catch (e) {
                    // Silently fail if querySelectorAll not available
                }
            };

            // Initialize scanner on main document
            attachScanner(document);
            
            // Scan existing page for shadow roots and iframes
            if (document.body) {
                scanForRoots(document.body);
            } else {
                // If body doesn't exist yet, wait for it
                document.addEventListener('DOMContentLoaded', () => {
                    if (document.body) scanForRoots(document.body);
                });
            }
            
            console.log('__UI_SCANNER_READY__');
        })();
        """

class NetworkDeduplicator:
    """A class to identify and diff similar network requests with smart simplification and resource bundling."""
    
    MAX_VALUE_LENGTH = 128
    MAX_URL_LENGTH = 200
    BUNDLE_WINDOW = 1.0  # 1 second debounce for resource bundling
    
    # Resource types that should be bundled
    BUNDLED_TYPES = {'Stylesheet', 'Script', 'Image', 'Font', 'Media', 'Other', 'Manifest'}
    
    def __init__(self, log_callback):
        self._reference_requests: Dict[str, dict] = {}
        self._log_callback = log_callback
        self._resource_bundle: List[dict] = []
        self._bundle_timer: Optional[asyncio.Task] = None
        self._bundle_lock = asyncio.Lock()

    async def shutdown(self):
        """Flush any pending resource bundles."""
        if self._bundle_timer:
            self._bundle_timer.cancel()
        await self._flush_bundle()

    def process(self, event: dict):
        """Process a network event - either bundle it or log it immediately."""
        request_type = event.get('type', 'Other')
        
        # Check if this should be bundled
        if request_type in self.BUNDLED_TYPES:
            asyncio.create_task(self._add_to_bundle(event))
        else:
            # Log XHR, Fetch, Document requests immediately
            request_info = event.get('request', {})
            url = request_info.get('url', '')
            method = request_info.get('method', '')
            
            parsed_url = urlparse(url)
            fingerprint = f"{method}::{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}"

            if fingerprint not in self._reference_requests:
                self._reference_requests[fingerprint] = event
                simplified = self._simplify_event(event)
                self._log_callback("NETWORK_REQUEST", simplified)
            else:
                reference_event = self._reference_requests[fingerprint]
                diff = DeepDiff(reference_event, event, ignore_order=True)
                
                changes = {}
                for path, change in diff.get('values_changed', {}).items():
                    if self._should_skip_path(path):
                        continue
                    new_value = change.get('new_value', change)
                    changes[path] = self._truncate_value(new_value)

                if changes:
                    diff_data = {
                        "fingerprint": fingerprint,
                        "method": method,
                        "url": self._simplify_url(url),
                        "changes": changes
                    }
                    self._log_callback("NETWORK_DIFF", diff_data)

    async def _add_to_bundle(self, event: dict):
        """Add a resource to the bundle and reset the timer."""
        async with self._bundle_lock:
            self._resource_bundle.append(event)
            
            # Cancel existing timer and create a new one
            if self._bundle_timer:
                self._bundle_timer.cancel()
            
            self._bundle_timer = asyncio.create_task(self._bundle_timeout())

    async def _bundle_timeout(self):
        """Wait for the bundle window, then flush."""
        try:
            await asyncio.sleep(self.BUNDLE_WINDOW)
            await self._flush_bundle()
        except asyncio.CancelledError:
            pass

    async def _flush_bundle(self):
        """Flush the current bundle to logs."""
        async with self._bundle_lock:
            if not self._resource_bundle:
                return
            
            # Group by type - just simple lists
            by_type = defaultdict(list)
            for event in self._resource_bundle:
                request = event.get('request', {})
                resource_type = event.get('type', 'Other').lower() + 's'  # pluralize
                url = request.get('url', '')
                by_type[resource_type].append(self._simplify_url(url))
            
            # Simple bundle format - just lists grouped by type
            bundle_data = dict(by_type)
            
            self._log_callback("RESOURCE_BUNDLE", bundle_data)
            self._resource_bundle.clear()
            self._bundle_timer = None

    def _simplify_event(self, event: dict) -> dict:
        """Simplify a network event for cleaner logging."""
        request = event.get('request', {})
        
        simplified = {
            "requestId": event.get('requestId'),
            "method": request.get('method'),
            "url": self._simplify_url(request.get('url', '')),
            "type": event.get('type'),
        }
        
        # Add initiator info if it exists, but simplified
        if 'initiator' in event:
            simplified['initiator'] = self._simplify_initiator(event['initiator'])
        
        # Add important headers only
        headers = request.get('headers', {})
        important_headers = {}
        for key in ['Content-Type', 'Authorization', 'X-Requested-With']:
            if key in headers:
                important_headers[key] = self._truncate_value(headers[key])
        if important_headers:
            simplified['headers'] = important_headers
            
        return simplified

    def _simplify_initiator(self, initiator: dict) -> dict:
        """Simplify initiator/stack trace information."""
        simplified = {"type": initiator.get('type')}
        
        if 'url' in initiator:
            simplified['url'] = self._simplify_url(initiator['url'])
        
        # Simplify stack trace
        if 'stack' in initiator:
            stack = initiator['stack']
            frames = stack.get('callFrames', [])[:3]  # Only keep top 3 frames
            simplified['stack'] = [
                {
                    'function': frame.get('functionName', 'anonymous')[:50],
                    'url': self._simplify_url(frame.get('url', '')),
                    'line': frame.get('lineNumber')
                }
                for frame in frames
            ]
        
        return simplified

    def _simplify_url(self, url: str) -> str:
        """Simplify long URLs by truncating query params intelligently."""
        if len(url) <= self.MAX_URL_LENGTH:
            return url
        
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        
        if len(base) > self.MAX_URL_LENGTH:
            return base[:self.MAX_URL_LENGTH] + "..."
        
        # Summarize query params
        if parsed.query:
            params = parsed.query.split('&')
            if len(params) > 3:
                return f"{base}?{params[0]}&...({len(params)} params)"
            return f"{base}?{parsed.query[:50]}..."
        
        return base

    def _truncate_value(self, value: Any) -> Any:
        """Truncate values to max length."""
        if isinstance(value, str):
            if len(value) > self.MAX_VALUE_LENGTH:
                return value[:self.MAX_VALUE_LENGTH] + f"... ({len(value)} chars)"
            return value
        elif isinstance(value, dict):
            return {k: self._truncate_value(v) for k, v in list(value.items())[:5]}
        elif isinstance(value, list):
            return [self._truncate_value(v) for v in value[:5]]
        return value

    def _should_skip_path(self, path: str) -> bool:
        """Determine if a diff path should be skipped (too verbose)."""
        skip_patterns = [
            'callFrames',
            'postData',
            'postDataEntries',
            'wallTime',
            'timestamp',
        ]
        return any(pattern in path for pattern in skip_patterns)
