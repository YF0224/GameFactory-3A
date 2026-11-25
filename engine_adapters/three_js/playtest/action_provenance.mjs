export function actionMetadata(action) {
  return Object.fromEntries(['action_id', 'probe_id', 'step_id', 'criterion_ids', 'purpose',
    'expected_observation', 'planned_t_ms', 'planned_end_t_ms']
    .filter((field) => Object.hasOwn(action, field)).map((field) => [field, action[field]]));
}
