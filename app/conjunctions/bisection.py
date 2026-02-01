import numpy as np  # type: ignore
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from org.orekit.time import AbsoluteDate  # type: ignore


def bisectionMethod(
        initialTime: 'AbsoluteDate',
        primary,
        secondary,
        h=10. * 60,
        criteria=1.
):
    """
    h in seconds
    criteria in meters/sec
    """
    # type: ignore[reportMissingImports]
    from org.orekit.frames import FramesFactory  # type: ignore
    # type: ignore[reportMissingImports]
    from org.orekit.propagation.analytical.tle import TLE, TLEPropagator  # type: ignore

    propagPrimary = TLEPropagator.selectExtrapolator(
        TLE(primary["TLE_LINE1"], primary["TLE_LINE2"])
    )
    propagSecondary = TLEPropagator.selectExtrapolator(
        TLE(secondary["TLE_LINE1"], secondary["TLE_LINE2"])
    )

    missDistance = []
    time = []

    inertialFrame = FramesFactory.getEME2000()

    simulationTime = initialTime

    count = 0

    while True:

        posPrimary = propagPrimary.getPVCoordinates(simulationTime, inertialFrame).getPosition()
        posSecondary = propagSecondary.getPVCoordinates(simulationTime, inertialFrame).getPosition()

        posPrimArr = np.array((posPrimary.getX(), posPrimary.getY(), posPrimary.getZ()))
        posSecArr = np.array((posSecondary.getX(), posSecondary.getY(), posSecondary.getZ()))
        missDistanceValue = np.linalg.norm(posPrimArr - posSecArr)

        if missDistance:
            if missDistanceValue > missDistance[-1]:
                missDistance.append(missDistanceValue)
                time.append(time[-1] + h)

                if (np.abs(h) == 1e-6):
                    pass
                elif np.abs(h) / 2 < 1e-6:
                    h = -1.e-6 * np.sign(h)
                else:
                    h = -h / 2.
                simulationTime = simulationTime.shiftedBy(float(h))
            else:
                nextPointTime = simulationTime.shiftedBy(float(h))
                posPrimary = propagPrimary.getPVCoordinates(
                    nextPointTime, inertialFrame
                ).getPosition()
                posSecondary = propagSecondary.getPVCoordinates(
                    nextPointTime, inertialFrame
                ).getPosition()
                nextMissDistance = np.linalg.norm(
                    np.array(
                        (posPrimary.getX(), posPrimary.getY(), posPrimary.getZ())
                    ) - np.array(
                        (posSecondary.getX(), posSecondary.getY(), posSecondary.getZ())
                    )
                )

                if (nextMissDistance < missDistanceValue):
                    missDistance.append(missDistanceValue)
                    missDistance.append(nextMissDistance)

                    time.append(time[-1] + h)
                    time.append(time[-1] + h)
                    simulationTime = simulationTime.shiftedBy(2 * float(h))
                else:
                    missDistance.append(missDistanceValue)
                    time.append(time[-1] + h)

                    if (np.abs(h) == 1e-6):
                        pass
                    elif np.abs(h) / 2 < 1e-6:
                        h = 1.e-6 * np.sign(h)
                    else:
                        h = h / 2.

                    simulationTime = simulationTime.shiftedBy(float(h))
            if abs((missDistance[-1] - missDistance[-2]) / h) < criteria:
                # print(f"dr: {abs(missDistance[-1] - missDistance[-2])}\th:{h}"
                #       f"\tdr/h:{abs((missDistance[-1] - missDistance[-2])/h)}")
                return time, missDistance

        else:
            missDistance.append(missDistanceValue)
            simulationTime = simulationTime.shiftedBy(float(h))
            time.append(count * h)

        count += 1
        if (count > 1e5):
            print("Exceed 1e5 interations")
            time = []
            missDistance = []
            return time, missDistance
