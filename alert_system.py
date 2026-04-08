import os
import logging
import threading
import time
from typing import List, Optional, Dict, Any, Callable
from dataclasses import dataclass, field
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent
from git import Repo, GitCommandError
import yaml
import click

# Configure module logger
logger = logging.getLogger(__name__)

@dataclass
class DriftConfig:
    """Configuration for drift detection settings."""
    watched_paths: List[str] = field(default_factory=list)
    git_repo_path: Optional[str] = None
    drift_threshold: float = 0.5
    alert_callback: Optional[Callable[[str, str], None]] = None

@dataclass
class DriftAlert:
    """Represents a detected drift event requiring notification."""
    message: str
    severity: str
    timestamp: float = field(default_factory=time.time)
    path: Optional[str] = None

    def is_significant(self) -> bool:
        """Determines if drift severity meets the threshold for alerting."""
        severity_levels = {"low": 1, "medium": 2, "high": 3, "critical": 4}
        level = severity_levels.get(self.severity, 0)
        return level >= 3

@dataclass
class DriftDetectionEvent:
    """Internal event wrapper for detection results."""
    source: str
    details: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)

class DriftFileEventHandler(FileSystemEventHandler):
    """Handles file system events for watched paths."""

    def on_created(self, event):
        """Called when a file is created."""
        if not event.is_directory:
            self._handle_event(event.src_path, "created")

    def on_modified(self, event):
        """Called when a file is modified."""
        if not event.is_directory:
            self._handle_event(event.src_path, "modified")

    def _handle_event(self, path: str, event_type: str):
        """Internal handler to emit detection events."""
        try:
            logger.info(f"Detected {event_type} in {path}")
            return DriftDetectionEvent(source=path, details={"type": event_type})
        except Exception as e:
            logger.error(f"Error processing file event for {path}: {e}")
            return None

class GitDriftChecker:
    """Checks for drift in Git repository state."""

    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path)
        self._repo: Optional[Repo] = None

    def get_repo(self) -> Optional[Repo]:
        """Returns the Git repository instance, loading if necessary."""
        if self._repo is None:
            try:
                if not self.repo_path.exists():
                    logger.warning(f"Git repository path does not exist: {self.repo_path}")
                    return None
                self._repo = Repo(str(self.repo_path))
            except GitCommandError as e:
                logger.error(f"Git initialization failed for {self.repo_path}: {e}")
                return None
            except Exception as e:
                logger.error(f"Unexpected error initializing Git: {e}")
                return None
        return self._repo

    def check_drift(self) -> List[Dict[str, Any]]:
        """Checks for uncommitted changes in the repository."""
        drifts = []
        repo = self.get_repo()
        if not repo:
            return drifts

        try:
            # Check for uncommitted changes
            status = repo.git.status()
            if status:
                drifts.append({"type": "git_uncommitted", "details": status, "path": str(self.repo_path)})
            
            # Check for detached HEAD or remote drift if remote URL exists
            remotes = repo.remotes
            for remote in remotes:
                try:
                    remote.fetch()
                    # Compare local HEAD with remote
                    if repo.head.is_detached or repo.active_branch:
                        if repo.head.is_detached:
                            drifts.append({"type": "detached_head", "path": str(self.repo_path)})
                except GitCommandError:
                    logger.warning(f"Failed to fetch from remote {remote.name}")
        except Exception as e:
            logger.error(f"Error checking Git drift for {self.repo_path}: {e}")
        return drifts

class NotificationService:
    """Manages alert notification delivery."""

    def __init__(self, callback: Optional[Callable[[str, str], None]] = None):
        self.callback = callback or self._default_print

    def _default_print(self, message: str, severity: str):
        """Default console notification handler."""
        prefix = {
            "high": "!!! ALERT !!!",
            "medium": "! WARNING !",
            "low": "* INFO *"
        }.get(severity, "INFO")
        click.echo(f"[{prefix}] [{time.strftime('%H:%M:%S')}] {message}")

    def notify(self, alert: DriftAlert) -> bool:
        """Sends a notification if drift is significant."""
        try:
            if alert.is_significant():
                if self.callback:
                    self.callback(alert.message, alert.severity)
                else:
                    self._default_print(alert.message, alert.severity)
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")
            return False

class DevDriftManager:
    """Main orchestration class for the drift detection system."""

    def __init__(self, config: DriftConfig):
        self.config = config
        self.observer: Optional[Observer] = None
        self.event_handler: Optional[DriftFileEventHandler] = None
        self.git_checker: Optional[GitDriftChecker] = None
        self.notification_service: NotificationService = NotificationService(config.alert_callback)
        self._lock = threading.Lock()
        self._is_running = False

    def _init_git_checker(self):
        """Initializes the Git drift checker if configured."""
        if self.config.git_repo_path:
            self.git_checker = GitDriftChecker(self.config.git_repo_path)

    def _init_file_observer(self):
        """Initializes the file system observer for configuration drift."""
        self.event_handler = DriftFileEventHandler()
        self.observer = Observer()
        for path in self.config.watched_paths:
            try:
                path_obj = Path(path)
                if path_obj.exists():
                    self.observer.schedule(self.event_handler, str(path_obj), recursive=True)
                    logger.info(f"Started watching path: {path}")
                else:
                    logger.warning(f"Watched path does not exist: {path}")
            except Exception as e:
                logger.error(f"Failed to schedule path {path}: {e}")

    def start_monitoring(self) -> bool:
        """Starts the drift detection services."""
        with self._lock:
            if self._is_running:
                logger.warning("Monitoring is already running.")
                return True

            self._is_running = True
            self._init_git_checker()
            self._init_file_observer()

            try:
                if self.observer:
                    self.observer.start()
                    logger.info("File system monitoring started.")
                
                # Run initial Git check
                if self.git_checker:
                    drifts = self.git_checker.check_drift()
                    for d in drifts:
                        self._handle_git_drift(d)
                
                logger.info("Drift detection system started.")
                return True
            except Exception as e:
                logger.error(f"Failed to start monitoring: {e}")
                self._is_running = False
                return False

    def stop_monitoring(self):
        """Stops the drift detection services."""
        with self._lock:
            self._is_running = False
            
            if self.observer:
                try:
                    self.observer.stop()
                    self.observer.join()
                except Exception as e:
                    logger.error(f"Error stopping observer: {e}")
            
            self.observer = None
            self.event_handler = None
            logger.info("Drift detection system stopped.")

    def _handle_git_drift(self, drift_info: Dict[str, Any]):
        """Processes detected Git drift and generates alerts."""
        try:
            if drift_info["type"] == "git_uncommitted":
                alert = DriftAlert(
                    message=f"Uncommitted changes detected in {drift_info['path']}",
                    severity="high",
                    path=drift_info["path"]
                )
                self.notification_service.notify(alert)
            elif drift_info["type"] == "detached_head":
                alert = DriftAlert(
                    message=f"Detached HEAD state detected in {drift_info['path']}",
                    severity="medium",
                    path=drift_info["path"]
                )
                self.notification_service.notify(alert)
        except Exception as e:
            logger.error(f"Error handling Git drift: {e}")

    def _handle_file_drift(self, event: DriftDetectionEvent):
        """Processes detected file drift and generates alerts."""
        try:
            if event.details["type"] in ["created", "modified"]:
                file_path = event.source
                # Simple content check simulation or just path existence for config
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        # Simple heuristic: empty files or yaml parsing failures might indicate drift
                        if not content.strip():
                            raise ValueError("Empty file content")
                        yaml.safe_load(content)
                except Exception:
                    # If we can't read/predict, assume drift
                    pass

                severity = "medium" if Path(file_path).suffix == ".yaml" else "low"
                
                alert = DriftAlert(
                    message=f"Configuration drift detected: {event.details['type']} in {file_path}",
                    severity=severity,
                    path=file_path
                )
                self.notification_service.notify(alert)
        except Exception as e:
            logger.error(f"Error handling file drift event: {e}")

    def check_all(self) -> List[DriftAlert]:
        """Manual check of all configured drift sources."""
        alerts = []
        
        if self.git_checker:
            drifts = self.git_checker.check_drift()
            for d in drifts:
                if d["type"] == "git_uncommitted":
                    alerts.append(DriftAlert(
                        message=f"Uncommitted changes in {d['path']}",
                        severity="high",
                        path=d["path"]
                    ))
        
        return alerts

# --- CLI Command Definitions ---

@click.group()
def cli():
    """Dev Environment Drift Detector CLI Group."""
    pass

@cli.command()
@click.option("--paths", "-p", multiple=True, help="Paths to watch for configuration drift.")
@click.option("--git-path", "-g", help="Path to the local Git repository.")
@click.option("--threshold", "-t", default=0.5, help="Drift severity threshold.")
def start_monitoring(paths, git_path, threshold):
    """Starts the drift detection monitoring process."""
    try:
        config = DriftConfig(
            watched_paths=list(paths),
            git_repo_path=git_path,
            drift_threshold=threshold
        )
        
        manager = DevDriftManager(config)
        
        click.echo("Starting drift detector...")
        manager.start_monitoring()
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            click.echo("Stopping drift detector...")
            manager.stop_monitoring()
            click.echo("Drift detector stopped successfully.")
    except Exception as e:
        click.echo(f"Error starting drift detector: {e}", err=True)
        return 1
    return 0

@cli.command()
@click.option("--git-path", "-g", help="Path to the local Git repository.")
def check_git(git_path):
    """Performs an immediate check for Git repository drift."""
    try:
        if not git_path:
            click.echo("No Git path provided. Scanning current directory.", err=True)
            git_path = os.getcwd()
        
        checker = GitDriftChecker(git_path)
        drifts = checker.check_drift()
        
        if drifts:
            click.echo(f"Drift detected in {git_path}:")
            for d in drifts:
                click.echo(f" - {d['type']}: {d.get('details', 'Details unavailable')}")
        else:
            click.echo("No Git drift detected.")
    except Exception as e:
        click.echo(f"Error during check: {e}", err=True)
        return 1
    return 0