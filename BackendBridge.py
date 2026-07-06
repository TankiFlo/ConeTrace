from PySide6.QtCore import QObject, Slot, Signal

class BackendBridge(QObject):
    '''
    Bridge between Foliums JS and Python
    '''
    markerClicked = Signal(str)
    mapClicked = Signal(float, float)
    semiCircleReturned = Signal(str, int, int, int, bool)
    markerMoved = Signal(str, float, float) 

    @Slot(str)
    def js_marker_clicked(self, marker_id):
        self.markerClicked.emit(marker_id)

    @Slot(float, float)
    def js_map_clicked(self, lat, lng):
        self.mapClicked.emit(lat, lng)

    @Slot(str, int, int, int, bool)
    def js_return_semicircle(self, marker_id, radius, direction, arc, updateUI = False):
        self.semiCircleReturned.emit(marker_id, radius, direction, arc, updateUI)

    @Slot(str, float, float)
    def js_marker_moved(self, marker_id, lat, lng):
        self.markerMoved.emit(marker_id, lat, lng)