import numpy as np
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from org.orekit.time import AbsoluteDate  # type: ignore


def conjunctionAnalysis(primary: dict,
                        secondary: dict,
                        tcaTime: 'AbsoluteDate',
                        creationDate,
                        nameFile,
                        save=True,
                        verbose=False):
    # type: ignore[reportMissingImports]
    from org.orekit.frames import FramesFactory  # type: ignore
    # type: ignore[reportMissingImports]
    from org.orekit.propagation.analytical.tle import TLE, TLEPropagator  # type: ignore
    # type: ignore[reportMissingImports]
    from org.orekit.ssa.collision.shorttermencounter.probability.twod import (  # type: ignore
        Alfriend1999Max,
        Alfriend1999,
        Alfano2005,
        Patera2005,
        Laas2015,
    )
    # type: ignore[reportMissingImports]
    from org.orekit.orbits import CartesianOrbit, OrbitType, PositionAngleType  # type: ignore
    # type: ignore[reportMissingImports]
    from org.orekit.utils import Constants  # type: ignore
    # type: ignore[reportMissingImports]
    from org.orekit.propagation import StateCovariance  # type: ignore
    from org.hipparchus.linear import (  # type: ignore
        MatrixUtils,
        LUDecomposition,
        Array2DRowRealMatrix,
    )
    from org.hipparchus.geometry.euclidean.twod import Vector2D  # type: ignore

    inertialFrame = FramesFactory.getEME2000()

    year = creationDate.year
    month = creationDate.month
    day = creationDate.day
    hour = creationDate.hour
    minute = creationDate.minute
    second = creationDate.second
    microsecond = creationDate.microsecond

    if (primary["OBJECT_TYPE"] == "DEBRIS"):
        rp = 1.
    elif primary["OBJECT_TYPE"] == "ROCKET BODY":
        rp = 3.
    else:
        rp = 5.

    if (secondary["OBJECT_TYPE"] == "DEBRIS"):
        rs = 1.
    elif secondary["OBJECT_TYPE"] == "ROCKET BODY":
        rs = 3.
    else:
        rs = 5.

    rc = rp + rs

    propagPrimary = TLEPropagator.selectExtrapolator(
        TLE(primary["TLE_LINE1"], primary["TLE_LINE2"])
    )
    propagSecondary = TLEPropagator.selectExtrapolator(
        TLE(secondary["TLE_LINE1"], secondary["TLE_LINE2"])
    )

    pvPrimary = propagPrimary.getPVCoordinates(tcaTime, inertialFrame)
    posPrimary = pvPrimary.getPosition()
    velPrimary = pvPrimary.getVelocity()

    pvSecondary = propagSecondary.getPVCoordinates(tcaTime, inertialFrame)
    posSecondary = pvSecondary.getPosition()
    velSecondary = pvSecondary.getVelocity()

    rPrimary = np.array((posPrimary.getX(), posPrimary.getY(), posPrimary.getZ()))
    vPrimary = np.array((velPrimary.getX(), velPrimary.getY(), velPrimary.getZ()))

    rSecondary = np.array((posSecondary.getX(), posSecondary.getY(), posSecondary.getZ()))
    vSecondary = np.array((velSecondary.getX(), velSecondary.getY(), velSecondary.getZ()))

    U_Primary = rPrimary / np.linalg.norm(rPrimary)
    W_Primary = np.linalg.cross(rPrimary, vPrimary) / np.linalg.norm(
        np.linalg.cross(rPrimary, vPrimary)
    )
    V_Primary = np.linalg.cross(W_Primary, U_Primary)

    U_Secondary = rSecondary / np.linalg.norm(rSecondary)
    W_Secondary = np.linalg.cross(rSecondary, vSecondary) / np.linalg.norm(
        np.linalg.cross(rSecondary, vSecondary)
    )
    V_Secondary = np.linalg.cross(W_Secondary, U_Secondary)

    R_UVW_Primary = np.array((U_Primary, V_Primary, W_Primary))
    R_UVW_Secondary = np.array((U_Secondary, V_Secondary, W_Secondary))

    covUVW = np.array((
        (100**2, 0, 0),
        (0, 300**2, 0),
        (0, 0, 100**2)
    ))

    covXYZ_Primary = np.matmul(
        np.matmul(np.transpose(R_UVW_Primary), covUVW), R_UVW_Primary
    )
    covXYZ_Secondary = np.matmul(
        np.matmul(np.transpose(R_UVW_Secondary), covUVW), R_UVW_Secondary
    )
    covXYZ = covXYZ_Primary + covXYZ_Secondary

    # if verbose:
    #     print(f"CovXYZ:\n{covXYZ}")

    deltaR = np.array(
        (posPrimary.getX(), posPrimary.getY(), posPrimary.getZ())
    ) - np.array((posSecondary.getX(), posSecondary.getY(), posSecondary.getZ()))
    missDistance = np.linalg.norm(deltaR)

    deltaV = np.array(
        (velPrimary.getX(), velPrimary.getY(), velPrimary.getZ())
    ) - np.array((velSecondary.getX(), velSecondary.getY(), velSecondary.getZ()))

    deltaR_UVW = np.matmul(R_UVW_Primary, deltaR)

    Xb = deltaR / np.linalg.norm(deltaR)
    Yb = np.linalg.cross(deltaR, deltaV) / np.linalg.norm(
        np.linalg.cross(deltaR, deltaV)
    )

    R_XbYb = np.array((Xb, Yb))

    Cb = np.matmul(np.matmul(R_XbYb, covXYZ), np.transpose(R_XbYb))

    # if verbose:
    #     print(f"Cb:\n{Cb}")
    deltaRb = np.matmul(R_XbYb, deltaR)

    # if verbose:
    #     print(f"deltaRb: {deltaRb}")

    eigCbValues, eigCbVectors = np.linalg.eig(Cb)
    # if verbose:
    #     print(f"\nEigvalues of Cb: {eigCbValues}")
    #     print(f"Eigvectors of Cb:\n{eigCbVectors}")

    if eigCbValues[0] > eigCbValues[1]:
        xb = eigCbVectors[:, 0]
        rotDiagCb = np.array((eigCbVectors[:, 0], eigCbVectors[:, 1]))
    else:
        xb = eigCbVectors[:, 1]
        rotDiagCb = np.array((eigCbVectors[:, 1], eigCbVectors[:, 0]))

    # if verbose:
    #     print(f"xb: {xb}")

    CbDiag = np.matmul(np.matmul(rotDiagCb, Cb), np.transpose(rotDiagCb))
    sigmaX = np.sqrt(CbDiag[0, 0])
    sigmaY = np.sqrt(CbDiag[1, 1])

    # if verbose:
    #     print(f"CbDiag:\n{CbDiag}")
    #     print(f"sigmaX = {sigmaX}")
    #     print(f"sigmaY = {sigmaY}")

    phi = np.atan2(xb[1], xb[0])

    rotationPhi = np.array((
        (np.cos(phi), -np.sin(phi)),
        (np.sin(phi), np.cos(phi)),
    ))

    deltaRtca = np.matmul(rotationPhi, deltaRb)
    xm = deltaRtca[0]
    ym = deltaRtca[1]

    # if verbose:
    #     print(f"xm = {xm}")
    #     print(f"ym = {ym}")

    deltaRtca = deltaRtca[np.newaxis, :]

    deltaRb = deltaRb[np.newaxis, :]

    k2sigmaMax = 0.5 * np.matmul(np.matmul(deltaRb, np.linalg.inv(Cb)), np.transpose(deltaRb))
    denom_term1 = np.exp(1) * np.sqrt(np.linalg.det(CbDiag))
    denom_term2 = np.matmul(
        np.matmul(deltaRtca, np.linalg.inv(CbDiag)),
        np.transpose(deltaRtca)
    )
    denom = denom_term1 * denom_term2
    PoCMax = rc**2. / denom

    position = Vector2D(float(xm), float(ym))

    covariance_values = [
        [float(sigmaX * sigmaX), 0.],
        [0., float(sigmaY * sigmaY)]
    ]
    covariance = MatrixUtils.createRealMatrix(2, 2)
    for i in range(2):
        for j in range(2):
            covariance.setEntry(i, j, covariance_values[i][j])

    # if verbose:
    #     print(f"Position: {position}\nCovariance:\n{covariance}")

    covarianceMatrixInverse = LUDecomposition(covariance).getSolver().getInverse()
    otherPositionOnCollisionPlaneMatrix = Array2DRowRealMatrix(position.toArray())

    # if verbose:
    #     print(f"Covatiance Matrix inverse:\n{covarianceMatrixInverse}")
    #     print(f"PositionOnCollisionPlaneMatrix:\n{otherPositionOnCollisionPlaneMatrix}")

    squaredMahalanobisDistance = otherPositionOnCollisionPlaneMatrix.transposeMultiply(
        covarianceMatrixInverse.multiply(otherPositionOnCollisionPlaneMatrix)
    ).getEntry(0, 0)

    covarianceMatrixDeterminant = LUDecomposition(covariance).getDeterminant()

    num = np.exp(-0.5 * squaredMahalanobisDistance) * rc * rc
    den = 2 * np.sqrt(covarianceMatrixDeterminant)
    PoCValueAlfriendOrekit = num / den

    PoCValueAlfriendMaxOrekit = rc * rc / (
        squaredMahalanobisDistance * np.sqrt(covarianceMatrixDeterminant) * np.e
    )

    cov_mat1 = MatrixUtils.createRealMatrix(6, 6)
    for i in range(3):
        for j in range(3):
            cov_mat1.setEntry(i, j, float(covXYZ_Primary[i][j]))

    cov_mat2 = MatrixUtils.createRealMatrix(6, 6)
    for i in range(3):
        for j in range(3):
            cov_mat2.setEntry(i, j, float(covXYZ_Secondary[i][j]))

    # if verbose:
    #     print(f"CovXYZ jarray: {jarray}")

    orbit1 = CartesianOrbit(pvPrimary,
                            FramesFactory.getEME2000(),
                            tcaTime,
                            Constants.WGS84_EARTH_MU)

    orbit2 = CartesianOrbit(pvSecondary,
                            FramesFactory.getEME2000(),
                            tcaTime,
                            Constants.WGS84_EARTH_MU)

    covariance1 = StateCovariance(
        cov_mat1, tcaTime, inertialFrame, OrbitType.CARTESIAN, PositionAngleType.TRUE
    )
    covariance2 = StateCovariance(
        cov_mat2, tcaTime, inertialFrame, OrbitType.CARTESIAN, PositionAngleType.TRUE
    )

    alfriend99 = Alfriend1999()
    PoCAlfriend = alfriend99.compute(orbit1, covariance1, orbit2, covariance2, rc, 1e-16)

    maxAlfriend99 = Alfriend1999Max()
    PoCMaxOrekit = maxAlfriend99.compute(orbit1, covariance1, orbit2, covariance2, rc, 1e-16)

    alfano2005 = Alfano2005()
    PoCAlfano = alfano2005.compute(orbit1, covariance1, orbit2, covariance2, rc, 1e-16)

    patera2005 = Patera2005()
    PoCPatera = patera2005.compute(orbit1, covariance1, orbit2, covariance2, rc, 1e-16)

    laas2015 = Laas2015()
    PoCLaas = laas2015.compute(orbit1, covariance1, orbit2, covariance2, rc, 1e-16)

    if save:
        fid = open(nameFile, "a+")

        # Format CSV line components
        tca_str = f"{tcaTime}"
        creation_str = f"{year}-{month}-{day} {hour}:{minute}:{second + microsecond / 1e6}"
        miss_dist_km = f"{missDistance * 1.e-3:.4f}"
        poc = f"{float(PoCMax):.4e}"
        rel_vel = f"{np.linalg.norm(deltaV) * 1.e-3:.4f}"
        radial_dist = f"{deltaR_UVW[0] * 1.e-3:.4f}"

        # Primary info
        p_id = f"{primary['NORAD_CAT_ID']}"
        p_name = f"{primary['OBJECT_NAME']}"
        p_type = f"{primary['OBJECT_TYPE']}"
        p_rad = f"{rp:.2f}"
        p_l1 = f"{primary['TLE_LINE1']}"
        p_l2 = f"{primary['TLE_LINE2']}"

        # Secondary info
        s_id = f"{secondary['NORAD_CAT_ID']}"
        s_name = f"{secondary['OBJECT_NAME']}"
        s_type = f"{secondary['OBJECT_TYPE']}"
        s_rad = f"{rs:.2f}"
        s_l1 = f"{secondary['TLE_LINE1']}"
        s_l2 = f"{secondary['TLE_LINE2']}"

        line_parts = [
            creation_str, tca_str, miss_dist_km, poc, rel_vel, radial_dist,
            p_id, p_name, p_type, p_rad, p_l1, p_l2,
            s_id, s_name, s_type, s_rad, s_l1, s_l2
        ]

        # Format CSV line components
        tca_str = f"{tcaTime}"
        creation_str = f"{year}-{month}-{day} {hour}:{minute}:{second + microsecond / 1e6}"
        miss_dist_km = f"{missDistance * 1.e-3:.4f}"
        poc = f"{float(PoCMax):.4e}"
        rel_vel = f"{np.linalg.norm(deltaV) * 1.e-3:.4f}"
        radial_dist = f"{deltaR_UVW[0] * 1.e-3:.4f}"

        # Primary info
        p_id = f"{primary['NORAD_CAT_ID']}"
        p_name = f"{primary['OBJECT_NAME']}"
        p_type = f"{primary['OBJECT_TYPE']}"
        p_rad = f"{rp:.2f}"
        p_l1 = f"{primary['TLE_LINE1']}"
        p_l2 = f"{primary['TLE_LINE2']}"

        # Secondary info
        s_id = f"{secondary['NORAD_CAT_ID']}"
        s_name = f"{secondary['OBJECT_NAME']}"
        s_type = f"{secondary['OBJECT_TYPE']}"
        s_rad = f"{rs:.2f}"
        s_l1 = f"{secondary['TLE_LINE1']}"
        s_l2 = f"{secondary['TLE_LINE2']}"

        line_parts = [
            creation_str, tca_str, miss_dist_km, poc, rel_vel, radial_dist,
            p_id, p_name, p_type, p_rad, p_l1, p_l2,
            s_id, s_name, s_type, s_rad, s_l1, s_l2
        ]

        fid.write("\n" + ",".join(line_parts))
        fid.close()

    print(f'\nSecondary: {secondary["OBJECT_NAME"]}    NORAD:{secondary["NORAD_CAT_ID"]}')
    print(f'TCA: {tcaTime}')
    print(f"Miss Distance: {missDistance * 1.e-3:.4f} km")
    print(f"Max probability of collision: {float(PoCMax):.4e}")
    print(f"Relativity velocity: {np.linalg.norm(deltaV) * 1.e-3:.4f} km/s")
    print(f"Radial distance: {deltaR_UVW[0] * 1.e-3:.4f} km")
    print(f"In-track distance: {deltaR_UVW[1] * 1.e-3:.4f} km")
    print(f"Cross-track distance: {deltaR_UVW[2] * 1.e-3:.4f} km")
    print(f"Dilution threshold: {np.sqrt(float(k2sigmaMax)) * 1.e-3:.4f} km")

    if verbose:
        print(f"PoC calculated using Klinkrad: {float(PoCMax):.4e} (Max Alfriend)\n")

        print(f"Orekit manual: {PoCValueAlfriendOrekit:.4e} (Alfriend 1999)")
        print(f"Orekit manual: {PoCValueAlfriendMaxOrekit:.4e} (Max Alfriend 1999)\n")

        print(f"PoC calculated using Orekit: {PoCAlfriend.getValue():.4e} (Alfriend 1999)")
        print(f"Orekit's method is a max prob? {PoCAlfriend.isMaxProbability()}\n")

        print(f"PoC calculated using Orekit: {PoCMaxOrekit.getValue():.4e} (Max Alfriend 1999)")
        print(f"Orekit's method is a max prob? {PoCMaxOrekit.isMaxProbability()}\n")

        print(f"PoC calculated using Orekit: {PoCAlfano.getValue():.4e} (Alfano 2005)")
        print(f"Orekit's method is a max prob? {PoCAlfano.isMaxProbability()}\n")

        print(f"PoC calculated using Orekit: {PoCPatera.getValue():.4e} (Patera 2005)")
        print(f"Orekit's method is a max prob? {PoCPatera.isMaxProbability()}\n")

        print(f"PoC calculated using Orekit: {PoCLaas.getValue():.4e} (Laas 2015)")
        print(f"Orekit's method is a max prob? {PoCLaas.isMaxProbability()}\n")
    print("##########")

    return {
        "secondary_name": secondary["OBJECT_NAME"],
        "secondary_id": secondary["NORAD_CAT_ID"],
        "tca_utc": tcaTime.toString(),
        "min_distance_m": float(missDistance),
        "poc_max": float(PoCMax)
    }
