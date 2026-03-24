import numpy as np  # type: ignore
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from org.orekit.time import AbsoluteDate  # type: ignore


def bisectionMethod(
        initialTime: 'AbsoluteDate',
        primary,
        secondary,
        primary_states=None,
        secondary_states=None,
        h=10. * 60,
        criteria=1.
):
    """
    h in seconds
    criteria in meters/sec, used as convergence for dr/dt approaching zero (minima).

    If primary_states and secondary_states are provided (list of (date, pos, vel, cov)),
    this function will interpolate PV coordinates instead of using TLE propagation.
    """
    # type: ignore[reportMissingImports]
    from org.orekit.frames import FramesFactory  # type: ignore
    # type: ignore[reportMissingImports]
    from org.orekit.propagation.analytical.tle import TLE, TLEPropagator  # type: ignore
    from org.hipparchus.analysis.interpolation import HermiteInterpolator  # type: ignore

    propagPrimary = None
    propagSecondary = None

    # Pre-check if we use interpolation or TLE
    use_interpolation = (primary_states is not None) and (secondary_states is not None)

    if not use_interpolation:
        propagPrimary = TLEPropagator.selectExtrapolator(
            TLE(primary["TLE_LINE1"], primary["TLE_LINE2"])
        )
        propagSecondary = TLEPropagator.selectExtrapolator(
            TLE(secondary["TLE_LINE1"], secondary["TLE_LINE2"])
        )

    missDistance = []
    time = []
    state_vectors = []  # List of (primary_pv, secondary_pv) tuples

    inertialFrame = FramesFactory.getEME2000()

    simulationTime = initialTime

    count = 0

    # Helper for interpolation
    def get_pv_at_date(target_date, states_list):
        # States list assumed sorted by date.
        # Find index i such that states_list[i].date <= target_date < states_list[i+1].date
        # We use bisect. Note states_list items are tuples, we need to compare dates.
        # Python's bisect doesn't support key until 3.10.
        # We'll use a simple linear search around a cached index or just search since h is small?
        # Given bisection jumps around, binary search is safer.

        # Extract dates for bisecting
        # dates = [s[0] for s in states_list]
        # We need a custom comparison because Java objects.
        # Let's rely on compareTo.
        # Optimization: since we are close to 'initialTime', find the index once?
        # Actually simplest robust way for now:

        # Find index where date > target_date
        # Since states list is potentially large, we should be efficient.
        # But for now, let's just loop or assume we can find neighbors.

        # Let's find neighbors [t0, t1, t2, t3] around target for Hermite.
        # target_date is an AbsoluteDate.

        # Simple scan?
        # closest_idx = 0
        # min_dt = float('inf')

        # Optimization: assume list is sorted.
        # Binary search for the insertion point
        low = 0
        high = len(states_list) - 1

        idx = -1

        # Doing manual binary search because we compare AbsoluteDate
        while low <= high:
            mid = (low + high) // 2
            mid_date = states_list[mid][0]
            diff = mid_date.durationFrom(target_date)
            if diff < 0:  # mid < target
                low = mid + 1
            elif diff > 0:  # mid > target
                high = mid - 1
            else:
                idx = mid
                break

        if idx == -1:
            idx = high  # close enough to start looking around

        # Ensure we are within bounds
        idx = max(0, min(idx, len(states_list) - 1))

        # Select n points for interpolation (e.g., 2 before, 2 after if possible)
        # Using 2 points (cubic Hermite with pos & vel) is usually sufficient for short intervals.
        # Let's pick the interval [t_i, t_{i+1}] containing target_date.

        if states_list[idx][0].durationFrom(target_date) > 0 and idx > 0:
            idx -= 1

        # Now states_list[idx] <= target_date <= states_list[idx+1]
        # Collect samples for interpolator
        interpolator = HermiteInterpolator()

        # Use 4 points for better accuracy if available: idx-1, idx, idx+1, idx+2
        start_k = max(0, idx - 1)
        end_k = min(len(states_list), idx + 3)

        for k in range(start_k, end_k):
            s_date, s_pos, s_vel, _ = states_list[k]
            # Convert to PVCoordinates
            # interpolator.addSamplePoint(date_double, value_double_array, deriv_double_array)
            # HermiteInterpolator works with raw doubles.
            # We map date relative to target_date in seconds
            dt = s_date.durationFrom(target_date)
            interpolator.addSamplePoint(dt, s_pos, s_vel)

        # Interpolate at dt=0 (target_date)
        # We need value ONLY (Position). No Derivative (Velocity).

        interp_res = interpolator.value(0.0)

        pos_x = interp_res[0]
        pos_y = interp_res[1]
        pos_z = interp_res[2]

        return np.array([pos_x, pos_y, pos_z])

    def get_pos(propagator, date, states=None):
        if use_interpolation and states:
            return get_pv_at_date(date, states)
        else:
            pv = propagator.getPVCoordinates(date, inertialFrame)
            pos = pv.getPosition()
            return np.array([pos.getX(), pos.getY(), pos.getZ()])

    while True:

        posPrimArr = get_pos(propagPrimary, simulationTime, primary_states)
        posSecArr = get_pos(propagSecondary, simulationTime, secondary_states)

        missDistanceValue = np.linalg.norm(posPrimArr - posSecArr)

        # Capture state for return (Position only)
        p_state = (simulationTime, posPrimArr)
        s_state = (simulationTime, posSecArr)

        if missDistance:
            if missDistanceValue > missDistance[-1]:
                missDistance.append(missDistanceValue)
                time.append(time[-1] + h)
                state_vectors.append((p_state, s_state))

                if (np.abs(h) == 1e-6):
                    pass
                elif np.abs(h) / 2 < 1e-6:
                    h = -1.e-6 * np.sign(h)
                else:
                    h = -h / 2.
                simulationTime = simulationTime.shiftedBy(float(h))
            else:
                nextPointTime = simulationTime.shiftedBy(float(h))

                posP_next = get_pos(propagPrimary, nextPointTime, primary_states)
                posS_next = get_pos(propagSecondary, nextPointTime, secondary_states)

                nextMissDistance = np.linalg.norm(posP_next - posS_next)

                if (nextMissDistance < missDistanceValue):
                    missDistance.append(missDistanceValue)
                    missDistance.append(nextMissDistance)

                    time.append(time[-1] + h)
                    time.append(time[-1] + h)

                    state_vectors.append((p_state, s_state))

                    # For the next point
                    p_next = (nextPointTime, posP_next)
                    s_next = (nextPointTime, posS_next)
                    state_vectors.append((p_next, s_next))

                    simulationTime = simulationTime.shiftedBy(2 * float(h))
                else:
                    missDistance.append(missDistanceValue)
                    time.append(time[-1] + h)
                    state_vectors.append((p_state, s_state))

                    if (np.abs(h) == 1e-6):
                        pass
                    elif np.abs(h) / 2 < 1e-6:
                        h = 1.e-6 * np.sign(h)
                    else:
                        h = h / 2.

                    simulationTime = simulationTime.shiftedBy(float(h))

            if abs((missDistance[-1] - missDistance[-2]) / h) < criteria:
                return time, missDistance, state_vectors

        else:
            missDistance.append(missDistanceValue)
            state_vectors.append((p_state, s_state))
            simulationTime = simulationTime.shiftedBy(float(h))
            time.append(count * h)

        count += 1
        if (count > 1e5):
            print("Exceed 1e5 interations")
            time = []
            missDistance = []
            return time, missDistance, state_vectors
