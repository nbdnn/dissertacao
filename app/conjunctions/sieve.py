from datetime import datetime, timezone
import logging
import sys
import os
from typing import TYPE_CHECKING
from .filter_pre import filterPre
from .bisection import bisectionMethod
from .conjunction_analysis import conjunctionAnalysis
from ..download_all_tles import requestTles
from .config import ELLIPSOID_BOUNDS
from .stk_parser import parse_stk_ephemeris

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Helper Functions for Ephemerides within Sieve ---


def load_ephemeris_states(norad_id, ephemerides_path, start, end, step, frame):
    """Loads ephemeris states for a given ID from file, returning as list."""
    # Construct filename pattern: SP_{id}_extended.e
    filename = f"SP_{norad_id}_extended.e"
    filepath = os.path.join(ephemerides_path, filename)

    if not os.path.exists(filepath):
        logger.warning(f"Ephemeris file not found for {norad_id}: {filepath}")
        return None

    try:
        data_map = parse_stk_ephemeris(filepath)
        # Handle cases where dict key might be string or int
        data = data_map.get(norad_id) or data_map.get(str(norad_id))

        # Fallback: if dict has only one key, assume it is the right one
        if data is None and len(data_map) == 1:
            data = list(data_map.values())[0]

        if data is None:
            logger.error(f"Could not find data for {norad_id} in {filepath}")
            return None

        # Return Raw Data for flexible interpolation
        return data

    except Exception as e:
        logger.error(f"Error loading ephemeris for {norad_id}: {e}")
        return None

def interpolate_ephemeris_at_dates(ephemeris_data, target_dates):
    """
    Interpolates ephemeris data (list of (date, pos, vel, cov)) at specified target_dates.
    Returns: list of (date, pos_arr, vel_arr, None)
    """
    if not ephemeris_data:
        return []

    from org.orekit.utils import TimeStampedPVCoordinates, CartesianDerivativesFilter, TimeStampedPVCoordinatesHermiteInterpolator
    from org.hipparchus.geometry.euclidean.threed import Vector3D
    import numpy as np
    # Convert entire dataset to TimeStampedPVCoordinates once (or lazy)
    # Optimization: conversion is cheap compared to search.
    
    samples = []
    for pt in ephemeris_data:
        d, p, v = pt[0], pt[1], pt[2]
        pos_vec = Vector3D(float(p[0]), float(p[1]), float(p[2]))
        vel_vec = Vector3D(float(v[0]), float(v[1]), float(v[2]))
        samples.append(TimeStampedPVCoordinates(d, pos_vec, vel_vec))

    results = []
    
    # Use Orekit's static interpolate method which handles search internally?
    # No, we usually pass neighbor samples. 
    # But TimeStampedPVCoordinates.interpolate(date, filter, Collection<TimeStampedPVCoordinates>) exists.
    # It might be slow if Collection is huge (linear scan).
    # Since target_dates are sorted and samples are sorted, we can optimize.
    
    n = len(samples)
    idx = 0
    
    # Create interpolator for standard case (2 points)
    standard_interpolator = TimeStampedPVCoordinatesHermiteInterpolator(2, CartesianDerivativesFilter.USE_PV)
    
    for date in target_dates:
        # Move idx to be close to date
        while idx < n - 1 and samples[idx+1].getDate().compareTo(date) < 0:
            idx += 1
            
        # Select window (e.g., 2 points before, 2 after -> 4 points cubic)
        # Use 4 neighbors for higher accuracy if possible
        
        # Taking 2 points before and 2 points after the interval [idx, idx+1]
        start = max(0, idx - 1)
        end = min(n, start + 4) # Try to get 4 points starting from 'start'
        
        # Adjust start back if we hit the end bound early to try and get 4 points
        if end == n:
            start = max(0, end - 4)

        subset = samples[start:end]
        
        if not subset:
            logger.warning(f"No samples for date {date}")
            continue

        # Use TimeStampedPVCoordinatesHermiteInterpolator for Orekit 12+
        # It requires the number of interpolation points (len(subset)) and the filter
        if len(subset) == 2:
            pv = standard_interpolator.interpolate(
                date,
                subset
            )
        else:
            interpolator = TimeStampedPVCoordinatesHermiteInterpolator(len(subset), CartesianDerivativesFilter.USE_PV)
            pv = interpolator.interpolate(
                date,
                subset
            )
        
        p = pv.getPosition()
        v = pv.getVelocity()
        results.append((
            date,
            np.array([p.getX(), p.getY(), p.getZ()]),
            np.array([v.getX(), v.getY(), v.getZ()]),
            None
        ))

    return results

# ---------------------------------------------------


# # Helper temporário para adaptar a chamada de requestTle
# def requestTle(ids):
#     # Baixa TUDO (ineficiente mas mapeia para o que temos)
#     # Na verdade, o codigo original talvez filtrasse no servidor.
#     # Vamos usar requestTles e filtrar em memória.
#     all_tles = requestTles()
#     primaries = []
#     secondaries = []

#     # Converte para o formato de dicionário esperado pelo código do usuário
#     # O código espera chaves: NORAD_CAT_ID, OBJECT_NAME, TLE_LINE1,
#     # TLE_LINE2, APOAPSIS, PERIAPSIS, OBJECT_TYPE
#     # Nossos models têm isso? requestTles retorna dicts com chaves parecidas.

#     # O TLEData não é usado aqui, o código usa dicts crus.

#     for item in all_tles:
#         # Verifica se é um dos primários
#         norad = int(item['NORAD_CAT_ID'])
#         if norad in ids:
#             primaries.append(item)
#         else:
#             secondaries.append(item)

#     return primaries, secondaries


def sieveAlgorithm(
        primariesID: list,
        daysOfSimulation: int,
        threshold: float,
        ellipsoid_bounds=ELLIPSOID_BOUNDS,
        verbose=False,
        verboseConjAnalysis=False,
        start_date=None,
        tles=None,
        screening_mode=False,
        ephemerides=None,
        secondariesID: list = None):

    # type: ignore[reportMissingImports]
    from org.orekit.time import AbsoluteDate, TimeScalesFactory  # type: ignore  # noqa: F811
    # type: ignore[reportMissingImports]
    from org.orekit.frames import FramesFactory  # type: ignore
    # type: ignore[reportMissingImports]
    from org.orekit.propagation.analytical.tle import TLE, TLEPropagator  # type: ignore
    import numpy as np

    conjunctions = []

    # Step size for filterPre
    h_step = 180.0

    if start_date:
        creationDate = start_date
    else:
        creationDate = datetime.now(timezone.utc)

    if verbose:
        print(
            f"Current Date Time: {creationDate.year}-{creationDate.month}-{creationDate.day} "
            f"{creationDate.hour}:{creationDate.minute}:"
            f"{creationDate.second + creationDate.microsecond / 1e6}"
        )

    initialTime = AbsoluteDate(
        creationDate.year,
        creationDate.month,
        creationDate.day,
        creationDate.hour,
        creationDate.minute,
        creationDate.second + creationDate.microsecond / 1e6,
        TimeScalesFactory.getUTC()
    )
    endTime = initialTime.shiftedBy(daysOfSimulation * 24 * 3600.)

    inertialFrame = FramesFactory.getEME2000()

    def propagate_states(tle_dict, start, end, step):
        """Propagate TLE over interval with fixed step, returning list of (date, pos, vel, cov)."""
        propagator = TLEPropagator.selectExtrapolator(
            TLE(tle_dict["TLE_LINE1"], tle_dict["TLE_LINE2"])
        )
        results = []
        curr = start
        while curr.compareTo(end) <= 0:
            pv = propagator.getPVCoordinates(curr, inertialFrame)
            p = pv.getPosition()
            v = pv.getVelocity()
            p_arr = np.array((p.getX(), p.getY(), p.getZ()))
            v_arr = np.array((v.getX(), v.getY(), v.getZ()))
            # For TLE propagation, covariance is not computed, so None
            results.append((curr, p_arr, v_arr, None))
            curr = curr.shiftedBy(step)
        return results

    # Determine execution mode: TLE or Ephemerides File
    use_ephemeris_files = False
    if isinstance(ephemerides, str):
        # 'ephemerides' argument is interpreted as the path to the data folder
        use_ephemeris_files = True
        ephemerides_path = ephemerides
        # Reset ephemerides dict so we don't try to reuse it as a dict below
        # We will load on demand
        ephemerides_dict = None 
    else:
        ephemerides_dict = ephemerides # assume it is a dict or None
        
    if tles:
        primaries, secondaries = tles
    elif use_ephemeris_files and secondariesID is not None:
         # Construct mock dictionaries for IDs
         primaries = [{"NORAD_CAT_ID": pid, "OBJECT_NAME": str(pid)} for pid in primariesID]
         secondaries = [{"NORAD_CAT_ID": sid, "OBJECT_NAME": str(sid)} for sid in secondariesID]
         if verbose:
             print(f"Running in Ephemeris File Mode. Path: {ephemerides_path}")
    else:
        primaries, secondaries = requestTle(primariesID)

    for primary in primaries:

        if verbose:
            print(f'Primary ID: {primary.get("NORAD_CAT_ID", "?")}')

        # Determine states source for Primary
        primary_id = int(primary['NORAD_CAT_ID'])
        use_ephem_primary = False
        primary_data_raw = None # For Ephemeris mode
        
        if ephemerides_dict and primary_id in ephemerides_dict:
            # Pre-loaded dict mode - assumes raw or processed?
            # Assuming raw if we want to enforce standard H
            primary_data_raw = ephemerides_dict[primary_id]
            use_ephem_primary = True
        elif use_ephemeris_files:
            # File loading mode
            primary_data_raw = load_ephemeris_states(primary_id, ephemerides_path, initialTime, endTime, h_step, inertialFrame)
            if primary_data_raw:
                use_ephem_primary = True
            else:
                if verbose: print(f"Skipping primary {primary_id} (No ephemeris)")
                continue
        
        # Generate grid for filterPre (Primary & Secondary must align)
        # We enforce h_step (180s) as requested
        
        simulation_dates = []
        curr = initialTime
        while curr.compareTo(endTime) <= 0:
            simulation_dates.append(curr)
            curr = curr.shiftedBy(float(h_step))
            
        if use_ephem_primary:
            # Interpolate primary to standard grid
            primary_states = interpolate_ephemeris_at_dates(primary_data_raw, simulation_dates)
        else:
            # Propagate TLE to standard grid
            primary_states = propagate_states(primary, initialTime, endTime, h_step)
            use_ephem_primary = False 



        # We also need apoapsis/periapsis for the high-level filter check
        # Assuming they are correct in the dict. If strictly following "filterPre" logic
        # we check altitude relative to each secondary.

        should_check_altitude = ephemerides is None
        if should_check_altitude:
            priApoapsis = float(primary["APOAPSIS"])
            priPeriapsis = float(primary["PERIAPSIS"])

        total_secondaries = len(secondaries)
        for idx, secondary in enumerate(secondaries):
            # Update progress check to every 1 item to show life, as processing is slow
            percent = 100.0 * idx / total_secondaries
            print(
                f"\rProgress: {percent:.2f}% ",
                f"({idx}/{total_secondaries}) ",
                f"- Checking ID {secondary.get('NORAD_CAT_ID', 'Unknown')}...", end="", flush=True)

            if secondary.get("NORAD_CAT_ID") != primary.get("NORAD_CAT_ID"):

                if should_check_altitude:
                    # OPTIMIZATION: Check altitude overlap BEFORE propagation
                    # This logic mimics filterPre's initial check
                    secPeriapsis = float(secondary["PERIAPSIS"])
                    secApoapsis = float(secondary["APOAPSIS"])

                    # Check for oldTLE flag (defaults to False here) but filterPre takes it.
                    altitude_overlap = (secPeriapsis < priApoapsis and priPeriapsis < secApoapsis)
                    if not (altitude_overlap and secPeriapsis > 250):
                        # Skip propagation
                        continue

                if verbose:
                    print(
                        f'\nSecondary ID: {secondary.get("NORAD_CAT_ID", "?")}'
                    )
                    if "TLE_LINE1" in secondary:
                        print(f"TLE\n{secondary['TLE_LINE1']}\n{secondary['TLE_LINE2']}")

                if verbose:
                    print(f'Ecentricidade: {secondary["ECCENTRICITY"]}')
                    print(f'Apogeu: {secondary["APOAPSIS"]}, Perigeo: {secondary["PERIAPSIS"]}')

                # Determine states source for Secondary
                secondary_id = int(secondary['NORAD_CAT_ID'])
                use_ephem_secondary = False
                secondary_data_raw = None
                
                if ephemerides_dict and secondary_id in ephemerides_dict:
                    secondary_data_raw = ephemerides_dict[secondary_id]
                    use_ephem_secondary = True
                elif use_ephemeris_files:
                    secondary_data_raw = load_ephemeris_states(secondary_id, ephemerides_path, initialTime, endTime, h_step, inertialFrame)
                    if secondary_data_raw:
                        use_ephem_secondary = True
                    else:
                        if verbose: print(f" Skipping secondary {secondary_id} (No ephemeris)")
                        continue
                
                if use_ephem_secondary:
                    # Interpolate secondary to standard grid
                    secondary_states = interpolate_ephemeris_at_dates(secondary_data_raw, simulation_dates)
                else:
                    # Propagate Secondary
                    secondary_states = propagate_states(secondary, initialTime, endTime, h_step)
                    use_ephem_secondary = False

                # filterPre returns times and list of (primary_state, secondary_state) tuples
                
                # Now we are guaranteed that primary_states and secondary_states are on the grid defined by h_step
                t, states_pairs = filterPre(
                    primary_states,
                    secondary_states,
                    primary=primary,
                    secondary=secondary,
                    rc=threshold,
                    h=h_step,
                    verbose=verbose
                )

                tcas = []

                for i in range(len(t)):

                    times, distances, bisection_states = bisectionMethod(
                        initialTime.shiftedBy(t[i]),
                        primary=primary,
                        secondary=secondary,
                        primary_states=primary_data_raw if use_ephem_primary else None,
                        secondary_states=secondary_data_raw if use_ephem_secondary else None,
                        h=1.
                    )
                    if not t:
                        pass # Sieve found nothing
                        # print(
                        #    f'\nSecondary: {secondary["OBJECT_NAME"]}    '
                        #    f'NORAD:{secondary["NORAD_CAT_ID"]}'
                        # )


                    if distances[-1] < distances[-2]:
                        tca, missDistance = times[-1], distances[-1]
                    else:
                        tca, missDistance = times[-2], distances[-2]

                    if missDistance < threshold:
                        tcas.append(t[i])

                        if len(tcas) == 1 or abs(tcas[-1] - tcas[-2]) > 10 * 60:
                            # Pick the correct state tuple from bisection output
                            # bisection_states matches 'times' and 'missDistance'
                            # If we picked index -1 (last), we use index -1 of states.

                            p_state_res, s_state_res = None, None

                            # Re-eval logic to match TCA choice
                            tca_time_shifted = initialTime.shiftedBy(t[i] + tca)

                            if distances[-1] < distances[-2]:
                                # Use last point
                                p_state_res, s_state_res = bisection_states[-1]
                            else:
                                # Use second to last
                                p_state_res, s_state_res = bisection_states[-2]

                            # Get full state vector for ephemeris mode to avoid TLE fallback crash
                            if use_ephem_primary and primary_data_raw:
                                p_state_res = interpolate_ephemeris_at_dates(primary_data_raw, [tca_time_shifted])[0]

                            if use_ephem_secondary and secondary_data_raw:
                                s_state_res = interpolate_ephemeris_at_dates(secondary_data_raw, [tca_time_shifted])[0]

                            result = conjunctionAnalysis(
                                primary=primary,
                                secondary=secondary,
                                tcaTime=tca_time_shifted,
                                verbose=verboseConjAnalysis,
                                ellipsoid_bounds=ellipsoid_bounds,
                                primary_state_vector=p_state_res,
                                secondary_state_vector=s_state_res
                            )
                            if result['is_violated']:
                                if screening_mode:
                                    conjunctions.append({
                                        "secondary_name": result["secondary_name"],
                                        "secondary_id": result["secondary_id"],
                                        "tca": result["tca_utc"],
                                        "kc2": result["kc_squared"],
                                        "is_violated": result["is_violated"]
                                    })
                                else:
                                    conjunctions.append(result)
        print()
    return conjunctions
