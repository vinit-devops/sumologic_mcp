# Development Guide

This guide covers setting up a development environment for the Sumo Logic MCP Server.

## Quick Start

```bash
# Clone and setup development environment
git clone <repository-url>
cd sumologic-mcp-python
make setup-dev

# Edit .env with your credentials
nano .env

# Test the setup
make validate-config
make test-server
```

## Development Environment Setup

### Prerequisites

- Python 3.10 or higher
- pip (latest version recommended)
- Git

### 1. Create Virtual Environment

```bash
# Create virtual environment
python3.12 -m venv sumologic-mcp-env

# Activate it
source sumologic-mcp-env/bin/activate  # macOS/Linux
# or
sumologic-mcp-env\Scripts\activate     # Windows
```

### 2. Install Dependencies

```bash
# Install in development mode with all dependencies
make install-dev

# Or manually:
pip install -e ".[dev]"
pip install -r requirements-dev.txt
```

### 3. Configure Environment

```bash
# Copy development environment template
cp .env.dev .env

# Edit with your Sumo Logic credentials
nano .env
```

### 4. Setup Pre-commit Hooks

```bash
# Install pre-commit hooks
pre-commit install

# Test pre-commit setup
make pre-commit
```

## Development Workflow

### Daily Development

```bash
# Start development session
source sumologic-mcp-env/bin/activate

# Run the server
make run

# Or with debug logging
SUMOLOGIC_LOG_LEVEL=DEBUG make run
```

### Code Quality

```bash
# Format code
make format

# Run linting
make lint

# Type checking
make type-check

# Run all quality checks
make all
```

### Testing

```bash
# Run all tests
make test

# Run with coverage
make test-cov

# Run specific test types
make test-unit
make test-integration

# Test server startup
make test-server
```

## Project Structure

```
sumologic-mcp-python/
├── sumologic_mcp/              # Main package
│   ├── __init__.py
│   ├── main.py                 # Entry point
│   ├── server.py               # MCP server implementation
│   ├── config.py               # Configuration management
│   ├── auth.py                 # Authentication
│   ├── api_client.py           # Sumo Logic API client
│   ├── time_utils.py           # Time parsing utilities
│   ├── exceptions/             # Custom exceptions
│   ├── models/                 # Data models
│   └── tools/                  # MCP tool implementations
│       ├── search_tools.py     # Search operations
│       ├── dashboard_tools.py  # Dashboard management
│       ├── metrics_tools.py    # Metrics queries
│       └── collector_tools.py  # Collector management
├── tests/                      # Test suite
├── docs/                       # Documentation
├── .env.dev                    # Development environment template
├── .env.example               # Production environment template
├── requirements-dev.txt       # Development dependencies
├── pyproject.toml            # Package configuration
├── Makefile                  # Development commands
└── README.md                 # Main documentation
```

## Configuration

### Environment Variables

The server supports multiple configuration methods:

1. **Environment variables** (highest precedence)
2. **Configuration file** (`config.json`)
3. **Default values** (lowest precedence)

### Development Configuration

Key development environment variables:

```bash
# API Configuration
SUMOLOGIC_ACCESS_ID=your_dev_access_id
SUMOLOGIC_ACCESS_KEY=your_dev_access_key
SUMOLOGIC_ENDPOINT=https://api.sumologic.com

# Development Settings
SUMOLOGIC_LOG_LEVEL=DEBUG
SUMOLOGIC_LOG_FORMAT=text
SUMOLOGIC_TIMEOUT=60

# Reference Compatibility
QUERY_TIMEOUT=300
MAX_RESULTS=1000
DEFAULT_VMWARE_SOURCE=otel/vmware
```

### Configuration Validation

```bash
# Validate current configuration
make validate-config

# Test with specific config file
sumologic-mcp-server --config-file config.json --validate-config
```

## Testing

### Test Structure

```
tests/
├── unit/                   # Unit tests
│   ├── test_config.py
│   ├── test_auth.py
│   ├── test_api_client.py
│   └── tools/
│       ├── test_search_tools.py
│       ├── test_dashboard_tools.py
│       ├── test_metrics_tools.py
│       └── test_collector_tools.py
├── integration/            # Integration tests
│   ├── test_server.py
│   └── test_mcp_protocol.py
└── fixtures/              # Test fixtures and data
```

### Running Tests

```bash
# All tests
pytest

# Unit tests only
pytest tests/unit/

# Integration tests only
pytest tests/integration/

# Specific test file
pytest tests/unit/test_config.py

# With coverage
pytest --cov=sumologic_mcp --cov-report=html

# Parallel execution
pytest -n auto
```

### Test Configuration

Tests use separate configuration:

```bash
# Test environment variables
SUMOLOGIC_TEST_ACCESS_ID=test_id
SUMOLOGIC_TEST_ACCESS_KEY=test_key
SUMOLOGIC_TEST_ENDPOINT=https://api.sumologic.com
```

## Code Quality Standards

### Formatting

- **Black** for code formatting (line length: 88)
- **isort** for import sorting

```bash
# Format code
black sumologic_mcp/ tests/
isort sumologic_mcp/ tests/
```

### Linting

- **flake8** for linting
- **mypy** for type checking

```bash
# Lint code
flake8 sumologic_mcp/ tests/

# Type check
mypy sumologic_mcp/
```

### Pre-commit Hooks

Pre-commit hooks run automatically on commit:

- Code formatting (black, isort)
- Linting (flake8)
- Type checking (mypy)
- Test execution

```bash
# Run manually
pre-commit run --all-files
```

## Debugging

### Debug Logging

```bash
# Enable debug logging
export SUMOLOGIC_LOG_LEVEL=DEBUG
export SUMOLOGIC_LOG_FORMAT=text

# Run server
make run
```

### Debug Configuration

```bash
# Validate configuration with debug output
SUMOLOGIC_LOG_LEVEL=DEBUG make validate-config
```

### IDE Setup

#### VS Code

Recommended extensions:
- Python
- Pylance
- Black Formatter
- isort

Settings (`.vscode/settings.json`):
```json
{
    "python.defaultInterpreterPath": "./sumologic-mcp-env/bin/python",
    "python.formatting.provider": "black",
    "python.linting.enabled": true,
    "python.linting.flake8Enabled": true,
    "python.linting.mypyEnabled": true
}
```

#### PyCharm

1. Set interpreter to `./sumologic-mcp-env/bin/python`
2. Enable Black formatter
3. Configure flake8 and mypy

## Contributing

### Pull Request Process

1. **Fork** the repository
2. **Create** a feature branch
3. **Make** your changes
4. **Run** quality checks: `make all`
5. **Write** tests for new functionality
6. **Update** documentation
7. **Submit** pull request

### Code Review Checklist

- [ ] Code follows style guidelines
- [ ] Tests pass (`make test`)
- [ ] Code coverage maintained
- [ ] Documentation updated
- [ ] Type hints added
- [ ] Error handling implemented
- [ ] Logging added where appropriate

### Commit Messages

Use conventional commit format:

```
feat: add new search tool for log analysis
fix: resolve authentication timeout issue
docs: update API documentation
test: add unit tests for metrics tools
```

## Troubleshooting

### Common Issues

1. **Import errors**: Ensure package is installed in development mode
2. **Authentication failures**: Check credentials and endpoint
3. **Test failures**: Verify test environment configuration
4. **Type errors**: Run `mypy` to identify issues

### Getting Help

1. Check existing [issues](https://github.com/sumologic/sumologic-mcp-python/issues)
2. Review [documentation](docs/)
3. Run `make help` for available commands
4. Enable debug logging for detailed error information

## Release Process

### Version Management

1. Update version in `pyproject.toml`
2. Update `CHANGELOG.md`
3. Create git tag
4. Build and publish

```bash
# Build package
make build

# Check distribution
make check-dist

# Publish (maintainers only)
python -m twine upload dist/*
```