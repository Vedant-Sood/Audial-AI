from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget, QDialog, QVBoxLayout, QLabel, QPushButton

from app.services.sign_lights import rasterize
from app.ui.widgets import draw_sign_image


class SignLightCanvas(QWidget):
    def __init__(self):
        super().__init__()
        self.points = None
        self.image = None
        self.message = "Indian Sign Language\nWaiting for the next input"
        self.setMinimumSize(240, 210)
        self.setAccessibleName("Indian Sign Language: hand and body motion displayed as on/off lights")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#101b28"))
        if self.image is not None:
            draw_sign_image(painter, self.rect(), self.image)
            return
        if self.points is None:
            painter.setPen(QColor("#d4e8e0"))
            painter.drawText(self.rect().adjusted(12, 12, -12, -12), Qt.AlignCenter | Qt.TextWordWrap, self.message)
            return
        grid = rasterize(self.points)
        size = min(self.width()/128, self.height()/96)
        origin_x,origin_y = (self.width()-128*size)/2, (self.height()-96*size)/2
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#82e8b7"))
        for y,x in zip(*grid.nonzero()):
            painter.drawRect(QRectF(origin_x+x*size,origin_y+y*size,max(.5,size*.78),max(.5,size*.78)))


class FloatingSignWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window | Qt.WindowStaysOnTopHint)
        self.setWindowTitle("AccessibilityAI · captions and signs")
        self.resize(440, 430)
        layout = QVBoxLayout(self)
        self.canvas = SignLightCanvas()
        layout.addWidget(self.canvas, 1)
        self.caption = QLabel("Start captions in the main app or browser.")
        self.caption.setTextFormat(Qt.PlainText)
        self.caption.setWordWrap(True)
        self.caption.setAccessibleName("Latest meeting caption")
        self.caption.setStyleSheet("font-size:20px;padding:12px;")
        layout.addWidget(self.caption)
        self.detail = QLabel("ISL phrase lookup · unknown words remain as text")
        self.detail.setTextFormat(Qt.PlainText)
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail)
        button = QPushButton("Close floating display")
        button.clicked.connect(self.close)
        layout.addWidget(button)
