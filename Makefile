.PHONY: test-e2e
test-e2e:
	cd tests/e2e && docker compose up --build --abort-on-container-exit --exit-code-from runner

.PHONY: test-e2e-clean
test-e2e-clean:
	cd tests/e2e && docker compose down -v --remove-orphans
	cd tests/e2e && docker compose up --build --abort-on-container-exit --exit-code-from runner
	cd tests/e2e && docker compose down -v --remove-orphans
