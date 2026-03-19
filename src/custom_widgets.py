import ipywidgets as ipw


class HBox(ipw.HBox):
    def __init__(self, metadata=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.metadata = metadata


class VBox(ipw.VBox):
    def __init__(self, metadata=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.metadata = metadata
