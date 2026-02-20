import numpy as np


def filterPre(
        primary_states,
        secondary_states,
        primary,
        secondary,
        h=180.,
        rc=20.e3,
        verbose=False
):
    # type: ignore[reportMissingImports]
    from org.orekit.utils import Constants  # type: ignore

    muEarth = Constants.IERS2010_EARTH_MU

    count = 0
    state_vectors = []
    times = []

    # Iterate over pre-calculated states
    for p_state, s_state in zip(primary_states, secondary_states):
        simulationTime, posPrimArr, velPrimArr = p_state[0], p_state[1], p_state[2]
        _, posSecArr, velSecArr = s_state[0], s_state[1], s_state[2]
        # Ensure times match (optional sanity check, skipping for performance)

        if verbose:
            print(f"\nSimulation time: {simulationTime}")

        r = np.linalg.norm(posPrimArr)

        ve = np.sqrt(2 * muEarth / r)
        rc1 = rc + ve * h

        deltaR = posSecArr - posPrimArr
        rho = np.linalg.norm(deltaR)

        deltaV = velSecArr - velPrimArr

        if (deltaR[0] > rc1 or deltaR[1] > rc1 or deltaR[2] > rc1 or rho > rc1):
            if verbose:
                print(f"{simulationTime} Nao calculado: RC1\nRC1: {rc1}\trho: {rho}")
                print(f"deltaR: {deltaR}")

            # We must adhere to the original logic: if skipped, we advance time.
            count += 1
            continue

        if (np.linalg.norm(deltaV) == 0 and rho < 50.e3):
            print(f'\nPrimary: {primary["OBJECT_NAME"]}    NORAD:{primary["NORAD_CAT_ID"]}')
            print(f'\nSecondary: {secondary["OBJECT_NAME"]}    NORAD:{secondary["NORAD_CAT_ID"]}')
            print('Rendezvous/Docking detected!!')
            print(f"dR: {deltaR}\ndV: {deltaV}")
            print(f"dR_norm: {rho}\ndV_norm: {np.linalg.norm(deltaV)}")
            print("##########")
            return [], []

        if (np.linalg.norm(deltaV) < 10. and rho < 50.e3):
            print(f'\nPrimary: {primary["OBJECT_NAME"]}    NORAD:{primary["NORAD_CAT_ID"]}')
            print(f'\nSecondary: {secondary["OBJECT_NAME"]}    NORAD:{secondary["NORAD_CAT_ID"]}')
            print('Rendezvous/Docking detected!!')
            print(f"dR: {deltaR}\ndV: {deltaV}")
            print(f"dR_norm: {rho}\ndV_norm: {np.linalg.norm(deltaV)}")
            velApprox = np.dot(deltaV, deltaR) / rho
            if velApprox < 0:
                print(f"Approach phase! ({-1. * velApprox * 1.e-3} km/s)")
            else:
                print(f"Withdrawal phase! ({velApprox * 1.e-3} km/s)")
            print("##########")
            return [], []

        rc3 = rc + 9.81 * h**2 + 0.5 * abs(np.dot(deltaV, deltaR)) * h / rho

        if (rho > rc3):
            if verbose:
                print(f"{simulationTime} Nao calculado: RC3\nRC3: {rc3}\trho: {rho}")
                print(f"deltaR: {deltaR}")

            count += 1
            continue

        # Store full state tuple: (primary_state, secondary_state)
        # where state is (AbsoluteDate, pos_vec, vel_vec, cov_mat_opt)
        state_vectors.append((p_state, s_state))
        times.append(count * h)
        count += 1

    return times, state_vectors
