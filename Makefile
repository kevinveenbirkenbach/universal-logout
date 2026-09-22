PYTHON ?= python3
E2E_IMAGE := universal-logout:e2e

.PHONY: install-dev
install-dev:
	$(PYTHON) -m pip install -e ".[dev]"

.PHONY: test
test: test-unit test-e2e

.PHONY: test-unit
test-unit:
	$(PYTHON) -m pytest tests/unit -q

.PHONY: e2e-image
e2e-image:
	docker build -t $(E2E_IMAGE) .

.PHONY: test-e2e
test-e2e: e2e-image
	cd tests/e2e && docker compose up --build --abort-on-container-exit --exit-code-from runner

.PHONY: test-e2e-clean
test-e2e-clean: e2e-image test-e2e-run

.PHONY: test-e2e-run
test-e2e-run:
	cd tests/e2e && docker compose down -v --remove-orphans
	cd tests/e2e && docker compose up --build --abort-on-container-exit --exit-code-from runner
	cd tests/e2e && docker compose down -v --remove-orphans
