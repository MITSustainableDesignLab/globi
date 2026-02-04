AWS_ENV ?= local.host
HATCHET_ENV ?= local.host

.PHONY: install
install: ## Install the virtual environment and install the pre-commit hooks
	@echo "🚀 Creating virtual environment using uv"
	@uv sync --all-extras --all-groups
	@uv run pre-commit install
	@uv run epi prisma generate

.PHONY: clean-env
clean-env: ## Clean the uv environment
	@echo "🚀 Removing .venv directory created by uv (if exists)"
	@rm -rf .venv

.PHONY: check
check: ## Run code quality tools.
	@echo "🚀 Checking lock file consistency with 'pyproject.toml'"
	@uv lock --locked
	@echo "🚀 Linting code: Running pre-commit"
	@uv run pre-commit run -a
	@echo "🚀 Static type checking: Running pyright"
	@uv run pyright

.PHONY: test
test: ## Test the code with pytest
	@echo "🚀 Testing code: Running pytest"
	@uv run pytest --cov --cov-config=pyproject.toml --cov-report=xml

.PHONY: build
build: clean-build ## Build wheel file
	@echo "🚀 Creating wheel file"
	@uvx --from build pyproject-build --installer uv

.PHONY: clean-build
clean-build: ## Clean build artifacts
	@echo "🚀 Removing build artifacts"
	@uv run python -c "import shutil; import os; shutil.rmtree('dist') if os.path.exists('dist') else None"

.PHONY: publish
publish: ## Publish a release to PyPI.
	@echo "🚀 Publishing."
	@uvx twine upload --repository-url https://upload.pypi.org/legacy/ dist/*

.PHONY: build-and-publish
build-and-publish: build publish ## Build and publish.

.PHONY: docs-test
docs-test: ## Test if documentation can be built without warnings or errors
	@uv run mkdocs build -s

.PHONY: docs
docs: ## Build and serve the documentation
	@uv run mkdocs serve

.PHONY: docs-deploy
docs-deploy: ## Build and serve the documentation
	@uv run mkdocs gh-deploy

.PHONY: worker-native
worker-native: ## Run the worker
	@uv run worker

.PHONY: simulations-native
simulations-native: ## Run the simulations
	@uv run --env-file .env.$(AWS_ENV).aws --env-file .env.$(HATCHET_ENV).hatchet --env-file .env.scythe.storage --env-file .env.scythe.simulations worker

.PHONY: fanouts-native
fanouts-native: ## Run the fanouts
	@uv run --env-file .env.$(AWS_ENV).aws --env-file .env.$(HATCHET_ENV).hatchet --env-file .env.scythe.storage --env-file .env.scythe.fanouts worker

.PHONY: worker
worker: ## Run the worker in a docker container
	@docker compose -f docker-compose.yml up simulations fanouts --build

.PHONY: viz-native
viz-native: ## Run the visualization tool # TODO: possibly add env vars to the command
	@uv run streamlit run src/globi/tools/visualization/main.py

.PHONY: viz
viz: ## Run the visualization tool in production
	@docker compose -f docker-compose.yml -f docker-compose.hatchet.yml -f docker-compose.aws.yml -f docker-compose.st.yml up visualizer --build -d

.PHONY: hatchet-lite
hatchet-lite: ## Run hatchet lite
	@docker compose -f docker-compose.yml -f docker-compose.hatchet.yml up hatchet-lite -d

.PHONY: hatchet-token
hatchet-token: ## Get the hatchet token
	@make hatchet-lite
	@docker compose -f docker-compose.yml -f docker-compose.hatchet.yml exec hatchet-lite /hatchet-admin token create --config /config --tenant-id 707d0855-80ab-4e1f-a156-f1c4546cbf52

.PHONY: engine
engine: ## Run the engine
	@docker compose -f docker-compose.yml -f docker-compose.hatchet.yml -f docker-compose.aws.yml up -d --build

.PHONY: build-engine
build-engine: ## Build the engine
	@docker compose -f docker-compose.yml -f docker-compose.hatchet.yml -f docker-compose.aws.yml build

.PHONY: env-debug
env-debug: ## Merge env files into .env.debug for the VS Code/Cursor debugger
	@uv run python scripts/merge_env_for_debug.py

.PHONY: cli-native
cli-native: ## Run the cli
	@uv run \
	--env-file .env.$(AWS_ENV).aws \
	--env-file .env.$(HATCHET_ENV).hatchet \
	--env-file .env.scythe.fanouts \
	--env-file .env.scythe.storage \
	globi $(filter-out $@,$(MAKECMDGOALS))

.PHONY: cli
cli: ## Run the cli in production
	@docker compose -f docker-compose.yml -f docker-compose.hatchet.yml -f docker-compose.aws.yml run --rm simulations uv run globi $(filter-out $@,$(MAKECMDGOALS))

.PHONY: interactive
interactive: ## Run the cli in production
	@docker compose -f docker-compose.yml -f docker-compose.hatchet.yml -f docker-compose.aws.yml exec -it fanouts /bin/bash

.PHONY: down
down: ## Down the docker containers
	@docker compose -f docker-compose.yml -f docker-compose.hatchet.yml -f docker-compose.aws.yml -f docker-compose.st.yml down

.PHONY: push-worker
push-worker: ## Push the worker to the workers
	@uv run --env-file .env.prod.aws make docker-login
	@docker compose -f docker-compose.yml build simulations
	@docker compose -f docker-compose.yml push simulations

.PHONY: docker-login
docker-login: ## Login to the docker registry
	@aws ecr get-login-password --region $(AWS_REGION) | docker login --username AWS --password-stdin $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com

.PHONY: help
help:
	@uv run python -c "import re; \
	[[print(f'\033[36m{m[0]:<20}\033[0m {m[1]}') for m in re.findall(r'^([a-zA-Z_-]+):.*?## (.*)$$', open(makefile).read(), re.M)] for makefile in ('$(MAKEFILE_LIST)').strip().split()]"

.DEFAULT_GOAL := help

%:
	@:
