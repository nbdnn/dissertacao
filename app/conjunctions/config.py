# Configuration for Conjunction Analysis and Screening

# Safety Ellipsoid Semiaxes (R_U, R_V, R_W) in meters
# Radial, In-Track, Cross-Track
ELLIPSOID_BOUNDS = (2000.0, 5000.0, 2000.0)

# Safer bounds strictly used by PyMoo GA during Virtual TLE verification
GA_ELLIPSOID_BOUNDS = (20000.0, 50000.0, 20000.0)

# Multiplier for the screening sieve (coarse filter)
# The screening ellipsoid will be SCREENING_MULTIPLIER * ELLIPSOID_BOUNDS
SCREENING_MULTIPLIER = 50.0

# Large Screening Bounds for Ephemeris Pipeline (TLE Initial Pass)
# 100 * 5000 meters for each semi-axis = 500km
LARGE_SCREENING_BOUNDS = (100000.0, 250000.0, 100000.0)

rc = 20.0  # Characteristic collision radius in meters (for probability calculations)

# Probability of Collision Theshold
POC_THRESHOLD = 1e-5
