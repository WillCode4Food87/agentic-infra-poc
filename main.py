#!/usr/bin/env python3
"""
Infrastructure Orchestrator CLI

A Python-based CLI orchestrator to manage infrastructure actions,
configuration resolution, and tool validation.
"""

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# Optional imports with fallback
try:
    from dotenv import load_dotenv
    HAS_DOTENV = True
except ImportError:
    HAS_DOTENV = False

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


@dataclass
class OrchestratorConfig:
    """Configuration for infrastructure orchestrator."""
    
    # Azure settings
    subscription_id: Optional[str] = None
    location: str = "eastus"
    
    # Environment settings
    env_name: str = "dev"
    profile: str = "default"
    
    # Resource settings
    resources: dict[str, Any] = field(default_factory=dict)
    
    # Deployment settings
    dry_run: bool = False
    what_if: bool = False
    apply: bool = False
    destroy: bool = False
    
    # Additional parameters
    extra_params: dict[str, str] = field(default_factory=dict)
    
    def __post_init__(self):
        """Initialize default resources if not provided."""
        if not self.resources:
            self.resources = {
                'container_registry': {'enabled': True},
                'storage_account': {'enabled': True},
                'ai_services': {'enabled': True},
                'search_service': {'enabled': True},
            }


def load_env_file(env_path: Path = Path(".env.example")) -> dict[str, str]:
    """
    Load environment variables from .env file.
    
    Args:
        env_path: Path to the .env file
        
    Returns:
        Dictionary of environment variables
    """
    env_vars = {}
    
    if HAS_DOTENV and env_path.exists():
        load_dotenv(env_path)
        # Read the file to get the variables
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    # Get from environment or use the value from file
                    env_vars[key.strip()] = os.getenv(key.strip(), value.strip())
    elif env_path.exists():
        # Manual parsing if dotenv not available
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    env_vars[key.strip()] = value.strip()
    
    return env_vars


def load_yaml_config(config_path: Path = Path("config.yaml")) -> dict[str, Any]:
    """
    Load configuration from YAML file.
    
    Args:
        config_path: Path to the YAML config file
        
    Returns:
        Dictionary of configuration values
    """
    if HAS_YAML and config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    elif config_path.exists():
        print(f"Warning: YAML library not available, skipping {config_path}")
    
    return {}


def resolve_config(args: argparse.Namespace) -> OrchestratorConfig:
    """
    Resolve configuration from multiple sources.
    
    Priority (highest to lowest):
    1. Command-line arguments
    2. Environment variables (.env)
    3. YAML configuration (config.yaml)
    4. Default values
    
    Args:
        args: Parsed command-line arguments
        
    Returns:
        OrchestratorConfig with merged configuration
    """
    # Load from files
    env_vars = load_env_file(Path(".env") if Path(".env").exists() else Path(".env.example"))
    yaml_config = load_yaml_config()
    
    # Start with defaults from YAML
    azure_config = yaml_config.get('azure', {})
    env_config = yaml_config.get('environment', {})
    resources_config = yaml_config.get('resources', {})
    deployment_config = yaml_config.get('deployment', {})
    
    # Build configuration with priority: CLI > ENV > YAML > Defaults
    config = OrchestratorConfig(
        # Azure settings
        subscription_id=(
            args.subscription or
            env_vars.get('AZURE_SUBSCRIPTION_ID') or
            azure_config.get('subscription_id')
        ),
        location=(
            args.location or
            env_vars.get('AZURE_LOCATION') or
            azure_config.get('location', 'eastus')
        ),
        
        # Environment settings
        env_name=(
            args.env or
            env_vars.get('AZURE_ENV_NAME') or
            env_config.get('name', 'dev')
        ),
        profile=(
            args.profile or
            env_vars.get('PROFILE') or
            env_config.get('profile', 'default')
        ),
        
        # Resource settings
        resources=resources_config if args.resources else resources_config,
        
        # Deployment settings
        dry_run=args.dry_run or deployment_config.get('dry_run', False),
        what_if=args.what_if or deployment_config.get('what_if', False),
        apply=args.apply,
        destroy=args.destroy,
    )
    
    # Add extra parameters from --set flags
    if args.set:
        for param in args.set:
            if '=' in param:
                key, value = param.split('=', 1)
                config.extra_params[key] = value
    
    return config


def run(command: list[str], capture: bool = True, check: bool = False) -> subprocess.CompletedProcess:
    """
    Run a shell command.
    
    Args:
        command: Command and arguments as a list
        capture: Whether to capture output
        check: Whether to raise exception on non-zero exit
        
    Returns:
        CompletedProcess with command results
    """
    try:
        if capture:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=check
            )
        else:
            result = subprocess.run(command, check=check)
        return result
    except FileNotFoundError:
        # Command not found
        return subprocess.CompletedProcess(
            args=command,
            returncode=127,
            stdout="",
            stderr=f"Command not found: {command[0]}"
        )
    except subprocess.CalledProcessError as e:
        if not check:
            return subprocess.CompletedProcess(
                args=command,
                returncode=e.returncode,
                stdout=e.stdout if hasattr(e, 'stdout') else "",
                stderr=e.stderr if hasattr(e, 'stderr') else ""
            )
        raise


def require_tools(tools: Optional[list[str]] = None) -> dict[str, bool]:
    """
    Check if required tools are installed.
    
    Args:
        tools: List of tool names to check (defaults to required tools from config)
        
    Returns:
        Dictionary mapping tool names to availability status
    """
    if tools is None:
        tools = ['az', 'azd', 'bicep']
    
    results = {}
    
    for tool in tools:
        # Check if tool exists
        if tool == 'bicep':
            # Bicep is usually checked via az bicep version
            result = run(['az', 'bicep', 'version'], capture=True)
            results[tool] = result.returncode == 0
        else:
            result = run([tool, '--version'], capture=True)
            results[tool] = result.returncode == 0
    
    return results


def get_tool_version(tool: str) -> Optional[str]:
    """
    Get the version of a tool.
    
    Args:
        tool: Tool name
        
    Returns:
        Version string or None if not available
    """
    try:
        if tool == 'bicep':
            result = run(['az', 'bicep', 'version'], capture=True)
        else:
            result = run([tool, '--version'], capture=True)
        
        if result.returncode == 0:
            output = result.stdout.strip()
            # Return first line of output
            return output.split('\n')[0] if output else None
    except Exception:
        pass
    
    return None


def azd_env_set(key: str, value: str, env_name: Optional[str] = None) -> bool:
    """
    Set an azd environment variable.
    
    Args:
        key: Environment variable key
        value: Environment variable value
        env_name: Optional environment name
        
    Returns:
        True if successful, False otherwise
    """
    cmd = ['azd', 'env', 'set', key, value]
    if env_name:
        cmd.extend(['-e', env_name])
    
    result = run(cmd, capture=True)
    return result.returncode == 0


def azd_env_get_values(env_name: Optional[str] = None) -> dict[str, str]:
    """
    Get all azd environment variables.
    
    Args:
        env_name: Optional environment name
        
    Returns:
        Dictionary of environment variables
    """
    cmd = ['azd', 'env', 'get-values']
    if env_name:
        cmd.extend(['-e', env_name])
    
    result = run(cmd, capture=True)
    
    env_vars = {}
    if result.returncode == 0:
        for line in result.stdout.split('\n'):
            line = line.strip()
            if line and '=' in line:
                key, value = line.split('=', 1)
                # Remove quotes if present
                value = value.strip('"').strip("'")
                env_vars[key] = value
    
    return env_vars


def bicep_validate(bicep_file: Path) -> bool:
    """
    Validate a Bicep file.
    
    Args:
        bicep_file: Path to Bicep file
        
    Returns:
        True if valid, False otherwise
    """
    if not bicep_file.exists():
        print(f"Error: Bicep file not found: {bicep_file}")
        return False
    
    result = run(['az', 'bicep', 'build', '--file', str(bicep_file), '--stdout'], capture=True)
    
    if result.returncode == 0:
        print(f"✓ Bicep file is valid: {bicep_file}")
        return True
    else:
        print(f"✗ Bicep validation failed: {bicep_file}")
        if result.stderr:
            print(f"Error: {result.stderr}")
        return False


def build_infra_params(config: OrchestratorConfig) -> dict[str, Any]:
    """
    Build infrastructure parameters from configuration.
    
    Args:
        config: OrchestratorConfig instance
        
    Returns:
        Dictionary of infrastructure parameters
    """
    params = {
        'location': config.location,
        'environmentName': config.env_name,
    }
    
    # Add subscription if provided
    if config.subscription_id:
        params['subscriptionId'] = config.subscription_id
    
    # Add resource-specific parameters
    for resource_name, resource_config in config.resources.items():
        if isinstance(resource_config, dict) and resource_config.get('enabled', True):
            # Convert resource name to parameter format
            # e.g., container_registry -> containerRegistry
            param_name = ''.join(word.capitalize() for word in resource_name.split('_'))
            param_name = param_name[0].lower() + param_name[1:]  # camelCase
            
            # Add enabled flag or specific config
            if 'sku' in resource_config:
                params[f"{param_name}Sku"] = resource_config['sku']
    
    # Add extra parameters
    params.update(config.extra_params)
    
    return params


def print_config(config: OrchestratorConfig):
    """Print the resolved configuration."""
    print("\n" + "="*60)
    print("RESOLVED CONFIGURATION")
    print("="*60)
    
    print("\nAzure Settings:")
    print(f"  Subscription ID: {config.subscription_id or '(not set)'}")
    print(f"  Location:        {config.location}")
    
    print("\nEnvironment Settings:")
    print(f"  Environment:     {config.env_name}")
    print(f"  Profile:         {config.profile}")
    
    print("\nDeployment Settings:")
    print(f"  Dry Run:         {config.dry_run}")
    print(f"  What-If:         {config.what_if}")
    print(f"  Apply:           {config.apply}")
    print(f"  Destroy:         {config.destroy}")
    
    print("\nResources:")
    for name, res_config in config.resources.items():
        if isinstance(res_config, dict):
            enabled = res_config.get('enabled', True)
            print(f"  {name:20s} {'enabled' if enabled else 'disabled'}")
    
    if config.extra_params:
        print("\nExtra Parameters:")
        for key, value in config.extra_params.items():
            print(f"  {key}: {value}")
    
    print("\nInfrastructure Parameters:")
    params = build_infra_params(config)
    print(json.dumps(params, indent=2))
    
    print("="*60 + "\n")


def check_tools():
    """Check and print status of required tools."""
    print("\n" + "="*60)
    print("TOOL VALIDATION")
    print("="*60 + "\n")
    
    tools = ['az', 'azd', 'bicep', 'docker', 'git']
    results = require_tools(tools)
    
    all_required_available = True
    required_tools = ['az', 'azd', 'bicep']
    
    for tool in tools:
        is_required = tool in required_tools
        available = results.get(tool, False)
        status = "✓" if available else "✗"
        req_marker = "[REQUIRED]" if is_required else "[OPTIONAL]"
        
        version = ""
        if available:
            version_str = get_tool_version(tool)
            if version_str:
                version = f" - {version_str}"
        
        print(f"{status} {tool:15s} {req_marker:12s} {version}")
        
        if is_required and not available:
            all_required_available = False
    
    print("\n" + "="*60 + "\n")
    
    if not all_required_available:
        print("Warning: Some required tools are not available!")
        return False
    
    return True


def validate_bicep_files():
    """Validate Bicep files in the infra directory."""
    print("\n" + "="*60)
    print("BICEP VALIDATION")
    print("="*60 + "\n")
    
    infra_dir = Path("infra")
    if not infra_dir.exists():
        print("Warning: infra directory not found")
        return False
    
    bicep_files = list(infra_dir.glob("*.bicep"))
    
    if not bicep_files:
        print("Warning: No Bicep files found in infra directory")
        return False
    
    all_valid = True
    for bicep_file in bicep_files:
        if not bicep_validate(bicep_file):
            all_valid = False
    
    print("\n" + "="*60 + "\n")
    
    return all_valid


def main():
    """Main entry point for the CLI orchestrator."""
    parser = argparse.ArgumentParser(
        description="Infrastructure Orchestrator - Manage Azure infrastructure provisioning",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Show help
  python main.py -h
  
  # Dry run with tool checks
  python main.py --dry-run
  
  # Preview changes (what-if mode)
  python main.py --what-if --location westus
  
  # Apply infrastructure changes
  python main.py --apply --env prod --location eastus2
  
  # Destroy infrastructure
  python main.py --destroy --env dev
  
  # Set custom parameters
  python main.py --apply --set modelName=gpt-4 --set capacity=10
        """
    )
    
    # Action flags
    action_group = parser.add_argument_group('action flags')
    action_group.add_argument(
        '--dry-run',
        action='store_true',
        help='Validate configuration and check tools without making changes'
    )
    action_group.add_argument(
        '--what-if',
        action='store_true',
        help='Preview what changes would be made without applying them'
    )
    action_group.add_argument(
        '--apply',
        action='store_true',
        help='Apply infrastructure changes'
    )
    action_group.add_argument(
        '--destroy',
        action='store_true',
        help='Destroy infrastructure resources'
    )
    
    # Configuration flags
    config_group = parser.add_argument_group('configuration flags')
    config_group.add_argument(
        '--resources',
        action='store_true',
        help='Show available resources'
    )
    config_group.add_argument(
        '--profile',
        type=str,
        help='Configuration profile to use'
    )
    config_group.add_argument(
        '--env',
        type=str,
        help='Environment name (e.g., dev, staging, prod)'
    )
    config_group.add_argument(
        '--location',
        type=str,
        help='Azure region for resources'
    )
    config_group.add_argument(
        '--subscription',
        type=str,
        help='Azure subscription ID'
    )
    config_group.add_argument(
        '--set',
        action='append',
        metavar='KEY=VALUE',
        help='Set additional parameters (can be used multiple times)'
    )
    
    args = parser.parse_args()
    
    # Resolve configuration
    config = resolve_config(args)
    
    # Print configuration
    print_config(config)
    
    # Dry run mode: check tools and validate
    if config.dry_run:
        print("Running in DRY-RUN mode - no changes will be made\n")
        check_tools()
        validate_bicep_files()
        return 0
    
    # What-if mode
    if config.what_if:
        print("Running in WHAT-IF mode - previewing changes\n")
        check_tools()
        validate_bicep_files()
        print("Note: Actual what-if analysis requires Azure provisioning (not yet implemented)")
        return 0
    
    # Apply mode
    if config.apply:
        print("APPLY mode requested")
        print("Note: Actual provisioning not yet implemented (configuration and validation only)")
        return 0
    
    # Destroy mode
    if config.destroy:
        print("DESTROY mode requested")
        print("Note: Actual resource destruction not yet implemented (configuration and validation only)")
        return 0
    
    # Default: just show configuration
    return 0


if __name__ == '__main__':
    sys.exit(main())
