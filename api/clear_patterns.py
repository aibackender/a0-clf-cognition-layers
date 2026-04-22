from __future__ import annotations

from usr.plugins.cognition_layers.helpers.compat import ApiHandler, Request, Response
from usr.plugins.cognition_layers.helpers.state import clear_patterns


class ClearPatterns(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict | Response:
        return clear_patterns()
