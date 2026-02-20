# Orekit dependencies will be imported inside functions to ensure JVM is active

def get_propagator(start_date, start_pv, mass=1000.0, area=1.0, cd=2.2, cr=1.2):

    # Delayed Imports
    from org.orekit.orbits import CartesianOrbit, OrbitType  # type: ignore
    from org.orekit.utils import Constants, IERSConventions  # type: ignore
    from org.orekit.frames import FramesFactory  # type: ignore
    from org.orekit.propagation.numerical import NumericalPropagator  # type: ignore
    from org.orekit.propagation import SpacecraftState  # type: ignore
    from org.orekit.forces.gravity.potential import GravityFieldFactory  # type: ignore
    from org.orekit.forces.gravity import (  # type: ignore
        HolmesFeatherstoneAttractionModel, ThirdBodyAttraction
    )
    from org.orekit.forces.drag import DragForce, IsotropicDrag  # type: ignore
    from org.orekit.forces.radiation import (  # type: ignore
        SolarRadiationPressure, IsotropicRadiationSingleCoefficient
    )
    from org.orekit.models.earth.atmosphere.data import (  # type: ignore
        MarshallSolarActivityFutureEstimation
    )
    from org.orekit.bodies import CelestialBodyFactory, OneAxisEllipsoid  # type: ignore
    from org.hipparchus.ode.nonstiff import DormandPrince853Integrator  # type: ignore
    from org.orekit.models.earth.atmosphere import DTM2000  # type: ignore

    # 1. Frames & Orbit
    inertial_frame = FramesFactory.getEME2000()
    ecef = FramesFactory.getITRF(IERSConventions.IERS_2010, True)

    mu = Constants.WGS84_EARTH_MU
    orbit = CartesianOrbit(start_pv, inertial_frame, start_date, mu)

    # 2. Integrator
    min_step = 0.001
    max_step = 300.0
    position_tolerance = 10.0
    integrator = DormandPrince853Integrator(
        min_step, max_step, position_tolerance, position_tolerance
    )

    propagator = NumericalPropagator(integrator)
    propagator.setOrbitType(OrbitType.CARTESIAN)  # Propagate Cartesian

    init_state = SpacecraftState(orbit, mass)
    propagator.setInitialState(init_state)

    # 3. Forces

    # GeoPotential (Gravity)
    # Using 10x10 for speed/accuracy trade-off
    provider = GravityFieldFactory.getNormalizedProvider(20, 20)
    gravity = HolmesFeatherstoneAttractionModel(ecef, provider)
    propagator.addForceModel(gravity)

    # Moon Interation (Third Body)
    moon = CelestialBodyFactory.getMoon()
    moon_3rd = ThirdBodyAttraction(moon)
    propagator.addForceModel(moon_3rd)

    # Sun Interaction (Third Body)
    sun = CelestialBodyFactory.getSun()
    sun_3rd = ThirdBodyAttraction(sun)
    propagator.addForceModel(sun_3rd)

    # Solar Radiation Pressure
    earth_radius = Constants.WGS84_EARTH_EQUATORIAL_RADIUS
    earth_shape = OneAxisEllipsoid(earth_radius, Constants.WGS84_EARTH_FLATTENING, ecef)

    srp_shape = IsotropicRadiationSingleCoefficient(area, cr)
    # Correct constructor for modern Orekit: (sun, earth, spacecraft)
    srp_force = SolarRadiationPressure(sun, earth_shape, srp_shape)
    propagator.addForceModel(srp_force)

    # Atmospheric Drag

    msafe = MarshallSolarActivityFutureEstimation(
        MarshallSolarActivityFutureEstimation.DEFAULT_SUPPORTED_NAMES,
        MarshallSolarActivityFutureEstimation.StrengthLevel.AVERAGE
    )

    atmosphere = DTM2000(msafe, sun, earth_shape)
    drag_shape = IsotropicDrag(area, cd)
    drag_force = DragForce(atmosphere, drag_shape)
    propagator.addForceModel(drag_force)

    return propagator


def write_extended_ephemeris(original_file, new_file, extra_states, ref_epoch_str):
    """
    Reads the header from original file, writes it to new file,
    writes original data points, then appends extra_states.
    """

    with open(original_file, 'r') as f:
        lines = f.readlines()

    header_lines = []
    eph_lines = []
    cov_lines = []

    mode = "header"

    for line in lines:
        s = line.strip()
        if s == "EphemerisTimePosVel":
            mode = "eph"
            continue
        if s == "CovarianceTimePosVel":
            mode = "cov"
            continue
        if s == "End Ephemeris":
            continue

        if mode == "header":
            header_lines.append(line)
        elif mode == "eph":
            if s:
                eph_lines.append(line)
        elif mode == "cov":
            if s:
                cov_lines.append(line)

    # Write everything
    with open(new_file, 'w') as out:
        out.writelines(header_lines)
        out.write("EphemerisTimePosVel\n")

        for eph_line in eph_lines:
            out.write(eph_line)

        # Append Ephemeris
        for s in extra_states:
            t = s[0]
            # meters -> km
            line_out = (
                f" {t:.9e} {s[1] / 1000:.9e} {s[2] / 1000:.9e} "
                f"{s[3] / 1000:.9e} {s[4] / 1000:.9e} {s[5] / 1000:.9e} "
                f"{s[6] / 1000:.9e}\n"
            )
            out.write(line_out)

        # Covariance
        if cov_lines:
            out.write("\nCovarianceTimePosVel\n")
            for cov_line in cov_lines:
                out.write(cov_line)

            if cov_lines:
                last_line = cov_lines[-1]
                parts = last_line.split()

                for s in extra_states:
                    t = s[0]
                    suffix = " ".join(parts[1:])
                    out.write(f" {t:.9e} {suffix}\n")

        out.write("End Ephemeris\n")


def extend_ephemeris_file(input_path, output_path, target_date_utc, mass=1000.0, area=2.0):

    # 1. Parse Last State
    from cenario2.parse_ephemerides import parse_stk_ephemeris, parse_stk_date
    from org.orekit.time import AbsoluteDate, TimeScalesFactory  # type: ignore
    from org.orekit.utils import PVCoordinates  # type: ignore
    from org.orekit.frames import FramesFactory  # type: ignore
    from org.hipparchus.geometry.euclidean.threed import Vector3D  # type: ignore
    import os
    import logging

    # Configure Logger
    logger = logging.getLogger("EphemerisExtension")
    if not logger.handlers:
        logger.setLevel(logging.INFO)

        # Console Handler
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%H:%M:%S'
        )
        ch.setFormatter(formatter)
        logger.addHandler(ch)

        fh = logging.FileHandler(os.path.join(os.path.dirname(__file__), 'extension_errors.log'))
        fh.setLevel(logging.ERROR)
        fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(fh)

    logger.propagate = False  # Prevent double logging if root logger is configured

    file_name = os.path.basename(input_path)
    # logger.info(f"Processing object: {file_name}")

    if os.path.exists(output_path):
        try:
            data_map_out = parse_stk_ephemeris(output_path)

            if not data_map_out:
                msg = (
                    f"Existing file {os.path.basename(output_path)} "
                    "is empty or invalid. Recreating."
                )
                logger.warning(f"\n\033[93m{msg}\033[0m")
            else:
                obj_id_out = list(data_map_out.keys())[0]
                states_out = data_map_out[obj_id_out]
                last_state_out = states_out[-1]
                last_date_out = last_state_out[0]

                if last_date_out.durationFrom(target_date_utc) >= -1.0:
                    msg = (
                        f"Extended file {os.path.basename(output_path)} "
                        "already exists and covers target date. Skipping."
                    )
                    # Green highlight
                    # logger.info(f"\033[92m{msg}\033[0m")
                    return
                else:
                    msg = (
                        f"Extended file exists but is too short "
                        f"(Ends: {last_date_out.toString()}). Recreating."
                    )
                    logger.info(f"\033[92m{msg}\033[0m")
        except Exception as e:
            logger.error(f"\nError checking existing extended file: {e}. Recreating.")

    data_map = parse_stk_ephemeris(input_path)
    # Get the only ID (assuming single object file)
    obj_id = list(data_map.keys())[0]
    states = data_map[obj_id]

    last_state = states[-1]
    last_date = last_state[0]  # AbsoluteDate
    last_pos = last_state[1]   # meters
    last_vel = last_state[2]   # m/s

    # Check if propagation is needed
    if last_date.compareTo(target_date_utc) >= 0:
        logger.info("\033[92mTarget date already covered. Copying file.\033[0m")
        import shutil
        shutil.copy(input_path, output_path)
        return

    # Safety Check: Do not extend files that are too old
    duration_gap = target_date_utc.durationFrom(last_date)
    if duration_gap > 10 * 86400:  # 10 days
        gap_days = duration_gap / 86400
        msg = (
            f"Skipping extension: File {file_name} is too old. "
            f"Ends at {last_date.toString()}, gap of {gap_days:.1f} days."
        )

        # Red highlight for console
        logger.error(f"\033[91m{msg}\033[0m")
        return

    if duration_gap > 2 * 86400:  # Warning for gaps > 2 days
        gap_days = duration_gap / 86400
        msg = (
            f"File {file_name} has a large gap of {gap_days:.1f} days. "
            f"Propagation may take longer and be less accurate."
        )
        logger.warning(f"\033[93m{msg}\033[0m")

    logger.info(
        f"\033[92mPropagating {file_name} from {last_date.toString()} "
        f"to {target_date_utc.toString()} (Gap: {duration_gap / 86400:.1f} days)\033[0m"
    )

    # 2. Setup Propagator
    start_pv = PVCoordinates(
        Vector3D(float(last_pos[0]), float(last_pos[1]), float(last_pos[2])),
        Vector3D(float(last_vel[0]), float(last_vel[1]), float(last_vel[2]))
    )

    propagator = get_propagator(last_date, start_pv, mass, area)

    # 3. Propagate step-by-step
    current_date = last_date
    final_date = target_date_utc.shiftedBy(300.0)  # +5 min buffer
    step = 60.0  # 60 seconds step

    extra_states = []

    # Let's extract ScenarioEpoch from file again roughly
    scenario_epoch = None
    with open(input_path, 'r') as f:
        for line in f:
            if "ScenarioEpoch" in line:
                # ScenarioEpoch 1 Feb 2026 10:04:42.866
                parts = line.strip().split(maxsplit=1)
                if len(parts) > 1:
                    dt = parse_stk_date(parts[1])
                    utc = TimeScalesFactory.getUTC()
                    scenario_epoch = AbsoluteDate(
                        dt.year, dt.month, dt.day, dt.hour, dt.minute,
                        dt.second + dt.microsecond / 1e6, utc
                    )
                break

    if not scenario_epoch:
        # Fallback: Assume first data point is t=0 or close
        scenario_epoch = states[0][0]

    while current_date.compareTo(final_date) < 0:
        current_date = current_date.shiftedBy(step)
        pv = propagator.getPVCoordinates(current_date, FramesFactory.getEME2000())

        pos = pv.getPosition()
        vel = pv.getVelocity()

        rel_time = current_date.durationFrom(scenario_epoch)

        extra_states.append(
            (rel_time, pos.getX(), pos.getY(), pos.getZ(), vel.getX(), vel.getY(), vel.getZ())
        )

        # Log progress every 60 steps (approx 1 hour of simulation data)
        if len(extra_states) % 60 == 0:
            print(f"Propagating... Current Date: {current_date.toString()}", end="\r", flush=True)
    logger.info(f"Propagation complete. Final Date: {current_date.toString()}\n")

    # 4. Write
    write_extended_ephemeris(input_path, output_path, extra_states, None)
    logger.info(f"Extended ephemeris written to {output_path}\n")
