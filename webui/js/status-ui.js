export async function fetchCognitionLayerStatus(contextId) {
  const payload = contextId ? { context_id: contextId } : {};
  const res = await fetch('/api/plugins/cognition_layers/get_status', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
  return res.json();
}
