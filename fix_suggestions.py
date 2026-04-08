import typing
import os
import subprocess
from pathlib import Path
import yaml
from typing import Dict, List, Optional, Tuple, Union
from git import Repo, GitCommandError, InvalidGitRepositoryError


class RemediationScriptGenerator:
    """
    Generates automated remediation scripts to revert detected changes to the baseline state.

    This class handles the comparison between the current development environment
    and a stored baseline state, producing shell scripts that can be executed
    to restore the original configuration. It utilizes GitPython for repository
    management and PyYAML for configuration file handling.
    """

    def __init__(
        self,
        repo_path: str,
        baseline_config_path: Optional[str] = None,
        output_dir: str = "./generated_fixes"
    ) -> None:
        """
        Initialize the RemediationScriptGenerator.

        Sets up the Git repository connection and ensures output directories exist.

        Args:
            repo_path: Path to the git repository root to monitor for changes.
            baseline_config_path: Optional path to a YAML baseline configuration for drift comparison.
            output_dir: Directory where fix scripts will be saved.

        Raises:
            ValueError: If the repo_path does not exist or is not a git repository.
            InvalidGitRepositoryError: If the specified path is invalid for a git repo.
        """
        self.repo_path = Path(repo_path).resolve()
        self.baseline_config_path = Path(baseline_config_path).resolve() if baseline_config_path else None
        self.output_dir = Path(output_dir).resolve()
        self.repo: Optional[Repo] = None
        self._baseline_yaml: Optional[Dict] = None

        self._validate_repo()
        self._ensure_output_dir()

    def _validate_repo(self) -> None:
        """
        Validates that the provided path is a valid git repository.
        
        Raises:
            ValueError: If the path is not a git repository.
        """
        try:
            if not self.repo_path.exists():
                raise InvalidGitRepositoryError(f"Path {self.repo_path} does not exist.")
            self.repo = Repo(self.repo_path)
        except InvalidGitRepositoryError as e:
            raise InvalidGitRepositoryError(f"Path {self.repo_path} is not a valid git repository: {e}")

    def _ensure_output_dir(self) -> None:
        """
        Creates the output directory if it does not exist.
        """
        try:
            if not self.output_dir.exists():
                self.output_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError as e:
            raise PermissionError(f"Cannot create output directory {self.output_dir}: {e}") from e

    def _load_baseline_yaml(self, path: Path) -> Dict:
        """
        Load the baseline YAML configuration file.

        Args:
            path: Path to the YAML file.

        Returns:
            The parsed YAML content as a dictionary.

        Raises:
            yaml.YAMLError: If the file content is not valid YAML.
            FileNotFoundError: If the file does not exist.
        """
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = yaml.safe_load(f)
                return content if content is not None else {}
        except FileNotFoundError as e:
            raise FileNotFoundError(f"Baseline configuration file not found: {path}") from e
        except yaml.YAMLError as e:
            raise yaml.YAMLError(f"Invalid YAML syntax in baseline configuration: {path}") from e

    def detect_git_drift(self) -> List[str]:
        """
        Detect uncommitted changes in the current git repository.

        Returns:
            A list of relative file paths that have been modified, staged, deleted, or are untracked.

        Raises:
            GitCommandError: If the git operation fails.
        """
        if self.repo is None:
            raise RuntimeError("Repository is not initialized.")

        try:
            staged_files = [item.a_path for item in self.repo.index.diff(None)]
            unstaged_files = [item.a_path for item in self.repo.index.diff("HEAD")]
            untracked_files = [item.path for item in self.repo.untracked_files]
            deleted_files = [item.a_path for item in self.repo.index.diff("HEAD") if item.b_path is None]

            all_paths = set(staged_files + unstaged_files + untracked_files + deleted_files)
            
            return [str(p) for p in all_paths]
        except GitCommandError as e:
            raise GitCommandError(f"Failed to detect git drift: {e}") from e

    def detect_yaml_drift(self) -> Optional[Tuple[str, Dict, Dict]]:
        """
        Detect drift in the YAML configuration file compared to the baseline.

        Returns:
            A tuple containing (file_path, current_content, baseline_content) if drift is detected.
            Returns None if no drift is detected, file is missing, or no baseline path is set.
        """
        if not self.baseline_config_path:
            return None

        try:
            config_file_path = self.baseline_config_path
            if not config_file_path.exists():
                return None

            current_content = self._load_baseline_yaml(config_file_path)
            self._baseline_yaml = self._load_baseline_yaml(self.baseline_config_path)

            if current_content != self._baseline_yaml:
                return (str(config_file_path), current_content, self._baseline_yaml)
            return None
        except (FileNotFoundError, yaml.YAMLError, PermissionError, Exception):
            return None

    def generate_remediation_script(
        self,
        drift_files: List[str],
        drift_yaml: Optional[Tuple[str, Dict, Dict]] = None
    ) -> Dict[str, Union[str, int]]:
        """
        Generate a shell script that reverts the detected drift to the baseline state.

        Args:
            drift_files: List of file paths detected as drifted in git.
            drift_yaml: Optional tuple containing (filepath, current, baseline) for YAML drift.

        Returns:
            A dictionary containing the script content, suggested file path, and status.

        Raises:
            ValueError: If inputs are invalid.
            PermissionError: If the script file cannot be written.
        """
        script_lines = ["#!/bin/bash", "# Automated remediation script generated by Dev Environment Drift Detector", "set -e", ""]
        script_lines.append("echo 'Starting environment restoration...'")
        script_lines.append(f"REPO_ROOT='{self.repo_path}'")
        script_lines.append("")

        # Handle Git Drift
        if drift_files:
            script_lines.append("# Git Revert Commands")
            for file_path in drift_files:
                if not file_path:
                    continue
                abs_path = self.repo_path / file_path
                script_lines.append(f"# Reverting change for: {file_path}")
                
                if not abs_path.exists():
                    script_lines.append(f"echo 'Skipping missing file {file_path}'")
                else:
                    # Escape quotes in file paths for safety
                    safe_path = file_path.replace('"', '\\"')
                    script_lines.append(f'git -C "$REPO_ROOT" checkout "{safe_path}"')

            script_lines.append("")
            script_lines.append("# Reset index if files were staged")
            script_lines.append('git -C "$REPO_ROOT" reset HEAD -- . 2>/dev/null || true')

        # Handle YAML Drift
        if drift_yaml:
            file_path, _, baseline_content = drift_yaml
            script_lines.append("# YAML Configuration Restore Commands")
            safe_path = file_path.replace('"', '\\"')
            script_lines.append(f'echo "Restoring configuration from baseline: {file_path}"')
            
            if self.repo_path:
                script_lines.append(f'git -C "$REPO_ROOT" checkout "{safe_path}"')
            else:
                script_lines.append(f"# Manual restore required for {file_path} from baseline YAML content")

        script_lines.append("")
        script_lines.append("echo 'Environment restoration complete.'")
        script_lines.append("exit 0")

        script_content = "\n".join(script_lines)
        try:
            if self.repo and self.repo.head:
                sha = self.repo.head.commit.hexsha[:8]
            else:
                sha = "latest"
        except Exception:
            sha = "latest"

        file_name = f"fix_env_{sha}.sh"
        file_path = self.output_dir / file_name

        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(script_content)
            os.chmod(file_path, 0o755)
        except PermissionError as e:
            raise PermissionError(f"Failed to write script to {file_path}: {e}") from e

        return {
            "script_path": str(file_path),
            "script_content": script_content,
            "files_affected": len(drift_files),
            "status": "success"
        }

    def get_drift_summary(self) -> Dict[str, Union[List[str], Optional[Dict]]]:
        """
        Retrieve a summary of detected drift without generating a script.

        Returns:
            A dictionary containing git drifted files and YAML drift details.
        """
        git_drift = []
        yaml_drift = None

        try:
            git_drift = self.detect_git_drift()
        except GitCommandError as e:
            pass  # Handle gracefully by leaving empty

        try:
            yaml_drift = self.detect_yaml_drift()
        except Exception:
            pass  # Handle gracefully

        return {
            "git_drifted_files": git_drift,
            "yaml_drift_details": dict(yaml_drift) if yaml_drift else None
        }