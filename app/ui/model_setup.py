"""One first-run setup screen; model acquisition runs in a console worker."""

import json
from pathlib import Path
import sys

from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from app.models.catalogue import catalogue


class ModelSetup(QWidget):
    failure = Signal(str)
    changed = Signal()

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.process = None
        self.entries = catalogue()
        self.rows = {entry["id"]: index for index, entry in enumerate(self.entries)}
        self.buffer = bytearray()
        self.pausing = False
        layout = QVBoxLayout(self)
        total = sum(entry["estimated_download_bytes"] for entry in self.entries)
        summary = QLabel(
            f"Complete local setup · about {total / 1e9:.1f} GB of model downloads, plus bundled assets. Allow 6 GB free for models and safe staging. Only active features load models into memory."
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)
        self.status = QLabel(
            "Setup starts automatically on first launch. Cached, verified files are reused."
        )
        self.status.setWordWrap(True)
        self.status.setAccessibleName("Model setup status")
        layout.addWidget(self.status)
        self.table = QTableWidget(len(self.entries), 3)
        self.table.setHorizontalHeaderLabels(
            ["Model asset", "Readiness", "Download progress"]
        )
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(320)
        self.bars = {}
        for row, entry in enumerate(self.entries):
            self.table.setItem(row, 0, QTableWidgetItem(entry["name"]))
            self.table.item(row, 0).setToolTip(entry["license"])
            self.table.setItem(row, 1, QTableWidgetItem("To check"))
            progress = QProgressBar()
            progress.setAccessibleName(entry["name"] + " download progress")
            progress.setValue(0)
            self.table.setCellWidget(row, 2, progress)
            self.bars[entry["id"]] = progress
        self.table.resizeColumnsToContents()
        layout.addWidget(self.table)
        self.accepted = QCheckBox(
            "I accepted the Community-1 model terms on Hugging Face"
        )
        self.accepted.setToolTip(
            "https://huggingface.co/pyannote/speaker-diarization-community-1"
        )
        layout.addWidget(self.accepted)
        credentials = QHBoxLayout()
        terms = QLabel(
            '<a href="https://huggingface.co/pyannote/speaker-diarization-community-1">Model terms</a> · <a href="https://huggingface.co/settings/tokens">Create a read token</a>'
        )
        terms.setOpenExternalLinks(True)
        credentials.addWidget(terms, 1)
        save = QPushButton("Save access token…")
        save.clicked.connect(self.save_credential)
        forget = QPushButton("Forget token")
        forget.clicked.connect(self.forget_credential)
        credentials.addWidget(save)
        credentials.addWidget(forget)
        save.setEnabled(sys.platform == "win32")
        forget.setEnabled(sys.platform == "win32")
        save.setToolTip(
            "Stored only in your Windows Credential Manager, never in project files or logs. Other platforms can provide HF_TOKEN."
        )
        layout.addLayout(credentials)
        note = QLabel(
            "Gated models require upstream acceptance. Windows uses installed SAPI5 speech voices. Missing terms, voices or access remain visible as Needs action; no training datasets are downloaded."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        controls = QHBoxLayout()
        self.start_button = QPushButton("Start / retry / resume setup")
        self.start_button.setObjectName("primary")
        self.pause_button = QPushButton("Pause downloads")
        self.pause_button.setEnabled(False)
        self.start_button.clicked.connect(self.start)
        self.pause_button.clicked.connect(self.pause)
        controls.addWidget(self.start_button)
        controls.addWidget(self.pause_button)
        layout.addLayout(controls)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(300)
        self.log.setMaximumHeight(130)
        self.log.setAccessibleName("Model setup diagnostics")
        layout.addWidget(self.log)

    def save_credential(self):
        token, accepted = QInputDialog.getText(
            self,
            "Model access",
            "Hugging Face read token (saved in Windows Credential Manager)",
            QLineEdit.Password,
        )
        if accepted and token:
            from app.utils.credentials import save_token

            try:
                save_token(token)
                self.status.setText(
                    "Access token saved securely for your Windows account. Accept the model terms, then Resume setup."
                )
            except (OSError, ValueError) as error:
                self.failure.emit(str(error))

    def forget_credential(self):
        from app.utils.credentials import forget_token

        try:
            forget_token()
            self.status.setText(
                "Saved token removed from Windows Credential Manager. Cached models are retained."
            )
        except OSError as error:
            self.failure.emit(str(error))

    def start(self):
        if self.process is not None:
            return
        self.buffer.clear()
        self.pausing = False
        process = QProcess(self)
        self.process = process
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("HF_HUB_OFFLINE", "0")
        environment.insert("TRANSFORMERS_OFFLINE", "0")
        environment.insert("HF_HUB_DISABLE_XET", "1")
        environment.insert("PYTHONUNBUFFERED", "1")
        process.setProcessEnvironment(environment)
        process.setProcessChannelMode(QProcess.MergedChannels)
        process.readyReadStandardOutput.connect(self.read_output)
        process.finished.connect(self.finished)

        def error_occurred(error):
            if error == QProcess.FailedToStart:
                self.log.appendPlainText(
                    "Could not run model setup: " + process.errorString()
                )
                self.finished(1, QProcess.CrashExit)

        process.errorOccurred.connect(error_occurred)
        executable = Path(sys.executable)
        frozen = getattr(sys, "frozen", False)
        if frozen:
            executable = executable.with_name("AccessibilityAIWorker.exe")
        elif sys.platform == "win32" and executable.name.lower() == "pythonw.exe":
            executable = executable.with_name("python.exe")
        arguments = ["--setup-models", "--model-root", str(self.manager.root)]
        if self.accepted.isChecked():
            arguments.append("--accepted-conditions")
        if not frozen:
            arguments = ["-m", "app.main", *arguments]
        from app.utils.paths import project_root

        process.setWorkingDirectory(str(project_root()))
        self.start_button.setEnabled(False)
        self.pause_button.setEnabled(True)
        self.status.setText(
            "Preparing models in the background. Text and bundled ISL playback remain available."
        )
        process.start(str(executable), arguments)

    def read_output(self):
        if self.process is None:
            return
        self.buffer.extend(bytes(self.process.readAllStandardOutput()))
        while b"\n" in self.buffer:
            line, _, remaining = self.buffer.partition(b"\n")
            self.buffer = bytearray(remaining)
            try:
                self.apply_event(json.loads(line))
            except (ValueError, TypeError, KeyError):
                self.log.appendPlainText(line.decode(errors="replace")[-2000:])
        if len(self.buffer) > 262144:
            self.buffer.clear()

    def apply_event(self, event):
        if not isinstance(event, dict) or event.get("model") not in self.rows:
            return
        model, state = event["model"], event["state"]
        labels = {
            "ready": "Ready offline",
            "failed": "Retry required",
            "needs_action": "Needs action",
            "paused": "Paused",
            "resolving": "Checking revision",
            "downloading": "Downloading",
            "verified": "Verifying",
        }
        self.table.item(self.rows[model], 1).setText(labels.get(state, state))
        self.table.item(self.rows[model], 1).setToolTip(event.get("message", ""))
        bar = self.bars[model]
        total = event.get("total")
        if state == "ready":
            bar.setRange(0, 100)
            bar.setValue(100)
        elif total:
            bar.setRange(0, 100)
            bar.setValue(min(100, round(event.get("downloaded", 0) / total * 100)))
        elif state in {"resolving", "downloading"}:
            bar.setRange(0, 0)
        else:
            bar.setRange(0, 100)
        if event.get("message"):
            self.log.appendPlainText(model + ": " + event["message"])
        if state in {"failed", "needs_action"}:
            self.status.setText(
                "Some models require attention. Read the per-model details below, resolve the cause, then Retry. Independent downloads continue."
            )

    def pause(self):
        if self.process is not None:
            self.pausing = True
            self.status.setText(
                "Pausing. Verified files and resumable parts are retained."
            )
            self.process.terminate()
            process = self.process
            QTimer.singleShot(
                2000,
                process,
                lambda: process.kill()
                if process.state() != QProcess.NotRunning
                else None,
            )

    def finished(self, code, status):
        self.read_output()
        process = self.process
        self.process = None
        self.start_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        states = [
            self.table.item(row, 1).text() for row in range(self.table.rowCount())
        ]
        if self.pausing:
            self.status.setText(
                "Paused. Resume reuses verified files and partially downloaded assets."
            )
        elif all(state == "Ready offline" for state in states):
            self.status.setText(
                "All supported model assets are ready offline. Features load their models only when used."
            )
        elif code:
            self.status.setText(
                "Setup is incomplete. Resolve the failed destinations or storage error, then Retry."
            )
            self.failure.emit(
                "Model setup is incomplete. Open setup for the failed model and its recovery steps."
            )
        else:
            self.status.setText(
                "Public assets are ready; models marked Needs action still require their stated prerequisite."
            )
        self.changed.emit()
        if process:
            process.deleteLater()

    def shutdown(self):
        if self.process:
            self.process.readyReadStandardOutput.disconnect()
            self.process.finished.disconnect()
            self.process.errorOccurred.disconnect()
            self.process.kill()
            self.process.waitForFinished(1000)
            self.process.deleteLater()
            self.process = None
