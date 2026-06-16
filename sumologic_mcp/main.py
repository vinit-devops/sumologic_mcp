"""Main entry point for Sumo Logic MCP server."""

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path
from typing import Optional

import structlog
from pydantic import ValidationError

from .config import SumoLogicConfig
from .exceptions import SumoLogicError
from .server import SumoLogicMCPServer


def setup_logging(config: SumoLogicConfig) -> None:
    """Set up structured logging based on configuration."""
    # Set the root logger level
    logging.basicConfig(level=getattr(logging, config.log_level))

    processors = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if config.log_format == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Sumo Logic MCP Server - Model Context Protocol server for Sumo Logic",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Environment Variables:
  SUMOLOGIC_ACCESS_ID       Sumo Logic Access ID (required)
  SUMOLOGIC_ACCESS_KEY      Sumo Logic Access Key (required)
  SUMOLOGIC_ENDPOINT        Sumo Logic API endpoint (required)
  SUMOLOGIC_TIMEOUT         Request timeout in seconds (default: 30)
  SUMOLOGIC_MAX_RETRIES     Maximum retry attempts (default: 3)
  SUMOLOGIC_RATE_LIMIT_DELAY Rate limit delay in seconds (default: 1.0)
  SUMOLOGIC_LOG_LEVEL       Log level: DEBUG, INFO, WARNING, ERROR, CRITICAL (default: INFO)
  SUMOLOGIC_LOG_FORMAT      Log format: json, text (default: json)
  SUMOLOGIC_SERVER_NAME     MCP server name (default: sumologic-mcp-server)
  SUMOLOGIC_SERVER_VERSION  MCP server version (default: 0.1.0)

Examples:
  # Start server with environment variables
  export SUMOLOGIC_ACCESS_ID="your_access_id"
  export SUMOLOGIC_ACCESS_KEY="your_access_key"
  export SUMOLOGIC_ENDPOINT="https://api.sumologic.com"
  python -m sumologic_mcp

  # Start server with custom log level
  SUMOLOGIC_LOG_LEVEL=DEBUG python -m sumologic_mcp

  # Start server with text logging format
  SUMOLOGIC_LOG_FORMAT=text python -m sumologic_mcp
        """,
    )

    parser.add_argument(
        "--config-file",
        type=Path,
        help="Path to configuration file (optional, environment variables take precedence)",
    )

    parser.add_argument(
        "--validate-config", action="store_true", help="Validate configuration and exit"
    )

    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Override log level from environment",
    )

    parser.add_argument(
        "--log-format",
        choices=["json", "text"],
        help="Override log format from environment",
    )

    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")

    # Subcommands
    subparsers = parser.add_subparsers(dest="command", help="Subcommands")

    # 'api' subcommand
    api_parser = subparsers.add_parser(
        "api", help="Execute a raw HTTP request to any Sumo Logic API endpoint"
    )
    api_parser.add_argument(
        "-X",
        "--method",
        choices=["GET", "POST", "PUT", "DELETE", "PATCH"],
        default="GET",
        help="HTTP Method (default: GET)",
    )
    api_parser.add_argument("path", help="API endpoint path (e.g., /v1/users)")
    api_parser.add_argument(
        "-b", "--body", help="JSON string body for POST/PUT/PATCH/DELETE requests"
    )
    api_parser.add_argument(
        "-p", "--param", action="append", help="Query parameters in KEY=VALUE format"
    )
    api_parser.add_argument(
        "-H",
        "--header",
        action="append",
        help="Custom headers in KEY=VALUE or KEY:VALUE format",
    )

    return parser.parse_args()


def load_configuration(args: argparse.Namespace) -> SumoLogicConfig:
    """Load and validate configuration from environment and arguments."""
    try:
        # Load configuration from environment and optional config file
        config = SumoLogicConfig.from_env_and_file(args.config_file)

        # Override with command-line arguments if provided
        if args.log_level:
            config.log_level = args.log_level
        if args.log_format:
            config.log_format = args.log_format

        return config

    except ValidationError as e:
        print("=" * 60, file=sys.stderr)
        print("CONFIGURATION VALIDATION ERROR", file=sys.stderr)
        print("=" * 60, file=sys.stderr)

        print("\nThe following configuration errors were found:", file=sys.stderr)
        for error in e.errors():
            field = " -> ".join(str(x) for x in error["loc"])
            message = error["msg"]
            print(f"  ❌ {field}: {message}", file=sys.stderr)

        print("\n" + "=" * 60, file=sys.stderr)
        print("CONFIGURATION HELP", file=sys.stderr)
        print("=" * 60, file=sys.stderr)

        print("\n1. Required Environment Variables:", file=sys.stderr)
        print("   export SUMOLOGIC_ACCESS_ID='your_access_id_here'", file=sys.stderr)
        print("   export SUMOLOGIC_ACCESS_KEY='your_access_key_here'", file=sys.stderr)
        print(
            "   export SUMOLOGIC_ENDPOINT='https://api.sumologic.com'", file=sys.stderr
        )

        print("\n2. Optional Environment Variables:", file=sys.stderr)
        print("   export SUMOLOGIC_TIMEOUT=30", file=sys.stderr)
        print("   export SUMOLOGIC_MAX_RETRIES=3", file=sys.stderr)
        print("   export SUMOLOGIC_RATE_LIMIT_DELAY=1.0", file=sys.stderr)
        print("   export SUMOLOGIC_LOG_LEVEL=INFO", file=sys.stderr)
        print("   export SUMOLOGIC_LOG_FORMAT=json", file=sys.stderr)

        if args.config_file:
            print(f"\n3. Configuration File: {args.config_file}", file=sys.stderr)
            print(
                "   Note: Environment variables take precedence over config file values.",
                file=sys.stderr,
            )
        else:
            print("\n3. Alternative: Use a JSON configuration file", file=sys.stderr)
            print("   Create config.json with:", file=sys.stderr)
            print("   {", file=sys.stderr)
            print('     "access_id": "your_access_id",', file=sys.stderr)
            print('     "access_key": "your_access_key",', file=sys.stderr)
            print('     "endpoint": "https://api.sumologic.com"', file=sys.stderr)
            print("   }", file=sys.stderr)
            print(
                "   Then run: python -m sumologic_mcp --config-file config.json",
                file=sys.stderr,
            )

        print("\n4. Validate Configuration:", file=sys.stderr)
        print("   python -m sumologic_mcp --validate-config", file=sys.stderr)

        print("\n5. Get Help:", file=sys.stderr)
        print("   python -m sumologic_mcp --help", file=sys.stderr)

        print("=" * 60, file=sys.stderr)
        sys.exit(1)

    except FileNotFoundError as e:
        print(f"❌ Configuration file error: {e}", file=sys.stderr)
        print("\nEither:", file=sys.stderr)
        print(
            "  • Remove --config-file option to use environment variables only",
            file=sys.stderr,
        )
        print("  • Create the specified configuration file", file=sys.stderr)
        print("  • Use a different path with --config-file", file=sys.stderr)
        sys.exit(1)

    except ValueError as e:
        print(f"❌ Configuration error: {e}", file=sys.stderr)
        print(
            "\nPlease check your configuration file format and environment variable values.",
            file=sys.stderr,
        )
        sys.exit(1)

    except Exception as e:
        print(f"❌ Unexpected error loading configuration: {e}", file=sys.stderr)
        print("Please check your configuration and try again.", file=sys.stderr)
        sys.exit(1)


def validate_configuration(config: SumoLogicConfig) -> None:
    """Validate configuration and print comprehensive results."""
    print("=" * 60)
    print("SUMO LOGIC MCP SERVER - CONFIGURATION VALIDATION")
    print("=" * 60)

    # Get comprehensive validation results
    validation = config.validate_startup_configuration()

    # Print configuration sources
    if hasattr(config, "_config_sources"):
        sources = config._config_sources
        print("\nConfiguration Sources:")
        if sources.get("file_loaded"):
            print(f"  📄 Config file: {sources['file_path']}")
        if sources.get("env_vars_found"):
            print(f"  🌍 Environment variables: {', '.join(sources['env_vars_found'])}")
        if sources.get("defaults_used"):
            defaults = validation["config_sources"]["defaults_used"]
            if defaults:
                print(f"  ⚙️  Using defaults for: {', '.join(defaults)}")

    # Print current configuration
    print("\nCurrent Configuration:")
    print(
        f"  Access ID: {'✓' if config.access_id else '✗'} {'(configured)' if config.access_id else '(missing)'}"
    )
    print(
        f"  Access Key: {'✓' if config.access_key else '✗'} {'(configured)' if config.access_key else '(missing)'}"
    )
    print(
        f"  Endpoint: {'✓' if config.endpoint else '✗'} {config.endpoint or '(missing)'}"
    )
    print(f"  Timeout: {config.timeout}s")
    print(f"  Max Retries: {config.max_retries}")
    print(f"  Rate Limit Delay: {config.rate_limit_delay}s")
    print(f"  Log Level: {config.log_level}")
    print(f"  Log Format: {config.log_format}")
    print(f"  Server Name: {config.server_name}")
    print(f"  Server Version: {config.server_version}")

    # Print validation errors
    if validation["errors"]:
        print("\n❌ CONFIGURATION ERRORS:")
        for error in validation["errors"]:
            print(f"  • {error['field']}: {error['message']}")

    # Print warnings
    if validation["warnings"]:
        print("\n⚠️  CONFIGURATION WARNINGS:")
        for warning in validation["warnings"]:
            print(f"  • {warning['field']}: {warning['message']}")
            if "recommendation" in warning:
                print(f"    💡 Recommendation: {warning['recommendation']}")

    # Print recommendations
    if validation["recommendations"]:
        print("\n💡 RECOMMENDATIONS:")
        for rec in validation["recommendations"]:
            print(f"  • {rec['field']}: {rec['message']}")
            if "recommendation" in rec:
                print(f"    {rec['recommendation']}")

    # Print final status
    print("\n" + "=" * 60)
    if validation["valid"]:
        print("✅ CONFIGURATION IS VALID - Server can start")
        print("\nTo start the server:")
        print("  python -m sumologic_mcp")
    else:
        print("❌ CONFIGURATION IS INVALID - Please fix the errors above")
        print("\nRequired environment variables:")
        print("  export SUMOLOGIC_ACCESS_ID='your_access_id'")
        print("  export SUMOLOGIC_ACCESS_KEY='your_access_key'")
        print("  export SUMOLOGIC_ENDPOINT='https://api.sumologic.com'")
        print("\nOr create a config.json file with:")
        print(
            '  {"access_id": "your_id", "access_key": "your_key", "endpoint": "https://api.sumologic.com"}'
        )
        sys.exit(1)
    print("=" * 60)


class GracefulShutdown:
    """Handle graceful shutdown of the server."""

    def __init__(self):
        self.shutdown_event = asyncio.Event()
        self.server: Optional[SumoLogicMCPServer] = None
        self.logger = structlog.get_logger(__name__)

    def setup_signal_handlers(self) -> None:
        """Set up signal handlers for graceful shutdown."""
        if sys.platform != "win32":
            # Unix-like systems
            loop = asyncio.get_event_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, self.signal_handler, sig)
        else:
            # Windows
            signal.signal(signal.SIGINT, self._windows_signal_handler)
            signal.signal(signal.SIGTERM, self._windows_signal_handler)

    def signal_handler(self, signum: int) -> None:
        """Handle shutdown signals."""
        self.logger.info(f"Received signal {signum}, initiating graceful shutdown")
        self.shutdown_event.set()

    def _windows_signal_handler(self, signum: int, frame) -> None:
        """Handle shutdown signals on Windows."""
        self.signal_handler(signum)

    async def shutdown(self) -> None:
        """Perform graceful shutdown."""
        self.logger.info("Starting graceful shutdown")

        if self.server:
            try:
                await self.server.shutdown()
                self.logger.info("Server shutdown completed")
            except Exception as e:
                self.logger.error("Error during server shutdown", error=str(e))

        # Cancel all remaining tasks
        tasks = [
            task for task in asyncio.all_tasks() if task is not asyncio.current_task()
        ]
        if tasks:
            self.logger.info(f"Cancelling {len(tasks)} remaining tasks")
            for task in tasks:
                task.cancel()

            await asyncio.gather(*tasks, return_exceptions=True)

        self.logger.info("Graceful shutdown completed")


async def main_async(args: argparse.Namespace) -> None:
    """Async main function."""
    # Load configuration
    config = load_configuration(args)

    # If validation requested, validate and exit
    if args.validate_config:
        validate_configuration(config)
        return

    # Perform startup configuration validation
    validation = config.validate_startup_configuration()
    if not validation["valid"]:
        print("❌ Configuration validation failed:", file=sys.stderr)
        for error in validation["errors"]:
            print(f"  • {error['field']}: {error['message']}", file=sys.stderr)
        print(
            "\nRun with --validate-config for detailed validation information.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Set up logging
    setup_logging(config)
    logger = structlog.get_logger(__name__)

    # Log configuration warnings if any
    if validation["warnings"]:
        for warning in validation["warnings"]:
            logger.warning(
                "Configuration warning",
                field=warning["field"],
                message=warning["message"],
                recommendation=warning.get("recommendation"),
            )

    # Set up graceful shutdown
    shutdown_handler = GracefulShutdown()
    shutdown_handler.setup_signal_handlers()

    try:
        logger.info(
            "Initializing Sumo Logic MCP server",
            server_name=config.server_name,
            server_version=config.server_version,
            endpoint=config.endpoint,
            timeout=config.timeout,
            max_retries=config.max_retries,
            rate_limit_delay=config.rate_limit_delay,
        )

        # Create and start server
        server = SumoLogicMCPServer(config)
        shutdown_handler.server = server

        await server.start()

        logger.info("Sumo Logic MCP server started successfully")

        # Run the MCP server with stdio transport for client communication
        await server.run_stdio()

    except SumoLogicError as e:
        logger.error("Sumo Logic specific error", error=str(e))
        sys.exit(1)
    except Exception as e:
        logger.error("Failed to start server", error=str(e), exc_info=True)
        sys.exit(1)
    finally:
        await shutdown_handler.shutdown()


async def run_api_command(args: argparse.Namespace) -> None:
    """Execute a raw API request and print the results."""
    import json

    from .api_client import SumoLogicAPIClient
    from .auth import SumoLogicAuth

    # Load configuration
    config = load_configuration(args)

    # Validate configuration
    validation = config.validate_startup_configuration()
    if not validation["valid"]:
        print("❌ Configuration validation failed:", file=sys.stderr)
        for error in validation["errors"]:
            print(f"  • {error['field']}: {error['message']}", file=sys.stderr)
        sys.exit(1)

    # For CLI api commands, default to WARNING log level to keep stdout/stderr clean, unless explicitly overridden
    if not args.log_level:
        config.log_level = "WARNING"

    # Set up logging
    setup_logging(config)

    # Parse query parameters from -p/--param
    params = {}
    if args.param:
        for p in args.param:
            if "=" in p:
                k, v = p.split("=", 1)
                params[k] = v
            else:
                params[p] = ""

    # Parse headers from -H/--header
    headers = {}
    if args.header:
        for h in args.header:
            if "=" in h:
                k, v = h.split("=", 1)
                headers[k] = v
            elif ":" in h:
                k, v = h.split(":", 1)
                headers[k.strip()] = v.strip()
            else:
                headers[h] = ""

    # Parse request body from -b/--body
    body = None
    if args.body:
        try:
            body = json.loads(args.body)
        except json.JSONDecodeError as e:
            print(f"❌ Error: Invalid JSON body: {e}", file=sys.stderr)
            sys.exit(1)

    # Instantiate client and make request
    auth = SumoLogicAuth(config)
    async with SumoLogicAPIClient(config, auth) as client:
        try:
            result = await client.execute_raw_request(
                method=args.method,
                path=args.path,
                params=params,
                body=body,
                headers=headers,
            )

            status_code = result["status_code"]
            response_body = result["body"]

            if 200 <= status_code < 300:
                if isinstance(response_body, (dict, list)):
                    print(json.dumps(response_body, indent=2))
                elif response_body:
                    print(response_body)
                else:
                    print(f"Status: {status_code} OK (No Content)", file=sys.stderr)
            else:
                print(f"❌ Request failed with status {status_code}", file=sys.stderr)
                if isinstance(response_body, (dict, list)):
                    print(json.dumps(response_body, indent=2), file=sys.stderr)
                elif response_body:
                    print(response_body, file=sys.stderr)
                sys.exit(1)

        except Exception as e:
            print(f"❌ Error executing request: {e}", file=sys.stderr)
            sys.exit(1)


def main() -> None:
    """Main entry point for the server."""
    try:
        args = parse_arguments()
        if args.command == "api":
            asyncio.run(run_api_command(args))
        else:
            asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\nShutdown complete")
        sys.exit(0)
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
