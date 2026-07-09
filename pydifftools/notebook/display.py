"""Small display helpers for fast notebook builds."""


class _NotebookCapture:
    """Emit notebook content in an explicit order."""

    def __init__(self):
        self._figures = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        for fig in self._figures:
            self._close_figure(fig)
        return False

    def md(self, text):
        """Display markdown text as a Jupyter Markdown MIME bundle."""
        from IPython.display import Markdown, display

        display(Markdown(text))

    def fig(self, obj=None):
        """Display a Matplotlib figure-like object and close it afterward."""
        from io import BytesIO

        from IPython.display import Image, display

        fig = self._figure_from_object(obj)
        if hasattr(fig, "savefig"):
            data = BytesIO()
            fig.savefig(data, format="png", bbox_inches="tight")
            display(Image(data=data.getvalue()))
        else:
            display(fig)
        self._figures.append(fig)
        self._close_figure(fig)

    def _figure_from_object(self, obj):
        import matplotlib.pyplot as plt

        if obj is None:
            return plt.gcf()
        if isinstance(obj, (list, tuple)):
            if not obj:
                raise ValueError("cannot display an empty figure object list")
            return self._figure_from_object(obj[0])
        if hasattr(obj, "get_figure"):
            fig = obj.get_figure()
            if fig is not None:
                return fig
        if hasattr(obj, "figure"):
            fig = obj.figure
            if fig is not None and fig is not obj:
                return fig
        return obj

    def _close_figure(self, fig):
        import matplotlib.pyplot as plt

        plt.close(fig)


def nb_capture():
    """Return an ordered notebook output capture context."""
    return _NotebookCapture()
