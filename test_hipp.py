import os
import sys

project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app.orekit_config import setup_orekit
setup_orekit()

from org.hipparchus.analysis.interpolation import HermiteInterpolator
import numpy as np

interpolator = HermiteInterpolator()
# dt, pos, vel
interpolator.addSamplePoint(0.0, [1.0, 2.0, 3.0], [0.1, 0.2, 0.3])
interpolator.addSamplePoint(10.0, [2.0, 4.0, 6.0], [0.1, 0.2, 0.3])

derivs = interpolator.derivatives(5.0, 1)

print("Type of derivs:", type(derivs))
for i, d in enumerate(derivs):
    print(f"deriv[{i}]:", type(d), [float(x) for x in d])
