import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from pathlib import Path as RealPath
import sys

from fix_suggestions import RemediationScriptGenerator


@pytest.fixture
def setup_fixtures(monkeypatch):
    """
    Sets up common mocks required for the generator class tests.
    Patches Path, Repo, yaml, os, and open within the fix_suggestions module.
    """
    # Mock Path
    mock_path_instance = MagicMock()
    mock_path_instance.resolve.return_value = mock_path_instance
    mock_path_instance.exists.return_value = True
    mock_path_instance.mkdir.return_value = None
    mock_path_instance.__truediv__.return_value = mock_path_instance
    mock_path_instance.__str__.return_value = "/mock/path"
    monkeypatch.setattr('fix_suggestions.Path', MagicMock(return_value=mock_path_instance))

    # Mock Repo
    mock_repo_instance = MagicMock()
    mock_repo_instance.index.diff.return_value = []
    mock_repo_instance.untracked_files = []
    mock_repo_instance.head.commit.hexsha = "abcdef12"
    monkeypatch.setattr('fix_suggestions.Repo', MagicMock(return_value=mock_repo_instance))

    # Mock yaml
    monkeypatch.setattr('fix_suggestions.yaml', MagicMock())
    monkeypatch.setattr('fix_suggestions.yaml.safe_load', return_value={})

    # Mock os
    monkeypatch.setattr('fix_suggestions.os.chmod', MagicMock())

    # Mock builtins.open for file writing
    with patch('builtins.open', new_callable=MagicMock):
        yield mock_path_instance, mock_repo_instance


@pytest.fixture
def generator_instance(setup_fixtures):
    """
    Provides a RemediationScriptGenerator instance with mocked dependencies.
    """
    mock_path, mock_repo = setup_fixtures
    
    # Setup specific properties for the instance
    with patch.object(mock_repo, 'repo_path', mock_path):
        instance = RemediationScriptGenerator("/test/repo", "/test/baseline.yaml")
        instance.repo_path = mock_path
        instance.repo = mock_repo
        instance.repo.head.commit.hexsha = "abcdef12"
        yield instance


class TestRemediationScriptGeneratorInit:
    """Tests for the __init__ method of RemediationScriptGenerator."""

    def test_init_valid_paths(self, generator_instance, setup_fixtures, monkeypatch):
        """Test initialization with valid repository and config paths."""
        mock_path, mock_repo = setup_fixtures
        assert generator_instance.repo_path == mock_path
        assert generator_instance.repo == mock_repo
        assert generator_instance.baseline_config_path == mock_path

    def test_init_invalid_repo_path_exists(self, monkeypatch, setup_fixtures):
        """Test initialization when the repo path exists but is not a git repo."""
        mock_path, mock_repo = setup_fixtures
        
        # Mock exists to True but Repo raising error
        def raise_error(path):
            from git import InvalidGitRepositoryError
            raise InvalidGitRepositoryError("Not a git repo")

        # We need to simulate this during class creation, so we patch Repo constructor behavior
        # Note: In a real scenario we'd mock the Repo class to raise, 
        # but __init__ catches it. Here we simulate the path check.
        monkeypatch.setattr('fix_suggestions.Path.exists', return_value=True)
        monkeypatch.setattr('fix_suggestions.Repo', side_effect=Exception("Not a repo"))
        
        with pytest.raises(Exception):
            RemediationScriptGenerator("/test/repo")

    def test_init_repo_does_not_exist(self, monkeypatch, setup_fixtures):
        """Test initialization when the repo path does not exist."""
        mock_path, mock_repo = setup_fixtures
        
        mock_path.exists.return_value = False
        monkeypatch.setattr('fix_suggestions.Path', MagicMock(return_value=mock_path))
        
        with pytest.raises(Exception):
            RemediationScriptGenerator("/test/repo")


class TestDetectGitDrift:
    """Tests for the detect_git_drift method."""

    def test_detect_git_drift_success(self, generator_instance, setup_fixtures):
        """Test detecting drift with staged and unstaged files."""
        mock_path, mock_repo = setup_fixtures
        
        # Setup mock return values for diff operations
        diff_object = MagicMock()
        diff_object.a_path = "config.yml"
        mock_repo.index.diff.return_value = [diff_object]
        mock_repo.untracked_files = []
        
        drift = generator_instance.detect_git_drift()
        
        assert "config.yml" in drift

    def test_detect_git_drift_no_changes(self, generator_instance, setup_fixtures):
        """Test detecting drift when there are no changes."""
        mock_path, mock_repo = setup_fixtures
        mock_repo.index.diff.return_value = []
        mock_repo.untracked_files = []
        
        drift = generator_instance.detect_git_drift()
        assert drift == []

    def test_detect_git_drift_git_error(self, generator_instance, monkeypatch, setup_fixtures):
        """Test detecting drift when a git command fails."""
        from git import GitCommandError
        mock_path, mock_repo = setup_fixtures
        
        mock_repo.index.diff.side_effect = GitCommandError("test", "Command failed")
        
        with pytest.raises(GitCommandError):
            generator_instance.detect_git_drift()


class TestDetectYamlDrift:
    """Tests for the detect_yaml_drift method."""

    def test_detect_yaml_drift_found(self, generator_instance, setup_fixtures):
        """Test detecting drift when yaml content differs."""
        mock_path, mock_repo = setup_fixtures
        
        current_content = {"key": "new_value"}
        baseline_content = {"key": "old_value"}
        
        # Mock safe_load to return different values on subsequent calls
        call_count = [0]
        def load_side_effect(*args, **kwargs):
            call_count[0] += 1
            return baseline_content if call_count[0] == 1 else current_content
        
        monkeypatch.setattr('fix_suggestions.yaml.safe_load', side_effect=load_side_effect)
        
        # Configure path to exist
        mock_path.exists.return_value = True
        
        result = generator_instance.detect_yaml_drift()
        
        assert result is not None
        assert result[0] == "/mock/path"
        assert result[1] == current_content

    def test_detect_yaml_drift_no_drift(self, generator_instance, setup_fixtures):
        """Test detecting drift when yaml content is identical."""
        mock_path, mock_repo = setup_fixtures
        
        yaml_content = {"key": "value"}
        monkeypatch.setattr('fix_suggestions.yaml.safe_load', return_value=yaml_content)
        
        mock_path.exists.return_value = True
        
        result = generator_instance.detect_yaml_drift()
        
        assert result is None

    def test_detect_yaml_drift_no_baseline_path(self, generator_instance):
        """Test detecting drift when no baseline path is provided."""
        # Re-init instance conceptually without baseline
        instance = RemediationScriptGenerator("/test/repo", baseline_config_path=None)
        # Mock repo and path temporarily
        instance.repo = MagicMock()
        instance.repo.head.commit.hexsha = "test"
        instance.repo_path = MagicMock()
        
        result = instance.detect_yaml_drift()
        assert result is None


class TestGenerateRemediationScript:
    """Tests for the generate_remediation_script method."""

    def test_generate_script_with_git_drift(self, generator_instance, setup_fixtures, monkeypatch):
        """Test script generation when git drift is detected."""
        mock_path, mock_repo = setup_fixtures
        
        drift_files = ["app.py", "config.yml"]
        monkeypatch.setattr('fix_suggestions.os.chmod', MagicMock())
        monkeypatch.setattr('fix_suggestions.Path.mkdir', MagicMock())
        
        with patch('builtins.open') as mock_open:
            mock_file = MagicMock()
            mock_open.return_value.__enter__.return_value = mock_file
            
            result = generator_instance.generate_remediation_script(drift_files=drift_files)
            
            assert result["status"] == "success"
            assert "git -C" in result["script_content"]
            assert mock_file.write.called

    def test_generate_script_with_yaml_drift(self, generator_instance, setup_fixtures, monkeypatch):
        """Test script generation when yaml drift is detected."""
        mock_path, mock_repo = setup_fixtures
        drift_files = []
        drift_yaml = ("config.yaml", {"current": 1}, {"baseline": 1})
        
        monkeypatch.setattr('fix_suggestions.os.chmod', MagicMock())
        
        with patch('builtins.open') as mock_open:
            mock_file = MagicMock()
            mock_open.return_value.__enter__.return_value = mock_file
            
            result = generator_instance.generate_remediation_script(drift_files=drift_files, drift_yaml=drift_yaml)
            
            assert "Restoring configuration" in result["script_content"]
            assert mock_file.write.called

    def test_generate_script_file_write_error(self, generator_instance, setup_fixtures, monkeypatch):
        """Test script generation when file write fails."""
        mock_path, mock_repo = setup_fixtures
        drift_files = ["app.py"]
        
        monkeypatch.setattr('fix_suggestions.os.chmod', MagicMock())
        
        # Simulate write error
        import builtins
        original_open = builtins.open
        
        def error_open(*args, **kwargs):
            raise PermissionError("No permission")
        
        monkeypatch.setattr('builtins.open', error_open)
        
        with pytest.raises(PermissionError):
            generator_instance.generate_remediation_script(drift_files=drift_files)


class TestGetDriftSummary:
    """Tests for the get_drift_summary method."""

    def test_get_summary_success(self, generator_instance, setup_fixtures, monkeypatch):
        """Test getting summary when all drifts are detected."""
        mock_path, mock_repo = setup_fixtures
        
        # Mock git drift
        mock_repo.index.diff.return_value = [MagicMock(a_path="file.txt")]
        mock_repo.untracked_files = []
        
        # Mock yaml drift
        call_count = [0]
        def yaml_load_side_effect(*args, **kwargs):
            call_count[0] += 1
            return {"different": "content"}
        
        monkeypatch.setattr('fix_suggestions.yaml.safe_load', side_effect=yaml_load_side_effect)
        mock_path.exists.return_value = True
        
        summary = generator_instance.get_drift_summary()
        
        assert "git_drifted_files" in summary
        assert "yaml_drift_details" in summary
        assert len(summary["git_drifted_files"]) > 0

    def test_get_summary_git_error(self, generator_instance, monkeypatch, setup_fixtures):
        """Test getting summary when git operation fails."""
        mock_path, mock_repo = setup_fixtures
        
        from git import GitCommandError
        mock_repo.index.diff.side_effect = GitCommandError("err", "cmd")
        
        # Reset summary logic to not throw in method
        monkeypatch.setattr('fix_suggestions.git', MagicMock())
        
        summary = generator_instance.get_drift_summary()
        
        assert summary["git_drifted_files"] == []

    def test_get_summary_yaml_error(self, generator_instance, monkeypatch, setup_fixtures):
        """Test getting summary when yaml parsing fails."""
        mock_path, mock_repo = setup_fixtures
        
        # Reset summary logic to not throw in method
        monkeypatch.setattr('fix_suggestions.yaml.safe_load', side_effect=yaml.YAMLError("bad yaml"))
        mock_path.exists.return_value = True
        
        summary = generator_instance.get_drift_summary()
        
        assert summary["yaml_drift_details"] is None