from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QLineEdit

class GlobalSpacebarFilter(QObject):
    """Intercepts the spacebar globally to toggle playback, ignoring text inputs."""
    def __init__(self, toggle_callback, parent=None):
        super().__init__(parent)
        self.toggle_callback = toggle_callback

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key_Space:
            # Allow normal spacebar behavior if the user is typing in a text input
            if isinstance(obj, QLineEdit):
                return False
                
            # Ignore auto-repeat if the user holds the spacebar down
            if not event.isAutoRepeat():
                self.toggle_callback()
                
            # Return True to consume the event so sliders/buttons don't also trigger
            return True 
            
        return super().eventFilter(obj, event)

class ProportionResizeFilter(QObject):
    def __init__(self, label_to_resize, width_ratio=0.25, parent=None):
        """
        :param label_to_resize: The widget whose minimum width will be adjusted
        :param width_ratio: The percentage of the parent's width to use (e.g., 0.25 for 25%)
        """
        super().__init__(parent)
        self.label_to_resize = label_to_resize
        self.width_ratio = width_ratio

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize:
            # Calculate the new minimum width based on the container's new size
            new_min_width = int(event.size().width() * self.width_ratio)
            self.label_to_resize.setMinimumWidth(new_min_width)
        
        # Always return False so the normal resize behavior continues
        return False

class VideoRightClickFilter(QObject):
    """Intercepts raw mouse events to force a context menu on video surfaces."""
    def __init__(self, index, callback, parent=None):
        super().__init__(parent)
        self.index = index
        self.callback = callback

    def eventFilter(self, obj, event):
        # Catch standard ContextMenu events
        if event.type() == QEvent.Type.ContextMenu:
            self.callback(event.globalPos(), self.index)
            return True
        # Fallback: forcefully catch Right-Click releases
        elif event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.RightButton:
            self.callback(event.globalPosition().toPoint(), self.index)
            return True
        
        return super().eventFilter(obj, event)

class VideoSelectFilter(QObject):
    """Event filter to capture left clicks on video widgets and select the corresponding map marker."""
    def __init__(self, marker_id, callback, parent=None):
        super().__init__(parent)
        self.marker_id = marker_id
        self.callback = callback

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                self.callback(self.marker_id)
                return True # Consume the event
        return super().eventFilter(obj, event)