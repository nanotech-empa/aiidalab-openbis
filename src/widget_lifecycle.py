"""Dispose private widget trees, not borrowed widgets from other views."""

import ipywidgets as ipw


def close_owned_widgets(*widgets, shared=()):
    """Close owned children, layouts and styles, releasing large payloads.

    Callers must unregister their external observers first. Only pass trees
    constructed by the caller; ownership cannot be inferred from arbitrary
    widget attributes or links.
    """
    seen = {id(widget) for widget in shared}

    def close(widget):
        if widget is None or id(widget) in seen:
            return
        seen.add(id(widget))
        for child in getattr(widget, "children", ()):
            close(child)
        if hasattr(widget, "children"):
            widget.children = ()
        if isinstance(widget, ipw.Image):
            widget.value = b""
        elif isinstance(widget, ipw.FileUpload):
            widget.value = type(widget.value)()
        close(getattr(widget, "layout", None))
        close(getattr(widget, "style", None))
        widget.close()

    for widget in widgets:
        close(widget)
