from __future__ import annotations
from usr.plugins.cognition_layers.clf.event_bus import get_event_bus
from usr.plugins.cognition_layers.helpers.compat import ApiHandler, Request, Response
class GetEvents(ApiHandler):
    async def process(self, input:dict, request:Request)->dict|Response:
        try: limit=int((input or {}).get("limit") or ((getattr(request,"args",None) or {}).get("limit")) or 100)
        except Exception: limit=100
        events=get_event_bus().recent(max(1,min(limit,500))); return {"events":events,"count":len(events)}
