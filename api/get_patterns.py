from __future__ import annotations
from usr.plugins.cognition_layers.clf.pattern_persistence import PatternPersistenceCore
from usr.plugins.cognition_layers.helpers.compat import ApiHandler, Request, Response
from usr.plugins.cognition_layers.helpers.policy import scope_for_agent
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
class GetPatterns(ApiHandler):
    async def process(self, input:dict, request:Request)->dict|Response:
        try: limit=int((input or {}).get("limit") or ((getattr(request,"args",None) or {}).get("limit")) or 50)
        except Exception: limit=50
        agent=_resolve_agent(input or {}, request); scope=scope_for_agent(agent).get("label") if agent else None
        return PatternPersistenceCore().summary(limit=max(1,min(limit,200)), scope_label=scope)
