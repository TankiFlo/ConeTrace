from PySide6.QtCore import QSize
from PySide6.QtWidgets import QWidget, QVBoxLayout

class AspectRatioWrapper(QWidget):
    """
    A container widget that forces its child widget to maintain 
    a strict aspect ratio while centering it dynamically.
    """
    def __init__(self, child_widget, ratio=16.0/9.0, parent=None):
        super().__init__(parent)
        self.ratio = ratio
        self.last_size = QSize(-1, -1)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(child_widget)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        current_size = event.size()
        
        # Guard clause to prevent infinite layout recalculation loops
        if current_size == self.last_size:
            return
        self.last_size = current_size

        full_width = current_size.width()
        full_height = current_size.height()

        target_width = min(full_width, int(full_height * self.ratio))
        target_height = min(full_height, int(full_width / self.ratio))

        h_margin = (full_width - target_width) // 2
        v_margin = (full_height - target_height) // 2

        self.setContentsMargins(h_margin, v_margin, h_margin, v_margin)