"""Configuration validation utilities for Sumo Logic MCP server."""

import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from pydantic import ValidationError

from .config import SumoLogicConfig


class ConfigurationValidator:
    """Comprehensive configuration validation and diagnostics."""
    
    def __init__(self):
        self.validation_results = {
            "valid": False,
            "errors": [],
            "warnings": [],
            "recommendations": [],
            "sources": {},
            "environment_check": {},
            "file_check": {}
        }
    
    def validate_environment_variables(self) -> Dict[str, Any]:
        """Check environment variables and their values."""
        env_check = {
            "variables_found": [],
            "variables_missing": [],
            "variables_invalid": [],
            "recommendations": []
        }
        
        # Required environment variables
        required_vars = [
            "SUMOLOGIC_ACCESS_ID",
            "SUMOLOGIC_ACCESS_KEY", 
            "SUMOLOGIC_ENDPOINT"
        ]
        
        # Optional environment variables with their expected types
        optional_vars = {
            "SUMOLOGIC_TIMEOUT": int,
            "SUMOLOGIC_MAX_RETRIES": int,
            "SUMOLOGIC_RATE_LIMIT_DELAY": float,
            "SUMOLOGIC_LOG_LEVEL": str,
            "SUMOLOGIC_LOG_FORMAT": str,
            "SUMOLOGIC_SERVER_NAME": str,
            "SUMOLOGIC_SERVER_VERSION": str
        }
        
        # Check required variables
        for var in required_vars:
            value = os.getenv(var)
            if value:
                env_check["variables_found"].append(var)
                # Basic validation
                if var == "SUMOLOGIC_ACCESS_ID" and len(value) != 14:
                    env_check["variables_invalid"].append({
                        "variable": var,
                        "issue": f"Should be 14 characters, got {len(value)}"
                    })
                elif var == "SUMOLOGIC_ACCESS_KEY" and len(value) < 20:
                    env_check["variables_invalid"].append({
                        "variable": var,
                        "issue": f"Should be at least 20 characters, got {len(value)}"
                    })
                elif var == "SUMOLOGIC_ENDPOINT" and not value.startswith("https://"):
                    env_check["variables_invalid"].append({
                        "variable": var,
                        "issue": "Should start with https://"
                    })
            else:
                env_check["variables_missing"].append(var)
        
        # Check optional variables
        for var, expected_type in optional_vars.items():
            value = os.getenv(var)
            if value:
                env_check["variables_found"].append(var)
                try:
                    if expected_type == int:
                        int(value)
                    elif expected_type == float:
                        float(value)
                    # str values are always valid
                except ValueError:
                    env_check["variables_invalid"].append({
                        "variable": var,
                        "issue": f"Invalid {expected_type.__name__} value: '{value}'"
                    })
        
        # Add recommendations
        if not env_check["variables_missing"]:
            env_check["recommendations"].append(
                "All required environment variables are set"
            )
        
        if "SUMOLOGIC_LOG_LEVEL" not in env_check["variables_found"]:
            env_check["recommendations"].append(
                "Consider setting SUMOLOGIC_LOG_LEVEL for explicit log control"
            )
        
        return env_check
    
    def validate_config_file(self, config_path: Optional[Path]) -> Dict[str, Any]:
        """Validate configuration file if provided."""
        file_check = {
            "exists": False,
            "readable": False,
            "valid_json": False,
            "valid_config": False,
            "errors": [],
            "warnings": []
        }
        
        if not config_path:
            return file_check
        
        # Check if file exists
        if config_path.exists():
            file_check["exists"] = True
        else:
            file_check["errors"].append(f"Configuration file not found: {config_path}")
            return file_check
        
        # Check if file is readable
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                content = f.read()
            file_check["readable"] = True
        except IOError as e:
            file_check["errors"].append(f"Cannot read configuration file: {e}")
            return file_check
        
        # Check if valid JSON
        try:
            config_data = json.loads(content)
            file_check["valid_json"] = True
        except json.JSONDecodeError as e:
            file_check["errors"].append(f"Invalid JSON: {e}")
            return file_check
        
        # Check if valid configuration
        try:
            SumoLogicConfig(**config_data)
            file_check["valid_config"] = True
        except ValidationError as e:
            file_check["errors"].append("Configuration validation failed:")
            for error in e.errors():
                field = " -> ".join(str(x) for x in error["loc"])
                message = error["msg"]
                file_check["errors"].append(f"  {field}: {message}")
        
        # Add warnings for missing recommended fields
        if isinstance(config_data, dict):
            if "timeout" not in config_data:
                file_check["warnings"].append("Consider setting 'timeout' explicitly")
            if "log_level" not in config_data:
                file_check["warnings"].append("Consider setting 'log_level' explicitly")
        
        return file_check
    
    def check_credential_format(self, access_id: str, access_key: str) -> List[Dict[str, str]]:
        """Check credential format and provide specific feedback."""
        issues = []
        
        if access_id:
            if len(access_id) != 14:
                issues.append({
                    "field": "access_id",
                    "issue": f"Should be exactly 14 characters, got {len(access_id)}",
                    "recommendation": "Check your Sumo Logic Access ID"
                })
            elif not access_id.isalnum():
                issues.append({
                    "field": "access_id", 
                    "issue": "Should contain only letters and numbers",
                    "recommendation": "Verify your Access ID format"
                })
        
        if access_key:
            if len(access_key) < 20:
                issues.append({
                    "field": "access_key",
                    "issue": f"Should be at least 20 characters, got {len(access_key)}",
                    "recommendation": "Check your Sumo Logic Access Key"
                })
        
        return issues
    
    def generate_configuration_report(
        self, 
        config_path: Optional[Path] = None,
        check_connection: bool = False
    ) -> Dict[str, Any]:
        """Generate comprehensive configuration validation report."""
        
        # Check environment variables
        env_check = self.validate_environment_variables()
        
        # Check configuration file if provided
        file_check = self.validate_config_file(config_path)
        
        # Try to load configuration
        config_valid = False
        config_errors = []
        config_warnings = []
        config_instance = None
        
        try:
            config_instance = SumoLogicConfig.from_env_and_file(config_path)
            config_valid = True
            
            # Get detailed validation
            validation = config_instance.validate_startup_configuration()
            config_errors = validation.get("errors", [])
            config_warnings = validation.get("warnings", [])
            
            # Check credential format
            credential_issues = self.check_credential_format(
                config_instance.access_id,
                config_instance.access_key
            )
            config_warnings.extend(credential_issues)
            
        except ValidationError as e:
            for error in e.errors():
                field = " -> ".join(str(x) for x in error["loc"])
                message = error["msg"]
                config_errors.append({
                    "field": field,
                    "message": message,
                    "category": "validation"
                })
        except Exception as e:
            config_errors.append({
                "field": "general",
                "message": str(e),
                "category": "loading"
            })
        
        # Compile final report
        report = {
            "overall_valid": config_valid and len(config_errors) == 0,
            "config_loaded": config_instance is not None,
            "environment_check": env_check,
            "file_check": file_check,
            "configuration": {
                "valid": config_valid,
                "errors": config_errors,
                "warnings": config_warnings,
                "instance": config_instance
            },
            "recommendations": self._generate_recommendations(
                env_check, file_check, config_errors, config_warnings
            )
        }
        
        return report
    
    def _generate_recommendations(
        self,
        env_check: Dict[str, Any],
        file_check: Dict[str, Any], 
        config_errors: List[Dict[str, Any]],
        config_warnings: List[Dict[str, Any]]
    ) -> List[str]:
        """Generate actionable recommendations based on validation results."""
        recommendations = []
        
        # Environment variable recommendations
        if env_check["variables_missing"]:
            recommendations.append(
                f"Set missing environment variables: {', '.join(env_check['variables_missing'])}"
            )
        
        if env_check["variables_invalid"]:
            recommendations.append(
                "Fix invalid environment variable values (see details above)"
            )
        
        # Configuration file recommendations
        if file_check.get("errors"):
            recommendations.append("Fix configuration file issues (see details above)")
        
        # General recommendations
        if not env_check["variables_missing"] and not config_errors:
            recommendations.append("Configuration looks good! You can start the server.")
        
        if len(config_warnings) > 0:
            recommendations.append("Review configuration warnings for optimal performance")
        
        # Security recommendations
        if "SUMOLOGIC_ACCESS_KEY" in env_check["variables_found"]:
            recommendations.append("Ensure access key is kept secure and not logged")
        
        return recommendations
    
    def print_detailed_report(self, config_path: Optional[Path] = None) -> bool:
        """Print a detailed configuration validation report."""
        report = self.generate_configuration_report(config_path)
        
        print("=" * 80)
        print("SUMO LOGIC MCP SERVER - DETAILED CONFIGURATION REPORT")
        print("=" * 80)
        
        # Overall status
        status = "✅ VALID" if report["overall_valid"] else "❌ INVALID"
        print(f"\nOverall Status: {status}")
        
        # Environment variables section
        print("\n" + "─" * 40)
        print("ENVIRONMENT VARIABLES")
        print("─" * 40)
        
        env = report["environment_check"]
        if env["variables_found"]:
            print(f"✅ Found: {', '.join(env['variables_found'])}")
        
        if env["variables_missing"]:
            print(f"❌ Missing: {', '.join(env['variables_missing'])}")
        
        if env["variables_invalid"]:
            print("⚠️  Invalid values:")
            for invalid in env["variables_invalid"]:
                print(f"   • {invalid['variable']}: {invalid['issue']}")
        
        # Configuration file section
        if config_path:
            print("\n" + "─" * 40)
            print("CONFIGURATION FILE")
            print("─" * 40)
            
            file_check = report["file_check"]
            print(f"File: {config_path}")
            print(f"Exists: {'✅' if file_check['exists'] else '❌'}")
            print(f"Readable: {'✅' if file_check['readable'] else '❌'}")
            print(f"Valid JSON: {'✅' if file_check['valid_json'] else '❌'}")
            print(f"Valid Config: {'✅' if file_check['valid_config'] else '❌'}")
            
            if file_check["errors"]:
                print("Errors:")
                for error in file_check["errors"]:
                    print(f"   • {error}")
            
            if file_check["warnings"]:
                print("Warnings:")
                for warning in file_check["warnings"]:
                    print(f"   • {warning}")
        
        # Configuration validation section
        print("\n" + "─" * 40)
        print("CONFIGURATION VALIDATION")
        print("─" * 40)
        
        config = report["configuration"]
        if config["errors"]:
            print("❌ Errors:")
            for error in config["errors"]:
                if isinstance(error, dict):
                    print(f"   • {error.get('field', 'unknown')}: {error.get('message', str(error))}")
                else:
                    print(f"   • {error}")
        
        if config["warnings"]:
            print("⚠️  Warnings:")
            for warning in config["warnings"]:
                if isinstance(warning, dict):
                    field = warning.get('field', 'unknown')
                    message = warning.get('message', str(warning))
                    print(f"   • {field}: {message}")
                    if 'recommendation' in warning:
                        print(f"     💡 {warning['recommendation']}")
                else:
                    print(f"   • {warning}")
        
        # Current configuration
        if config["instance"]:
            print("\n" + "─" * 40)
            print("CURRENT CONFIGURATION")
            print("─" * 40)
            
            cfg = config["instance"]
            print(f"Access ID: {'✓' if cfg.access_id else '✗'} {'(configured)' if cfg.access_id else '(missing)'}")
            print(f"Access Key: {'✓' if cfg.access_key else '✗'} {'(configured)' if cfg.access_key else '(missing)'}")
            print(f"Endpoint: {'✓' if cfg.endpoint else '✗'} {cfg.endpoint or '(missing)'}")
            print(f"Timeout: {cfg.timeout}s")
            print(f"Max Retries: {cfg.max_retries}")
            print(f"Rate Limit Delay: {cfg.rate_limit_delay}s")
            print(f"Log Level: {cfg.log_level}")
            print(f"Log Format: {cfg.log_format}")
        
        # Recommendations
        if report["recommendations"]:
            print("\n" + "─" * 40)
            print("RECOMMENDATIONS")
            print("─" * 40)
            
            for i, rec in enumerate(report["recommendations"], 1):
                print(f"{i}. {rec}")
        
        print("\n" + "=" * 80)
        
        return report["overall_valid"]


def main():
    """Command-line interface for configuration validation."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Validate Sumo Logic MCP Server configuration"
    )
    parser.add_argument(
        "--config-file",
        type=Path,
        help="Path to configuration file to validate"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results in JSON format"
    )
    
    args = parser.parse_args()
    
    validator = ConfigurationValidator()
    
    if args.json:
        report = validator.generate_configuration_report(args.config_file)
        print(json.dumps(report, indent=2, default=str))
    else:
        is_valid = validator.print_detailed_report(args.config_file)
        sys.exit(0 if is_valid else 1)


if __name__ == "__main__":
    main()