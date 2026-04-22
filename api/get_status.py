from __future__ import annotations
from usr.plugins.cognition_layers.clf.runtime import get_runtime
from usr.plugins.cognition_layers.helpers.compat import ApiHandler, Request, Response
try:
    from agent import AgentContext
except Exception:
    AgentContext=None

def _resolve_agent(input:dict, request:Request):
    context_id=(input or {}).get("context_id") or ((getattr(request,"args",None) or {}).get("context_id"))
    if context_id and AgentContext is not None:
        try:
            ctx=AgentContext.get(context_id); return (getattr(ctx,"streaming_agent",None) or getattr(ctx,"agent0",None)) if ctx else None
        except Exception: return None
    return None
class GetStatus(ApiHandler):
    async def process(self, input:dict, request:Request)->dict|Response:
        agent=_resolve_agent(input or {}, request); return get_runtime(agent).status(agent)
