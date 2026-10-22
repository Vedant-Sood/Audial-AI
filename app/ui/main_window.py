import json
import os
from pathlib import Path
import queue
import sys
import time
import numpy as np
import yaml
from PySide6.QtCore import Qt, QTimer, QProcess, QProcessEnvironment, QUrl, QSignalBlocker
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QListWidget, QStackedWidget, QPushButton, QLineEdit, QComboBox, QCheckBox,
    QFormLayout, QSpinBox, QDoubleSpinBox, QFileDialog, QMessageBox, QInputDialog, QBoxLayout,
    QScrollArea, QPlainTextEdit, QTableWidget, QTableWidgetItem, QTabWidget, QFrame,
    QColorDialog, QApplication)
from app.utils.paths import data_root, project_root, atomic_json
from app.utils.config import Settings, PRESETS
from app.models.manager import ModelManager, REGISTRY
from app.storage.transcript import Session
from app.services.engine import AudioEngine, CameraEngine
from app.services.isl import ISLVocabulary, load_pose_frames
from app.services.tts import LocalTTS
from app.ui.widgets import button, card, TonePanel, CaptionPanel, PoseCanvas, rgb_pixmap
from app.ui.sign_lights import SignLightCanvas, FloatingSignWindow
from app.utils.palette import DEFAULT_EMOTION_COLORS, foreground
from app.services.text_input import read_text
from app import __version__
from app.ui.notifications import Notifications
from app.ui.style import install_style
from app.ui.model_setup import ModelSetup


class MainWindow(QMainWindow):
    """Native workspace with shared caption/voice workers and explicit capture.

    Everyday modes and setup stay visible; training and diagnostics are
    available through Advanced tools. Text playback never records audio.
    """
    TITLES = ["Start", "Captions", "Indian Sign Language", "Voice & emotion", "Conversation",
              "Setup & models", "Training", "Settings", "Sessions", "Privacy", "Diagnostics", "About", "Kandha"]

    def __init__(self, auto_setup=False):
        super().__init__()
        install_style()
        self.device_process = None
        self._closing = False
        try:
            self.settings = Settings.load()
        except ValueError:
            self.settings = Settings()
        self.manager = ModelManager()
        self.isl = ISLVocabulary()
        self.engine = AudioEngine(self.settings, self.manager)
        self.camera = CameraEngine(self.settings, self.manager, self.engine.emit)
        self.session = Session()
        self.session_dirty = False
        self.tts = None
        self.tts_resume_audio = False
        self.processes = []
        self.training_process = None
        self.training_output = None
        self.media_queue = []
        self.media_player = None
        self.current_sign_step = None
        self.pose_frames = None
        self.pose_frame_index = 0
        self.last_sign = ""
        self.caption_panels, self.tone_panels, self.live_buttons = [], [], []
        self.sign_canvases = []
        self.responsive_layouts = []
        self.floating_display = None
        self.browser_service = None
        self.kandha_window = None
        self.setWindowTitle("Audial-AI")
        self.resize(1160, 800)
        self.setMinimumSize(860, 600)
        self.setWindowIcon(QIcon(str(project_root() / "assets" / "icon.svg")))
        self.setStyleSheet((project_root() / "assets" / "theme.qss").read_text().replace("@ASSETS@", (project_root() / "assets").as_posix()))
        central = QWidget()
        self.setCentralWidget(central)
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(196)
        sidebar = QVBoxLayout(side)
        sidebar.setContentsMargins(0, 20, 0, 12)
        brand = QLabel("Audial AI")
        brand.setObjectName("brand")
        sidebar.addWidget(brand)
        note = QLabel("Hear. See. Connect.")
        note.setObjectName("sideNote")
        sidebar.addWidget(note)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.addItems(self.TITLES)
        self.nav.setAccessibleName("Application navigation")
        sidebar.addWidget(self.nav, 1)
        self.show_advanced = QCheckBox("Advanced tools")
        self.show_advanced.setAccessibleName("Show training, privacy, diagnostics and about pages")
        self.show_advanced.toggled.connect(self.toggle_advanced)
        sidebar.addWidget(self.show_advanced)
        self.toggle_advanced(False)
        bottom = QLabel("Private by design\nVersion " + __version__)
        bottom.setObjectName("sideNote")
        sidebar.addWidget(bottom)
        outer.addWidget(side)
        content = QWidget()
        box = QVBoxLayout(content)
        box.setContentsMargins(28, 22, 28, 18)
        header = QHBoxLayout()
        self.heading = QLabel("Home")
        self.heading.setObjectName("heading")
        header.addWidget(self.heading, 1)
        self.auto_sign = QCheckBox("ISL with captions")
        self.auto_sign.setChecked(self.settings.auto_sign)
        self.auto_sign.setToolTip("Use Indian Sign Language with captions from every audio source. Unknown content stays as text.")
        self.auto_sign.toggled.connect(self.change_auto_sign)
        header.addWidget(self.auto_sign)
        self.chip = QLabel("LOCAL INFERENCE")
        self.chip.setObjectName("chip")
        header.addWidget(self.chip)
        header.addWidget(button("Notifications", lambda: self.notifications.show_history()))
        box.addLayout(header)
        self.notifications = Notifications(self)
        self.notifications.actionRequested.connect(self.resolve_notification)
        box.addWidget(self.notifications)
        self.stack = QStackedWidget()
        box.addWidget(self.stack, 1)
        outer.addWidget(content, 1)
        pages = [self.home_page(), self.captions_page(), self.sign_page(), self.tone_page(),
                 self.combined_page(), self.models_page(), self.training_page(), self.settings_page(),
                 self.sessions_page(), self.privacy_page(), self.diagnostics_page(), self.about_page(),
                 self.kandha_page()]
        for page in pages:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(page)
            self.stack.addWidget(scroll)
        self.nav.currentRowChanged.connect(self.navigate)
        self.nav.setCurrentRow(0)
        self.statusBar().showMessage("Idle · microphone and webcam are off")
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(60)
        self.pose_timer = QTimer(self)
        self.pose_timer.timeout.connect(self.next_pose_frame)
        self.refresh_models()
        self.refresh_sessions()
        for panel in self.tone_panels:
            panel.colors = self.settings.intensity_colors.copy()
            panel.set_emotion_colors(self.settings.emotion_colors)
        if auto_setup:
            QTimer.singleShot(0, self, self.start_model_setup)
            QTimer.singleShot(0, self, self.start_browser_service)

    def toggle_advanced(self, enabled):
        for index in (6, 9, 10, 11):
            self.nav.item(index).setHidden(not enabled)
        if not enabled and self.nav.currentRow() in (6, 9, 10, 11):
            self.nav.setCurrentRow(0)

    def page(self, description):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        label = QLabel(description)
        label.setWordWrap(True)
        label.setObjectName("muted")
        layout.addWidget(label)
        return page, layout

    def navigate(self, index):
        if index < 0:
            return
        if index in (6, 9, 10, 11):
            self.show_advanced.setChecked(True)
        self.stack.setCurrentIndex(index)
        self.heading.setText(self.TITLES[index])
        if index == 5:
            self.refresh_models()
        if index == 8:
            self.refresh_sessions()
        if index == 7:
            self.refresh_emotion_colors()
            QTimer.singleShot(0, self, self.discover_devices)

    def home_page(self):
        p, layout = self.page("Choose an input, then follow captions, signs, and voice estimates in one place.")
        hero = QLabel("Follow the\nconversation.")
        hero.setObjectName("hero")
        layout.addWidget(hero)
        layout.addWidget(QLabel("Your microphone and camera stay off until you start. Processing runs on your computer."))
        layout.addWidget(button("Open conversation", lambda: self.nav.setCurrentRow(4), True))
        grid = QGridLayout()
        for i, (title, sub, target) in enumerate([
            ("Live captions", "Readable speech, timestamps and speaker colours. Speaker assignment is experimental.", 1),
            ("Indian Sign Language", "Text, documents, subtitles and recordings share the default ISL display.", 2),
            ("Voice & emotion", "See voice measurements and optional emotion estimates with your chosen colors.", 3)]):
            frame, inner = card(title, sub)
            inner.addStretch()
            inner.addWidget(button("Open " + title, lambda checked=False, n=target: self.nav.setCurrentRow(n)))
            grid.addWidget(frame, 0, i)
        layout.addLayout(grid)
        setup, inner = card("Your local workspace", "First-run setup prepares the full supported model catalogue automatically. You can follow progress, pause, retry, and review any gated model requirements in Setup & models.")
        row = QHBoxLayout()
        row.addWidget(button("View model setup", lambda: self.nav.setCurrentRow(5)))
        row.addWidget(button("Run diagnostics", lambda: self.nav.setCurrentRow(10)))
        inner.addLayout(row)
        layout.addWidget(setup)
        layout.addStretch()
        return p

    def live_controls(self, layout, mode):
        row = QHBoxLayout()
        source = QComboBox()
        source.addItem("Microphone", "microphone")
        source.addItem("Computer / app audio", "system")
        source.setAccessibleName("Audio source")
        start = button("Start listening", lambda: self.start_audio(mode, source=source.currentData()), True)
        pause = button("Pause / resume", self.pause_audio)
        stop = button("Stop", self.stop_audio)
        file = button("Open audio / video", lambda: self.open_audio(mode))
        row.addWidget(source, 2)
        row.addWidget(start, 1)
        row.addWidget(file, 1)
        layout.addLayout(row)
        self.live_buttons.append((start, pause, stop, file))
        extra = QHBoxLayout()
        extra.addWidget(pause)
        extra.addWidget(stop)
        extra.addWidget(button("Open browser companion", self.open_browser))
        extra.addWidget(button("Float captions and signs", self.open_floating))
        layout.addLayout(extra)
        pause.setEnabled(False)
        stop.setEnabled(False)

    def session_controls(self, layout):
        row = QHBoxLayout()
        for text, callback in [("New session", self.new_session), ("Rename speaker", self.rename_speaker),
                               ("Save session", self.save_session), ("Export…", self.export_session)]:
            row.addWidget(button(text, callback))
        layout.addLayout(row)

    def captions_page(self):
        p, layout = self.page("Listen to speech or open a recording. ISL accompanies completed captions by default; words without a loaded sign stay readable.")
        self.live_controls(layout, "captions")
        panel = CaptionPanel()
        self.caption_panels.append(panel)
        row = QHBoxLayout()
        row.addWidget(panel, 2)
        lights = SignLightCanvas()
        self.sign_canvases.append(lights)
        row.addWidget(lights, 1)
        layout.addLayout(row, 1)
        self.session_controls(layout)
        return p

    def tone_page(self):
        p, layout = self.page("See pitch and recorded level. Enable voice emotion in Settings to add labeled color indications; low-confidence estimates appear as uncertain.")
        self.live_controls(layout, "tone")
        panel = TonePanel()
        self.tone_panels.append(panel)
        layout.addWidget(panel)
        lights = SignLightCanvas()
        self.sign_canvases.append(lights)
        layout.addWidget(lights)
        layout.addStretch()
        return p

    def combined_page(self):
        p, layout = self.page("Start listening or open a recording. Captions, ISL playback, and voice estimates share the same session.")
        self.live_controls(layout, "combined")
        tabs = QTabWidget()
        captions = CaptionPanel()
        tone = TonePanel()
        self.caption_panels.append(captions)
        self.tone_panels.append(tone)
        tabs.addTab(captions, "Captions")
        tabs.addTab(tone, "Voice & emotion")
        display_row = QBoxLayout(QBoxLayout.LeftToRight)
        self.responsive_layouts.append(display_row)
        display_row.addWidget(tabs, 2)
        lights = SignLightCanvas()
        self.sign_canvases.append(lights)
        display_row.addWidget(lights, 1)
        layout.addLayout(display_row, 1)
        layout.addWidget(button("Open ISL workspace", lambda: self.nav.setCurrentRow(2)))
        self.session_controls(layout)
        return p

    def resizeEvent(self, event):
        super().resizeEvent(event)
        for layout in getattr(self, "responsive_layouts", []):
            layout.setDirection(QBoxLayout.LeftToRight if self.width() >= 1080 else QBoxLayout.TopToBottom)

    def sign_page(self):
        p, layout = self.page("Indian Sign Language is the default for every supported input. Type, paste, open a document or recording, or listen live. Loaded signs and readable text play in order.")
        self.live_controls(layout, "combined")
        camera_tools = QWidget()
        camera_layout = QVBoxLayout(camera_tools)
        top = QHBoxLayout()
        self.camera_label = QLabel("Webcam is off")
        self.camera_label.setAlignment(Qt.AlignCenter)
        self.camera_label.setMinimumSize(360, 240)
        self.camera_label.setStyleSheet("background:#112b35;color:#bfdbd9;border-radius:10px;")
        self.pose = PoseCanvas()
        self.sign_canvases.append(self.pose)
        top.addWidget(self.camera_label, 1)
        camera_layout.addLayout(top)
        row = QHBoxLayout()
        row.addWidget(button("Start webcam", self.start_camera, True))
        row.addWidget(button("Stop webcam", self.camera.stop))
        self.record_button = button("Record one sign", self.toggle_record)
        row.addWidget(self.record_button)
        camera_layout.addLayout(row)
        self.camera_status = QLabel("Install pose assets and import a trained ISL checkpoint on Models.")
        self.camera_status.setWordWrap(True)
        camera_layout.addWidget(self.camera_status)
        self.sign_result = QLabel("Recognised sign: —")
        self.sign_result.setObjectName("cardTitle")
        camera_layout.addWidget(self.sign_result)
        self.reply = QLineEdit()
        self.reply.setPlaceholderText("Edit the recognised text before speaking, or type a reply")
        self.reply.setAccessibleName("Reply text for local speech synthesis")
        camera_layout.addWidget(self.reply)
        camera_layout.addWidget(button("Speak reply locally", lambda: self.speak(self.reply.text())))
        output, inner = card("Text and signs", "Native hand and body playback with source-attributed ISL assets. English and Hindi aliases are supported for the included phrases.")
        inner.addWidget(self.pose)
        self.sign_text = QPlainTextEdit()
        self.sign_text.setMaximumHeight(130)
        self.sign_text.setPlaceholderText("Type any text. Try: Good evening, team. Thank you! / धन्यवाद")
        self.sign_text.setAccessibleName("Text to display with ISL phrase support")
        inner.addWidget(self.sign_text)
        row = QHBoxLayout()
        row.addWidget(button("Display in ISL", lambda: self.play_signs(self.sign_text.toPlainText()), True))
        row.addWidget(button("Open document / subtitles / media", self.open_sign_input))
        row.addWidget(button("Use clipboard", self.clipboard_signs))
        inner.addLayout(row)
        more = QHBoxLayout()
        more.addWidget(button("Add an ISL vocabulary", self.import_lexicon))
        more.addWidget(button("Use bundled vocabulary", self.reset_lexicon))
        more.addWidget(button("Stop playback", self.stop_playback))
        more.addWidget(button("Float sign display", self.open_floating))
        inner.addLayout(more)
        motion = QHBoxLayout()
        self.sign_pause = button("Pause / resume signs", self.pause_signs)
        motion.addWidget(self.sign_pause)
        motion.addWidget(button("Next frame", self.step_sign))
        self.sign_speed = QDoubleSpinBox()
        self.sign_speed.setRange(.25, 2)
        self.sign_speed.setSingleStep(.25)
        self.sign_speed.setValue(self.settings.sign_speed)
        self.sign_speed.valueChanged.connect(self.change_sign_speed)
        motion.addWidget(QLabel("Playback speed"))
        motion.addWidget(self.sign_speed)
        self.reduce_motion = QCheckBox("Reduced motion (manual frames)")
        self.reduce_motion.setChecked(self.settings.reduced_motion)
        self.reduce_motion.toggled.connect(self.change_reduced_motion)
        motion.addWidget(self.reduce_motion)
        inner.addLayout(motion)
        self.lexicon_label = QLabel("No lexicon loaded. Import a lexicon and its media folder.")
        self.lexicon_label.setTextFormat(Qt.PlainText)
        self.lexicon_label.setWordWrap(True)
        inner.addWidget(self.lexicon_label)
        self.sign_fallback = QLabel("")
        self.sign_fallback.setTextFormat(Qt.PlainText)
        self.sign_fallback.setWordWrap(True)
        self.sign_fallback.setObjectName("partial")
        self.sign_fallback.setAccessibleName("Original text without a loaded ISL sign")
        inner.addWidget(self.sign_fallback)
        layout.addWidget(output)
        reveal_camera = QCheckBox("Show experimental webcam sign recognition")
        camera_tools.setVisible(False)
        reveal_camera.toggled.connect(camera_tools.setVisible)
        layout.addWidget(reveal_camera)
        layout.addWidget(camera_tools)
        layout.addStretch()
        self.refresh_lexicon_summary()
        return p

    def models_page(self):
        p, layout = self.page("One setup prepares all supported model assets. Inference stays local, and models load only when a feature needs them. Recordings and training datasets are never part of setup requests.")
        self.model_setup = ModelSetup(self.manager, self)
        self.model_setup.failure.connect(lambda message: self.notify_worker(message, "error"))
        self.model_setup.changed.connect(self.refresh_models)
        layout.addWidget(self.model_setup)
        advanced = QWidget()
        advanced.setVisible(False)
        reveal = QCheckBox("Show individual model tools for development")
        reveal.toggled.connect(advanced.setVisible)
        layout.addWidget(reveal)
        layout.addWidget(advanced)
        layout = QVBoxLayout(advanced)
        self.model_table = QTableWidget(0, 6)
        self.model_table.setHorizontalHeaderLabels(["Model", "Task", "Installed", "Size", "Device", "Precision"])
        self.model_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.model_table.setSelectionMode(QTableWidget.SingleSelection)
        self.model_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.model_table.horizontalHeader().setStretchLastSection(True)
        self.model_table.setMinimumHeight(300)
        layout.addWidget(self.model_table)
        self.accepted = QCheckBox("I have accepted Community-1's conditions on its Hugging Face page (HF_TOKEN set locally)")
        layout.addWidget(self.accepted)
        row = QHBoxLayout()
        for text, cb in [("Install selected", self.install_selected), ("Remove selected", self.remove_selected),
                         ("Switch ASR preset", self.switch_model), ("Details", self.model_details)]:
            row.addWidget(button(text, cb, text.startswith("Install")))
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(button("Import ISL checkpoint", lambda: self.import_checkpoint("sign")))
        row.addWidget(button("Import prosody checkpoint", lambda: self.import_checkpoint("prosody")))
        row.addWidget(button("Install bundled research checkpoints", self.install_bundled))
        layout.addLayout(row)
        self.model_log = QPlainTextEdit()
        self.model_log.setReadOnly(True)
        self.model_log.setMaximumBlockCount(500)
        layout.addWidget(self.model_log, 1)
        return p

    def start_model_setup(self):
        if self._closing:
            return
        if not self.manager.installed("whisper-tiny"):
            self.nav.setCurrentRow(5)
        if (data_root() / "model-setup-paused.json").exists():
            self.model_setup.status.setText("Downloads are paused. Resume setup when you are ready; verified files and partial downloads are retained.")
            return
        self.model_setup.start()

    def training_page(self):
        p, layout = self.page("Local PyTorch training using preprocessed real data. Live inference stops before training. Pause and Stop are honored after the current epoch and save latest.pt.")
        form = QFormLayout()
        self.train_task = QComboBox()
        self.train_task.addItems(["sign", "prosody", "diarization"])
        form.addRow("Task", self.train_task)
        self.train_architecture = QLabel("Bidirectional GRU · isolated ISL pose sequences")
        architectures = {"sign": "Bidirectional GRU · isolated ISL pose sequences", "prosody": "Small MFCC MLP · acted-speech research", "diarization": "Small ECAPA-feature MLP · fixed enrolled speakers"}
        self.train_task.currentTextChanged.connect(lambda task: self.train_architecture.setText(architectures[task]))
        form.addRow("Model", self.train_architecture)
        self.train_data = QLineEdit()
        self.train_data.setPlaceholderText("Preprocessed .npz with its provenance .json beside it")
        form.addRow("Dataset", self.train_data)
        self.train_epochs = QSpinBox()
        self.train_epochs.setRange(1, 1000)
        self.train_epochs.setValue(30)
        form.addRow("Epochs", self.train_epochs)
        self.train_batch = QSpinBox()
        self.train_batch.setRange(1, 512)
        self.train_batch.setValue(16)
        form.addRow("Batch size", self.train_batch)
        layout.addLayout(form)
        layout.addWidget(button("Choose preprocessed dataset", self.choose_training_data))
        row = QHBoxLayout()
        for text, cb in [("Start", self.start_training), ("Pause after epoch", lambda: self.control_training("pause")),
                         ("Stop after epoch", lambda: self.control_training("stop")), ("Resume", self.resume_training)]:
            row.addWidget(button(text, cb, text == "Start"))
        layout.addLayout(row)
        self.train_summary = QLabel("No training run started. Data access and preprocessing instructions are in docs/local_training.md.")
        self.train_summary.setWordWrap(True)
        layout.addWidget(self.train_summary)
        self.train_log = QPlainTextEdit()
        self.train_log.setReadOnly(True)
        self.train_log.setMaximumBlockCount(600)
        layout.addWidget(self.train_log, 1)
        layout.addWidget(button("Import this run's best checkpoint", self.import_training_result))
        return p

    def settings_page(self):
        p, layout = self.page("Settings apply to the next session. FAST uses tiny; BALANCED uses small; ACCURATE uses medium. These are hardware targets until locally benchmarked.")
        form = QFormLayout()
        self.preset_box = QComboBox()
        for name in PRESETS:
            self.preset_box.addItem(name.capitalize(), name)
        self.preset_box.setCurrentIndex(self.preset_box.findData(self.settings.preset))
        form.addRow("Caption quality", self.preset_box)
        self.device_box = QComboBox()
        for label, value in [("Automatic", "auto"), ("CPU", "cpu"), ("NVIDIA GPU", "cuda")]:
            self.device_box.addItem(label, value)
        self.device_box.setCurrentIndex(self.device_box.findData(self.settings.device))
        form.addRow("Processing device", self.device_box)
        self.language_box = QComboBox()
        for name, code in [("Detect automatically", ""), ("English", "en"), ("Hindi", "hi"),
                           ("Bengali", "bn"), ("Tamil", "ta"), ("Telugu", "te"), ("Marathi", "mr"),
                           ("Gujarati", "gu"), ("Kannada", "kn"), ("Malayalam", "ml"), ("Punjabi", "pa")]:
            self.language_box.addItem(name, code)
        index = self.language_box.findData(self.settings.language)
        if index < 0:
            self.language_box.addItem(self.settings.language, self.settings.language)
            index = self.language_box.count() - 1
        self.language_box.setCurrentIndex(index)
        form.addRow("Speech language", self.language_box)
        self.mic_box = QComboBox()
        self.mic_box.addItem("Default microphone", None)
        self.mic_box.setToolTip("Discovering audio devices in the background…")
        if self.settings.microphone is not None and self.mic_box.findData(self.settings.microphone) < 0:
            self.mic_box.addItem("Saved microphone " + str(self.settings.microphone), self.settings.microphone)
        self.mic_box.setCurrentIndex(max(0, self.mic_box.findData(self.settings.microphone)))
        form.addRow("Microphone", self.mic_box)
        self.camera_box = QSpinBox()
        self.camera_box.setRange(0, 20)
        self.camera_box.setValue(self.settings.camera)
        form.addRow("Camera index", self.camera_box)
        self.diarization_box = QComboBox()
        for label, value in [("Off", "off"), ("Separate speakers", "ecapa"), ("Overlap (experimental)", "pyannote")]:
            self.diarization_box.addItem(label, value)
        self.diarization_box.setCurrentIndex(self.diarization_box.findData(self.settings.diarization))
        form.addRow("Speaker labels", self.diarization_box)
        self.threshold_box = QDoubleSpinBox()
        self.threshold_box.setRange(0, 1)
        self.threshold_box.setSingleStep(0.05)
        self.threshold_box.setValue(self.settings.sign_threshold)
        form.addRow("Minimum sign score", self.threshold_box)
        layout.addLayout(form)
        self.partial_box = QCheckBox("Show partial captions (additional ASR work)")
        self.partial_box.setChecked(self.settings.partial_updates)
        layout.addWidget(self.partial_box)
        self.classifier_box = QCheckBox("Enable voice emotion estimates (experimental)")
        self.classifier_box.setChecked(self.settings.prosody_classifier)
        layout.addWidget(self.classifier_box)
        self.speak_box = QCheckBox("Automatically speak accepted isolated signs; microphone pauses during speech")
        self.speak_box.setChecked(self.settings.auto_speak_sign)
        layout.addWidget(self.speak_box)
        palette, inner = card("Emotion color pool", "Assign a color to each emotion. Labels stay readable on every color. Choose Uncertain for predictions the model cannot trust.")
        self.emotion_color_buttons = {}
        grid = QGridLayout()
        for index, emotion in enumerate(DEFAULT_EMOTION_COLORS):
            choice = button(emotion.capitalize(), lambda checked=False, name=emotion: self.pick_emotion_color(name))
            choice.setAccessibleName("Choose color for " + emotion)
            self.emotion_color_buttons[emotion] = choice
            grid.addWidget(choice, index // 3, index % 3)
        inner.addLayout(grid)
        inner.addWidget(button("Reset emotion colors", self.reset_emotion_colors))
        layout.addWidget(palette)
        self.refresh_emotion_colors()
        row = QHBoxLayout()
        for index, text in enumerate(["Low intensity colour", "Medium intensity colour", "High intensity colour"]):
            row.addWidget(button(text, lambda checked=False, i=index: self.pick_color(i)))
        layout.addLayout(row)
        layout.addWidget(button("Save settings", self.save_settings, True))
        layout.addStretch()
        return p

    def sessions_page(self):
        p, layout = self.page("Sessions are saved only when you choose Save. This history contains transcripts, names and timestamps; raw microphone audio and video are not saved.")
        self.sessions_list = QListWidget()
        layout.addWidget(self.sessions_list, 1)
        row = QHBoxLayout()
        row.addWidget(button("Open selected session", self.open_session))
        row.addWidget(button("Delete selected session", self.delete_session))
        row.addWidget(button("Refresh", self.refresh_sessions))
        layout.addLayout(row)
        return p

    def privacy_page(self):
        p, layout = self.page("You control capture, model installation and saved transcripts.")
        for title, text in [
            ("Local inference", "Audio, webcam frames, sign poses and transcripts are processed on this computer. Normal inference uses model files already on disk, with Hugging Face offline mode enabled."),
            ("Explicit downloads", "Install connects to Hugging Face or Google's MediaPipe model host. Dataset commands connect to upstream providers. Those providers receive ordinary network metadata during downloads. No user media is sent."),
            ("No telemetry", "The app has no analytics, remote logging or remote inference client. Hugging Face telemetry and pyannote metrics are explicitly disabled."),
            ("Saving and deletion", "Microphone and webcam buffers stay in memory. Save writes transcripts locally. Delete a session to remove its saved JSON. Exported copies are independent files and can be deleted in File Explorer."),
            ("Research labels", "Speaker embeddings, ISL scores and acted-speech categories are experimental. The app does not infer honesty, make diagnoses, or establish a person's emotional state.")]:
            frame, inner = card(title, text)
            layout.addWidget(frame)
        layout.addStretch()
        return p

    def diagnostics_page(self):
        p, layout = self.page("Run on your laptop to inspect actual hardware. Webcam validation opens the camera briefly; microphone validation captures a short clip locally. These are user-triggered tests.")
        row = QHBoxLayout()
        row.addWidget(button("Inspect hardware", lambda: self.run_diagnostics(False), True))
        row.addWidget(button("Run local validation", lambda: self.run_diagnostics(True)))
        layout.addLayout(row)
        self.diagnostics_log = QPlainTextEdit()
        self.diagnostics_log.setReadOnly(True)
        layout.addWidget(self.diagnostics_log, 1)
        return p

    def about_page(self):
        p, layout = self.page("ACCESSIBILITY AI · version 0.3.1")
        for title, sub in [
            ("WORKING", "Desktop interface, local audio feature analysis, transcript/session export, model installation, WAV input, training/evaluation scripts and local hardware checks. Inference requires the appropriate models."),
            ("EXPERIMENTAL", "Chunked live ASR, online speaker clustering, optional overlap annotation, isolated ISL recognition with imported checkpoints, acted-speech classification, local clip lookup and skeleton pose replay."),
            ("FUTURE RESEARCH", "Fluent sentence-level ISL recognition/translation and learned sign generation; robust attribution of words from simultaneous speakers; native streaming ASR and automatic continuous-sign segmentation.")]:
            f, inner = card(title, sub)
            layout.addWidget(f)
        layout.addWidget(QLabel("Cloud and Windows results are separate. Read README.md and docs/limitations.md before interpreting research metrics."))
        layout.addStretch()
        return p

    def alert(self, message):
        self.notifications.publish(str(message), "warning")

    def resolve_notification(self, action):
        if action == "browser":
            self.open_browser()
        else:
            self.nav.setCurrentRow({"models": 5, "settings": 7, "diagnostics": 10}.get(action, 10))

    def notify_worker(self, message, severity):
        text = str(message)
        lower = text.lower()
        if any(word in lower for word in ("model", "checkpoint", "install", "download")):
            action = "models"
        elif any(word in lower for word in ("microphone", "camera", "audio device", "cuda", "gpu")):
            action = "settings"
        elif "browser" in lower or "extension" in lower:
            action = "browser"
        else:
            action = "diagnostics"
        self.notifications.publish(text, severity, action=action)

    def discover_devices(self):
        if self._closing or self.device_process is not None:
            return
        proc = QProcess(self)
        self.device_process = proc
        proc.setProcessChannelMode(QProcess.SeparateChannels)
        proc.setWorkingDirectory(str(project_root()))
        output = bytearray()
        def read_output():
            if self.device_process is proc:
                output.extend(bytes(proc.readAllStandardOutput())[:max(0, 262144 - len(output))])
        proc.readyReadStandardOutput.connect(read_output)
        def done(code, status):
            if self.device_process is not proc:
                return
            try:
                if code != 0:
                    raise RuntimeError("Audio device discovery failed. Check your device and Windows privacy permissions.")
                devices = json.loads(output)
                selected = self.mic_box.currentData()
                for device in devices:
                    if self.mic_box.findData(device["index"]) < 0:
                        self.mic_box.addItem(device["name"], device["index"])
                self.mic_box.setCurrentIndex(max(0, self.mic_box.findData(selected)))
                self.mic_box.setToolTip("Available audio inputs. Device access is checked when you start listening.")
                if not devices:
                    self.notify_worker("No microphone input was found. Connect an input device and review Windows microphone privacy settings, then reopen Settings to retry.", "warning")
            except (ValueError, KeyError, RuntimeError) as error:
                self.notify_worker(str(error), "warning")
            self.device_process = None
            proc.deleteLater()
        proc.finished.connect(done)
        def failed(error):
            if error == QProcess.FailedToStart:
                done(1, QProcess.CrashExit)
        proc.errorOccurred.connect(failed)
        executable = Path(sys.executable)
        if getattr(sys, "frozen", False):
            executable = executable.with_name("AccessibilityAIWorker.exe")
        elif sys.platform == "win32" and executable.name.lower() == "pythonw.exe":
            executable = executable.with_name("python.exe")
        proc.start(str(executable), ["--list-devices"] if getattr(sys, "frozen", False) else ["-m", "app.main", "--list-devices"])
        QTimer.singleShot(10000, proc, lambda: proc.kill() if proc.state() != QProcess.NotRunning else None)

    def cancel_device_discovery(self):
        proc = self.device_process
        self.device_process = None
        if proc is not None:
            proc.readyReadStandardOutput.disconnect()
            proc.finished.disconnect()
            proc.errorOccurred.disconnect()
            proc.kill()
            proc.waitForFinished(500)
            proc.deleteLater()

    def busy(self):
        return self.engine.running or (self.camera.thread and self.camera.thread.is_alive()) or (self.training_process and self.training_process.state() != QProcess.NotRunning)

    def start_audio(self, mode, file_path=None, source="microphone"):
        if self.training_process and self.training_process.state() != QProcess.NotRunning:
            self.alert("Stop training before starting inference.")
            return
        try:
            self.engine.start(mode, file_path, source)
        except Exception as exc:
            self.alert(exc)

    def open_audio(self, mode):
        path, _ = QFileDialog.getOpenFileName(self, "Open local audio or video", "", "Audio and video (*.wav *.flac *.ogg *.mp3 *.m4a *.mp4 *.webm *.mkv)")
        if path:
            self.start_audio(mode, path)

    def pause_audio(self):
        self.engine.pause(not self.engine.paused.is_set())

    def stop_audio(self):
        self.engine.stop()

    def start_camera(self):
        if self.training_process and self.training_process.state() != QProcess.NotRunning:
            self.alert("Stop training before starting the webcam.")
            return
        self.camera.start()

    def toggle_record(self):
        if not self.camera.thread or not self.camera.thread.is_alive():
            self.alert("Start the webcam before recording a sign.")
            return
        if self.camera.record.is_set():
            self.camera.record.clear()
        else:
            self.camera.record.set()

    def speak(self, text):
        if not text.strip():
            return
        if self.tts is None:
            self.tts = LocalTTS()
        if self.engine.running and not self.engine.paused.is_set():
            self.engine.pause(True)
            self.tts_resume_audio = True
        try:
            self.tts.say(text)
        except queue.Full:
            self.alert("Speech queue is full; wait for the current reply.")
        except RuntimeError as exc:
            if self.tts_resume_audio:
                self.engine.pause(False)
                self.tts_resume_audio = False
            self.alert("Local speech synthesis: " + str(exc))
            self.tts = None

    def new_session(self):
        if self.engine.running:
            self.alert("Stop capture before creating a new session.")
            return
        if self.session.captions:
            answer = QMessageBox.question(self, "New session", "Save the current transcript first?", QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            if answer == QMessageBox.Cancel:
                return
            if answer == QMessageBox.Yes and not self.save_session():
                return
        self.session = Session()
        self.session_dirty = False
        self.refresh_captions()

    def refresh_captions(self):
        for panel in self.caption_panels:
            panel.refresh(self.session)

    def rename_speaker(self):
        ids = list(self.session.speakers)
        if not ids:
            return
        speaker, ok = QInputDialog.getItem(self, "Rename speaker", "Speaker ID", ids, 0, False)
        if ok:
            name, ok = QInputDialog.getText(self, "Rename speaker", "Display name", text=self.session.speakers[speaker]["name"])
            if ok and name.strip():
                self.session.rename(speaker, name)
                self.session_dirty = True
                self.refresh_captions()

    def save_session(self):
        name, ok = QInputDialog.getText(self, "Save session", "Session title", text=self.session.title)
        if ok:
            self.session.title = name.strip() or "Untitled session"
            self.session.save()
            self.session_dirty = False
            self.statusBar().showMessage("Session saved locally")
            self.refresh_sessions()
        return ok

    def export_session(self):
        path, selected = QFileDialog.getSaveFileName(self, "Export transcript", "transcript.vtt", "WebVTT (*.vtt);;SRT (*.srt);;Text (*.txt);;CSV (*.csv);;JSON (*.json)")
        if path:
            kind = "vtt" if "WebVTT" in selected else "srt" if "SRT" in selected else "csv" if "CSV" in selected else "json" if "JSON" in selected else "txt"
            if not path.lower().endswith("." + kind):
                path += "." + kind
            self.session.export(path, kind)
            self.statusBar().showMessage("Transcript exported")

    def refresh_sessions(self):
        self.sessions_list.clear()
        for file in sorted((data_root() / "sessions").glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                self.sessions_list.addItem(f"{data['title']}  ·  {data['created'][:19]}  ·  {len(data['captions'])} lines")
                self.sessions_list.item(self.sessions_list.count() - 1).setData(Qt.UserRole, str(file))
            except (ValueError, KeyError, OSError):
                continue

    def open_session(self):
        item = self.sessions_list.currentItem()
        if item and not self.engine.running:
            session_path = item.data(Qt.UserRole)
            if self.session_dirty:
                answer = QMessageBox.question(self, "Open session", "Save the current transcript first?", QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
                if answer == QMessageBox.Cancel or (answer == QMessageBox.Yes and not self.save_session()):
                    return
            self.session = Session.load(session_path)
            self.session_dirty = False
            self.refresh_captions()
            self.nav.setCurrentRow(1)

    def delete_session(self):
        item = self.sessions_list.currentItem()
        if item and QMessageBox.question(self, "Delete transcript", "Delete this saved transcript? Exported copies remain separate.") == QMessageBox.Yes:
            Path(item.data(Qt.UserRole)).unlink()
            self.refresh_sessions()

    def selected_model(self):
        item = self.model_table.item(self.model_table.currentRow(), 0)
        return item.data(Qt.UserRole) if item else None

    def refresh_models(self):
        specs = list(REGISTRY.values())
        self.model_table.setRowCount(len(specs) + 2)
        for row, spec in enumerate(specs):
            installed = self.manager.installed(spec.id)
            size = f"{sum(p.stat().st_size for p in self.manager.path(spec.id).rglob('*') if p.is_file()) / 1e6:.1f} MB" if installed else spec.size
            device = "CPU / CUDA" if spec.task == "ASR" else "CPU"
            precision = "INT8 / FP16" if spec.task == "ASR" else "FP32"
            for col, value in enumerate([spec.name, spec.task, "Yes" if installed else "No", size, device, precision]):
                self.model_table.setItem(row, col, QTableWidgetItem(value))
            self.model_table.item(row, 0).setData(Qt.UserRole, spec.id)
        for i, task in enumerate(["sign", "prosody"]):
            row, model = len(specs) + i, task + "-local"
            installed = self.manager.installed(model)
            for col, value in enumerate([f"Local {task} checkpoint", "ISL" if task == "sign" else "Acted speech", "Yes" if installed else "No", "Local file", "CPU", "FP32"]):
                self.model_table.setItem(row, col, QTableWidgetItem(value))
            self.model_table.item(row, 0).setData(Qt.UserRole, model)
        self.model_table.resizeColumnsToContents()

    def launch_process(self, flags, log, finished=None):
        proc = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("HF_HUB_DISABLE_TELEMETRY", "1")
        env.insert("PYANNOTE_METRICS_ENABLED", "0")
        env.insert("PYTHONUNBUFFERED", "1")
        if "--install-model" in flags:
            env.insert("HF_HUB_OFFLINE", "0")
            env.insert("TRANSFORMERS_OFFLINE", "0")
        proc.setProcessEnvironment(env)
        proc.setWorkingDirectory(str(project_root()))
        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.readyReadStandardOutput.connect(lambda: log.appendPlainText(bytes(proc.readAllStandardOutput()).decode(errors="replace").rstrip()))
        completed = False
        def done(code, status):
            nonlocal completed
            if completed:
                return
            completed = True
            log.appendPlainText(f"Process exited: {code}")
            if code != 0:
                self.notify_worker("Background operation failed. Open diagnostics for details; retry the operation after resolving its reported cause.", "error")
            if finished:
                finished(code)
            if proc in self.processes:
                self.processes.remove(proc)
            if self.training_process is proc:
                self.training_process = None
            self.refresh_models()
            proc.deleteLater()
        proc.finished.connect(done)
        def failed(error):
            self.notify_worker("Could not launch background operation: " + proc.errorString(), "error")
            if error == QProcess.FailedToStart:
                done(1, QProcess.CrashExit)
        proc.errorOccurred.connect(failed)
        executable = Path(sys.executable)
        if getattr(sys, "frozen", False):
            executable = executable.with_name("AccessibilityAIWorker.exe")
        elif sys.platform == "win32" and executable.name.lower() == "pythonw.exe":
            executable = executable.with_name("python.exe")
        proc.start(str(executable), flags if getattr(sys, "frozen", False) else ["-m", "app.main", *flags])
        self.processes.append(proc)
        return proc

    def install_selected(self):
        if self.busy():
            self.alert("Stop inference and training before changing model files.")
            return
        if self.model_setup.process is not None:
            self.alert("Pause automatic setup before using the individual developer installer.")
            return
        model = self.selected_model()
        if model not in REGISTRY:
            self.alert("Use Import checkpoint for a locally trained model.")
            return
        if any(p.state() != QProcess.NotRunning for p in self.processes):
            self.alert("Wait for the current model or diagnostics operation to finish.")
            return
        flags = ["--install-model", model, "--model-root", str(self.manager.root)]
        if self.accepted.isChecked():
            flags.append("--accepted-conditions")
        self.launch_process(flags, self.model_log)

    def remove_selected(self):
        model = self.selected_model()
        if model and not self.busy() and not any(p.state() != QProcess.NotRunning for p in self.processes):
            if QMessageBox.question(self, "Remove model", "Remove these local model files? They can be installed again.") == QMessageBox.Yes:
                self.manager.remove(model)
                self.refresh_models()

    def switch_model(self):
        model = self.selected_model()
        for name, preset in PRESETS.items():
            if preset["asr"] == model:
                self.preset_box.setCurrentIndex(self.preset_box.findData(name))
                self.save_settings()
                return
        self.alert("Select a Whisper ASR model to switch its preset.")

    def model_details(self):
        model = self.selected_model()
        if model in REGISTRY:
            spec = REGISTRY[model]
            QMessageBox.information(self, spec.name, f"Task: {spec.task}\nSource: {spec.source}\nLicense: {spec.license}\nSize: {spec.size}\nGated: {spec.gated}\n\n{spec.notes}")
        elif model:
            QMessageBox.information(self, "Local checkpoint", "Research checkpoint. See its dataset provenance and experiment results in training/experiments. Model scores are uncalibrated.")

    def import_checkpoint(self, task, path=None):
        if self.busy():
            self.alert("Stop inference and training before importing a checkpoint.")
            return
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "Import local checkpoint", "", "PyTorch checkpoint (*.pt)")
        if path:
            try:
                self.manager.import_checkpoint(path, task)
                self.refresh_models()
                self.statusBar().showMessage(f"Imported experimental {task} checkpoint")
            except Exception as exc:
                self.alert(exc)

    def install_bundled(self):
        for task in ["sign", "prosody"]:
            path = project_root() / "models" / "research" / (task + ".pt")
            if path.exists():
                self.import_checkpoint(task, str(path))

    def import_lexicon(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select local ISL lexicon", "", "JSON (*.json)")
        if path:
            try:
                self.isl.select(path)
                self.stop_playback()
                self.refresh_lexicon_summary()
                self.engine.emit("isl_vocabulary", self.isl.summary())
            except Exception as exc:
                self.alert(exc)

    def refresh_lexicon_summary(self):
        info = self.isl.summary()
        self.lexicon_label.setText(f"Indian Sign Language · {info['entries']} loaded signs. Add a licensed pack to extend coverage.\n" + info["warning"])

    def reset_lexicon(self):
        self.isl.use_bundled()
        self.stop_playback()
        self.refresh_lexicon_summary()
        self.engine.emit("isl_vocabulary", self.isl.summary())

    def change_auto_sign(self, enabled):
        self.settings.auto_sign = enabled
        self.settings.save()
        self.engine.emit("isl_settings", {"language": "ISL", "auto_sign": enabled})
        if not enabled:
            self.stop_caption_signs()

    def stop_caption_signs(self):
        """Disabling automatic captions must preserve explicit document requests."""
        self.media_queue = [step for step in self.media_queue if not step.get("from_captions")]
        if self.current_sign_step and self.current_sign_step.get("from_captions"):
            remaining = self.media_queue
            self.stop_playback()
            self.media_queue = remaining
            self.next_media()

    def stop_playback(self):
        self.media_queue = []
        self.current_sign_step = None
        self.pose_frames = None
        self.text_step_pending = False
        self.pose_timer.stop()
        if self.media_player:
            self.media_player.stop()
        self.publish_pose(None)
        self.sign_fallback.clear()

    def publish_pose(self, points, message=None):
        for canvas in self.sign_canvases:
            canvas.points = points
            canvas.image = None
            if message is not None:
                canvas.message = message
            elif points is None:
                canvas.message = "Indian Sign Language\nWaiting for the next input"
            if points is None:
                canvas.setAccessibleName(canvas.message)
            canvas.update()

    def publish_video(self, frame):
        step = self.current_sign_step
        if not step or step.get("kind") != "sign" or step["entry"]["path"].suffix == ".npy":
            return
        image = frame.toImage()
        if not image.isNull():
            for canvas in self.sign_canvases:
                canvas.points = None
                canvas.image = image
                canvas.setAccessibleName("Indian Sign Language video: " + step["entry"]["gloss"])
                canvas.update()

    def pause_signs(self):
        if (self.media_player and self.current_sign_step and self.current_sign_step.get("kind") == "sign"
                and self.current_sign_step["entry"]["path"].suffix.lower() != ".npy"):
            if self.media_player.isPlaying():
                self.media_player.pause()
            elif not self.reduce_motion.isChecked():
                self.media_player.play()
            return
        if self.pose_timer.isActive():
            self.pose_timer.stop()
        elif self.pose_frames is not None and not self.reduce_motion.isChecked():
            self.pose_timer.start(round(1000 / (self.pose_fps * self.sign_speed.value())))
        elif getattr(self, "text_step_pending", False) and not self.reduce_motion.isChecked():
            self.pose_timer.start(1500)

    def step_sign(self):
        self.pose_timer.stop()
        self.next_pose_frame()
        self.pose_timer.stop()

    def change_reduced_motion(self, enabled):
        if enabled and hasattr(self, "pose_timer"):
            self.pose_timer.stop()
            if self.media_player:
                self.media_player.pause()

    def change_sign_speed(self, value):
        if self.media_player:
            self.media_player.setPlaybackRate(value)
        if hasattr(self, "pose_timer") and self.pose_timer.isActive() and self.pose_frames is not None:
            self.pose_timer.setInterval(round(1000 / (self.pose_fps * value)))

    def open_floating(self):
        if self.floating_display is None:
            self.floating_display = FloatingSignWindow(self)
            self.sign_canvases.append(self.floating_display.canvas)
        self.floating_display.canvas.points = self.pose.points
        self.floating_display.canvas.image = self.pose.image
        self.floating_display.canvas.message = self.pose.message
        if self.session.captions:
            caption = self.session.captions[-1]
            self.floating_display.caption.setText(self.session.speakers[caption.speaker]["name"] + ": " + caption.text)
        elif self.sign_text.toPlainText().strip():
            self.floating_display.caption.setText(self.sign_text.toPlainText())
        self.floating_display.show()
        self.floating_display.raise_()

    def kandha_page(self):
        page, layout = self.page("Kandha: live captions in the speaker's colour, who is speaking and where they sit, "
                                 "tone cues felt on the Kandha Stole, and a queue strip for taking a turn. "
                                 "Built for deaf students who lip-read.")
        layout.addWidget(button("Open Kandha", self.open_kandha, True))
        note = QLabel("Kandha opens in its own window and uses the microphone only after you press Start there. "
                      "The stole is optional: without one, the on-screen virtual stole shows every tap. "
                      "Let people in the room know live captions are on. See docs/kandha/USER_GUIDE.md.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def open_kandha(self):
        try:
            self.start_browser_service()
            if self.browser_service is None:
                return
            from app.ui.kandha_window import KandhaWindow, prepare_chromium_flags
            prepare_chromium_flags()
            if self.kandha_window is None:
                self.kandha_window = KandhaWindow(self.browser_service.url)
            self.kandha_window.show()
            self.kandha_window.raise_()
            self.statusBar().showMessage("Kandha: " + self.browser_service.url + "/kandha/")
        except Exception as error:
            self.alert(error)

    def open_browser(self):
        try:
            self.start_browser_service()
            if self.browser_service is None:
                return
            import webbrowser
            webbrowser.open(self.browser_service.url)
            self.statusBar().showMessage("Browser companion: " + self.browser_service.url)
        except Exception as error:
            self.alert(error)

    def start_browser_service(self):
        if self._closing or self.browser_service is not None:
            return
        try:
            from app.services.browser import BrowserService
            self.browser_service = BrowserService(self.engine, self.settings, vocabulary=self.isl)
            self.browser_service.start()
        except Exception as error:
            self.browser_service = None
            self.notify_worker("Browser bridge could not start: " + str(error), "error")

    def play_signs(self, text, append=False):
        try:
            plan = self.isl.plan(text)
            for step in plan:
                step["from_captions"] = append
            signs = sum(s["kind"] == "sign" for s in plan)
            fallback = sum(s["kind"] == "text" for s in plan)
            preview = "; ".join(s["text"] for s in plan if s["kind"] == "text")
            if len(preview) > 240:
                preview = preview[:240] + "… (full text remains in playback)"
            self.lexicon_label.setText(f"ISL · {signs} sign steps · {fallback} text passages without a loaded sign.\nText passages: {preview or 'none'}\n" + self.isl.warning)
            if not append:
                self.stop_playback()
                if self.floating_display:
                    self.floating_display.caption.setText(text)
            self.media_queue.extend(plan)
            if self.current_sign_step is None:
                self.next_media()
        except Exception as exc:
            self.alert(exc)

    def clipboard_signs(self):
        text = QApplication.clipboard().text().strip()
        if not text:
            self.statusBar().showMessage("Copy text from your browser or another app first.")
            return
        if len(text) > 20000:
            self.alert("Choose a clipboard extract up to 20,000 characters for sign playback.")
            return
        self.sign_text.setPlainText(text)
        self.play_signs(text)

    def open_sign_input(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open input for Indian Sign Language", "",
                "Supported input (*.txt *.md *.csv *.html *.htm *.docx *.pdf *.srt *.vtt *.json *.wav *.flac *.ogg *.mp3 *.m4a *.mp4 *.webm *.mkv)")
        if path:
            self.display_sign_file(path)

    def open_sign_text(self):
        # Compatibility with the previous public UI action.
        self.open_sign_input()

    def display_sign_file(self, path):
        if Path(path).suffix.lower() in {".wav", ".flac", ".ogg", ".mp3", ".m4a", ".mp4", ".webm", ".mkv"}:
            self.auto_sign.setChecked(True)
            self.start_audio("combined", path)
        else:
            try:
                text = read_text(path)
                if len(text) > 20000:
                    raise ValueError("Use an extract up to 20,000 characters for sign playback.")
                self.sign_text.setPlainText(text)
                self.play_signs(text)
            except (ValueError, OSError) as error:
                self.alert(error)

    def next_media(self):
        self.current_sign_step = None
        self.text_step_pending = False
        self.pose_frames = None
        self.pose_timer.stop()
        if not self.media_queue:
            self.publish_pose(None)
            return
        step = self.media_queue.pop(0)
        self.current_sign_step = step
        if step.get("kind") == "text":
            self.show_text_step(step["text"])
            return
        self.text_step_pending = False
        entry = step.get("entry", step)
        self.sign_fallback.setText("ISL: " + entry["gloss"] + " · " + step.get("text", entry["gloss"]))
        if self.floating_display:
            self.floating_display.detail.setText("ISL phrase: " + entry["gloss"])
        path = entry["path"]
        if path.suffix.lower() == ".npy":
            try:
                self.pose_frames = load_pose_frames(entry)
            except (OSError, ValueError, TypeError) as error:
                self.show_text_step(step["text"], "The loaded ISL pose could not play: " + str(error))
                return
            self.pose_fps = entry.get("fps", 15)
            self.pose_frame_index = 0
            for canvas in self.sign_canvases:
                canvas.setAccessibleName("ISL light sign: " + entry["gloss"])
            self.next_pose_frame()
            if not self.reduce_motion.isChecked():
                self.pose_timer.start(round(1000 / (self.pose_fps * self.sign_speed.value())))
        else:
            self.publish_pose(None, "Indian Sign Language video\n" + entry["gloss"])
            from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
            if self.media_player is None:
                self.media_player = QMediaPlayer(self)
                self.video_sink = QVideoSink(self)
                self.video_sink.videoFrameChanged.connect(self.publish_video)
                self.media_player.setVideoSink(self.video_sink)
                self.media_player.mediaStatusChanged.connect(lambda status: self.next_media() if status == QMediaPlayer.EndOfMedia else None)
                self.media_player.errorOccurred.connect(self.sign_video_error)
            # Dictionary videos are intentionally silent.
            self.media_player.setSource(QUrl.fromLocalFile(str(path)))
            self.media_player.setPlaybackRate(self.sign_speed.value())
            if not self.reduce_motion.isChecked():
                self.media_player.play()

    def show_text_step(self, text, reason="Text · no loaded ISL sign"):
        origin = bool(self.current_sign_step and self.current_sign_step.get("from_captions"))
        self.current_sign_step = {"kind": "text", "text": text, "from_captions": origin}
        self.publish_pose(None, reason + "\n" + text)
        self.sign_fallback.setText(reason + "\n" + text)
        if self.floating_display:
            self.floating_display.detail.setText(reason + "\n" + text)
        self.pose_frames = None
        self.text_step_pending = True
        if not self.reduce_motion.isChecked():
            self.pose_timer.start(round(max(1200, min(4500, len(text) * 65)) / self.sign_speed.value()))

    def sign_video_error(self, error, message):
        if self.current_sign_step and self.current_sign_step.get("kind") == "sign":
            original = self.current_sign_step["text"]
            self.media_player.stop()
            self.show_text_step(original, "ISL clip could not play: " + message)

    def next_pose_frame(self):
        if getattr(self, "text_step_pending", False):
            self.text_step_pending = False
            self.pose_timer.stop()
            self.next_media()
            return
        if self.pose_frames is None:
            if self.current_sign_step and self.current_sign_step.get("kind") == "sign" and self.media_player:
                position = self.media_player.position() + round(1000 / self.current_sign_step["entry"].get("fps", 15))
                if self.media_player.duration() and position >= self.media_player.duration():
                    self.media_player.stop()
                    self.next_media()
                else:
                    self.media_player.setPosition(position)
            return
        if self.pose_frame_index >= len(self.pose_frames):
            self.pose_timer.stop()
            self.pose_frames = None
            self.next_media()
            return
        self.publish_pose(self.pose_frames[self.pose_frame_index])
        self.pose_frame_index += 1

    def pick_color(self, index):
        color = QColorDialog.getColor(parent=self, title="Choose intensity colour")
        if color.isValid():
            self.settings.intensity_colors[index] = color.name()

    def refresh_emotion_colors(self):
        for emotion, choice in self.emotion_color_buttons.items():
            color = self.settings.emotion_colors[emotion]
            choice.setText(emotion.capitalize() + "  " + color.upper())
            choice.setStyleSheet(f"background:{color};color:{foreground(color)};")

    def pick_emotion_color(self, emotion):
        from PySide6.QtGui import QColor
        color = QColorDialog.getColor(QColor(self.settings.emotion_colors[emotion]), self,
                                     "Choose color for " + emotion)
        if color.isValid():
            self.settings.emotion_colors[emotion] = color.name()
            self.refresh_emotion_colors()

    def reset_emotion_colors(self):
        self.settings.emotion_colors = DEFAULT_EMOTION_COLORS.copy()
        self.refresh_emotion_colors()

    def save_settings(self):
        if self.busy():
            self.alert("Stop active inference and training before saving settings.")
            return
        self.settings.preset = self.preset_box.currentData()
        self.settings.device = self.device_box.currentData()
        self.settings.language = self.language_box.currentData()
        self.settings.microphone = self.mic_box.currentData()
        self.settings.camera = self.camera_box.value()
        self.settings.diarization = self.diarization_box.currentData()
        self.settings.sign_threshold = self.threshold_box.value()
        self.settings.partial_updates = self.partial_box.isChecked()
        self.settings.prosody_classifier = self.classifier_box.isChecked()
        self.settings.auto_speak_sign = self.speak_box.isChecked()
        self.settings.sign_speed = self.sign_speed.value()
        self.settings.reduced_motion = self.reduce_motion.isChecked()
        self.settings.save()
        for panel in self.tone_panels:
            panel.colors = self.settings.intensity_colors
            panel.set_emotion_colors(self.settings.emotion_colors)
        self.statusBar().showMessage("Settings saved")

    def choose_training_data(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose preprocessed dataset", "", "NPZ (*.npz)")
        if path:
            self.train_data.setText(path)

    def start_training(self, resume=False):
        if self.busy():
            self.alert("Stop microphone and webcam inference before starting a training run.")
            return
        task = self.train_task.currentText()
        if not resume:
            data = Path(self.train_data.text())
            if not data.is_file() or not data.with_suffix(".json").is_file():
                self.alert("Select an NPZ dataset with its provenance JSON beside it.")
                return
            self.training_output = data_root() / "training" / f"{task}_{int(time.time())}"
            self.training_output.mkdir(parents=True)
            cfg = yaml.safe_load((project_root() / "training" / {"sign": "sign_recognition", "prosody": "prosody", "diarization": "diarization"}[task] / "config.yaml").read_text())
            cfg.update(data=str(data), output=str(self.training_output), epochs=self.train_epochs.value(), batch_size=self.train_batch.value())
            (self.training_output / "config.yaml").write_text(yaml.safe_dump(cfg))
        self.control_training("run")
        flags = ["--train-task", task, "--train-config", str(self.training_output / "config.yaml"), "--control", str(self.training_output / "control.json")]
        if resume:
            flags += ["--resume", str(self.training_output / "latest.pt")]
        self.training_process = self.launch_process(flags, self.train_log)

    def control_training(self, command):
        if self.training_output:
            atomic_json(self.training_output / "control.json", {"command": command})
            self.train_summary.setText("Requested " + command + "; pause/stop take effect after the current epoch.")

    def resume_training(self):
        if self.training_process and self.training_process.state() != QProcess.NotRunning:
            self.control_training("run")
        elif self.training_output and (self.training_output / "latest.pt").exists():
            self.start_training(True)

    def import_training_result(self):
        if self.train_task.currentText() == "diarization":
            self.alert("The enrolled-speaker head is a research tool. Evaluate it with training/diarization/inference.py; live diarization uses ECAPA clustering.")
            return
        if self.training_output and (self.training_output / "best.pt").exists():
            self.import_checkpoint(self.train_task.currentText(), str(self.training_output / "best.pt"))

    def run_diagnostics(self, validation):
        if self.busy():
            self.alert("Stop active capture and training before running diagnostics.")
            return
        self.launch_process(["--validate-local"] if validation else ["--hardware-check"], self.diagnostics_log)

    def poll(self):
        if self.auto_sign.isChecked() != self.settings.auto_sign:
            with QSignalBlocker(self.auto_sign):
                self.auto_sign.setChecked(self.settings.auto_sign)
            if not self.settings.auto_sign:
                self.stop_caption_signs()
        for _ in range(100):
            try:
                kind, data = self.engine.events.get_nowait()
            except queue.Empty:
                break
            if kind == "caption":
                self.session.add(data)
                self.session_dirty = True
                for panel in self.caption_panels:
                    panel.append_caption(self.session, data)
                if self.auto_sign.isChecked():
                    self.play_signs(data.text, append=True)
                if self.floating_display:
                    speaker = self.session.speakers[data.speaker]["name"]
                    self.floating_display.caption.setText(speaker + ": " + data.text)
            elif kind == "partial":
                for panel in self.caption_panels:
                    panel.partial.setText(data or "Listening for the next phrase…")
            elif kind == "prosody":
                for panel in self.tone_panels:
                    panel.set_emotion_colors(self.settings.emotion_colors)
                    panel.update_features(data)
            elif kind == "emotion":
                for panel in self.tone_panels:
                    if data["estimate"] is not None:
                        panel.show_emotion(data["estimate"])
                    else:
                        panel.last_emotion = None
                        panel.emotion_badge.setText("Expression estimates are off")
                        panel.emotion_badge.setStyleSheet("")
                        panel.emotion_detail.setText("Objective prosody remains available. Enable experimental estimates in Settings.")
            elif kind == "caption_voice":
                for caption in reversed(self.session.captions[-40:]):
                    if (caption.start, caption.end, caption.speaker) == (data["start"], data["end"], data["speaker"]):
                        estimate = data["estimate"]
                        caption.voice = {**caption.voice, "tone": estimate["tone"], "tone_confidence": estimate.get("confidence")}
                        for panel in self.caption_panels:
                            panel.update_voice(self.session, caption)
                        self.session_dirty = True
                        break
            elif kind == "frame":
                self.camera_label.setPixmap(rgb_pixmap(data, self.camera_label.size()))
            elif kind == "pose" and self.current_sign_step is None:
                self.publish_pose(data)
            elif kind == "camera_status":
                self.camera_status.setText(data)
            elif kind == "sign":
                accepted = data["accepted"]
                self.last_sign = data["label"] if accepted else ""
                self.sign_result.setText(f"{'Recognised' if accepted else 'Uncertain candidate'}: {data['label']} · score {data['score']:.0%} (uncalibrated)")
                if accepted:
                    self.reply.setText(data["label"])
                    if self.settings.auto_speak_sign:
                        self.speak(data["label"])
            elif kind in {"error", "warning", "status"}:
                self.statusBar().showMessage(data)
                if kind in {"error", "warning"}:
                    self.notify_worker(data, kind)
                if kind == "status" and data in {"Idle", "Paused"}:
                    for panel in self.caption_panels:
                        panel.partial.setText("Audio stopped. Start the microphone or open a local file." if data == "Idle" else "Audio paused.")
                if kind == "error":
                    self.model_log.appendPlainText("ERROR: " + data)
            elif kind == "performance":
                rtf = data["inference_seconds"] / max(data["audio_seconds"], 0.001)
                self.statusBar().showMessage(f"Local chunk RTF {rtf:.2f} · caption queue {data['queue_depth']} · overlap {'available' if self.settings.diarization == 'pyannote' else 'unmeasured'}")
        for start, pause, stop, file in self.live_buttons:
            start.setEnabled(not self.engine.running)
            file.setEnabled(not self.engine.running)
            pause.setEnabled(self.engine.running)
            stop.setEnabled(self.engine.running)
        self.record_button.setText("Finish sign recording" if self.camera.record.is_set() else "Record one sign")
        if self.training_output and (self.training_output / "progress.json").exists():
            try:
                info = json.loads((self.training_output / "progress.json").read_text())
                gpu = info.get("gpu_utilization_percent")
                gpu_text = f"{gpu:.0f}% (device)" if gpu is not None else "unavailable / CPU"
                self.train_summary.setText(f"{info.get('task', '')} · {info.get('status', '')} · epoch {info.get('epoch', 0)} · loss {info.get('loss', 0):.4f} · validation F1 {info.get('validation_macro_f1', 0):.3f}\nDevice {info.get('device', '')} · GPU {gpu_text} · VRAM {info.get('vram_mb', 0):.0f} MB · elapsed {info.get('elapsed_seconds', 0):.0f}s · ETA {info.get('eta_seconds', 0):.0f}s")
            except (ValueError, OSError):
                pass
        if self.tts:
            if self.tts.error:
                self.camera_status.setText("Local speech synthesis: " + self.tts.error)
                self.notify_worker("Local speech synthesis: " + self.tts.error, "error")
                self.tts.error = None
            if self.tts_resume_audio and not self.tts.speaking.is_set():
                self.engine.pause(False)
                self.tts_resume_audio = False

    def closeEvent(self, event):
        self.cancel_device_discovery()
        if self.training_process and self.training_process.state() != QProcess.NotRunning:
            self.alert("Stop training and wait for its checkpoint before closing the app.")
            event.ignore()
            return
        if any(p.state() != QProcess.NotRunning for p in self.processes):
            self.alert("Wait for the current download or diagnostics operation to finish before closing.")
            event.ignore()
            return
        if self.engine.running or (self.camera.thread and self.camera.thread.is_alive()):
            self.engine.stop()
            self.camera.stop()
            self.statusBar().showMessage("Stopping workers…")
            QTimer.singleShot(300, self.close)
            event.ignore()
            return
        if self.session_dirty:
            answer = QMessageBox.question(self, "Save transcript", "Save the current transcript before closing?", QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            if answer == QMessageBox.Cancel or (answer == QMessageBox.Yes and not self.save_session()):
                event.ignore()
                return
        if self.tts:
            self.tts.close()
        if self.browser_service:
            self.browser_service.stop()
        self.model_setup.shutdown()
        self._closing = True
        event.accept()
