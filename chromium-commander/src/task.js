// Task state for one objective: plan, progress, observations, failures and evidence.
// The final report says "verified" only when a check passed after the last failure and the last
// recorded verification did not fail. A claim of success needs that, not just "no error".
export class TaskState {
  constructor({ objective, plan = [], constraints = [] }) {
    this.objective = objective;
    this.plan = plan.map((description, i) => ({ index: i, description, status: 'pending' }));
    this.current = this.plan.length ? 0 : null;
    this.constraints = constraints;
    this.status = 'running';
    this.started_at = new Date().toISOString();
    this.actions = [];
    this.observations = [];
    this.failures = [];
    this.retries = 0;
    this.evidence = { screenshots: [], downloads: [] };
    this.url = null;
  }

  record(result) {
    this.actions.push({ step: result.step, action: result.action, status: result.status, url: result.url ?? null, at: result.at, ...(result.error ? { error: result.error.code } : {}) });
    if (result.url) this.url = result.url;
    this.retries += result.retries || 0;
    if (['FAILED', 'VERIFICATION_FAILED', 'BLOCKED'].includes(result.status)) {
      this.failures.push({ action: result.action, status: result.status, error: result.error ?? null, reasons: result.reasons ?? null, failed_checks: (result.verification?.checks || []).filter((c) => !c.passed), at: result.at });
    }
    if (result.evidence?.screenshot) this.evidence.screenshots.push({ path: result.evidence.screenshot, url: result.url, step: result.step });
    if (result.evidence?.download) this.evidence.downloads.push({ path: result.evidence.download, size: result.observed?.size ?? null });
  }

  observe(note) {
    this.observations.push({ note: String(note).slice(0, 1000), at: new Date().toISOString() });
  }

  completeStep(index = this.current) {
    const step = this.plan[index];
    if (!step) return;
    step.status = 'done';
    const next = this.plan.find((s) => s.status === 'pending');
    this.current = next ? next.index : null;
  }

  verificationStatus() {
    let lastFailure = -1;
    let lastPass = -1;
    let lastVerification = null;
    this.actions.forEach((a, i) => {
      if (['FAILED', 'VERIFICATION_FAILED'].includes(a.status)) lastFailure = i;
      if (a.status === 'VERIFIED') lastPass = i;
      if (['VERIFIED', 'VERIFICATION_FAILED'].includes(a.status)) lastVerification = a.status;
    });
    if (lastPass > lastFailure && lastVerification === 'VERIFIED') return 'verified';
    if (lastFailure > lastPass) return 'failed';
    return 'not_verified';
  }

  snapshot() {
    return {
      objective: this.objective,
      status: this.status,
      url: this.url,
      current_step: this.current === null ? null : this.plan[this.current],
      completed_steps: this.plan.filter((s) => s.status === 'done'),
      remaining_steps: this.plan.filter((s) => s.status === 'pending'),
      actions_run: this.actions.length,
      observations: this.observations.slice(-20),
      failed_actions: this.failures,
      retry_count: this.retries,
      safety_constraints: this.constraints,
      verification_status: this.verificationStatus(),
      evidence: this.evidence,
      started_at: this.started_at,
    };
  }

  finish(outcome, summary) {
    const verification = this.verificationStatus();
    // "completed" is only accepted with evidence; otherwise it is reported as unverified.
    this.status = outcome === 'completed' && verification !== 'verified' ? 'completed_unverified' : outcome;
    this.finished_at = new Date().toISOString();
    return { ...this.snapshot(), summary: summary ?? null, finished_at: this.finished_at, action_log: this.actions };
  }
}
