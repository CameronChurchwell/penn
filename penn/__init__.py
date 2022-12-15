# Development
# - Yapecs passwords
# - Huggingface models
# - Reserve module name on PyPi
# - Figures
#   - Gershwin powerpoint***
#   - Density powerpoint**

# Paper
# - Cross-domain
#   - Text*


###############################################################################
# Configuration
###############################################################################


# Default configuration parameters to be modified
from .config import defaults

# Modify configuration
import yapecs
yapecs.configure(defaults)

# Import configuration parameters
from .config.defaults import *
from . import time
from .config.static import *


###############################################################################
# Module imports
###############################################################################


from .core import *
from .model import Model
from . import checkpoint
from . import convert
from . import data
from . import decode
from . import dsp
from . import evaluate
from . import load
from . import partition
from . import periodicity
from . import plot
from . import train
from . import write