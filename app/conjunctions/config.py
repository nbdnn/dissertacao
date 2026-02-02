# Configuration for Conjunction Analysis and Screening

# Safety Ellipsoid Semiaxes (R_U, R_V, R_W) in meters
# Radial, In-Track, Cross-Track
ELLIPSOID_BOUNDS = (2000.0, 5000.0, 2000.0)

# Multiplier for the screening sieve (coarse filter)
# The screening ellipsoid will be SCREENING_MULTIPLIER * ELLIPSOID_BOUNDS
SCREENING_MULTIPLIER = 10.0
