import sys

# Find Logging Widget Currently in trendahl home area
LOG_PATH = "/opt/switchtool/EpicsQT/"
sys.path.insert(0, LOG_PATH)

from . import dialogs, widgets
from .widgets.switch import SwitchWidget

__all__ = ["widgets", "dialogs"]
