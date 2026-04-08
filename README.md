# 🛠️ Dev Environment Drift Detector

[![Python Version](https://img.shields.io/pypi/pyversions/dev-environment-drift-detector)](https://pypi.org/project/dev-environment-drift-detector/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PyPI Version](https://img.shields.io/pypi/v/dev-environment-drift-detector)](https://pypi.org/project/dev-environment-drift-detector/)
[![GitHub Stars](https://img.shields.io/github/stars/placeholder/dev-environment-drift-detector?style=social)](https://github.com/placeholder/dev-environment-drift-detector)

**Dev Environment Drift Detector** is a robust CLI tool designed to continuously monitor and alert on configuration or dependency drift in local development environments. By ensuring consistency across developer machines and CI pipelines, this tool effectively prevents the "it works on my machine" syndrome, helping teams maintain stable, reproducible, and secure development setups.

## ✨ Features

*   **Continuous Monitoring**: Uses `watchdog` to watch file changes in real-time and detect drift as it happens.
*   **Smart Baselines**: Automatically initializes and stores known-good baselines for comparison.
*   **Comprehensive Scanning**: Analyzes dependencies, environment variables, and system configurations via `scan_engine`.
*   **Real-Time Alerts**: Immediate notifications via `alert_system` when significant drift exceeds configurable thresholds.
*   **Automated Remediation**: `fix_suggestions` module generates scripts to revert environments to a known state.
*   **Auditable History**: `history_logger` tracks all drift events for auditing and trend analysis.
*   **CI/CD Integration**: `report_generator` exports drift reports in JSON or HTML formats.
*   **Version Control Sync**: Utilizes `gitpython` to track changes within repository configurations.

## 📦 Installation

Prerequisites: Python 3.8+

Install the package via PyPI:

```bash
pip install dev-environment-drift-detector
```

Alternatively, install from source:

```bash
git clone https://github.com/your-username/dev-environment-drift-detector.git
cd dev-environment-drift-detector
pip install -e .
```

## 🚀 Quick Start

1.  **Initialize a Baseline**: Capture the current state of your environment.
    ```bash
    dev-env-detector init --name "stable-v1"
    ```

2.  **Run a Scan**: Compare the current state against the baseline.
    ```bash
    dev-env-detector scan --threshold 0.05
    ```

3.  **Enable Watch Mode**: Start continuous monitoring for real-time drift detection.
    ```bash
    dev-env-detector watch --config ~/.dev-detector.yaml
    ```

## 📖 Usage

The CLI provides several subcommands to manage drift detection and reporting.

### Configuration
You can configure thresholds, output formats, and paths using a YAML configuration file:
```yaml
# .dev-detector.yaml
baseline_dir: ./baselines
watch_paths:
  - .env
  - requirements.txt
  - .gitignore
alert_on_diff: true
threshold: 0.1
```

### Commands

| Command | Description |
| :--- | :--- |
| `init` | Initialize a new baseline snapshot of the current environment. |
| `scan` | Run a one-off comparison against the stored baseline. |
| `watch` | Enter continuous monitoring mode using file system watchers. |
| `report` | Generate HTML or JSON drift reports for external integration. |
| `revert` | Apply automatic remediation scripts to fix detected drift. |
| `history` | View logs of previous drift events and audits. |

**Example: Generate an HTML Report**
```bash
dev-env-detector report --format html --output drift-report.html
```

**Example: Check for Critical Dependencies Only**
```bash
dev-env-detector scan --categories dependencies --severity critical
```

## 🏗️ Architecture

The project is structured into modular components to ensure scalability and maintainability.

*   **`scan_engine`**: Scans the current environment state including dependencies, env vars, and system configurations.
*   **`baseline_manager`**: Initializes and stores known-good baselines for comparison against the current state.
*   **`diff_analyzer`**: Compares the current environment state against the stored baseline to identify changes.
*   **`alert_system`**: Notifies developers immediately when significant drift is detected beyond a configurable threshold.
*   **`fix_suggestions`**: Provides automated remediation scripts to revert detected changes to the baseline state.
*   **`history_logger`**: Tracks drift events over time for auditing and identifying recurring environment issues.
*   **`report_generator`**: Exports drift reports in JSON or HTML formats for integration with CI/CD pipelines.

**Tech Stack**:
*   `click` for CLI handling
*   `watchdog` for file system monitoring
*   `pyyaml` for configuration management
*   `gitpython` for version control tracking

## 🤝 Contributing

Contributions are welcome! To contribute to **Dev Environment Drift Detector**:

1.  Fork the repository.
2.  Create a feature branch (`git checkout -b feature/amazing-feature`).
3.  Make your changes and ensure tests pass.
4.  Push to the branch (`git push origin feature/amazing-feature`).
5.  Open a Pull Request.

Please read our [Code of Conduct](./CODE_OF_CONDUCT.md) and [Contributing Guidelines](./CONTRIBUTING.md) before submitting changes.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](./LICENSE) file for details.

---

*Built with ❤️ by the DevOps Team*