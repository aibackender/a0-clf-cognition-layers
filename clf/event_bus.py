from __future__ import annotations
from collections import defaultdict, deque
from threading import RLock
from typing import Any, Callable
import uuid
from usr.plugins.cognition_layers.clf.types import utc_now_iso
from usr.plugins.cognition_layers.helpers import state
EventHandler=Callable[[dict[str,Any]],None]
class EventBus:
    def __init__(self, max_history:int=500, persist:bool=True, max_queue:int=128):
        self.max_history=max(10,int(max_history)); self.persist=persist; self.max_queue=max(1,int(max_queue)); self._history=deque(maxlen=self.max_history); self._subs=defaultdict(list); self._lock=RLock(); self._queue=deque(); self._dispatching=False; self._sequence=0; self._stats={"delivered":0,"rejected":0,"high_water_mark":0,"subscriber_errors":0}
    def publish(self,event_name:str,payload:dict[str,Any]|None=None)->dict[str,Any]:
        event={"id":f"event-{uuid.uuid4().hex[:12]}","timestamp":utc_now_iso(),"name":str(event_name or "unknown"),"payload":payload or {}}
        with self._lock:
            if len(self._queue) >= self.max_queue:
                self._stats["rejected"] += 1
                event["sequence"] = self._sequence + 1
                event["delivery"] = {"status":"rejected","reason":"back_pressure","policy":"reject_new","queue_depth":len(self._queue)}
                return event
            self._sequence += 1
            event["sequence"] = self._sequence
            event["delivery"] = {"status":"accepted","policy":"reject_new","queue_depth":len(self._queue)+1}
            self._queue.append(event)
            self._stats["high_water_mark"] = max(self._stats["high_water_mark"], len(self._queue))
            if self.persist: state.append_event(event)
            if self._dispatching:
                return event
            self._dispatching = True
        self._drain_queue()
        return event
    def subscribe(self,event_name:str,handler:EventHandler)->None:
        with self._lock: self._subs[str(event_name or "*")].append(handler)
    def configure(self, *, max_history:int|None=None, max_queue:int|None=None)->None:
        with self._lock:
            if max_history is not None and int(max_history) != self.max_history:
                self.max_history=max(10,int(max_history)); self._history=deque(list(self._history), maxlen=self.max_history)
            if max_queue is not None:
                self.max_queue=max(1,int(max_queue))
    def stats(self)->dict[str,Any]:
        with self._lock:
            return {"last_sequence":self._sequence,"queue_depth":len(self._queue),"max_queue":self.max_queue,**self._stats}
    def recent(self,limit:int=100)->list[dict[str,Any]]:
        limit=max(1,min(int(limit or 100),self.max_history)); persisted=state.recent_events(limit); memory=list(self._history)[-limit:]
        seen=set(); out=[]
        for e in persisted+memory:
            i=str(e.get("id",""));
            if i and i in seen: continue
            if i: seen.add(i)
            out.append(e)
        return out[-limit:]
    def _drain_queue(self)->None:
        while True:
            with self._lock:
                if not self._queue:
                    self._dispatching=False
                    return
                event=self._queue.popleft()
                self._history.append(event)
                handlers=list(self._subs.get(event["name"],[]))+list(self._subs.get("*",[]))
            for h in handlers:
                try:
                    h(event)
                except Exception:
                    with self._lock: self._stats["subscriber_errors"] += 1
            with self._lock:
                self._stats["delivered"] += 1
_GLOBAL_BUS=EventBus()
def get_event_bus(*, max_history:int|None=None, max_queue:int|None=None)->EventBus:
    if max_history is not None or max_queue is not None:
        _GLOBAL_BUS.configure(max_history=max_history, max_queue=max_queue)
    return _GLOBAL_BUS
