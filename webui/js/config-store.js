export function normalizeList(text) {
  return String(text || '').split('\n').map(v => v.trim()).filter(Boolean);
}
export function listText(items) {
  return (items || []).join('\n');
}
