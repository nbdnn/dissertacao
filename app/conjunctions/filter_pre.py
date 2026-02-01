import numpy as np
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from org.orekit.time import AbsoluteDate  # type: ignore


def filterPre(
        initialTime: 'AbsoluteDate',
        endSimulation: 'AbsoluteDate',
        primary,
        secondary,
        h=180.,
        rc=20.e3,
        oldTLE=False,
        verbose=False
):
    # type: ignore[reportMissingImports]
    from org.orekit.frames import FramesFactory  # type: ignore
    # type: ignore[reportMissingImports]
    from org.orekit.propagation.analytical.tle import TLE, TLEPropagator  # type: ignore
    # type: ignore[reportMissingImports]
    from org.orekit.utils import Constants  # type: ignore

    propagPrimary = TLEPropagator.selectExtrapolator(
        TLE(primary["TLE_LINE1"], primary["TLE_LINE2"])
    )
    propagSecondary = TLEPropagator.selectExtrapolator(
        TLE(secondary["TLE_LINE1"], secondary["TLE_LINE2"])
    )

    if not oldTLE:
        priApoapsis = float(primary["APOAPSIS"])
        priPeriapsis = float(primary["PERIAPSIS"])

        secPeriapsis = float(secondary["PERIAPSIS"])
        secApoapsis = float(secondary["APOAPSIS"])

        if not (secPeriapsis < priApoapsis and priPeriapsis < secApoapsis and secPeriapsis > 250):
            if verbose:
                print(f'Primary: Apoapsis: {priApoapsis}, Periapsis: {priPeriapsis}')
                print(f'Secondary: Apoapsis: {secApoapsis}, Periapsis: {secPeriapsis}')
                print("Nao calculado: filtro de altitude")
            return [], []

    inertialFrame = FramesFactory.getEME2000()
    muEarth = Constants.IERS2010_EARTH_MU

    count = 0
    simulationTime = initialTime
    missDistances = []
    times = []

    while (simulationTime.compareTo(endSimulation) <= 0.):
        pvPrimary = propagPrimary.getPVCoordinates(simulationTime, inertialFrame)
        posPrimary = pvPrimary.getPosition()
        velPrimary = pvPrimary.getVelocity()

        pvSecondary = propagSecondary.getPVCoordinates(simulationTime, inertialFrame)
        posSecondary = pvSecondary.getPosition()
        velSecondary = pvSecondary.getVelocity()

        if verbose:
            print(f"\nSimulation time: {simulationTime}")

        r = np.linalg.norm(np.array((posPrimary.getX(), posPrimary.getY(), posPrimary.getZ())))

        ve = np.sqrt(2 * muEarth / r)
        rc1 = rc + ve * h

        posPrimArr = np.array((posPrimary.getX(), posPrimary.getY(), posPrimary.getZ()))
        posSecArr = np.array((posSecondary.getX(), posSecondary.getY(), posSecondary.getZ()))
        deltaR = posSecArr - posPrimArr
        rho = np.linalg.norm(deltaR)

        velPrimArr = np.array((velPrimary.getX(), velPrimary.getY(), velPrimary.getZ()))
        velSecArr = np.array((velSecondary.getX(), velSecondary.getY(), velSecondary.getZ()))
        deltaV = velSecArr - velPrimArr

        if (deltaR[0] > rc1 or deltaR[1] > rc1 or deltaR[2] > rc1 or rho > rc1):
            if verbose:
                print(f"{simulationTime} Nao calculado: RC1\nRC1: {rc1}\trho: {rho}")
                print(f"deltaR: {deltaR}")
                print(f"Pos primary: {posPrimary}")
                print(f"Pos secondary: {posSecondary}")
            simulationTime = simulationTime.shiftedBy(h)
            count += 1
            continue

        if (np.linalg.norm(deltaV) == 0 and rho < 50.e3):
            print(f'\nSecondary: {secondary["OBJECT_NAME"]}    NORAD:{secondary["NORAD_CAT_ID"]}')
            print('Rendezvous/Docking detected!!')
            print(f"dR: {deltaR}\ndV: {deltaV}")
            print(f"dR_norm: {rho}\ndV_norm: {np.linalg.norm(deltaV)}")
            print("##########")
            return [], []

        if (np.linalg.norm(deltaV) < 10. and rho < 50.e3):
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
                print(f"Pos primary: {posPrimary}")
                print(f"Pos secondary: {posSecondary}")
            simulationTime = simulationTime.shiftedBy(h)
            count += 1
            continue

        missDistances.append(rho)
        times.append(count * h)
        simulationTime = simulationTime.shiftedBy(h)
        count += 1
    return times, missDistances
