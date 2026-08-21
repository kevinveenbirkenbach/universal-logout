PYTHON ?= python3

.PHONY: install-dev
install-dev:
	$(PYTHON) -m pip install -e ".[dev]"

.PHONY: test
test: test-unit test-e2e

.PHONY: test-unit
test-unit:
	$(PYTHON) -m pytest tests/unit -q

.PHONY: test-e2e
test-e2e:
	cd tests/e2e && docker compose up --build --abort-on-container-exit --exit-code-from runner

.PHONY: test-e2e-clean
test-e2e-clean:
	cd tests/e2e && docker compose down -v --remove-orphans
	cd tests/e2e && docker compose up --build --abort-on-container-exit --exit-code-from runner
	cd tests/e2e && docker compose down -v --remove-orphans
