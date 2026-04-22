from __future__ import annotations
from usr.plugins.cognition_layers.clf.runtime import get_runtime
from usr.plugins.cognition_layers.helpers.compat import Extension
class CognitionLayersLoopEnd(Extension):
    async def execute(self, **kwargs):
        runtime=get_runtime(self.agent); context=runtime.build_context(self.agent, trigger="loop_end", **kwargs); effects=runtime.on_loop_end(context); runtime.adapter.emit_effects(self.agent,effects,context=context); return None
