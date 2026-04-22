from __future__ import annotations
from typing import Any
from usr.plugins.cognition_layers.clf.registry import resolve_profile
from usr.plugins.cognition_layers.helpers import state
from usr.plugins.cognition_layers.helpers.policy import resolve_config

def resolve_profile_status(agent:Any|None=None, explicit:dict|None=None)->dict:
    cfg=resolve_config(agent=agent, explicit=explicit); status=resolve_profile(cfg).to_dict(); state.save_profile_status(status); return status

def current_profile_status()->dict: return state.load_profile_status()
