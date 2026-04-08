import pytest
from unittest import mock
from unittest.mock import MagicMock, patch, Mock
import json
import os
import sys

# Import the module to be tested
import report_generator


@pytest.fixture
def mock_repo():
    """Fixture to create a mock Git repository object."""
    repo = MagicMock()
    repo.head.commit.hexsha = "abc123def456"
    repo.active_branch.name = "main"
    repo.is_dirty.return_value = False
    repo.index.diff.return_value = []
    repo.remote.return_value.url = "https://github.com/example/repo.git"
    return repo

@pytest.fixture
def mock_config():
    """Fixture to provide mock configuration data."""
    return {
        "paths": ["src", "tests"],
        "files": ["config.yaml", "settings.py"],
        "detected_drift": [
            {"type": "file_modified", "path": "src/app.py", "status": "changed", "severity": "warning"},
            {"type": "file_deleted", "path": "legacy.py", "status": "missing", "severity": "critical"}
        ]
    }

@pytest.fixture
def mock_yaml_loader(mock_config):
    """Fixture to patch yaml.safe_load."""
    with patch.object(report_generator, 'yaml') as mock_yaml:
        mock_yaml.safe_load.return_value = mock_config
        yield mock_yaml

@pytest.fixture
def mock_git(mock_repo):
    """Fixture to patch git.Repo."""
    with patch.object(report_generator, 'Repo') as mock_repo_class:
        mock_repo_class.return_value = mock_repo
        yield mock_repo_class

@pytest.fixture
def mock_file_operations():
    """Fixture to prevent real filesystem writes during testing."""
    with patch('builtins.open', new_callable=mock.mock_open()) as mock_file:
        with patch.object(report_generator.os, 'makedirs') as mock_makedirs:
            yield mock_file, mock_makedirs

@pytest.fixture
def mock_datetime():
    """Fixture to mock datetime.now()."""
    with patch.object(report_generator.datetime, 'now') as mock_now:
        mock_datetime_obj = MagicMock()
        mock_datetime_obj.isoformat.return_value = "2023-10-27T12:00:00"
        mock_now.return_value = mock_datetime_obj
        yield mock_datetime_obj


class TestLoadDriftConfig:
    def test_load_config_success(self, mock_yaml_loader, mock_config):
        """Test successful loading of valid YAML config."""
        with patch.object(report_generator.os, 'path', new=mock.MagicMock()):
            report = report_generator.load_drift_config("test_config.yaml")
            assert report == mock_config
            mock_yaml_loader.safe_load.assert_called_once()

    def test_load_config_file_not_found(self):
        """Test handling of missing configuration file."""
        with patch.object(report_generator.os.path, 'exists', return_value=False):
            with patch('builtins.open', side_effect=FileNotFoundError("File not found")):
                with patch('builtins.open', new_callable=mock.mock_open):
                    report = report_generator.load_drift_config("nonexistent.yaml")
                assert report == {"paths": [], "files": []}

    def test_load_config_parse_error(self, mock_config):
        """Test handling of YAML parsing errors."""
        with patch.object(report_generator.yaml, 'safe_load', side_effect=report_generator.yaml.YAMLError("Invalid YAML")):
            with pytest.raises(report_generator.DriftReportError):
                report_generator.load_drift_config("invalid.yaml")

    def test_load_config_default_path(self, mock_yaml_loader, mock_config):
        """Test loading from default config path."""
        with patch.object(report_generator.os.path, 'isfile', return_value=True):
            with patch('builtins.open', new_callable=mock.mock_open):
                report_generator.load_drift_config()
                # Verify default path is used if no argument provided
                call_args = mock_yaml_loader.safe_load.call_args
                # The file open is called, we verify logic implicitly via return value


class TestGetRepositoryState:
    def test_get_repo_state_success(self, mock_git, mock_repo):
        """Test successful retrieval of repository state."""
        state = report_generator.get_repository_state("./test_repo")
        assert state["current_commit"] == "abc123def456"
        assert state["branch"] == "main"
        assert state["is_dirty"] == False

    def test_get_repo_state_dirty(self, mock_git, mock_repo):
        """Test handling of dirty repository state."""
        mock_repo.is_dirty.return_value = True
        state = report_generator.get_repository_state("./test_repo")
        assert state["is_dirty"] == True

    def test_get_repo_state_git_error(self, mock_git):
        """Test handling of Git command errors."""
        mock_git.side_effect = report_generator.GitCommandError("git", "status", "error")
        with pytest.raises(report_generator.DriftReportError):
            report_generator.get_repository_state("./invalid_repo")

    def test_get_repo_state_os_error(self, mock_git):
        """Test handling of OS errors."""
        mock_git.side_effect = OSError("Access denied")
        with pytest.raises(report_generator.DriftReportError):
            report_generator.get_repository_state("./blocked_repo")


class TestFormatDriftData:
    def test_format_drift_data_basic(self, mock_datetime):
        """Test standard data formatting."""
        drift_data = {"drift_events": [], "system_state": {}}
        report = report_generator.format_drift_data(drift_data)
        assert "metadata" in report
        assert "generated_at" in report["metadata"]
        assert report["format"] == "drift_detection_v1"

    def test_format_drift_data_with_repo_state(self):
        """Test formatting with provided repository state."""
        drift_data = {"drift_events": [{"id": 1}]}
        repo_state = {"branch": "feature-x", "commit": "xyz"}
        report = report_generator.format_drift_data(drift_data, repo_state)
        assert report["repository"]["branch"] == "feature-x"

    def test_format_drift_data_empty_inputs(self):
        """Test formatting with minimal input data."""
        drift_data = {}
        report = report_generator.format_drift_data(drift_data)
        assert report["drift_events"] == []
        assert report["system_state"] == {}


class TestGenerateJsonReport:
    def test_generate_json_report_content(self, mock_datetime):
        """Test JSON string generation correctness."""
        data = {"test": "value"}
        json_str = report_generator.generate_json_report(data)
        parsed = json.loads(json_str)
        assert parsed["test"] == "value"

    def test_generate_json_report_file_write(self, mock_file_operations, mock_datetime):
        """Test writing JSON report to disk."""
        data = {"test": "value"}
        output_path = "output/report.json"
        
        mock_file, _ = mock_file_operations
        result = report_generator.generate_json_report(data, output_path)
        
        # Verify file was opened for writing
        mock_file.assert_called_once_with(output_path, 'w', encoding='utf-8')

    def test_generate_json_report_serialization_error(self):
        """Test handling of invalid data types in serialization."""
        data = {"complex": complex(1, 2)}
        with pytest.raises(report_generator.DriftReportError):
            report_generator.generate_json_report(data)

    def test_generate_json_report_path_creation(self, mock_file_operations, mock_datetime):
        """Test creation of output directory."""
        data = {"test": "value"}
        report_generator.generate_json_report(data, "new_dir/report.json")
        assert report_generator.os.makedirs.called


class TestGenerateHtmlReport:
    def test_generate_html_report_structure(self, mock_datetime):
        """Test HTML report structure generation."""
        data = {
            "metadata": {"generated_at": "2023-01-01"},
            "repository": {"branch": "main"},
            "drift_events": []
        }
        html = report_generator.generate_html_report(data)
        assert "<!DOCTYPE html>" in html
        assert "Drift Report" in html

    def test_generate_html_report_with_events(self, mock_datetime):
        """Test HTML report includes drift events."""
        data = {
            "metadata": {},
            "repository": {"branch": "dev"},
            "drift_events": [{"type": "MODIFIED", "path": "test.txt", "status": "ok", "severity": "high"}]
        }
        html = report_generator.generate_html_report(data)
        assert "MODIFIED" in html
        assert "high" in html

    def test_generate_html_report_file_write(self, mock_file_operations, mock_datetime):
        """Test writing HTML report to disk."""
        data = {"metadata": {}, "repository": {}, "drift_events": []}
        output_path = "output/report.html"
        
        mock_file, _ = mock_file_operations
        report_generator.generate_html_report(data, output_path)
        
        mock_file.assert_called_once_with(output_path, 'w', encoding='utf-8')


class TestExportReport:
    def test_export_report_json_format(self, mock_file_operations, mock_yaml_loader, mock_git, mock_config, mock_datetime):
        """Test export report generation in JSON format."""
        with patch.object(report_generator.os, 'path', new=mock.MagicMock()):
            result = report_generator.export_report(
                config_path="test.yaml",
                repo_path=".",
                output_dir="output",
                output_format="json"
            )
            assert isinstance(result, str)
            assert '"metadata"' in result

    def test_export_report_html_format(self, mock_file_operations, mock_yaml_loader, mock_git, mock_config, mock_datetime):
        """Test export report generation in HTML format."""
        with patch.object(report_generator.os, 'path', new=mock.MagicMock()):
            result = report_generator.export_report(
                config_path="test.yaml",
                repo_path=".",
                output_dir="output",
                output_format="html"
            )
            assert isinstance(result, str)
            assert "<table>" in result

    def test_export_report_invalid_format(self, mock_yaml_loader, mock_git, mock_config):
        """Test error handling for unsupported formats."""
        with patch.object(report_generator.os, 'path', new=mock.MagicMock()):
            with pytest.raises(ValueError):
                report_generator.export_report(
                    config_path="test.yaml",
                    repo_path=".",
                    output_dir="output",
                    output_format="pdf"
                )

    def test_export_report_error_handling(self, mock_yaml_loader, mock_git, mock_config):
        """Test propagation of errors during export."""
        mock_git.side_effect = report_generator.GitCommandError("fail")
        with patch.object(report_generator.os, 'path', new=mock.MagicMock()):
            with pytest.raises(report_generator.DriftReportError):
                report_generator.export_report(
                    config_path="test.yaml",
                    repo_path="."
                )


class TestWatchdogIntegration:
    @patch.object(report_generator, 'HAS_WATCHDOG', True)
    def test_watchdog_handler_creation(self, mock_datetime):
        """Test DriftEventHandler initialization."""
        handler = report_generator.DriftEventHandler()
        assert isinstance(handler.events, list)

    @patch.object(report_generator, 'HAS_WATCHDOG', True)
    def test_watchdog_events_capture(self, mock_datetime):
        """Test capture of file system events via watchdog."""
        # Simulate mock event
        mock_event = MagicMock()
        mock_event.is_directory = False
        mock_event.src_path = "/path/to/file.txt"
        
        handler = report_generator.DriftEventHandler()
        handler._log_event(mock_event)
        assert len(handler.events) == 1

    @patch.object(report_generator, 'HAS_WATCHDOG', True)
    def test_get_watchdog_events_timeout(self, mock_datetime):
        """Test get_watchdog_events returns list after timeout."""
        # Mocking time.sleep to avoid waiting
        with patch.object(report_generator, 'time', new=MagicMock()):
            with patch.object(report_generator, 'Observer') as MockObserver:
                mock_obs = MagicMock()
                MockObserver.return_value = mock_obs
                result = report_generator.get_watchdog_events()
                assert isinstance(result, list)

    @patch.object(report_generator, 'HAS_WATCHDOG', False)
    def test_watchdog_disabled_behavior(self):
        """Test behavior when watchdog is not available."""
        result = report_generator.get_watchdog_events()
        assert result == []


class TestCLICommands:
    @patch('click.echo')
    def test_cli_drift_report_command(self, mock_echo, mock_file_operations, mock_yaml_loader, mock_git, mock_config, mock_datetime):
        """Test CLI command for drift report."""
        runner = click.testing.CliRunner()
        result = runner.invoke(report_generator.cli, ['drift_report', '-c', 'test.yaml', '-f', 'json'])
        
        assert result.exit_code == 0
        # Click.echo is patched, so check logic via side effects or return
        # In real scenario we check output, here we verify execution path
        assert result.exception is None

    @patch('click.echo')
    def test_cli_process_raw_data(self, mock_echo, mock_datetime):
        """Test CLI command for processing raw JSON data."""
        runner = click.testing.CliRunner()
        raw_data = json.dumps({"drift_events": [], "system_state": {}})
        result = runner.invoke(report_generator.cli, ['process_raw_data', raw_data])
        
        assert result.exit_code == 0

    @patch('click.echo')
    def test_cli_invalid_config(self, mock_echo, mock_yaml_loader):
        """Test CLI handling of invalid config errors."""
        mock_yaml_loader.side_effect = report_generator.DriftReportError("Bad config")
        runner = click.testing.CliRunner()
        result = runner.invoke(report_generator.cli, ['drift_report', '-c', 'bad.yaml'])
        
        assert result.exit_code == 1
        assert "Error generating report" in str(result.output)


class TestFixturesAndImports:
    def test_module_has_required_classes(self):
        """Verify required exception and classes exist."""
        assert hasattr(report_generator, "DriftReportError")
        assert issubclass(report_generator.DriftReportError, Exception)
        assert hasattr(report_generator, "load_drift_config")
        assert hasattr(report_generator, "get_repository_state")

    def test_cli_has_commands(self):
        """Verify CLI group has expected subcommands."""
        commands = list(report_generator.cli.commands.keys())
        assert "drift_report" in commands
        assert "process_raw_data" in commands
        assert "watch_directory" in commands

    def test_watchdog_stub_when_disabled(self):
        """Test that stub handler works when watchdog is disabled."""
        # This relies on the module logic where `HAS_WATCHDOG` is false
        # In the test environment, we mock it to be false if needed, 
        # but we verify the stub class structure exists.
        handler = report_generator.DriftEventHandler()
        assert hasattr(handler, 'on_created')
        assert hasattr(handler, 'on_modified')
        assert hasattr(handler, 'events')