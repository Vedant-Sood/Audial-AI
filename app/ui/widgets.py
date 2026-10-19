from collections import deque
from html import escape
import numpy as np
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QPainterPath, QImage, QPixmap
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QListWidget, QListWidgetItem, QListView
from app.utils.palette import DEFAULT_EMOTION_COLORS, foreground


def button(text, callback, primary=False):
    b = QPushButton(text.replace("&", "&&"))
    b.setCursor(Qt.PointingHandCursor)
    if primary:
        b.setObjectName("primary")
    b.clicked.connect(callback)
    return b


def card(title, subtitle):
    f = QFrame()
    f.setObjectName("card")
    layout = QVBoxLayout(f)
    layout.setContentsMargins(22, 20, 22, 20)
    title_label = QLabel(title)
    title_label.setObjectName("cardTitle")
    layout.addWidget(title_label)
    sub = QLabel(subtitle)
    sub.setWordWrap(True)
    sub.setObjectName("muted")
    layout.addWidget(sub)
    return f, layout


def draw_sign_image(painter, rect, image):
    """Fit original signer video frames without cropping hands or face."""
    size = image.size().scaled(rect.size(), Qt.KeepAspectRatio)
    target = QRectF((rect.width() - size.width()) / 2, (rect.height() - size.height()) / 2,
                    size.width(), size.height())
    painter.drawImage(target, image)


class Plot(QWidget):
    def __init__(self, kind="line", color="#008c7f", minimum=None, maximum=None):
        super().__init__()
        self.kind, self.color = kind, color
        self.minimum, self.maximum = minimum, maximum
        self.values = []
        self.setMinimumHeight(110)
        self.setAccessibleName("Audio " + kind + " plot; values are also shown as text")

    def set_values(self, values):
        self.values = values
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#f3f7f8"))
        for y in [0.25, 0.5, 0.75]:
            p.setPen(QPen(QColor("#dfe9e9"), 1))
            p.drawLine(QPointF(0, self.height() * y), QPointF(self.width(), self.height() * y))
        finite = [v for v in self.values if v is not None and np.isfinite(v)]
        if not finite:
            return
        lo = self.minimum if self.minimum is not None else min(finite)
        hi = self.maximum if self.maximum is not None else max(finite)
        span = max(hi - lo, 0.001)
        path = QPainterPath()
        connected = False
        for i, value in enumerate(self.values):
            if value is None or not np.isfinite(value):
                connected = False
                continue
            x = i * (self.width() - 12) / max(len(self.values) - 1, 1) + 6
            y = self.height() - 8 - np.clip((value - lo) / span, 0, 1) * (self.height() - 16)
            if connected:
                path.lineTo(x, y)
            else:
                path.moveTo(x, y)
                connected = True
        p.setPen(QPen(QColor(self.color), 2.2))
        p.drawPath(path)


class TonePanel(QWidget):
    def __init__(self):
        super().__init__()
        self.history = deque(maxlen=180)
        self.colors = ["#2263ac", "#087f75", "#b75a17"]
        self.emotion_colors = DEFAULT_EMOTION_COLORS.copy()
        self.last_emotion = None
        layout = QVBoxLayout(self)
        self.emotion_badge = QLabel("Emotion estimates are off")
        self.emotion_badge.setAlignment(Qt.AlignCenter)
        self.emotion_badge.setAccessibleName("Voice emotion estimate")
        self.emotion_badge.setMinimumHeight(64)
        layout.addWidget(self.emotion_badge)
        self.emotion_detail = QLabel("Enable voice emotion in Settings. Colors always appear with a label.")
        self.emotion_detail.setWordWrap(True)
        layout.addWidget(self.emotion_detail)
        top = QHBoxLayout()
        self.pitch = QLabel("Pitch  — Hz")
        self.energy = QLabel("Digital level  — dBFS")
        self.rate = QLabel("Speaking rate  —")
        for label in [self.pitch, self.energy, self.rate]:
            label.setObjectName("metric")
            top.addWidget(label)
        layout.addLayout(top)
        layout.addWidget(QLabel("WAVEFORM"))
        self.wave = Plot(minimum=-0.5, maximum=0.5)
        layout.addWidget(self.wave)
        layout.addWidget(QLabel("PITCH HISTORY  ·  60–450 Hz"))
        self.f0 = Plot(minimum=60, maximum=450)
        layout.addWidget(self.f0)
        layout.addWidget(QLabel("DIGITAL LEVEL HISTORY  ·  −80 to 0 dBFS"))
        self.level = Plot(minimum=-80, maximum=0)
        layout.addWidget(self.level)
        self.detail = QLabel("Waiting for audio. Pitch confidence measures periodicity; dBFS is not calibrated loudness.")
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail)
        self.category = QLabel("Objective features enabled. Optional acted-speech classifier is off.")
        self.category.setWordWrap(True)
        self.category.setObjectName("muted")
        layout.addWidget(self.category)

    def set_emotion_colors(self, colors):
        if self.emotion_colors == colors:
            return
        self.emotion_colors = colors.copy()
        if self.last_emotion is not None:
            self.show_emotion(self.last_emotion)

    def show_emotion(self, estimate):
        self.last_emotion = estimate
        label = estimate.get("tone", "uncertain")
        if label not in self.emotion_colors:
            label = "uncertain"
        color = self.emotion_colors[label]
        self.emotion_badge.setText(label.capitalize())
        self.emotion_badge.setStyleSheet(
            f"background:{color};color:{foreground(color)};font-size:24px;font-weight:600;"
            "border-radius:12px;padding:14px;")
        confidence = estimate.get("confidence")
        reason = estimate.get("reason")
        if label == "uncertain":
            text = "No reliable estimate" + (" · " + reason.replace("_", " ") if reason else "")
        else:
            text = "Voice estimate" + (f" · model confidence {confidence:.0%}" if confidence is not None else "")
        self.emotion_detail.setText(text + ". This is an acoustic estimate, not a fact about feelings.")

    def update_features(self, f):
        self.history.append(f)
        pitch = f['f0_hz']
        self.pitch.setText(f"Pitch  {pitch:.0f} Hz" if pitch is not None else "Pitch  unvoiced")
        self.energy.setText(f"Digital level  {f['dbfs']:.1f} dBFS")
        rate = f.get("speaking_rate_wpm")
        self.rate.setText(f"Speaking rate  {rate:.0f} wpm" if rate is not None else "Speaking rate  awaiting captions")
        self.wave.set_values(f["waveform"])
        self.f0.set_values([d["f0_hz"] for d in self.history])
        self.level.color = self.colors[0 if f["dbfs"] < -35 else 1 if f["dbfs"] < -20 else 2]
        self.level.set_values([d["dbfs"] for d in self.history])
        self.detail.setText(f"Pitch periodicity {f['pitch_confidence']:.0%} · pauses in analysis window {f['pause_count']} / {f['pause_seconds']:.2f}s · spectral centroid {f['spectral_centroid_hz']:.0f} Hz")
        if "classification" in f:
            c = f["classification"]
            self.category.setText(f"EXPERIMENTAL · {c['label']} · model score {c['score']:.0%} (uncalibrated). Acted-speech labels cannot establish a speaker's feelings.")
        if "emotion" in f:
            c = f["emotion"]
            self.show_emotion(c)
            self.category.setText("Voice-tone estimate: " + c["tone"] + ". Experimental acoustic model; spoken words remain unchanged.")


class CaptionPanel(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        self.legend = QLabel("Speaker names and colours appear after speech is processed.")
        self.legend.setTextFormat(Qt.RichText)
        self.legend.setWordWrap(True)
        layout.addWidget(self.legend)
        self.lines = QListWidget()
        self.lines.setLayoutMode(QListView.Batched)
        self.lines.setBatchSize(100)
        self.visible_limit = 500
        self._legend_state = None
        self._caption_items = {}
        self.lines.setWordWrap(True)
        self.lines.setAccessibleName("Completed live transcript")
        self.lines.setMinimumHeight(210)
        layout.addWidget(self.lines, 1)
        self.partial = QLabel("Partial captions will appear here…")
        self.partial.setWordWrap(True)
        self.partial.setObjectName("partial")
        self.partial.setMinimumHeight(48)
        layout.addWidget(self.partial)

    def refresh(self, session):
        self.lines.clear()
        self._caption_items.clear()
        self.lines.setUpdatesEnabled(False)
        for c in session.captions[-self.visible_limit:]:
            self.append_caption(session, c, scroll=False)
        self.lines.setUpdatesEnabled(True)
        self.lines.scrollToBottom()
        self.update_legend(session)

    def update_legend(self, session):
        state = tuple((speaker, s["name"], s["color"]) for speaker, s in session.speakers.items())
        if state == self._legend_state:
            return
        self._legend_state = state
        items = []
        for s in session.speakers.values():
            color = QColor(s["color"])
            color = color.name() if color.isValid() else "#18353d"
            items.append(f'<span style="color:{color}">● {escape(s["name"])}</span>')
        self.legend.setText(" &nbsp; | &nbsp; ".join(items) or "No speakers yet")

    def append_caption(self, session, caption, scroll=True):
        item = QListWidgetItem(self.caption_text(session, caption))
        item.setForeground(QColor(session.speakers[caption.speaker]["color"]))
        key = (caption.start, caption.end, caption.speaker)
        item.setData(Qt.UserRole, key)
        self._caption_items[key] = item
        follow = getattr(self, "_scroll_pending", False) or self.lines.verticalScrollBar().value() >= self.lines.verticalScrollBar().maximum() - 4
        self.lines.addItem(item)
        while self.lines.count() > self.visible_limit:
            removed = self.lines.takeItem(0)
            self._caption_items.pop(tuple(removed.data(Qt.UserRole)), None)
        self.update_legend(session)
        if scroll and follow and not getattr(self, "_scroll_pending", False):
            from PySide6.QtCore import QTimer
            self._scroll_pending = True
            def scroll_to_end():
                self._scroll_pending = False
                self.lines.scrollToBottom()
            QTimer.singleShot(0, self, scroll_to_end)

    def update_voice(self, session, caption):
        item = self._caption_items.get((caption.start, caption.end, caption.speaker))
        if item is not None:
            item.setText(self.caption_text(session, caption))

    @staticmethod
    def caption_text(session, caption):
        c = caption
        speaker = session.speakers[c.speaker]
        certainty = "" if c.word_confidence is None else f" · ASR score {c.word_confidence:.0%}"
        voice = c.voice or {}
        if voice.get("f0_hz") is not None:
            certainty += f" · voice {voice['f0_hz']:.0f} Hz"
        if voice.get("tone"):
            certainty += " · tone " + voice["tone"]
        return f"{speaker['name']}  ·  {c.start:07.2f}s{certainty}\n{c.text}"


class PoseCanvas(QWidget):
    def __init__(self):
        super().__init__()
        self.points = None
        self.image = None
        self.message = "Indian Sign Language\nWaiting for the next input"
        self.setMinimumSize(280, 200)
        self.setAccessibleName("ISL pose replay: experimental skeleton view")

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#112b35"))
        if self.image is not None:
            draw_sign_image(p, self.rect(), self.image)
            return
        if self.points is None:
            p.setPen(QColor("#bfdbd9"))
            p.drawText(self.rect().adjusted(12, 12, -12, -12), Qt.AlignCenter | Qt.TextWordWrap, self.message)
            return
        points = np.asarray(self.points).reshape(49, 4)
        hand_edges = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8),
            (5, 9), (9, 10), (10, 11), (11, 12), (9, 13), (13, 14), (14, 15), (15, 16),
            (13, 17), (0, 17), (17, 18), (18, 19), (19, 20)]
        edges = [(1, 2), (1, 3), (3, 5), (2, 4), (4, 6)]
        edges += [(a + o, b + o) for o in [7, 28] for a, b in hand_edges]
        def pos(index):
            return QPointF(float(points[index, 0]) * self.width(), float(points[index, 1]) * self.height())
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor("#52e3b6"), 2))
        for a, b in edges:
            if points[a, 3] > 0.3 and points[b, 3] > 0.3:
                p.drawLine(pos(a), pos(b))
        p.setBrush(QColor("#f2c56b"))
        p.setPen(Qt.NoPen)
        for j in range(49):
            if points[j, 3] > 0.3:
                p.drawEllipse(pos(j), 2.8, 2.8)


def rgb_pixmap(rgb, size):
    h, w, _ = rgb.shape
    image = QImage(rgb.data, w, h, rgb.strides[0], QImage.Format_RGB888).copy()
    return QPixmap.fromImage(image).scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
