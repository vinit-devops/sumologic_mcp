# Sumo Logic MCP Server - Development Makefile

.PHONY: help install install-dev test test-cov lint format type-check pre-commit clean build run validate-config

# Default target
help:
	@echo "Sumo Logic MCP Server - Development Commands"
	@echo ""
	@echo "Setup:"
	@echo "  install          Install package in development mode"
	@echo "  install-dev      Install with development dependencies"
	@echo "  setup-dev        Complete development environment setup"
	@echo ""
	@echo "Development:"
	@echo "  run              Run the MCP server"
	@echo "  validate-config  Validate configuration"
	@echo "  test-server      Test server startup"
	@echo ""
	@echo "Code Quality:"
	@echo "  format           Format code with black and isort"
	@echo "  lint             Run linting (flake8)"
	@echo "  type-check       Run type checking (mypy)"
	@echo "  pre-commit       Run pre-commit hooks"
	@echo ""
	@echo "Testing:"
	@echo "  test             Run tests"
	@echo "  test-cov         Run tests with coverage"
	@echo "  test-unit        Run unit tests only"
	@echo "  test-integration Run integration tests only"
	@echo ""
	@echo "Build & Deploy:"
	@echo "  build            Build package"
	@echo "  clean            Clean build artifacts"
	@echo "  check-dist       Check distribution"

# Installation
install:
	pip install -e .

install-dev:
	pip install -e ".[dev]"
	pip install -r requirements-dev.txt

setup-dev: install-dev
	@echo "Setting up development environment..."
	@if [ ! -f .env ]; then \
		echo "Creating .env from .env.dev template..."; \
		cp .env.dev .env; \
		echo "⚠️  Please edit .env with your actual Sumo Logic credentials"; \
	fi
	pre-commit install
	@echo "✅ Development environment setup complete!"
	@echo ""
	@echo "Next steps:"
	@echo "1. Edit .env with your Sumo Logic credentials"
	@echo "2. Run 'make validate-config' to test configuration"
	@echo "3. Run 'make test-server' to test server startup"

# Development
run:
	sumologic-mcp-server

validate-config:
	sumologic-mcp-server --validate-config

test-server:
	@echo "Testing server startup..."
	@python -c "
import asyncio
import os
from sumologic_mcp.config import SumoLogicConfig
from sumologic_mcp.server import SumoLogicMCPServer

async def test():
    try:
        config = SumoLogicConfig.from_env()
        server = SumoLogicMCPServer(config)
        await server.start()
        print(f'✅ Server started successfully with {len(server.tool_handlers)} tools')
        await server.shutdown()
        return True
    except Exception as e:
        print(f'❌ Server test failed: {e}')
        return False

success = asyncio.run(test())
exit(0 if success else 1)
"

# Code Quality
format:
	black sumologic_mcp/ tests/ --line-length 88
	isort sumologic_mcp/ tests/ --profile black

lint:
	flake8 sumologic_mcp/ tests/ --max-line-length=88 --extend-ignore=E203,W503

type-check:
	mypy sumologic_mcp/ --strict

pre-commit:
	pre-commit run --all-files

# Testing
test:
	pytest

test-cov:
	pytest --cov=sumologic_mcp --cov-report=html --cov-report=term-missing

test-unit:
	pytest -m unit

test-integration:
	pytest -m integration

# Build & Deploy
build:
	python -m build

clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf .coverage
	rm -rf htmlcov/
	rm -rf .mypy_cache/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

check-dist:
	python -m twine check dist/*

# Development shortcuts
dev: setup-dev
all: format lint type-check test
ci: format lint type-check test-cov