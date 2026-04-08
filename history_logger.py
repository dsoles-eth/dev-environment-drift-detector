from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
import yaml
import os


@dataclass
class DriftEntry:
    """Represents a single drift event recorded in the history log."""
    timestamp: datetime
    drift_type: str
    file_path: str
    message: str
    severity: str
    metadata: Optional[Dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Converts the entry to a dictionary for YAML serialization."""
        data = asdict(self)
        data['timestamp'] = self.timestamp.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DriftEntry':
        """Reconstructs an entry from a dictionary."""
        timestamp_str = data.get('timestamp')
        if timestamp_str:
            data['timestamp'] = datetime.fromisoformat(timestamp_str)
        return cls(**data)


class DriftHistoryLogger:
    """Manages the persistence and retrieval of drift event history."""

    def __init__(self, log_path: Optional[str] = None):
        """
        Initialize the DriftHistoryLogger.

        Args:
            log_path: The absolute or relative path to the YAML log file.
                      Defaults to 'drift_history.yaml' in the current directory.

        Raises:
            ValueError: If the log_path is empty or None.
        """
        self.log_path = Path(log_path) if log_path else Path('drift_history.yaml')
        
        if not self.log_path:
            raise ValueError("Log path cannot be empty")

        try:
            self._ensure_directory_exists()
            self._initialize_history()
        except OSError as e:
            raise RuntimeError(f"Failed to initialize logger storage at {self.log_path}: {e}")

    def _ensure_directory_exists(self) -> None:
        """Creates the parent directory for the log file if it does not exist."""
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise OSError(f"Could not create directory for log file: {e}")

    def _initialize_history(self) -> Dict[str, Any]:
        """
        Loads existing history from the log file.

        Returns:
            The loaded history data dictionary.
        """
        history = {'entries': []}
        if not self.log_path.exists():
            return history

        try:
            with open(self.log_path, 'r', encoding='utf-8') as f:
                loaded_data = yaml.safe_load(f)
                if isinstance(loaded_data, dict) and 'entries' in loaded_data:
                    history = loaded_data
                else:
                    # Corrupted or unexpected format, start fresh
                    history = {'entries': []}
                    self._write_history(history)
        except (yaml.YAMLError, IOError) as e:
            raise RuntimeError(f"Failed to read existing history log: {e}")
        
        return history

    def _write_history(self, data: Dict[str, Any]) -> None:
        """
        Writes the history data to the file safely.

        Args:
            data: The dictionary containing history entries to save.
        
        Raises:
            IOError: If writing to the file fails.
        """
        try:
            with open(self.log_path, 'w', encoding='utf-8') as f:
                yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        except IOError as e:
            raise IOError(f"Failed to write history log: {e}")

    def log_drift(self, drift_type: str, file_path: str, message: str, 
                  severity: str = "INFO", metadata: Optional[Dict[str, Any]] = None) -> DriftEntry:
        """
        Records a new drift event to the history.

        Args:
            drift_type: The category of the drift (e.g., 'dependency_change', 'config_update').
            file_path: The path of the file experiencing drift.
            message: A descriptive message about the drift.
            severity: The severity level of the event (e.g., 'INFO', 'WARNING', 'ERROR').
            metadata: Optional extra context data.

        Returns:
            The created DriftEntry instance.
        
        Raises:
            ValueError: If drift_type, file_path, or message are empty.
            IOError: If unable to persist the new entry.
        """
        if not drift_type or not file_path or not message:
            raise ValueError("drift_type, file_path, and message are required.")

        entry = DriftEntry(
            timestamp=datetime.now(),
            drift_type=drift_type,
            file_path=file_path,
            message=message,
            severity=severity,
            metadata=metadata or {}
        )

        try:
            current_data = self._load_current_history()
            current_data['entries'].append(entry.to_dict())
            self._write_history(current_data)
        except (RuntimeError, IOError) as e:
            # Fail gracefully: we log but don't crash the monitoring loop
            print(f"Warning: Failed to log drift event: {e}")

        return entry

    def _load_current_history(self) -> Dict[str, Any]:
        """
        Helper method to load the current state of the history from the file.

        Returns:
            The dictionary structure of the history.

        Raises:
            RuntimeError: If the file cannot be read.
        """
        try:
            with open(self.log_path, 'r', encoding='utf-8') as f:
                loaded_data = yaml.safe_load(f)
                if not loaded_data or not isinstance(loaded_data, dict):
                    return {'entries': []}
                return loaded_data
        except (yaml.YAMLError, IOError) as e:
            raise RuntimeError(f"Failed to load current history state: {e}")

    def get_drifts(self, drift_type: Optional[str] = None, 
                   limit: Optional[int] = 50, 
                   ascending: bool = False) -> List[Dict[str, Any]]:
        """
        Retrieves drift events from the history log.

        Args:
            drift_type: Optional filter to retrieve only specific drift types.
            limit: Maximum number of entries to return. Defaults to 50.
            ascending: Sort order for the results. Default is False (most recent first).

        Returns:
            A list of dictionaries containing the drift data.
        
        Raises:
            RuntimeError: If the log file cannot be read.
        """
        try:
            current_data = self._load_current_history()
            entries = current_data.get('entries', [])
        except RuntimeError as e:
            raise e

        filtered_entries = entries
        if drift_type:
            filtered_entries = [e for e in entries if e.get('drift_type') == drift_type]

        # Sort by timestamp descending (newest first) unless ascending is requested
        sorted_entries = sorted(
            filtered_entries, 
            key=lambda x: x.get('timestamp', ''), 
            reverse=not ascending
        )

        return sorted_entries[:limit]

    def get_recurring_drifts(self, threshold: int = 3) -> List[Dict[str, Any]]:
        """
        Identifies drift events that have occurred multiple times.

        Args:
            threshold: The minimum occurrence count to be considered recurring.

        Returns:
            A list of drift types and their occurrence counts.
        """
        try:
            current_data = self._load_current_history()
            entries = current_data.get('entries', [])
        except RuntimeError as e:
            raise e

        counts: Dict[str, int] = {}
        for entry in entries:
            drift_type = entry.get('drift_type', 'unknown')
            counts[drift_type] = counts.get(drift_type, 0) + 1

        recurring = []
        for drift_type, count in counts.items():
            if count >= threshold:
                recurring.append({
                    'drift_type': drift_type,
                    'count': count,
                    'is_recurring': True
                })
        
        return sorted(recurring, key=lambda x: x['count'], reverse=True)

    def clear_history(self) -> bool:
        """
        Clears all drift events from the history log.

        Returns:
            True if cleared successfully, False otherwise.
        """
        try:
            self._write_history({'entries': []})
            return True
        except IOError:
            return False

    def cleanup_old_entries(self, days: int = 30) -> int:
        """
        Removes drift events older than a specified number of days.

        Args:
            days: The maximum age of entries to retain.

        Returns:
            The number of entries removed.
        """
        try:
            current_data = self._load_current_history()
            entries = current_data.get('entries', [])
            cutoff_time = datetime.now()
            
            retained_entries = []
            removed_count = 0

            for entry in entries:
                entry_time = datetime.fromisoformat(entry.get('timestamp', ''))
                delta = (cutoff_time - entry_time).days
                
                if delta <= days:
                    retained_entries.append(entry)
                else:
                    removed_count += 1

            if removed_count > 0:
                current_data['entries'] = retained_entries
                self._write_history(current_data)

            return removed_count
        except (ValueError, RuntimeError, IOError):
            return 0