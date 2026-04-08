import os
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
import datetime
import yaml
from git import Repo, GitCommandError
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Configure logger for the module
logger = logging.getLogger(__name__)


class BaselineManagerError(Exception):
    """Base exception for BaselineManager errors."""
    pass


class StorageError(BaselineManagerError):
    """Raised when baseline storage operations fail."""
    pass


class GitStateError(BaselineManagerError):
    """Raised when git state capture operations fail."""
    pass


class BaselineManager:
    """
    Manages initialization, storage, and comparison of known-good baselines.
    Supports tracking git repository state and project dependencies.
    """

    def __init__(self, baseline_dir: str, git_repo_path: str) -> None:
        """
        Initialize the BaselineManager with specific directories.

        Args:
            baseline_dir: Path to the directory where baselines are stored.
            git_repo_path: Path to the git repository root.
        """
        self._baseline_dir = Path(baseline_dir).expanduser().resolve()
        self._git_repo_path = Path(git_repo_path).expanduser().resolve()
        self._baselines: Dict[str, Dict[str, Any]] = {}
        self._observer: Optional[Observer] = None

        try:
            if not self._baseline_dir.exists():
                self._baseline_dir.mkdir(parents=True, exist_ok=True)
            if not self._git_repo_path.exists():
                logger.warning(f"Git repository path does not exist: {self._git_repo_path}")
        except OSError as e:
            raise BaselineManagerError(f"Failed to initialize directories: {e}")

    def capture_git_state(self) -> Dict[str, Any]:
        """
        Captures the current state of the git repository.

        Returns:
            A dictionary containing commit hash, branch, and status details.

        Raises:
            GitStateError: If the repository cannot be accessed or cloned.
        """
        state = {
            "timestamp": datetime.datetime.now().isoformat(),
            "repo": str(self._git_repo_path),
            "commit_hash": None,
            "branch": None,
            "is_clean": None,
            "status": []
        }
        try:
            repo = Repo(self._git_repo_path, search_parent_directories=True)
            state["commit_hash"] = repo.head.object.hexsha
            state["branch"] = repo.active_branch.name if repo.active_branch else "DETACHED"
            state["is_clean"] = repo.is_dirty() is False
            state["status"] = [f"{item.a_path}/{item.b_path}" for item in repo.index.diff(None)]
            return state
        except GitCommandError as e:
            raise GitStateError(f"Git repository access failed at {self._git_repo_path}: {e}")
        except Exception as e:
            raise GitStateError(f"Unexpected error capturing git state: {e}")

    def capture_dependencies(self) -> Dict[str, Any]:
        """
        Captures current project dependencies, typically from requirements.txt.

        Returns:
            A dictionary of parsed dependency strings or hash.

        Raises:
            StorageError: If requirements file is not found or parsing fails.
        """
        state = {
            "timestamp": datetime.datetime.now().isoformat(),
            "requirements_file": "requirements.txt",
            "content": None,
            "hash": None
        }
        req_path = self._git_repo_path / "requirements.txt"
        try:
            if req_path.exists():
                with open(req_path, "r", encoding="utf-8") as f:
                    content = f.read()
                import hashlib
                state["content"] = content
                state["hash"] = hashlib.sha256(content.encode()).hexdigest()
            else:
                logger.warning("requirements.txt not found in git repo root.")
                state["content"] = ""
            return state
        except OSError as e:
            raise StorageError(f"Failed to read requirements file: {e}")
        except Exception as e:
            raise StorageError(f"Unexpected error during dependency capture: {e}")

    def initialize_baseline(self, name: str = "default") -> Dict[str, Any]:
        """
        Creates a new baseline snapshot of the current environment and persists it.

        Args:
            name: Unique identifier for the baseline.

        Returns:
            The saved baseline content.

        Raises:
            BaselineManagerError: If saving the baseline fails.
        """
        baseline_data = {
            "name": name,
            "created_at": datetime.datetime.now().isoformat(),
            "git_state": self.capture_git_state(),
            "dependencies": self.capture_dependencies(),
            "config_files": {}
        }

        filepath = self._baseline_dir / f"{name}.yaml"
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                yaml.dump(baseline_data, f, default_flow_style=False, sort_keys=False)
            logger.info(f"Baseline '{name}' initialized and saved to {filepath}")
            return baseline_data
        except IOError as e:
            raise BaselineManagerError(f"Failed to initialize baseline: {e}")

    def load_baseline(self, name: str = "default") -> Optional[Dict[str, Any]]:
        """
        Loads a previously saved baseline from the storage directory.

        Args:
            name: Unique identifier for the baseline.

        Returns:
            The baseline dictionary if found, else None.

        Raises:
            BaselineManagerError: If loading fails.
        """
        filepath = self._baseline_dir / f"{name}.yaml"
        try:
            if not filepath.exists():
                logger.info(f"Baseline '{name}' does not exist.")
                return None
            with open(filepath, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise BaselineManagerError(f"Failed to parse baseline YAML file: {e}")
        except IOError as e:
            raise BaselineManagerError(f"Failed to read baseline file: {e}")

    def compare_baseline(self, name: str = "default") -> Dict[str, Any]:
        """
        Compares the current environment state against a specified baseline.

        Args:
            name: Unique identifier for the baseline to compare against.

        Returns:
            A dictionary detailing drift or consistency.

        Raises:
            BaselineManagerError: If comparison logic fails.
        """
        baseline = self.load_baseline(name)
        if not baseline:
            return {"error": "Baseline not found", "name": name}

        current = {
            "git_state": self.capture_git_state(),
            "dependencies": self.capture_dependencies()
        }

        drift_report = {
            "baseline_name": name,
            "timestamp": datetime.datetime.now().isoformat(),
            "is_drifted": False,
            "changes": []
        }

        try:
            # Compare Git State
            baseline_git = baseline.get("git_state", {})
            current_git = current["git_state"]

            if baseline_git.get("commit_hash") != current_git.get("commit_hash"):
                drift_report["is_drifted"] = True
                drift_report["changes"].append({
                    "category": "git_commit",
                    "baseline": baseline_git.get("commit_hash"),
                    "current": current_git.get("commit_hash")
                })
            elif baseline_git.get("is_clean") is not None and \
                 current_git.get("is_clean") is not None and \
                 baseline_git["is_clean"] != current_git["is_clean"]:
                drift_report["is_drifted"] = True
                drift_report["changes"].append({
                    "category": "git_cleanliness",
                    "baseline": "Clean" if baseline_git["is_clean"] else "Dirty",
                    "current": "Clean" if current_git["is_clean"] else "Dirty"
                })

            # Compare Dependencies
            baseline_deps = baseline.get("dependencies", {})
            current_deps = current["dependencies"]

            if baseline_deps.get("hash") != current_deps.get("hash"):
                drift_report["is_drifted"] = True
                drift_report["changes"].append({
                    "category": "dependencies",
                    "baseline": baseline_deps.get("hash"),
                    "current": current_deps.get("hash")
                })

            return drift_report
        except Exception as e:
            raise BaselineManagerError(f"Failed to compare baselines: {e}")

    def delete_baseline(self, name: str) -> bool:
        """
        Removes a specific baseline file from storage.

        Args:
            name: Unique identifier for the baseline.

        Returns:
            True if successful, False otherwise.

        Raises:
            BaselineManagerError: If deletion fails.
        """
        filepath = self._baseline_dir / f"{name}.yaml"
        try:
            if filepath.exists():
                os.remove(filepath)
                logger.info(f"Baseline '{name}' deleted.")
                return True
            return False
        except OSError as e:
            raise BaselineManagerError(f"Failed to delete baseline file: {e}")

    def list_baselines(self) -> List[str]:
        """
        Lists all known baseline names stored in the directory.

        Returns:
            A list of baseline names without extensions.
        """
        baselines = []
        try:
            files = self._baseline_dir.glob("*.yaml")
            for file in files:
                baselines.append(file.stem)
            return sorted(baselines)
        except OSError as e:
            raise BaselineManagerError(f"Failed to list baselines: {e}")

    def setup_watcher(self, handler: Optional[FileSystemEventHandler] = None) -> Observer:
        """
        Initializes a file system watcher for detecting changes during active sessions.

        Args:
            handler: An optional FileSystemEventHandler instance.

        Returns:
            A watchdog.Observer instance configured for the baseline directory.
        """
        handler = handler or BaselineEventHandler()
        self._observer = Observer()
        self._observer.schedule(handler, str(self._baseline_dir), recursive=False)
        self._observer.start()
        logger.info("File watcher started for baseline directory.")
        return self._observer


class BaselineEventHandler(FileSystemEventHandler):
    """
    Custom handler for baseline file system events.
    """

    def on_modified(self, event):
        if not event.is_directory:
            logger.info(f"Baseline file modified: {event.src_path}")

    def on_created(self, event):
        if not event.is_directory:
            logger.info(f"Baseline file created: {event.src_path}")