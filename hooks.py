from __future__ import annotations
from usr.plugins.cognition_layers.helpers import state

def install(**kwargs):
    state.ensure_storage()
    return {"ok": True, "plugin": "cognition_layers", "runtime": "clf-v2"}

def uninstall(**kwargs):
    return {"ok": True, "plugin": "cognition_layers"}
