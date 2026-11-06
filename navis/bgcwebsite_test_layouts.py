"""Small-multiples layout branch for testing BGC engineering plots.

This launcher keeps the normal bgcwebsite_test.py file unchanged for regular
runs while enabling the alternate layout for across-float plots.
"""

import os
import runpy
from pathlib import Path


os.environ['BGC_PLOT_LAYOUT_MODE'] = 'small_multiples'
os.environ['BGC_PLOTS_ONLY'] = 'true'
runpy.run_path(
    str(Path(__file__).with_name('bgcwebsite_test.py')),
    run_name='__main__',
)
