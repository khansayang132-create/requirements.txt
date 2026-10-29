// Runs a scripted multi-step workflow:
//   { "objective": "...", "steps": [ { "action": "open_url", "args": {...}, "description": "...", "approve": false } ] }
// Each step goes through Commander.execute (policy, retries, verification). A step marked
// "approve": true runs a sensitive action only when the caller also passes allowSensitive (the CLI's
// --allow-sensitive flag): the workflow author and the person running it both have to opt in.
// On a failure the runner inspects the page, records it, and stops (stop_on_failure defaults to true).
// Cancellation: abort the signal; the current step finishes, no further steps start.
import { TaskState } from './task.js';
import { validate } from './schema.js';
import { ACTIONS } from './actions.js';

const WORKFLOW_SCHEMA = {
  type: 'object',
  properties: {
    objective: { type: 'string', minLength: 1 },
    stop_on_failure: { type: 'boolean' },
    steps: {
      type: 'array', minItems: 1,
      items: {
        type: 'object',
        properties: { action: { type: 'string' }, args: { type: 'object' }, description: { type: 'string' }, approve: { type: 'boolean' } },
        required: ['action'], additionalProperties: false,
      },
    },
  },
  required: ['objective', 'steps'],
  additionalProperties: false,
};

export function checkWorkflow(def) {
  const errors = validate(WORKFLOW_SCHEMA, def, 'workflow');
  def?.steps?.forEach?.((s, i) => {
    if (s && !ACTIONS[s.action]) errors.push(`workflow.steps[${i}].action: unknown action ${s.action}`);
  });
  return errors;
}

export async function runWorkflow(commander, def, { allowSensitive = false, signal, onStep = () => {} } = {}) {
  const errors = checkWorkflow(def);
  if (errors.length) throw new Error(`invalid workflow: ${errors.join('; ')}`);
  const task = new TaskState({
    objective: def.objective,
    plan: def.steps.map((s, i) => s.description || `${i + 1}. ${s.action}`),
    constraints: [`approval mode: ${commander.cfg.approval}`, `sensitive steps allowed: ${allowSensitive}`, ...(commander.cfg.allowedHosts.length ? [`allowed hosts: ${commander.cfg.allowedHosts.join(', ')}`] : [])],
  });
  commander.task = task;
  const stopOnFailure = def.stop_on_failure ?? true;
  try {
    for (const [i, step] of def.steps.entries()) {
      if (signal?.aborted) {
        task.observe(`cancelled before step ${i + 1}`);
        return task.finish('cancelled', `cancelled before step ${i + 1} of ${def.steps.length}`);
      }
      let result = await commander.execute(step.action, step.args || {}, { step: i });
      if (result.status === 'APPROVAL_REQUIRED') {
        if (step.approve && allowSensitive) {
          task.observe(`step ${i + 1} is sensitive (${(result.reasons || []).join('; ')}); pre-approved by the workflow and --allow-sensitive`);
          result = await commander.confirm(result.approval_id);
        } else {
          task.observe(`step ${i + 1} needs human approval: ${(result.reasons || []).join('; ')}`);
          onStep(i, result);
          return task.finish('needs_approval', `stopped at step ${i + 1}: sensitive action not approved (mark the step "approve": true and run with --allow-sensitive)`);
        }
      }
      onStep(i, result);
      if (result.ok) {
        task.completeStep(i);
        continue;
      }
      if (stopOnFailure) {
        if (result.recovery) task.observe(`after failure the page is ${result.recovery.url ?? '(no page)'}`);
        return task.finish('failed', `step ${i + 1} (${step.action}) ended ${result.status}${result.error ? `: ${result.error.message}` : ''}`);
      }
    }
    return task.finish('completed', `all ${def.steps.length} steps ran`);
  } finally {
    commander.task = null;
  }
}
