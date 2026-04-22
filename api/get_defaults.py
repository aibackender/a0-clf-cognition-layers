from __future__ import annotations
from usr.plugins.cognition_layers.helpers.compat import ApiHandler, Request, Response
from usr.plugins.cognition_layers.helpers.policy import load_default_config


class GetDefaults(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict | Response:
        return load_default_config()
