from PySide6.QtWidgets import QSlider, QStyle, QStyleOptionSlider
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QPainter, QColor

class VideoTimeline(QSlider):
    '''
    Custom QSlider that draws rectangles representing video segments 
    relative to the total timeline, with forced high-contrast ticks.
    '''
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOrientation(Qt.Orientation.Horizontal)
        self.video_segments = []
        self.is_dark = False  # Track theme state internally

    def set_video_segments(self, segments):
        """Pass a list of (start_offset, duration) tuples."""
        self.video_segments = segments
        self.update()  # Trigger a repaint

    def paintEvent(self, event):
        # 1. Let Qt draw the custom styled groove and handle first
        super().paintEvent(event)
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        groove_rect = self.style().subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderGroove, self)
        handle_rect = self.style().subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderHandle, self)

        # 2. Draw High-Contrast Ticks
        tick_pos = self.tickPosition()
        if tick_pos != QSlider.NoTicks and self.maximum() > 0:
            tick_color = QColor("#ffffff") if self.is_dark else QColor("#555555")
            painter.setPen(tick_color)
            
            # Pad the available width so ticks perfectly align with the handle's center
            available_width = self.width() - handle_rect.width()
            start_x = handle_rect.width() // 2
            
            min_val = self.minimum()
            max_val = self.maximum()
            val_range = max_val - min_val
            
            interval = self.tickInterval()
            if interval <= 0:
                interval = max(self.pageStep(), 1)
                    
            if val_range > 0:
                for val in range(min_val, max_val + 1, interval):
                    x = start_x + int(((val - min_val) / val_range) * available_width)
                    
                    if tick_pos in [QSlider.TicksAbove, QSlider.TicksBothSides]:
                        painter.drawLine(x, 1, x, 5)
                    if tick_pos in [QSlider.TicksBelow, QSlider.TicksBothSides]:
                        painter.drawLine(x, self.height() - 5, x, self.height() - 1)

        # 3. Draw Video Segments and Keyframes
        if not self.video_segments or self.maximum() <= 0:
            painter.end()
            return

        for start, duration, name, color_hex, keyframes in self.video_segments:
            x = groove_rect.left() + int((start / self.maximum()) * groove_rect.width())
            w = int((duration / self.maximum()) * groove_rect.width())
            rect = QRect(x, groove_rect.top() + 2, w, groove_rect.height() - 4)
            
            # Draw the Background using the marker's specific color
            painter.setPen(Qt.NoPen)
            base_color = QColor(color_hex)
            base_color.setAlpha(120) # Keep it semi-transparent
            painter.setBrush(base_color)
            painter.drawRect(rect)
            
            # Draw the Camera Name text
            painter.setPen(QColor(0, 0, 0) if not self.is_dark else QColor(255, 255, 255)) 
            font = painter.font()
            font.setPointSize(8) 
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignCenter | Qt.TextWordWrap, name)

            # Draw Keyframes as little dots
            painter.setBrush(QColor(255, 255, 255))
            painter.setPen(QColor(0, 0, 0)) # Thin black border for visibility
            for kf_scaled_time in keyframes:
                kf_x = groove_rect.left() + int((kf_scaled_time / self.maximum()) * groove_rect.width())
                # Draw small circle representing the keyframe
                painter.drawEllipse(kf_x - 3, groove_rect.center().y() - 3, 6, 6)
            
        painter.end()