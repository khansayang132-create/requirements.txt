# Adapted from Anthropic Skill Creator (Apache 2.0) - see NOTICE
"""Generate a standalone HTML review page for trigger eval results.

Discovers run directories with outputs/, generates a review page,
and optionally serves via simple HTTP server.
"""
import http.server
import json
import sys
from pathlib import Path
from typing import Any


def discover_runs(workspace_dir: Path) -> list[dict[str, Any]]:
    """Discover run directories containing outputs/ subdirectories.

    Args:
        workspace_dir: Root workspace directory to search.

    Returns:
        List of dicts with run metadata and paths.
    """
    runs = []
    for run_dir in sorted(workspace_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        outputs_dir = run_dir / "outputs"
        if not outputs_dir.exists():
            # Also check for direct grading.json
            if not (run_dir / "grading.json").exists():
                continue

        run_info: dict[str, Any] = {
            "name": run_dir.name,
            "path": str(run_dir),
        }

        # Load grading if available
        grading_path = run_dir / "grading.json"
        if not grading_path.exists():
            grading_path = outputs_dir / "grading.json" if outputs_dir.exists() else None
        if grading_path and grading_path.exists():
            with open(grading_path) as f:
                run_info["grading"] = json.load(f)

        # Load response if available
        response_path = outputs_dir / "response.txt" if outputs_dir.exists() else None
        if response_path and response_path.exists():
            run_info["response"] = response_path.read_text()[:2000]  # Truncate

        runs.append(run_info)

    return runs


def generate_review_html(
    workspace_dir: Path,
    output_path: Path | None = None,
) -> str:
    """Generate a standalone HTML review page.

    Args:
        workspace_dir: Directory containing run results.
        output_path: Optional path to write HTML file.

    Returns:
        The generated HTML string.
    """
    runs = discover_runs(workspace_dir)

    # Load feedback if exists
    feedback_path = workspace_dir / "feedback.json"
    existing_feedback = {}
    if feedback_path.exists():
        with open(feedback_path) as f:
            existing_feedback = json.load(f)

    runs_json = json.dumps(runs, indent=2)
    feedback_json = json.dumps(existing_feedback, indent=2)

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Eval Review - {workspace_dir.name}</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #f5f5f5; padding: 2em; }}
h1 {{ color: #1a1a2e; margin-bottom: 1em; }}
.controls {{ display: flex; gap: 1em; margin-bottom: 1.5em; flex-wrap: wrap; }}
.controls button {{ padding: 8px 16px; border: 1px solid #ddd; border-radius: 4px; cursor: pointer; background: white; }}
.controls button:hover {{ background: #e8e8e8; }}
.controls button.active {{ background: #3498db; color: white; border-color: #3498db; }}
.run-card {{ background: white; border-radius: 8px; padding: 1.5em; margin: 1em 0; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
.run-card.pass {{ border-left: 4px solid #2ecc71; }}
.run-card.fail {{ border-left: 4px solid #e74c3c; }}
.run-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5em; }}
.run-name {{ font-weight: bold; font-size: 1.1em; }}
.score {{ font-size: 1.2em; font-weight: bold; }}
.score.good {{ color: #2ecc71; }}
.score.bad {{ color: #e74c3c; }}
.response {{ background: #f8f8f8; padding: 1em; border-radius: 4px; margin: 0.5em 0; font-family: monospace; font-size: 0.85em; white-space: pre-wrap; max-height: 200px; overflow-y: auto; }}
.feedback-section {{ margin-top: 1em; padding-top: 1em; border-top: 1px solid #eee; }}
.feedback-section textarea {{ width: 100%; height: 60px; padding: 8px; border: 1px solid #ddd; border-radius: 4px; font-family: inherit; resize: vertical; }}
.feedback-section button {{ margin-top: 0.5em; padding: 6px 12px; background: #3498db; color: white; border: none; border-radius: 4px; cursor: pointer; }}
.export-bar {{ position: sticky; top: 0; background: white; padding: 1em; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); z-index: 10; margin-bottom: 1em; display: flex; justify-content: space-between; align-items: center; }}
.export-bar button {{ padding: 8px 20px; background: #2ecc71; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 1em; }}
.export-bar button:hover {{ background: #27ae60; }}
.stat {{ display: inline-block; margin-right: 1.5em; }}
.stat-value {{ font-weight: bold; font-size: 1.2em; }}
</style>
</head>
<body>
<h1>Eval Review: {_escape_html(workspace_dir.name)}</h1>

<div class="export-bar">
  <div>
    <span class="stat">Runs: <span class="stat-value" id="total-count">0</span></span>
    <span class="stat">Avg Score: <span class="stat-value" id="avg-score">-</span></span>
  </div>
  <div>
    <button onclick="exportFeedback()">Export Feedback JSON</button>
  </div>
</div>

<div class="controls">
  <button class="active" onclick="filterRuns('all', this)">All</button>
  <button onclick="filterRuns('pass', this)">Passing</button>
  <button onclick="filterRuns('fail', this)">Failing</button>
</div>

<div id="runs-container"></div>

<script>
const runs = {runs_json};
const feedback = {feedback_json};

function init() {{
  renderRuns(runs);
  updateStats();
}}

function renderRuns(runsToShow) {{
  const container = document.getElementById('runs-container');
  container.innerHTML = '';

  runsToShow.forEach((run, idx) => {{
    const score = run.grading?.score ?? null;
    const passed = score !== null && score >= 0.5;
    const card = document.createElement('div');
    card.className = 'run-card ' + (score !== null ? (passed ? 'pass' : 'fail') : '');
    card.dataset.score = score;

    const scoreClass = score !== null ? (score >= 0.5 ? 'good' : 'bad') : '';
    const scoreText = score !== null ? score.toFixed(2) : 'N/A';

    card.innerHTML = `
      <div class="run-header">
        <span class="run-name">${{run.name}}</span>
        <span class="score ${{scoreClass}}">${{scoreText}}</span>
      </div>
      ${{run.grading?.reasoning ? '<p>' + run.grading.reasoning + '</p>' : ''}}
      ${{run.response ? '<div class="response">' + escapeHtml(run.response) + '</div>' : ''}}
      <div class="feedback-section">
        <textarea placeholder="Add feedback for this run..." id="feedback-${{idx}}">${{feedback[run.name] || ''}}</textarea>
        <button onclick="saveFeedback('${{run.name}}', ${{idx}})">Save Feedback</button>
      </div>
    `;
    container.appendChild(card);
  }});
}}

function filterRuns(filter, btn) {{
  document.querySelectorAll('.controls button').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');

  if (filter === 'all') {{
    renderRuns(runs);
  }} else if (filter === 'pass') {{
    renderRuns(runs.filter(r => (r.grading?.score ?? 0) >= 0.5));
  }} else {{
    renderRuns(runs.filter(r => (r.grading?.score ?? 1) < 0.5));
  }}
}}

function updateStats() {{
  document.getElementById('total-count').textContent = runs.length;
  const scores = runs.filter(r => r.grading?.score != null).map(r => r.grading.score);
  if (scores.length > 0) {{
    const avg = scores.reduce((a, b) => a + b, 0) / scores.length;
    document.getElementById('avg-score').textContent = avg.toFixed(3);
  }}
}}

function saveFeedback(runName, idx) {{
  const textarea = document.getElementById('feedback-' + idx);
  feedback[runName] = textarea.value;
}}

function exportFeedback() {{
  const blob = new Blob([JSON.stringify(feedback, null, 2)], {{ type: 'application/json' }});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'feedback.json';
  a.click();
}}

function escapeHtml(text) {{
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}}

init();
</script>
</body>
</html>"""

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html)
        print(f"Review page written to {output_path}")

    return html


def _escape_html(text: str) -> str:
    """Basic HTML escaping."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def serve_review(workspace_dir: Path, port: int = 8080) -> None:
    """Serve the review page via simple HTTP server.

    Args:
        workspace_dir: Directory containing run results.
        port: Port to serve on.
    """
    output_path = workspace_dir / "review.html"
    generate_review_html(workspace_dir, output_path)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(workspace_dir), **kwargs)

    print(f"Serving review at http://localhost:{port}/review.html")
    with http.server.HTTPServer(("", port), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Generate eval review page")
    parser.add_argument("workspace_dir", type=Path, help="Workspace directory with runs")
    parser.add_argument("--output", type=Path, default=None, help="Output HTML path")
    parser.add_argument("--serve", action="store_true", help="Serve via HTTP")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    if args.serve:
        serve_review(args.workspace_dir, args.port)
    else:
        output = args.output or args.workspace_dir / "review.html"
        generate_review_html(args.workspace_dir, output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
