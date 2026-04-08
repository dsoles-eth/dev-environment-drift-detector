import pytest
from unittest.mock import patch, MagicMock, mock_open, Mock
from pathlib import Path
import sys
import time
import alert_system
import logging

# Configure pytest to ignore logging warnings from tests
@pytest.fixture(autouse=True)
def setup_logging():
    logging.getLogger('alert_system').setLevel(logging.ERROR)

@pytest.fixture
def mock_git_repo():
    repo = Mock()
    repo.git.status.return_value = "M file1\n M file2"
    repo.remotes = [Mock(name='origin')]
    repo.remotes[0].fetch.return_value = None
    repo.head.is_detached = False
    repo.active_branch = True
    return repo

@pytest.fixture
def mock_file_system():
    path = Mock(spec=Path)
    path.exists.return_value = True
    path.suffix = ".yaml"
    return path

@pytest.fixture
def mock_click_echo():
    return Mock()

class TestDriftAlert:
    @patch.object(alert_system, 'time')
    def test_alert_is_significant_high(self, mock_time):
        mock_time.time.return_value = 1000.0
        alert = alert_system.DriftAlert(message="Test", severity="high")
        assert alert.is_significant() is True

    @patch.object(alert_system, 'time')
    def test_alert_is_significant_critical(self, mock_time):
        mock_time.time.return_value = 1000.0
        alert = alert_system.DriftAlert(message="Test", severity="critical")
        assert alert.is_significant() is True

    @patch.object(alert_system, 'time')
    def test_alert_is_significant_low(self, mock_time):
        mock_time.time.return_value = 1000.0
        alert = alert_system.DriftAlert(message="Test", severity="low")
        assert alert.is_significant() is False

class TestDriftFileEventHandler:
    @patch.object(alert_system, 'DriftDetectionEvent')
    def test_on_created_emits_event(self, mock_event):
        mock_event.side_effect = lambda source, details: alert_system.DriftDetectionEvent(source=source, details=details)
        handler = alert_system.DriftFileEventHandler()
        event = Mock()
        event.is_directory = False
        event.src_path = "/tmp/test.txt"
        result = handler.on_created(event)
        assert isinstance(result, alert_system.DriftDetectionEvent)
        assert result.source == "/tmp/test.txt"
        assert result.details["type"] == "created"

    @patch.object(alert_system, 'DriftDetectionEvent')
    def test_on_modified_emits_event(self, mock_event):
        mock_event.side_effect = lambda source, details: alert_system.DriftDetectionEvent(source=source, details=details)
        handler = alert_system.DriftFileEventHandler()
        event = Mock()
        event.is_directory = False
        event.src_path = "/tmp/test.txt"
        result = handler.on_modified(event)
        assert isinstance(result, alert_system.DriftDetectionEvent)
        assert result.details["type"] == "modified"

    @patch.object(alert_system, 'logger')
    @patch.object(alert_system, 'DriftDetectionEvent')
    def test_on_created_error_path(self, mock_event, mock_logger):
        handler = alert_system.DriftFileEventHandler()
        event = Mock()
        event.is_directory = False
        event.src_path = "/tmp/test.txt"
        mock_event.side_effect = Exception("File system error")
        result = handler._handle_event(event.src_path, "created")
        assert result is None
        mock_logger.error.assert_called()

class TestGitDriftChecker:
    @patch.object(alert_system, 'Repo')
    @patch.object(alert_system, 'Path')
    def test_get_repo_success(self, mock_path, mock_repo):
        mock_path.return_value.exists.return_value = True
        mock_repo.return_value = Mock()
        checker = alert_system.GitDriftChecker("/tmp/repo")
        result = checker.get_repo()
        assert result is mock_repo.return_value

    @patch.object(alert_system, 'Repo')
    @patch.object(alert_system, 'Path')
    def test_get_repo_no_path(self, mock_path, mock_repo):
        mock_path.return_value.exists.return_value = False
        checker = alert_system.GitDriftChecker("/tmp/repo")
        result = checker.get_repo()
        assert result is None

    @patch.object(alert_system, 'Repo')
    def test_check_drift_no_repo(self, mock_repo):
        mock_repo.return_value = None
        checker = alert_system.GitDriftChecker("/tmp/repo")
        checker._repo = None
        result = checker.check_drift()
        assert result == []

class TestNotificationService:
    @patch.object(alert_system, 'DriftAlert')
    def test_notify_significant_high(self, mock_alert):
        alert = Mock()
        alert.is_significant.return_value = True
        alert.message = "Test"
        alert.severity = "high"
        service = alert_system.NotificationService()
        result = service.notify(alert)
        assert result is True
        alert.is_significant.assert_called()

    @patch.object(alert_system, 'DriftAlert')
    def test_notify_not_significant(self, mock_alert):
        alert = Mock()
        alert.is_significant.return_value = False
        alert.message = "Test"
        alert.severity = "low"
        service = alert_system.NotificationService()
        result = service.notify(alert)
        assert result is False

    @patch.object(alert_system, 'logging')
    def test_notify_callback_error(self, mock_logging):
        callback = Mock(side_effect=Exception("Callback failed"))
        service = alert_system.NotificationService(callback=callback)
        alert = Mock()
        alert.is_significant.return_value = True
        alert.message = "Test"
        alert.severity = "high"
        result = service.notify(alert)
        assert result is False
        mock_logging.error.assert_called()

class TestDevDriftManager:
    @patch.object(alert_system, 'Observer')
    @patch.object(alert_system, 'DriftFileEventHandler')
    @patch.object(alert_system, 'GitDriftChecker')
    @patch.object(alert_system, 'NotificationService')
    def test_start_monitoring_success(self, mock_notify, mock_checker, mock_handler, mock_observer):
        mock_observer.return_value = Mock()
        mock_checker.return_value = Mock()
        mock_handler.return_value = Mock()
        config = alert_system.DriftConfig(watched_paths=["/tmp"], git_repo_path="/tmp")
        manager = alert_system.DevDriftManager(config)
        result = manager.start_monitoring()
        assert result is True
        mock_observer.return_value.start.assert_called_once()

    @patch.object(alert_system, 'Observer')
    @patch.object(alert_system, 'DriftFileEventHandler')
    @patch.object(alert_system, 'GitDriftChecker')
    @patch.object(alert_system, 'NotificationService')
    def test_start_monitoring_already_running(self, mock_notify, mock_checker, mock_handler, mock_observer):
        mock_observer.return_value = Mock()
        mock_checker.return_value = Mock()
        mock_handler.return_value = Mock()
        config = alert_system.DriftConfig(watched_paths=["/tmp"], git_repo_path="/tmp")
        manager = alert_system.DevDriftManager(config)
        manager._is_running = True
        result = manager.start_monitoring()
        assert result is True

    @patch.object(alert_system, 'Observer')
    @patch.object(alert_system, 'GitDriftChecker')
    @patch.object(alert_system, 'NotificationService')
    def test_stop_monitoring_success(self, mock_notify, mock_checker, mock_observer):
        manager = alert_system.DevDriftManager(alert_system.DriftConfig())
        manager.observer = Mock()
        manager.stop_monitoring()
        manager.observer.stop.assert_called_once()

class TestDevDriftManagerDriftHandling:
    @patch.object(alert_system, 'NotificationService')
    def test_handle_git_drift_uncommitted(self, mock_notify):
        manager = alert_system.DevDriftManager(alert_system.DriftConfig())
        manager.notification_service = mock_notify
        drift = {"type": "git_uncommitted", "path": "/repo"}
        manager._handle_git_drift(drift)
        mock_notify.notify.assert_called_once()

    @patch.object(alert_system, 'NotificationService')
    @patch('builtins.open', new_callable=mock_open, read_data="key: value\n")
    def test_handle_file_drift_success(self, mock_open, mock_notify):
        manager = alert_system.DevDriftManager(alert_system.DriftConfig())
        manager.notification_service = mock_notify
        event = alert_system.DriftDetectionEvent(source="/tmp/config.yaml", details={"type": "modified"})
        manager._handle_file_drift(event)
        mock_open.assert_called_once()
        mock_notify.notify.assert_called_once()

    @patch.object(alert_system, 'NotificationService')
    @patch('builtins.open', new_callable=mock_open, side_effect=Exception("Read Error"))
    def test_handle_file_drift_error(self, mock_open, mock_notify):
        manager = alert_system.DevDriftManager(alert_system.DriftConfig())
        manager.notification_service = mock_notify
        event = alert_system.DriftDetectionEvent(source="/tmp/config.txt", details={"type": "modified"})
        manager._handle_file_drift(event)
        mock_open.assert_called_once()

class TestDevDriftManagerCheckAll:
    @patch.object(alert_system, 'GitDriftChecker')
    def test_check_all_returns_alerts(self, mock_checker):
        mock_checker.return_value.check_drift.return_value = [{"type": "git_uncommitted", "path": "/repo"}]
        config = alert_system.DriftConfig(git_repo_path="/repo")
        manager = alert_system.DevDriftManager(config)
        manager.git_checker = mock_checker.return_value
        alerts = manager.check_all()
        assert len(alerts) == 1
        assert alerts[0].severity == "high"

    @patch.object(alert_system, 'GitDriftChecker')
    def test_check_all_no_drift(self, mock_checker):
        mock_checker.return_value.check_drift.return_value = []
        config = alert_system.DriftConfig(git_repo_path="/repo")
        manager = alert_system.DevDriftManager(config)
        manager.git_checker = mock_checker.return_value
        alerts = manager.check_all()
        assert len(alerts) == 0

    @patch.object(alert_system, 'GitDriftChecker')
    def test_check_all_git_checker_none(self, mock_checker):
        config = alert_system.DriftConfig(git_repo_path=None)
        manager = alert_system.DevDriftManager(config)
        alerts = manager.check_all()
        assert len(alerts) == 0

class TestCLI:
    @patch.object(alert_system, 'click')
    @patch.object(alert_system, 'DevDriftManager')
    @patch.object(alert_system, 'DriftConfig')
    @patch.object(alert_system, 'time')
    def test_cli_check_git_success(self, mock_time, mock_config, mock_manager, mock_click):
        with patch.object(alert_system, 'GitDriftChecker') as mock_checker:
            mock_checker.return_value.check_drift.return_value = []
            alert_system.cli(['check-git', '--git-path', '/repo'])
            mock_click.echo.assert_called()

    @patch.object(alert_system, 'click')
    def test_cli_check_git_no_path(self, mock_click):
        with patch.object(alert_system, 'GitDriftChecker') as mock_checker:
            mock_checker.return_value.check_drift.return_value = []
            alert_system.cli(['check-git'])
            mock_click.echo.assert_called()

    @patch.object(alert_system, 'click')
    @patch.object(alert_system, 'DevDriftManager')
    @patch.object(alert_system, 'DriftConfig')
    def test_cli_start_monitoring(self, mock_config, mock_manager, mock_click):
        mock_manager.return_value.start_monitoring.return_value = True
        mock_manager.return_value.stop_monitoring.return_value = None
        with patch.object(alert_system, 'time'):
            with patch.object(alert_system, 'click', side_effect=KeyboardInterrupt):
                with patch.object(alert_system, 'DevDriftManager'):
                    alert_system.cli(['start-monitoring', '-p', '/tmp'])
                    mock_click.echo.assert_called()

    @patch.object(alert_system, 'click')
    def test_cli_check_git_error(self, mock_click):
        with patch.object(alert_system, 'GitDriftChecker') as mock_checker:
            mock_checker.side_effect = Exception("Git Error")
            exit_code = alert_system.cli(['check-git', '--git-path', '/repo'])
            assert exit_code == 1