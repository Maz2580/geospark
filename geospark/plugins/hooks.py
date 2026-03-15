"""
Plugin lifecycle hooks.

Provides a simple publish/subscribe mechanism that plugins (and the
host application) can use to react to tool lifecycle events.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

VALID_HOOK_NAMES = frozenset(
    {
        "before_tool_call",
        "after_tool_call",
        "on_error",
        "on_load",
        "on_unload",
    }
)


class PluginHooks:
    """Registry of lifecycle callbacks.

    Supported hook names:

    * ``on_load`` -- fired after a plugin tool is successfully loaded.
    * ``on_unload`` -- fired when a plugin is unloaded.
    * ``before_tool_call`` -- fired before a tool's ``execute()`` runs.
    * ``after_tool_call`` -- fired after a tool's ``execute()`` returns.
    * ``on_error`` -- fired when a tool's ``execute()`` raises.

    Callbacks are invoked in FIFO (first-registered, first-called) order.
    """

    def __init__(self) -> None:
        self._hooks: dict[str, list[Callable[..., Any]]] = {
            name: [] for name in VALID_HOOK_NAMES
        }

    def register(self, hook_name: str, callback: Callable[..., Any]) -> None:
        """Register a callback for a lifecycle hook.

        Args:
            hook_name: One of the supported hook names.
            callback: A callable to invoke when the hook fires.

        Raises:
            ValueError: If *hook_name* is not a recognised hook.
        """
        if hook_name not in self._hooks:
            raise ValueError(
                f"Unknown hook '{hook_name}'. "
                f"Valid hooks: {sorted(VALID_HOOK_NAMES)}"
            )
        self._hooks[hook_name].append(callback)

    def unregister(self, hook_name: str, callback: Callable[..., Any]) -> None:
        """Remove a previously registered callback.

        Args:
            hook_name: The hook to remove the callback from.
            callback: The exact callable that was registered.

        Raises:
            ValueError: If *hook_name* is not recognised or the
                callback is not currently registered.
        """
        if hook_name not in self._hooks:
            raise ValueError(
                f"Unknown hook '{hook_name}'. "
                f"Valid hooks: {sorted(VALID_HOOK_NAMES)}"
            )
        try:
            self._hooks[hook_name].remove(callback)
        except ValueError:
            raise ValueError(
                f"Callback {callback!r} is not registered for hook '{hook_name}'"
            ) from None

    def trigger(self, hook_name: str, **kwargs: Any) -> list[Any]:
        """Fire all callbacks for a hook and collect results.

        Callbacks are called in registration (FIFO) order.  Each
        callback receives the supplied keyword arguments.

        Args:
            hook_name: The hook to trigger.
            **kwargs: Arbitrary keyword arguments forwarded to each
                callback.

        Returns:
            A list of return values, one per callback.

        Raises:
            ValueError: If *hook_name* is not recognised.
        """
        if hook_name not in self._hooks:
            raise ValueError(
                f"Unknown hook '{hook_name}'. "
                f"Valid hooks: {sorted(VALID_HOOK_NAMES)}"
            )
        results: list[Any] = []
        for callback in self._hooks[hook_name]:
            results.append(callback(**kwargs))
        return results

    def clear(self, hook_name: str | None = None) -> None:
        """Remove all callbacks for a hook, or all hooks if *None*.

        Args:
            hook_name: Specific hook to clear, or ``None`` to clear all.

        Raises:
            ValueError: If a specific *hook_name* is given but not
                recognised.
        """
        if hook_name is None:
            for name in self._hooks:
                self._hooks[name] = []
        else:
            if hook_name not in self._hooks:
                raise ValueError(
                    f"Unknown hook '{hook_name}'. "
                    f"Valid hooks: {sorted(VALID_HOOK_NAMES)}"
                )
            self._hooks[hook_name] = []
