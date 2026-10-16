"""expose the validated settings API for the read-only IMAP MCP package
keep configuration types available without importing server runtime components
"""

from .config import HttpSettings, Settings, SettingsError, load_settings

__all__ = ["HttpSettings", "Settings", "SettingsError", "load_settings"]
