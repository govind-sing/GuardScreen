class GuardScreenError(Exception):
    """Base class for all custom GuardScreen exceptions."""


class UnsupportedFileTypeError(GuardScreenError):
    """Raised when a file's type isn't one we know how to parse."""


class ExtractionFailedError(GuardScreenError):
    """Raised when a file is the right type but couldn't be parsed (corrupt, encrypted, etc.)."""