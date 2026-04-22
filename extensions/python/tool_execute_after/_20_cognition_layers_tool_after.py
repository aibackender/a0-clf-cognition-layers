from __future__ import annotations
from usr.plugins.cognition_layers.clf.runtime import get_runtime
from usr.plugins.cognition_layers.helpers.compat import Extension
class CognitionLayersToolAfter(Extension):
    async def execute(self, **kwargs):
        runtime=get_runtime(self.agent); context=runtime.build_context(self.agent, trigger="tool_after", **kwargs); effects=runtime.on_tool_after(context); runtime.adapter.emit_effects(self.agent,effects,context=context); return None
