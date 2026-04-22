from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _load_extension_base():
    try:
        from helpers.extension import Extension
        return Extension
    except Exception:
        try:
            from python.helpers.extension import Extension
            return Extension
        except Exception:
            class Extension:
                def __init__(self, agent: Any | None = None, **kwargs: Any) -> None:
                    self.agent = agent
                    self.kwargs = kwargs

            return Extension


def _load_api_types():
    try:
        from helpers.api import ApiHandler, Request, Response
        return ApiHandler, Request, Response
    except Exception:
        @dataclass
        class Request:
            args: dict[str, Any] | None = None
            json: dict[str, Any] | None = None

        class Response(dict):
            pass

        class ApiHandler:
            async def process(self, input: dict, request: Request) -> dict | Response:
                raise NotImplementedError

        return ApiHandler, Request, Response


def _load_repairable_exception():
    try:
        from helpers.errors import RepairableException
        return RepairableException
    except Exception:
        try:
            from python.helpers.errors import RepairableException
            return RepairableException
        except Exception:
            class RepairableException(Exception):
                pass

            return RepairableException


def _load_get_plugin_config():
    try:
        from helpers.plugins import get_plugin_config
        return get_plugin_config
    except Exception:
        try:
            from python.helpers.plugins import get_plugin_config
            return get_plugin_config
        except Exception:
            def get_plugin_config(plugin_name: str, agent: Any | None = None) -> dict[str, Any]:
                return {}

            return get_plugin_config


def _load_message_queue():
    try:
        from helpers.messages import mq
        return mq
    except Exception:
        class _FallbackMq:
            @staticmethod
            def log_user_message(*args: Any, **kwargs: Any) -> None:
                return None

        return _FallbackMq()


Extension = _load_extension_base()
ApiHandler, Request, Response = _load_api_types()
RepairableException = _load_repairable_exception()
get_plugin_config = _load_get_plugin_config()
mq = _load_message_queue()
