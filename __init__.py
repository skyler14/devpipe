"""
devpipe - A toolkit for interactive website monitoring and debugging.

Monitor browser activity, track network requests, detect UI interactions,
and debug workflows using Chrome DevTools Protocol (CDP).
"""

from .monitor import EventDrivenMonitor
from . import webrtcprivacy

__version__ = "0.1.0"
__all__ = ["EventDrivenMonitor", "webrtcprivacy"]
