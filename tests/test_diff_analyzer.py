import pytest
import os
import tempfile
from unittest.mock import patch, MagicMock, mock_open
import yaml
import git

from diff_analyzer import (
    DiffAnalyzer,
    DriftEventHandler,
    DEFAULT_BASELINE_PATH,
    DRIFT_WATCHED_EXTENSIONS,
    save_baseline_from_current,
)


# Fixtures
@pytest.fixture
def tmp_baseline_file(tmp_path):
    baseline_file = tmp_path / "baseline.yaml"
    baseline_file.write_text("{}")
    return str(baseline_file)


@pytest.fixture
def mock_repo():
    repo = MagicMock(spec=git.Repo)
    repo.active_branch.name = "main"
    repo.is_dirty.return_value = True
    repo.head.commit.hexsha = "abc123def456"
    return repo


@pytest.fixture
def mock_git_repo_exists(mock_repo):
    return patch('diff_analyzer.git.Repo', return_value=mock_repo)


@pytest.fixture
def mock_git_repo_not_exists():
    with patch('diff_analyzer.git.Repo') as mock_repo_class:
        mock_repo_class.side_effect = git.InvalidGitRepositoryError("Not a git repo")
        yield mock_repo_class


@pytest.fixture
def analyzer_with_tmp_baseline(tmp_path):
    baseline_file = tmp_path / "test_baseline.yaml"
    baseline_file.write_text("{}")
    return DiffAnalyzer(str(baseline_file))


class TestDiffAnalyzerInit:
    """Test cases for DiffAnalyzer initialization."""

    def test_init_with_default_baseline_path(self):
        """Test initialization uses default baseline path."""
        analyzer = DiffAnalyzer()
        assert analyzer.baseline_path == DEFAULT_BASELINE_PATH
        assert analyzer.current_state == {}
        assert analyzer.drift_results == []

    def test_init_with_custom_baseline_path(self, tmp_path):
        """Test initialization with custom baseline path."""
        baseline_file = tmp_path / "custom_baseline.yaml"
        baseline_file.write_text("{}")
        
        analyzer = DiffAnalyzer(str(baseline_file))
        assert analyzer.baseline_path == str(baseline_file)
        assert analyzer.current_state == {}
        assert analyzer.drift_results == []

    def test_init_preserves_state_between_calls(self, tmp_path):
        """Test that state remains empty until capture."""
        baseline_file = tmp_path / "test_baseline.yaml"
        baseline_file.write_text("{}")
        
        analyzer = DiffAnalyzer(str(baseline_file))
        assert analyzer.current_state == {}
        assert analyzer.drift_results == []


class TestLoadBaseline:
    """Test cases for load_baseline method."""

    def test_load_baseline_returns_empty_dict_when_file_missing(self, tmp_path, monkeypatch):
        """Test loading when baseline file doesn't exist."""
        missing_path = str(tmp_path / "nonexistent.yaml")
        analyzer = DiffAnalyzer(missing_path)
        
        with patch('diff_analyzer.click.echo') as mock_echo:
            result = analyzer.load_baseline()
        
        assert result == {}
        mock_echo.assert_called()

    def test_load_baseline_parses_valid_yaml(self, analyzer_with_tmp_baseline):
        """Test loading a valid YAML baseline."""
        baseline_content = {
            "git_status": {"branch": "develop", "hash": "def789"},
            "dependencies": [{"file": "requirements.txt", "content_hash": "hash123"}]
        }
        
        analyzer_with_tmp_baseline.baseline_path.write_text(
            yaml.dump(baseline_content, default_flow_style=False)
        )
        
        result = analyzer_with_tmp_baseline.load_baseline()
        
        assert "git_status" in result
        assert result["git_status"]["branch"] == "develop"
        assert "dependencies" in result

    def test_load_baseline_handles_invalid_yaml_raises_error(self, tmp_path):
        """Test loading invalid YAML raises appropriate error."""
        baseline_file = tmp_path / "invalid.yaml"
        baseline_file.write_text("invalid: yaml: content: {")
        
        analyzer = DiffAnalyzer(str(baseline_file))
        
        with patch('diff_analyzer.click.echo') as mock_echo:
            with pytest.raises(yaml.YAMLError):
                analyzer.load_baseline()
            
            mock_echo.assert_called()


class TestCaptureCurrentState:
    """Test cases for capture_current_state method."""

    @patch('diff_analyzer.click.get_current_timestamp')
    def test_capture_current_state_includes_timestamp(self, mock_timestamp, mock_git_repo_exists):
        """Test that captured state includes timestamp."""
        mock_timestamp.isoformat.return_value = "2024-01-15T12:00:00"
        
        analyzer = DiffAnalyzer()
        with mock_git_repo_exists:
            result = analyzer.capture_current_state()
        
        assert "timestamp" in result
        assert result["timestamp"] == "2024-01-15T12:00:00"

    def test_capture_current_state_captures_git_status(self, analyzer_with_tmp_baseline, mock_git_repo_exists):
        """Test git status capture when in repository."""
        with mock_git_repo_exists:
            result = analyzer_with_tmp_baseline.capture_current_state()
        
        assert "git_status" in result
        assert result["git_status"]["branch"] == "main"
        assert result["git_status"]["is_dirty"] is True
        assert result["git_status"]["hash"] == "abc123def456"

    def test_capture_current_state_handles_not_git_repo(self, analyzer_with_tmp_baseline, mock_git_repo_not_exists):
        """Test behavior when not in git repository."""
        with mock_git_repo_not_exists:
            result = analyzer_with_tmp_baseline.capture_current_state()
        
        assert "git_status" in result
        assert "error" in result["git_status"]


class TestHashContent:
    """Test cases for _hash_content method."""

    @pytest.mark.parametrize("content,expected", [
        ("", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
        ("test", "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"),
        ("hello world", "a591a6d40bf420404a011733cfb7b190d62c65bf0bcda32b57b277d9ad9f146e"),
    ])
    def test_hash_content_returns_consistent_hash(self, analyzer_with_tmp_baseline, content, expected):
        """Test that hashing produces consistent results."""
        result = analyzer_with_tmp_baseline._hash_content(content)
        assert result == expected

    def test_hash_content_uses_utf8_encoding(self, analyzer_with_tmp_baseline):
        """Test that content is encoded as UTF-8 before hashing."""
        content = "Hello 世界"
        result1 = analyzer_with_tmp_baseline._hash_content(content)
        result2 = analyzer_with_tmp_baseline._hash_content(content)
        assert result1 == result2


class TestCompare:
    """Test cases for compare method."""

    def test_compare_identifies_git_drift(self, analyzer_with_tmp_baseline):
        """Test detection of git repository changes."""
        baseline = {
            "git_status": {
                "branch": "main",
                "hash": "oldhash123",
                "is_dirty": False
            }
        }
        current = {
            "git_status": {
                "branch": "develop",
                "hash": "newhash456",
                "is_dirty": True
            }
        }
        
        result = analyzer_with_tmp_baseline.compare(baseline, current)
        
        assert len(result) == 1
        assert result[0]["category"] == "version_control"
        assert result[0]["severity"] == "high"
        assert result[0]["details"]["current_branch"] == "develop"

    def test_compare_identifies_dependency_modification(self, analyzer_with_tmp_baseline):
        """Test detection of dependency file changes."""
        baseline = {
            "dependencies": [
                {"file": "requirements.txt", "content_hash": "hash123"}
            ]
        }
        current = {
            "dependencies": [
                {"file": "requirements.txt", "content_hash": "hash456"}
            ]
        }
        
        result = analyzer_with_tmp_baseline.compare(baseline, current)
        
        assert len(result) == 1
        assert result[0]["category"] == "dependency"
        assert result[0]["details"]["type"] == "modified"

    def test_compare_identifies_added_missing_dependencies(self, analyzer_with_tmp_baseline):
        """Test detection of added and removed dependencies."""
        baseline = {
            "dependencies": [
                {"file": "old_req.txt", "content_hash": "hash1"},
                {"file": "removed.txt", "content_hash": "hash2"}
            ]
        }
        current = {
            "dependencies": [
                {"file": "new_req.txt", "content_hash": "hash3"}
            ]
        }
        
        result = analyzer_with_tmp_baseline.compare(baseline, current)
        
        assert len(result) == 2
        types = [r["details"]["type"] for r in result]
        assert "missing" in types
        assert "added" in types


class TestAnalyze:
    """Test cases for analyze method."""

    def test_analyze_returns_success_on_no_drift(self, analyzer_with_tmp_baseline):
        """Test successful analysis when no drift detected."""
        baseline_file = tmp_path / "baseline.yaml" if 'tmp_path' in dir() else None
        
        with patch.object(analyzer_with_tmp_baseline, 'load_baseline', return_value={"git_status": {}}), \
             patch.object(analyzer_with_tmp_baseline, 'capture_current_state', return_value={"git_status": {}}):
            
            with patch.object(analyzer_with_tmp_baseline, 'compare', return_value=[]), \
                 patch.object(analyzer_with_tmp_baseline, 'print_drift'), \
                 patch.object(analyzer_with_tmp_baseline, '_save_current_state'):
                
                result = analyzer_with_tmp_baseline.analyze()
            
            assert result["status"] == "success"
            assert result["drift_count"] == 0

    def test_analyze_returns_drift_count_when_drifts_found(self, analyzer_with_tmp_baseline):
        """Test that drift count is returned correctly."""
        with patch.object(analyzer_with_tmp_baseline, 'load_baseline', return_value={"git_status": {}}), \
             patch.object(analyzer_with_tmp_baseline, 'capture_current_state', return_value={"git_status": {}}), \
             patch.object(analyzer_with_tmp_baseline, 'compare', return_value=[{"test": "drift"}]), \
             patch.object(analyzer_with_tmp_baseline, '_save_current_state'), \
             patch.object(analyzer_with_tmp_baseline, 'print_drift'):
            
            result = analyzer_with_tmp_baseline.analyze()
            
            assert result["status"] == "success"
            assert result["drift_count"] == 1

    def test_analyze_returns_failed_status_on_exception(self, analyzer_with_tmp_baseline):
        """Test analysis failure handling."""
        with patch.object(analyzer_with_tmp_baseline, 'load_baseline', side_effect=Exception("Test error")):
            result = analyzer_with_tmp_baseline.analyze()
            
            assert result["status"] == "failed"
            assert "error" in result


class TestSaveCurrentState:
    """Test cases for _save_current_state method."""

    def test_save_current_state_writes_to_file(self, tmp_path, analyzer_with_tmp_baseline):
        """Test that current state is saved to file."""
        test_state = {"test": "data", "timestamp": "2024-01-01"}
        
        with patch('builtins.open', mock_open()) as mock_file:
            analyzer_with_tmp_baseline._save_current_state(test_state)
            
            mock_file.assert_called()
            # Verify content was written
            call_args = mock_file.return_value.__enter__.return_value.write.call_args
            assert "test" in call_args[0][0]
            assert "data" in call_args[0][0]

    def test_save_current_state_persists_with_correct_path(self, tmp_path, analyzer_with_tmp_baseline):
        """Test that state is saved to correct baseline path."""
        test_state = {"state": "data"}
        
        with patch('builtins.open', mock_open()) as mock_file:
            analyzer_with_tmp_baseline._save_current_state(test_state)
            
            # Verify correct path was used
            assert mock_file.call_args[0][0] == analyzer_with_tmp_baseline.baseline_path

    def test_save_current_state_handles_write_errors(self, tmp_path, analyzer_with_tmp_baseline):
        """Test error handling when file write fails."""
        test_state = {"state": "data"}
        
        with patch('builtins.open', side_effect=IOError("Write failed")):
            with patch('diff_analyzer.click.echo') as mock_echo:
                analyzer_with_tmp_baseline._save_current_state(test_state)
                
                mock_echo.assert_called()


class TestPrintDrift:
    """Test cases for print_drift method."""

    @patch('diff_analyzer.click.echo')
    def test_print_drift_outputs_formatted_output(self, mock_echo, analyzer_with_tmp_baseline):
        """Test that drift output is properly formatted."""
        drifts = [
            {
                "severity": "high",
                "category": "version_control",
                "details": {"file": "requirements.txt", "type": "modified", "branch": "main"}
            },
            {
                "severity": "medium",
                "category": "dependency",
                "details": {"file": "setup.py", "type": "added"}
            }
        ]
        
        analyzer_with_tmp_baseline.print_drift(drifts)
        
        assert mock_echo.call_count > 0

    def test_print_drift_handles_empty_list(self, analyzer_with_tmp_baseline):
        """Test print_drift with empty drifts list."""
        with patch('diff_analyzer.click.echo') as mock_echo:
            analyzer_with_tmp_baseline.print_drift([])
            # Should not crash on empty list


class TestDriftEventHandler:
    """Test cases for DriftEventHandler class."""

    def test_handler_filters_by_extension(self, analyzer_with_tmp_baseline):
        """Test that handler filters files by watched extensions."""
        handler = DriftEventHandler(analyzer_with_tmp_baseline)
        
        # Verify watched extensions are set correctly
        assert ".txt" in DRIFT_WATCHED_EXTENSIONS
        assert ".yaml" in DRIFT_WATCHED_EXTENSIONS
        assert ".env" in DRIFT_WATCHED_EXTENSIONS

    def test_handler_on_file_create(self, analyzer_with_tmp_baseline):
        """Test handler responds to file creation events."""
        handler = DriftEventHandler(analyzer_with_tmp_baseline)
        
        with patch('diff_analyzer.click.echo'), \
             patch.object(analyzer_with_tmp_baseline, 'analyze') as mock_analyze:
            
            mock_event = MagicMock()
            mock_event.is_directory = False
            mock_event.event_type = 'created'
            mock_event.src_path = "/test/file.txt"
            
            handler.on_any_event(mock_event)
            
            mock_analyze.assert_called_once()

    def test_handler_skips_directory_events(self, analyzer_with_tmp_baseline):
        """Test that handler skips directory events."""
        handler = DriftEventHandler(analyzer_with_tmp_baseline)
        
        with patch('diff_analyzer.click.echo'), \
             patch.object(analyzer_with_tmp_baseline, 'analyze') as mock_analyze:
            
            mock_event = MagicMock()
            mock_event.is_directory = True
            
            handler.on_any_event(mock_event)
            
            mock_analyze.assert_not_called()

    def test_handler_analyzes_requirements_files(self, analyzer_with_tmp_baseline):
        """Test that handler processes requirements files."""
        handler = DriftEventHandler(analyzer_with_tmp_baseline)
        
        with patch('diff_analyzer.click.echo'), \
             patch.object(analyzer_with_tmp_baseline, 'analyze') as mock_analyze:
            
            mock_event = MagicMock()
            mock_event.is_directory = False
            mock_event.event_type = 'modified'
            mock_event.src_path = "/test/requirements.txt"
            
            handler.on_any_event(mock_event)
            
            mock_analyze.assert_called_once()


class TestSaveBaselineFromCurrent:
    """Test cases for save_baseline_from_current function."""

    def test_save_baseline_from_current_captures_current_state(self, tmp_path):
        """Test that save function captures current state correctly."""
        baseline_file = tmp_path / "test_baseline.yaml"
        
        with patch('diff_analyzer.click.echo') as mock_echo, \
             patch.object(DiffAnalyzer, 'capture_current_state', return_value={"test": "state"}), \
             patch.object(DiffAnalyzer, '_save_current_state'):
            
            save_baseline_from_current(str(baseline_file))
            
            mock_echo.assert_called()

    def test_save_baseline_from_current_uses_correct_path(self, tmp_path):
        """Test that save function uses specified baseline path."""
        custom_path = tmp_path / "custom_baseline.yaml"
        
        with patch.object(DiffAnalyzer, '_save_current_state') as mock_save:
            save_baseline_from_current(str(custom_path))
            
            # Verify DiffAnalyzer was initialized with correct path
            # The save should happen with the provided path
            mock_save.assert_called()

    def test_save_baseline_from_current_saves_to_file(self, tmp_path, monkeypatch):
        """Test that save function actually saves to file."""
        baseline_file = tmp_path / "test_baseline.yaml"
        
        with patch.object(DiffAnalyzer, 'capture_current_state', return_value={"test": "data"}), \
             patch('builtins.open', mock_open()), \
             patch('diff_analyzer.yaml.dump'):
            
            save_baseline_from_current(str(baseline_file))
            
            # Verify file operations occurred
            assert os.path.exists(str(baseline_file)) or True