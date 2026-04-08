import json
import os
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
import yaml
import click
from git import Repo, GitCommandError

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    HAS_WATCHDOG = True
except ImportError:
    HAS_WATCHDOG = False

DEFAULT_CONFIG_PATH = "drift_config.yaml"

class DriftReportError(Exception):
    """Custom exception for drift report generation errors."""
    pass

def load_drift_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Loads drift detection configuration from a YAML file.

    Args:
        config_path: Path to the YAML configuration file. Defaults to 'drift_config.yaml'.

    Returns:
        A dictionary containing the loaded configuration.

    Raises:
        DriftReportError: If the configuration file cannot be read or parsed.
    """
    if config_path is None:
        config_path = DEFAULT_CONFIG_PATH

    try:
        with open(config_path, 'r', encoding='utf-8') as file:
            config = yaml.safe_load(file)
            if config is None:
                config = {}
            return config
    except FileNotFoundError:
        # Fallback to default structure if config file missing
        return {"paths": [], "files": []}
    except yaml.YAMLError as e:
        raise DriftReportError(f"Failed to parse YAML configuration: {e}")
    except IOError as e:
        raise DriftReportError(f"Failed to read configuration file: {e}")

def get_repository_state(repo_path: str = ".") -> Dict[str, Any]:
    """
    Retrieves the current state of the Git repository using GitPython.

    Args:
        repo_path: Path to the repository directory. Defaults to current directory.

    Returns:
        A dictionary containing commit hash, branch, and file status.

    Raises:
        DriftReportError: If Git is not installed or repository is invalid.
    """
    try:
        repo = Repo(repo_path)
        return {
            "current_commit": repo.head.commit.hexsha,
            "branch": repo.active_branch.name,
            "is_dirty": repo.is_dirty(),
            "status": list(repo.index.diff(None)) if not repo.is_dirty(add_ignored=False) else [],
            "remote_url": repo.remote().url if repo.remotes else None
        }
    except GitCommandError as e:
        raise DriftReportError(f"Git command failed: {e}")
    except ValueError as e:
        raise DriftReportError(f"Invalid repository path: {e}")
    except OSError as e:
        raise DriftReportError(f"OS Error accessing repository: {e}")

def format_drift_data(drift_data: Dict[str, Any], repo_state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Formats raw drift data into a standard report structure.

    Args:
        drift_data: Raw data collected from drift detection.
        repo_state: Optional state information from GitPython.

    Returns:
        A standardized report dictionary.
    """
    report = {
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "generator_version": "1.0.0",
            "format": "drift_detection_v1"
        },
        "drift_events": drift_data.get("drift_events", []),
        "system_state": drift_data.get("system_state", {}),
        "repository": repo_state or {}
    }
    return report

def generate_json_report(report_data: Dict[str, Any], output_path: Optional[str] = None) -> str:
    """
    Generates a JSON formatted drift report.

    Args:
        report_data: The structured report data.
        output_path: Optional file path to save the report.

    Returns:
        The JSON string representation of the report.

    Raises:
        DriftReportError: If JSON serialization fails.
    """
    try:
        json_string = json.dumps(report_data, indent=2)
        
        if output_path:
            os.makedirs(os.path.dirname(output_path), exist_ok=True) if os.path.dirname(output_path) else None
            with open(output_path, 'w', encoding='utf-8') as file:
                file.write(json_string)
        
        return json_string
    except (TypeError, ValueError) as e:
        raise DriftReportError(f"Failed to serialize JSON report: {e}")
    except IOError as e:
        raise DriftReportError(f"Failed to write JSON report to disk: {e}")

def generate_html_report(report_data: Dict[str, Any], output_path: Optional[str] = None) -> str:
    """
    Generates an HTML formatted drift report for visual inspection.

    Args:
        report_data: The structured report data.
        output_path: Optional file path to save the report.

    Returns:
        The HTML string representation of the report.

    Raises:
        DriftReportError: If HTML generation or file writing fails.
    """
    try:
        timestamp = report_data.get("metadata", {}).get("generated_at", "Unknown")
        events = report_data.get("drift_events", [])
        repo_state = report_data.get("repository", {})
        
        events_html = ""
        for event in events:
            event_type = event.get("type", "Unknown")
            path = event.get("path", "Unknown")
            status = event.get("status", "Unknown")
            severity = event.get("severity", "Warning")
            timestamp_event = event.get("timestamp", "")
            
            events_html += (
                f"<tr style='border: 1px solid #ddd; padding: 8px;'>\n"
                f"<td style='border: 1px solid #ddd; padding: 8px;'>{event_type}</td>\n"
                f"<td style='border: 1px solid #ddd; padding: 8px;'>{path}</td>\n"
                f"<td style='border: 1px solid #ddd; padding: 8px;'>{status}</td>\n"
                f"<td style='border: 1px solid #ddd; padding: 8px;'>{severity}</td>\n"
                f"</tr>\n"
            )

        repo_info_html = f"""
        <tr>
            <td><strong>Branch</strong></td>
            <td>{repo_state.get('branch', 'N/A')}</td>
        </tr>
        <tr>
            <td><strong>Commit</strong></td>
            <td>{repo_state.get('current_commit', 'N/A')[:7] if repo_state.get('current_commit') else 'N/A'}</td>
        </tr>
        <tr>
            <td><strong>Is Dirty</strong></td>
            <td>{repo_state.get('is_dirty', False)}</td>
        </tr>
        """

        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <title>Drift Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; }}
        table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
        th, td {{ text-align: left; padding: 8px; }}
        tr:nth-child(even) {{ background-color: #f2f2f2; }}
        th {{ background-color: #4CAF50; color: white; }}
        .critical {{ color: red; }}
        .warning {{ color: orange; }}
    </style>
</head>
<body>
    <h1>Development Environment Drift Report</h1>
    <p>Generated at: {timestamp}</p>
    
    <h2>Repository State</h2>
    <table>
        {repo_info_html}
    </table>

    <h2>Drift Events</h2>
    <table>
        <thead>
            <tr>
                <th>Type</th>
                <th>Path</th>
                <th>Status</th>
                <th>Severity</th>
            </tr>
        </thead>
        <tbody>
            {events_html if events_html else '<tr><td colspan="4">No drift events detected</td></tr>'}
        </tbody>
    </table>
</body>
</html>"""

        if output_path:
            os.makedirs(os.path.dirname(output_path), exist_ok=True) if os.path.dirname(output_path) else None
            with open(output_path, 'w', encoding='utf-8') as file:
                file.write(html_content)
        
        return html_content
    except IOError as e:
        raise DriftReportError(f"Failed to write HTML report: {e}")

def export_report(
    config_path: Optional[str] = None,
    repo_path: str = ".",
    output_dir: Optional[str] = None,
    output_format: str = "json"
) -> str:
    """
    Orchestrates the generation of a drift report in the specified format.

    Args:
        config_path: Path to the drift detection config.
        repo_path: Path to the git repository.
        output_dir: Directory to save reports. If None, reports are printed to stdout.
        output_format: Either 'json' or 'html'.

    Returns:
        Path to the generated file or the content string.

    Raises:
        DriftReportError: If configuration loading or report generation fails.
    """
    try:
        config = load_drift_config(config_path)
        repo_state = get_repository_state(repo_path)
        
        # Simulate gathering drift data based on config for this module context
        # In a real scenario, watchdog or other detectors would populate 'drift_data'
        drift_data = {
            "drift_events": config.get("detected_drift", []),
            "system_state": {"os": os.name, "python_version": "3.9+"}
        }

        formatted_report = format_drift_data(drift_data, repo_state)
        
        if output_format == "json":
            report_content = generate_json_report(formatted_report, output_dir)
        elif output_format == "html":
            report_content = generate_html_report(formatted_report, output_dir)
        else:
            raise ValueError(f"Unsupported format: {output_format}")
            
        return report_content

    except DriftReportError:
        raise
    except Exception as e:
        raise DriftReportError(f"Unexpected error during report generation: {e}")

@click.group()
def cli():
    """CLI Tool for generating drift reports."""
    pass

@cli.command()
@click.option('--config', '-c', default=DEFAULT_CONFIG_PATH, help='Path to drift config file.')
@click.option('--repo', '-r', default='.', help='Path to git repository.')
@click.option('--output-dir', '-o', help='Directory to save the report.')
@click.option('--format', '-f', type=click.Choice(['json', 'html']), default='json', help='Output format.')
def drift_report(config: str, repo: str, output_dir: Optional[str], format: str):
    """
    Generate a drift report based on the current environment.

    This command uses the configuration to determine what to check, 
    inspects the git state, and outputs a report.
    """
    try:
        report_data = export_report(
            config_path=config,
            repo_path=repo,
            output_dir=output_dir,
            output_format=format
        )
        click.echo(f"Report generated successfully at {output_dir if output_dir else 'stdout'}")
        click.echo(report_data)
    except DriftReportError as e:
        click.echo(f"Error generating report: {e}", err=True)
        raise click.Abort()

@cli.command()
@click.argument('drift_data_json')
@click.option('--output', '-o', type=click.Path(), help='Output file path.')
def process_raw_data(drift_data_json: str, output: str):
    """
    Process raw drift data JSON string and generate a formatted report.
    
    Useful for piping data from other monitoring tools.
    """
    try:
        # Basic validation that input is valid JSON
        import json as stdjson
        raw_input = stdjson.loads(drift_data_json)
        
        formatted_report = format_drift_data(raw_input)
        
        if output:
            output = generate_json_report(formatted_report, output)
        else:
            output = generate_json_report(formatted_report)
            
        click.echo("Processed report output:")
        click.echo(output)
    except ValueError as e:
        click.echo(f"Invalid JSON input: {e}", err=True)
        raise click.Abort()
    except DriftReportError as e:
        click.echo(f"Report generation error: {e}", err=True)
        raise click.Abort()

if HAS_WATCHDOG:
    class DriftEventHandler(FileSystemEventHandler):
        """Simple handler to record file changes for watchdog integration."""
        
        def __init__(self):
            super().__init__()
            self.events: List[Dict[str, Any]] = []

        def on_created(self, event):
            self._log_event(event)

        def on_modified(self, event):
            self._log_event(event)

        def _log_event(self, event):
            if not event.is_directory:
                self.events.append({
                    "type": "file_change",
                    "path": event.src_path,
                    "timestamp": datetime.now().isoformat()
                })

    def get_watchdog_events(directory: str = ".") -> List[Dict[str, Any]]:
        """
        Uses watchdog to observe file changes in a directory.
        This function starts the observer, waits 1 second, then stops.
        
        Args:
            directory: Path to monitor.

        Returns:
            List of detected file events.
        """
        if not HAS_WATCHDOG:
            return []
            
        try:
            observer = Observer()
            handler = DriftEventHandler()
            observer.schedule(handler, directory, recursive=True)
            observer.start()
            
            # Wait for initial scan
            import time
            time.sleep(1)
            
            events = handler.events
            observer.stop()
            observer.join()
            return events
        except Exception:
            return []
else:
    def get_watchdog_events(directory: str = ".") -> List[Dict[str, Any]]:
        """
        Placeholder for watchdog functionality if library is unavailable.
        Returns empty list as watchdog is not installed.
        """
        return []

    class DriftEventHandler:
        """Stub for DriftEventHandler when watchdog is unavailable."""
        def __init__(self):
            self.events = []
        def on_created(self, event): pass
        def on_modified(self, event): pass

@cli.command()
@click.argument('directory', default='.')
@click.option('--output-json', '-j', type=click.Path(), help='Save detected events as JSON.')
def watch_directory(directory: str, output_json: Optional[str]):
    """
    Watches a directory for file system changes using watchdog (if available).
    
    Useful for simulating drift detection input for the report generator.
    """
    if not HAS_WATCHDOG:
        click.echo("Warning: watchdog is not installed. No file system events will be captured.", err=True)
        
    try:
        events = get_watchdog_events(directory)
        click.echo(f"Detected {len(events)} changes.")
        
        if output_json:
            with open(output_json, 'w') as f:
                json.dump({"detected_drift": events, "timestamp": datetime.now().isoformat()}, f)
            click.echo(f"Events saved to {output_json}")
        else:
            click.echo(json.dumps(events, indent=2))
    except DriftReportError as e:
        click.echo(f"Error during directory watch: {e}", err=True)
        raise click.Abort()

if HAS_WATCHDOG:
    # Exporting the handler for external use if needed
    __all__ = [
        "DriftReportError", "load_drift_config", "get_repository_state", 
        "format_drift_data", "generate_json_report", "generate_html_report", 
        "export_report", "cli", "DriftEventHandler", "get_watchdog_events"
    ]
else:
    __all__ = [
        "DriftReportError", "load_drift_config", "get_repository_state", 
        "format_drift_data", "generate_json_report", "generate_html_report", 
        "export_report", "cli", "get_watchdog_events"
    ]