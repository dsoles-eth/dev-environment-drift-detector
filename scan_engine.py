from __future__ import annotations

import os
import sys
import subprocess
import threading
import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime

import yaml
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from git import Repo, GitCommandError, InvalidGitRepositoryError
import click

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    """Represents the outcome of a scanning operation."""
    timestamp: datetime = field(default_factory=datetime.now)
    success: bool = True
    message: str = ""
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "success": self.success,
            "message": self.message,
            "data": self.data
        }


@dataclass
class DriftConfig:
    """Configuration for the drift scanning engine."""
    path: str = "."
    watch_patterns: List[str] = field(default_factory=lambda: ["*.py", "*.txt", "*.yml", "*.yaml"])
    config_file: str = ".drift_config.yml"

    @classmethod
    def load(cls, file_path: Optional[str] = None) -> DriftConfig:
        path = file_path or ".drift_config.yml"
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    config_dict = yaml.safe_load(f) or {}
                    return cls(**config_dict)
            except Exception as e:
                logger.warning(f"Failed to load config {path}: {e}")
        return cls()


class ScanResultData:
    """Wrapper for collected scan data."""
    def __init__(self):
        self.dependencies: List[Dict[str, str]] = []
        self.environment_variables: Dict[str, str] = {}
        self.git_status: Dict[str, Any] = {}
        self.system_configs: Dict[str, str] = {}


class DriftScanner:
    """Engine for scanning local development environment drift."""

    def __init__(self, base_path: str = "."):
        """Initialize the scanner with a base directory."""
        self.base_path = os.path.abspath(base_path)
        self.config = DriftConfig.load(os.path.join(base_path, ".drift_config.yml"))

    def _run_subprocess(self, command: List[str], timeout: int = 30) -> Tuple[bool, str]:
        """Helper to run subprocess commands safely."""
        try:
            result = subprocess.run(
                command,
                cwd=self.base_path,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return result.returncode == 0, result.stdout
        except subprocess.TimeoutExpired:
            return False, "Command timed out."
        except FileNotFoundError:
            return False, "Command not found."
        except Exception as e:
            return False, str(e)

    def scan_dependencies(self) -> ScanResult:
        """
        Scans the current Python environment dependencies.
        
        Checks for installed packages using pip and parses requirements files.
        
        Returns:
            ScanResult: Result object containing dependency list and metadata.
        """
        data = []
        success = True
        message = "Dependencies scanned successfully."

        # Scan pip list
        success_pip, stdout = self._run_subprocess(["pip", "list", "--format=json"])
        if success_pip:
            try:
                import json
                deps = json.loads(stdout)
                for pkg in deps:
                    data.append({
                        "name": pkg.get("name", ""),
                        "version": pkg.get("version", "")
                    })
            except json.JSONDecodeError as e:
                success = False
                message = f"Failed to parse pip output: {e}"

        # Scan requirements.txt
        req_file = os.path.join(self.base_path, "requirements.txt")
        if os.path.exists(req_file):
            try:
                with open(req_file, "r") as f:
                    lines = f.readlines()
                    for line in lines:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            if "==" in line:
                                name, version = line.split("==")
                                data.append({"name": name, "version": version, "source": "requirements.txt"})
                            else:
                                data.append({"name": line.split(">=")[0].split("<=")[0], "version": "N/A", "source": "requirements.txt"})
            except IOError as e:
                message = f"Could not read requirements.txt: {e}"
                success = False

        return ScanResult(success=success, message=message, data={"dependencies": data})

    def scan_environment_variables(self) -> ScanResult:
        """
        Scans critical environment variables relevant to development.
        
        Checks for common dev tools, SDKs, and credentials flags.
        
        Returns:
            ScanResult: Result object containing environment data and metadata.
        """
        target_vars = [
            "PATH", "HOME", "USER", "LANG", "SHELL",
            "PYTHON_VERSION", "NODE_ENV", "AWS_PROFILE"
        ]
        collected = {}
        success = True
        message = "Environment variables scanned."

        for var in target_vars:
            val = os.environ.get(var)
            if val is not None:
                # Mask common sensitive-looking values
                if var in ["AWS_PROFILE", "PATH"]:
                    collected[var] = val
                else:
                    collected[var] = val
        
        return ScanResult(success=success, message=message, data={"env": collected})

    def scan_git_status(self) -> ScanResult:
        """
        Scans the current Git repository state for drift.
        
        Identifies uncommitted changes and current branch.
        
        Returns:
            ScanResult: Result object containing git status and metadata.
        """
        result_data = {"branch": None, "dirty": False, "untracked": [], "status": "Not a git repo"}
        success = True
        message = "Git scan completed."

        try:
            repo = Repo(self.base_path, search_parent_directories=True)
            if not repo:
                raise InvalidGitRepositoryError("Repo not found.")
            
            result_data["branch"] = repo.active_branch.name if repo.head.is_detached else repo.active_branch.name
            result_data["status"] = "OK"

            status = repo.git.status()
            if status:
                result_data["dirty"] = True
                for line in status.splitlines():
                    if line.startswith("??"):
                        result_data["untracked"].append(line.split("??", 1)[1].strip())
                    
        except InvalidGitRepositoryError:
            success = True
            message = "Not a Git repository."
            result_data["status"] = "No Repo"
        except GitCommandError as e:
            success = False
            message = f"Git command error: {e}"
        except Exception as e:
            success = False
            message = f"Failed to scan git status: {e}"

        return ScanResult(success=success, message=message, data=result_data)

    def scan_system_configs(self) -> ScanResult:
        """
        Scans system and language specific configurations.
        
        Checks Python version and general OS info.
        
        Returns:
            ScanResult: Result object containing system info.
        """
        info = {}
        success = True
        message = "System info collected."

        try:
            info["python_version"] = sys.version
            info["python_executable"] = sys.executable
            info["platform"] = sys.platform
            info["os_user"] = os.environ.get("USER", os.environ.get("USERNAME", "Unknown"))
        except Exception as e:
            success = False
            message = f"Failed to collect system info: {e}"

        return ScanResult(success=success, message=message, data={"system": info})

    def collect_all(self) -> ScanResult:
        """
        Collects all environment states into a unified report.
        
        Runs all scanner methods and aggregates the results.
        
        Returns:
            ScanResult: Aggregated scan report.
        """
        results = []
        all_data = {}

        try:
            deps = self.scan_dependencies()
            results.append(("dependencies", deps))
            all_data.update(deps.data)

            env = self.scan_environment_variables()
            results.append(("environment", env))
            all_data.update(env.data)

            git = self.scan_git_status()
            results.append(("git", git))
            all_data.update(git.data)

            sys_info = self.scan_system_configs()
            results.append(("system", sys_info))
            all_data.update(sys_info.data)

            failures = [r for _, r in results if not r.success]
            all_messages = [r.message for _, r in results]
            
            overall_success = len(failures) == 0
            overall_message = "; ".join(all_messages)

            return ScanResult(success=overall_success, message=overall_message, data={"scans": all_data})

        except Exception as e:
            return ScanResult(success=False, message=f"Scanner crash: {e}", data={})


class FileWatcher(FileSystemEventHandler):
    """File system event handler for detecting configuration drift."""

    def __init__(self, callback=None):
        super().__init__()
        self.callback = callback
        self.observed_paths = []

    def on_modified(self, event):
        """Triggered when a watched file is modified."""
        if event.is_directory:
            return
        logger.info(f"Detected modification: {event.src_path}")
        if self.callback:
            try:
                self.callback(event.src_path)
            except Exception as e:
                logger.error(f"Callback failed: {e}")

    def on_created(self, event):
        """Triggered when a watched file is created."""
        if event.is_directory:
            return
        logger.info(f"Detected creation: {event.src_path}")

    def start_watching(self, paths: List[str], recursive: bool = True):
        """Starts observing the specified paths."""
        observer = Observer()
        for path in paths:
            if os.path.exists(path):
                self.observed_paths.append(path)
                observer.schedule(self, path=path, recursive=recursive)
        
        try:
            observer.start()
            logger.info(f"Watchdog started on {paths}")
        except Exception as e:
            logger.error(f"Watchdog start failed: {e}")
        return observer


def load_configuration(file_path: str) -> Dict[str, Any]:
    """
    Loads configuration from a YAML file.
    
    Args:
        file_path: Path to the YAML configuration file.
        
    Returns:
        Dict[str, Any]: Parsed configuration dictionary.
    """
    try:
        with open(file_path, "r") as f:
            content = yaml.safe_load(f)
            return content if isinstance(content, dict) else {}
    except FileNotFoundError:
        logger.warning(f"Configuration file not found: {file_path}")
        return {}
    except yaml.YAMLError as e:
        logger.error(f"YAML parsing error: {e}")
        return {}
    except Exception as e:
        logger.error(f"Error reading config file: {e}")
        return {}


@click.group()
@click.version_option(version="1.0.0")
def cli():
    """Drift Detector CLI entry point wrapper."""
    pass


@click.command()
@click.argument("path", default=".")
def scan(path: str):
    """Command to run a full environment scan."""
    scanner = DriftScanner(path)
    result = scanner.collect_all()
    click.echo(f"Scan Complete: {result.message}")
    click.echo(f"Success: {result.success}")
    click.echo(f"Timestamp: {result.timestamp}")
    click.echo(f"Data: {result.to_dict()}")
    return result