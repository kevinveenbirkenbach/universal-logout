PYTHON ?= python3
E2E_IMAGE := universal-logout:e2e
DOCKER_RUN := docker run --rm -v "$(CURDIR):/repo" -w /repo

LINTERS := lint-python lint-javascript lint-json lint-yaml lint-toml lint-docker \
	lint-markdown lint-actions lint-html lint-nginx lint-compose

.PHONY: lint $(LINTERS)
lint: $(LINTERS)

lint-python:
	$(DOCKER_RUN) ghcr.io/astral-sh/ruff:latest check --no-cache .
	$(DOCKER_RUN) ghcr.io/astral-sh/ruff:latest format --check --no-cache .

lint-javascript:
	$(DOCKER_RUN) node:22-alpine npx --yes eslint@10 .

lint-json:
	$(DOCKER_RUN) python:3.12-alpine sh -c \
		'find . -name "*.json" -not -path "./.git/*" -not -path "*/node_modules/*" -print0 \
		| xargs -0 -n1 python -m json.tool > /dev/null'

lint-yaml:
	$(DOCKER_RUN) python:3.12-alpine sh -c \
		'pip install --quiet --root-user-action=ignore yamllint && yamllint --strict .'

lint-toml:
	$(DOCKER_RUN) python:3.12-alpine python -c \
		'import tomllib; tomllib.load(open("pyproject.toml", "rb"))'

lint-docker:
	$(DOCKER_RUN) hadolint/hadolint:latest-alpine hadolint \
		Dockerfile tests/e2e/cookie-lab/Dockerfile tests/e2e/runner/Dockerfile

lint-markdown:
	docker run --rm -v "$(CURDIR):/workdir" davidanson/markdownlint-cli2:latest

lint-actions:
	$(DOCKER_RUN) rhysd/actionlint:latest -no-color

lint-html:
	$(DOCKER_RUN) python:3.12-alpine sh -c \
		'pip install --quiet --root-user-action=ignore djlint && djlint templates --lint'

lint-nginx:
	docker run --rm --add-host cookie-lab:127.0.0.1 --add-host logout:127.0.0.1 \
		-v "$(CURDIR)/tests/e2e/nginx.conf.example:/etc/nginx/conf.d/default.conf:ro" \
		-v "$(CURDIR)/tests/e2e/certs:/etc/nginx/certs:ro" \
		nginx:1.27-alpine nginx -t

lint-compose:
	docker compose -f tests/e2e/docker-compose.yml config --quiet

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
