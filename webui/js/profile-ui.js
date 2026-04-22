export const PROFILE_SURFACES = {
  core: ['cognition_adapter', 'event_bus', 'cognition_orchestrator', 'verification_guardian'],
  standard: ['cognition_adapter', 'event_bus', 'cognition_orchestrator', 'verification_guardian', 'pattern_detector', 'pattern_persistence_core'],
  full: ['cognition_adapter', 'event_bus', 'cognition_orchestrator', 'verification_guardian', 'pattern_detector', 'pattern_persistence_core', 'context_manager', 'self_correction_trigger']
};
export function expectedSurfaces(profile) {
  const active = PROFILE_SURFACES[profile] || PROFILE_SURFACES.full;
  return Object.fromEntries(Object.keys(PROFILE_SURFACES.full.reduce((a, k) => (a[k] = true, a), {})).map(k => [k, active.includes(k)]));
}
