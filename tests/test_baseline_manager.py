import pytest
from unittest.mock import patch, MagicMock, mock_open, call, PropertyMock
import datetime
import os
import yaml
from pathlib import Path
import sys

# Import the module to be tested
from baseline_manager import (
    BaselineManager,
    BaselineEventHandler,
    GitStateError,
    StorageError,
    BaselineManagerError
)

# Ensure we can patch the module's attributes
import baseline_manager


@pytest.fixture
def mock_datetime():
    """Fixture to mock datetime.datetime.now."""
    with patch('baseline_manager.datetime') as mock_dt:
        mock_datetime_obj = MagicMock()
        mock_datetime_obj.isoformat.return_value = "2023-01-01T00:00:00"
        mock_dt.datetime.now.return_value = mock_datetime_obj
        yield mock_dt


@pytest.fixture
def mock_git_repo():
    """Fixture to mock the git Repo object."""
    mock_repo = MagicMock()
    mock_repo.head.object.hexsha = "abc123"
    mock_repo.active_branch.name = "main"
    mock_repo.is_dirty.return_value = False
    mock_repo.index.diff(None).return_value = []
    
    with patch('baseline_manager.Repo') as mock_repo_class:
        mock_repo_class.return_value = mock_repo
        yield mock_repo


@pytest.fixture
def mock_path_methods():
    """Fixture to mock Path methods used during initialization."""
    mock_path = MagicMock()
    mock_path.expanduser.return_value = mock_path
    mock_path.resolve.return_value = mock_path
    mock_path.exists.return_value = True
    
    # Configure Path.glob for list_baselines
    mock_file = MagicMock()
    mock_file.stem = "test_baseline"
    mock_path.glob.return_value = [mock_file]
    
    # Configure Path / operator
    mock_path.__truediv__ = MagicMock(return_value=MagicMock())
    
    with patch('baseline_manager.Path', return_value=mock_path) as mock_path_class:
        yield mock_path, mock_path_class


@pytest.fixture
def mock_yaml():
    """Fixture to mock yaml operations."""
    mock_dump = MagicMock()
    mock_safe_load = MagicMock(return_value={"name": "default"})
    
    with patch('baseline_manager.yaml.dump', mock_dump) as mock_dump:
        with patch('baseline_manager.yaml.safe_load', mock_safe_load) as mock_load:
            yield mock_dump, mock_load


@pytest.fixture
def mock_os_remove():
    """Fixture to mock os.remove."""
    with patch('baseline_manager.os.remove') as mock_remove:
        yield mock_remove


@pytest.fixture
def mock_hashlib():
    """Fixture to mock hashlib.sha256."""
    mock_hash = MagicMock()
    mock_hash.hexdigest.return_value = "d41d8cd98f00b204e9800998ecf8427e"
    with patch('baseline_manager.hashlib.sha256') as mock_sha:
        mock_sha.return_value = mock_hash
        yield mock_sha, mock_hash


@pytest.fixture
def mock_watcher():
    """Fixture to mock watchdog Observer."""
    mock_observer = MagicMock()
    mock_observer.start = MagicMock()
    
    with patch('baseline_manager.Observer') as mock_observer_class:
        mock_observer_class.return_value = mock_observer
        yield mock_observer


@pytest.fixture
def setup_event_handler():
    """Configure the BaselineEventHandler for testing."""
    handler = BaselineEventHandler()
    return handler


# --- BaselineManager Init Tests ---

@patch('baseline_manager.datetime')
def test_init_success(mock_dt, mock_path_methods, mock_git_repo, mock_datetime):
    mock_path_class = mock_path_methods[1]
    mock_dt.datetime.now.return_value.isoformat.return_value = "2023-01-01T00:00:00"
    
    bm = BaselineManager("/tmp/baseline", "/tmp/repo")
    
    assert bm._baseline_dir.exists()
    assert bm._git_repo_path.exists()
    mock_path_class.assert_called()


@patch('baseline_manager.datetime')
def test_init_missing_dirs(mock_dt, mock_path_methods, mock_git_repo, mock_datetime, capsys):
    mock_path_class = mock_path_methods[1]
    mock_path = mock_path_methods[0]
    mock_path.exists.return_value = False
    mock_dt.datetime.now.return_value.isoformat.return_value = "2023-01-01T00:00:00"
    
    bm = BaselineManager("/tmp/baseline", "/tmp/repo")
    
    # Verify mkdir called for missing baseline dir
    assert mock_path.mkdir.called


@patch('baseline_manager.datetime')
def test_init_os_error(mock_dt, mock_path_methods, mock_git_repo, mock_datetime):
    mock_path_class = mock_path_methods[1]
    mock_path = mock_path_methods[0]
    mock_path.exists.side_effect = OSError("Access denied")
    mock_dt.datetime.now.return_value.isoformat.return_value = "2023-01-01T00:00:00"
    
    with pytest.raises(BaselineManagerError):
        BaselineManager("/tmp/baseline", "/tmp/repo")


# --- Git State Tests ---

def test_capture_git_state_success(mock_git_repo, mock_datetime):
    bm = BaselineManager("/tmp/baseline", "/tmp/repo")
    result = bm.capture_git_state()
    
    assert "commit_hash" in result
    assert "branch" in result
    assert result["commit_hash"] == "abc123"
    assert result["branch"] == "main"
    assert result["is_clean"] is True


def test_capture_git_state_dirty(mock_git_repo, mock_datetime):
    mock_repo = MagicMock()
    mock_repo.head.object.hexsha = "abc123"
    mock_repo.active_branch.name = "main"
    mock_repo.is_dirty.return_value = True
    mock_repo.index.diff(None).return_value = []
    
    with patch('baseline_manager.Repo') as mock_repo_class:
        mock_repo_class.return_value = mock_repo
        bm = BaselineManager("/tmp/baseline", "/tmp/repo")
        result = bm.capture_git_state()
        assert result["is_clean"] is False


def test_capture_git_state_git_error(mock_git_repo, mock_datetime):
    with patch('baseline_manager.Repo', side_effect=Exception("Git access denied")):
        bm = BaselineManager("/tmp/baseline", "/tmp/repo")
        with pytest.raises(GitStateError):
            bm.capture_git_state()


# --- Dependencies Tests ---

@patch('builtins.open', new_callable=mock_open, read_data="numpy==1.0")
def test_capture_dependencies_success(mock_file, mock_path_methods, mock_hashlib, mock_datetime):
    mock_path_class = mock_path_methods[1]
    mock_sha, mock_hash = mock_hashlib
    mock_sha.hexdigest.return_value = "test_hash"
    mock_dt = mock_datetime
    
    bm = BaselineManager("/tmp/baseline", "/tmp/repo")
    result = bm.capture_dependencies()
    
    assert "content" in result
    assert result["content"] == "numpy==1.0"
    assert "hash" in result
    assert result["hash"] == "test_hash"
    mock_file.assert_called_once_with("/tmp/repo/requirements.txt", encoding="utf-8")


@patch('builtins.open', new_callable=mock_open, read_data="numpy==1.0")
def test_capture_dependencies_missing_file(mock_file, mock_path_methods, mock_hashlib, mock_datetime, capsys):
    mock_path_class = mock_path_methods[1]
    mock_path = mock_path_methods[0]
    mock_sha, mock_hash = mock_hashlib
    mock_sha.hexdigest.return_value = "test_hash"
    mock_dt = mock_datetime
    
    # Make requirements.txt not exist
    mock_path.exists.side_effect = lambda: False if "requirements" in str(mock_path) else True
    
    bm = BaselineManager("/tmp/baseline", "/tmp/repo")
    result = bm.capture_dependencies()
    
    assert result["content"] == ""


def test_capture_dependencies_os_error(mock_path_methods, mock_hashlib, mock_datetime):
    mock_path_class = mock_path_methods[1]
    mock_sha, mock_hash = mock_hashlib
    
    with patch('builtins.open', side_effect=OSError("File locked")):
        bm = BaselineManager("/tmp/baseline", "/tmp/repo")
        with pytest.raises(StorageError):
            bm.capture_dependencies()


# --- Baseline Initialization Tests ---

def test_initialize_baseline_success(mock_datetime, mock_yaml, mock_path_methods, mock_git_repo):
    mock_dump, mock_load = mock_yaml
    mock_dt = mock_datetime
    mock_dt.datetime.now.return_value.isoformat.return_value = "2023-01-01T00:00:00"
    
    bm = BaselineManager("/tmp/baseline", "/tmp/repo")
    result = bm.initialize_baseline(name="new_baseline")
    
    assert result["name"] == "new_baseline"
    assert "git_state" in result
    mock_dump.assert_called_once()


def test_initialize_baseline_io_error(mock_datetime, mock_yaml, mock_path_methods, mock_git_repo):
    mock_dt = mock_datetime
    mock_dt.datetime.now.return_value.isoformat.return_value = "2023-01-01T00:00:00"
    
    with patch('builtins.open', side_effect=IOError("Disk Full")):
        bm = BaselineManager("/tmp/baseline", "/tmp/repo")
        with pytest.raises(BaselineManagerError):
            bm.initialize_baseline()


def test_initialize_baseline_custom_name(mock_datetime, mock_yaml, mock_path_methods, mock_git_repo):
    mock_dt = mock_datetime
    mock_dt.datetime.now.return_value.isoformat.return_value = "2023-01-01T00:00:00"
    
    bm = BaselineManager("/tmp/baseline", "/tmp/repo")
    result = bm.initialize_baseline(name="v2.0")
    
    assert result["name"] == "v2.0"
    assert "git_state" in result


# --- Baseline Loading Tests ---

def test_load_baseline_success(mock_datetime, mock_yaml, mock_path_methods):
    mock_load = mock_yaml[1]
    mock_load.return_value = {"name": "v1", "status": "ok"}
    mock_dt = mock_datetime
    mock_dt.datetime.now.return_value.isoformat.return_value = "2023-01-01T00:00:00"
    
    bm = BaselineManager("/tmp/baseline", "/tmp/repo")
    result = bm.load_baseline(name="v1")
    
    assert result is not None
    assert result["name"] == "v1"


def test_load_baseline_not_found(mock_datetime, mock_yaml, mock_path_methods):
    mock_load = mock_yaml[1]
    mock_load.return_value = None
    mock_dt = mock_datetime
    mock_dt.datetime.now.return_value.isoformat.return_value = "2023-01-01T00:00:00"
    mock_path = mock_path_methods[0]
    mock_path.exists.return_value = False
    
    bm = BaselineManager("/tmp/baseline", "/tmp/repo")
    result = bm.load_baseline(name="nonexistent")
    
    assert result is None


def test_load_baseline_yaml_error(mock_datetime, mock_yaml, mock_path_methods):
    mock_load = mock_yaml[1]
    mock_load.side_effect = yaml.YAMLError("Bad Syntax")
    
    bm = BaselineManager("/tmp/baseline", "/tmp/repo")
    with pytest.raises(BaselineManagerError):
        bm.load_baseline(name="broken")


# --- Comparison Tests ---

def test_compare_baseline_no_drift(mock_datetime, mock_yaml, mock_path_methods, mock_git_repo):
    mock_dt = mock_datetime
    mock_dt.datetime.now.return_value.isoformat.return_value = "2023-01-01T00:00:00"
    mock_load = mock_yaml[1]
    mock_load.return_value = {
        "git_state": {"commit_hash": "abc123", "is_clean": True},
        "dependencies": {"hash": "hash1"}
    }
    bm = BaselineManager("/tmp/baseline", "/tmp/repo")
    result = bm.compare_baseline()
    
    assert result["is_drifted"] is False


def test_compare_baseline_git_drift(mock_datetime, mock_yaml, mock_path_methods, mock_git_repo):
    mock_dt = mock_datetime
    mock_dt.datetime.now.return_value.isoformat.return_value = "2023-01-01T00:00:00"
    mock_load = mock_yaml[1]
    mock_load.return_value = {
        "git_state": {"commit_hash": "old_hash"},
        "dependencies": {"hash": "hash1"}
    }
    bm = BaselineManager("/tmp/baseline", "/tmp/repo")
    result = bm.compare_baseline()
    
    assert result["is_drifted"] is True
    assert len(result["changes"]) > 0


def test_compare_baseline_not_found(mock_datetime, mock_yaml, mock_path_methods):
    mock_load = mock_yaml[1]
    mock_load.return_value = None
    
    bm = BaselineManager("/tmp/baseline", "/tmp/repo")
    result = bm.compare_baseline(name="missing")
    
    assert "error" in result
    assert result["error"] == "Baseline not found"


# --- Deletion Tests ---

def test_delete_baseline_success(mock_datetime, mock_os_remove, mock_path_methods, mock_yaml):
    mock_dt = mock_datetime
    mock_dt.datetime.now.return_value.isoformat.return_value = "2023-01-01T00:00:00"
    
    bm = BaselineManager("/tmp/baseline", "/tmp/repo")
    result = bm.delete_baseline(name="test_baseline")
    
    assert result is True
    mock_os_remove.assert_called_once()


def test_delete_baseline_not_found(mock_datetime, mock_os_remove, mock_path_methods, mock_yaml):
    mock_dt = mock_datetime
    mock_dt.datetime.now.return_value.isoformat.return_value = "2023-01-01T00:00:00"
    mock_path = mock_path_methods[0]
    mock_path.exists.return_value = False
    
    bm = BaselineManager("/tmp/baseline", "/tmp/repo")
    result = bm.delete_baseline(name="missing")
    
    assert result is False
    mock_os_remove.assert_not_called()


def test_delete_baseline_os_error(mock_datetime, mock_os_remove, mock_path_methods, mock_yaml):
    mock_dt = mock_datetime
    mock_dt.datetime.now.return_value.isoformat.return_value = "2023-01-01T00:00:00"
    mock_os_remove.side_effect = OSError("Permission denied")
    
    bm = BaselineManager("/tmp/baseline", "/tmp/repo")
    with pytest.raises(BaselineManagerError):
        bm.delete_baseline(name="test")


# --- List Baselines Tests ---

def test_list_baselines_success(mock_datetime, mock_path_methods, mock_git_repo, mock_yaml):
    mock_dt = mock_datetime
    mock_dt.datetime.now.return_value.isoformat.return_value = "2023-01-01T00:00:00"
    
    bm = BaselineManager("/tmp/baseline", "/tmp/repo")
    result = bm.list_baselines()
    
    assert "test_baseline" in result


def test_list_baselines_empty(mock_datetime, mock_path_methods, mock_git_repo, mock_yaml):
    mock_dt = mock_datetime
    mock_dt.datetime.now.return_value.isoformat.return_value = "2023-01-01T00:00:00"
    mock_path = mock_path_methods[0]
    mock_path.glob.return_value = []
    
    bm = BaselineManager("/tmp/baseline", "/tmp/repo")
    result = bm.list_baselines()
    
    assert len(result) == 0


def test_list_baselines_os_error(mock_datetime, mock_path_methods, mock_git_repo, mock_yaml):
    mock_dt = mock_datetime
    mock_dt.datetime.now.return_value.isoformat.return_value = "2023-01-01T00:00:00"
    mock_path = mock_path_methods[0]
    mock_path.glob.side_effect = OSError("Disk full")
    
    bm = BaselineManager("/tmp/baseline", "/tmp/repo")
    with pytest.raises(BaselineManagerError):
        bm.list_baselines()


# --- Watcher Tests ---

def test_setup_watcher_success(mock_watcher, mock_datetime, mock_path_methods, mock_yaml, mock_git_repo):
    mock_dt = mock_datetime
    mock_dt.datetime.now.return_value.isoformat.return_value = "2023-01-01T00:00:00"
    
    bm = BaselineManager("/tmp/baseline", "/tmp/repo")
    observer = bm.setup_watcher()
    
    assert observer is not None
    mock_watcher.start.assert_called_once()


def test_setup_watcher_custom_handler(mock_watcher, mock_datetime, mock_path_methods, mock_yaml, mock_git_repo):
    mock_dt = mock_datetime
    mock_dt.datetime.now.return_value.isoformat.return_value = "2023-01-01T00:00:00"
    mock_handler = MagicMock()
    
    bm = BaselineManager("/tmp/baseline", "/tmp/repo")
    observer = bm.setup_watcher(handler=mock_handler)
    
    # Check schedule was called with custom handler
    assert mock_watcher.schedule.called


def test_setup_watcher_default_handler(mock_watcher, mock_datetime, mock_path_methods, mock_yaml, mock_git_repo):
    mock_dt = mock_datetime
    mock_dt.datetime.now.return_value.isoformat.return_value = "2023-01-01T00:00:00"
    
    bm = BaselineManager("/tmp/baseline", "/tmp/repo")
    observer = bm.setup_watcher()
    
    # Check default handler was used
    from baseline_manager import BaselineEventHandler
    # Since we patched Observer, we check the arguments to schedule if possible
    # Or verify that BaselineEventHandler was imported/used logic-wise. 
    # The logic check: schedule is called.
    assert mock_watcher.schedule.called


# --- Event Handler Tests ---

def test_event_handler_on_modified(setup_event_handler, caplog):
    handler = setup_event_handler
    mock_event = MagicMock()
    mock_event.is_directory = False
    mock_event.src_path = "/path/to/file.yaml"
    
    import logging
    caplog.set_level(logging.INFO)
    
    handler.on_modified(mock_event)
    
    assert "Baseline file modified" in caplog.text


def test_event_handler_on_created(setup_event_handler, caplog):
    handler = setup_event_handler
    mock_event = MagicMock()
    mock_event.is_directory = False
    mock_event.src_path = "/path/to/new.yaml"
    
    import logging
    caplog.set_level(logging.INFO)
    
    handler.on_created(mock_event)
    
    assert "Baseline file created" in caplog.text


def test_event_handler_directory_ignored(setup_event_handler, caplog):
    handler = setup_event_handler
    mock_event = MagicMock()
    mock_event.is_directory = True
    mock_event.src_path = "/path/to/dir"
    
    import logging
    caplog.set_level(logging.INFO)
    
    handler.on_modified(mock_event)
    
    # No log should be generated for directories
    assert "Baseline file modified" not in caplog.text
    assert "Baseline file created" not in caplog.text