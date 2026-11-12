.PHONY: install test lint doctor run-demo
install:
	uv venv .venv && uv pip install --python .venv -e ".[all,dev]"
test:
	.venv/bin/pytest -q
lint:
	.venv/bin/ruff check src tests
doctor:
	.venv/bin/dhfactory doctor
run-demo:
	.venv/bin/dhfactory init-job --script scripts/demo-presenter.txt --job demo-presenter && .venv/bin/dhfactory run --job demo-presenter
