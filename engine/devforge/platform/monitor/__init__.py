"""DevForge Monitor — structured event logging, request tracing, and analytics.

This module captures every step of the DevForge pipeline. The Monitor class
lives in ``monitor.py``; this file provides the module-level singleton import.

Usage:
    from devforge.platform.monitor import monitor
"""

from .monitor import Monitor, EventType, Severity, Trace  # noqa: F401

monitor = Monitor()
