import numpy as np
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from org.orekit.time import AbsoluteDate  # type: ignore

from .config import ELLIPSOID_BOUNDS, rc, POC_THRESHOLD


def conjunctionAnalysis(primary: dict,
                        secondary: dict,
                        tcaTime: 'AbsoluteDate',
                        verbose=False,
                        ellipsoid_bounds=ELLIPSOID_BOUNDS,
                        primary_state_vector=None,
                        secondary_state_vector=None):
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
    from org.orekit.utils import Constants, PVCoordinates  # type: ignore
    # type: ignore[reportMissingImports]
    from org.orekit.propagation import StateCovariance  # type: ignore
    from org.hipparchus.linear import (  # type: ignore
        MatrixUtils,
    )

    from org.hipparchus.geometry.euclidean.threed import Vector3D  # type: ignore

    inertialFrame = FramesFactory.getEME2000()

    if primary_state_vector and len(primary_state_vector) == 4 and secondary_state_vector and len(secondary_state_vector) == 4:
        # Use provided vectors (tuples: date, pos_arr, vel_arr, cov_opt)
        # Note: tcaTime argument is redundant if we assume vectors ARE at TCA,
        # but let's assume they are indeed at TCA.

        # Primary
        _, p_pos, p_vel, p_cov = primary_state_vector
        pvPrimary = PVCoordinates(
            Vector3D(float(p_pos[0]), float(p_pos[1]), float(p_pos[2])),
            Vector3D(float(p_vel[0]), float(p_vel[1]), float(p_vel[2]))
        )

        # Secondary
        _, s_pos, s_vel, s_cov = secondary_state_vector
        pvSecondary = PVCoordinates(
            Vector3D(float(s_pos[0]), float(s_pos[1]), float(s_pos[2])),
            Vector3D(float(s_vel[0]), float(s_vel[1]), float(s_vel[2]))
        )

        posPrimary = pvPrimary.getPosition()
        velPrimary = pvPrimary.getVelocity()

        posSecondary = pvSecondary.getPosition()
        velSecondary = pvSecondary.getVelocity()

    else:
        # TLE Propagation Fallback
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
    R_UVW_Primary = np.array((U_Primary, V_Primary, W_Primary))

    U_Secondary = rSecondary / np.linalg.norm(rSecondary)
    W_Secondary = np.linalg.cross(rSecondary, vSecondary) / np.linalg.norm(
        np.linalg.cross(rSecondary, vSecondary)
    )
    V_Secondary = np.linalg.cross(W_Secondary, U_Secondary)
    R_UVW_Secondary = np.array((U_Secondary, V_Secondary, W_Secondary))

    has_covariance = (
        primary_state_vector and len(primary_state_vector) == 4 and primary_state_vector[3] is not None and
        secondary_state_vector and len(secondary_state_vector) == 4 and secondary_state_vector[3] is not None
    )

    if has_covariance:
        # Let's assume input covariance is 6x6 or 3x3 numpy array in XYZ Frame.
        p_cov_in = primary_state_vector[3]
        if p_cov_in.shape == (6, 6):
            covXYZ_Primary = p_cov_in[0:3, 0:3]  # Extract 3x3 pos
        else:
            covXYZ_Primary = p_cov_in

        s_cov_in = secondary_state_vector[3]
        if s_cov_in.shape == (6, 6):
            covXYZ_Secondary = s_cov_in[0:3, 0:3]
        else:
            covXYZ_Secondary = s_cov_in

        # Rotate Covariance to UVW
        covUVW_Primary = R_UVW_Primary @ covXYZ_Primary @ R_UVW_Primary.T
        sigma_UVW_Primary = np.sqrt(np.diag(covUVW_Primary))

        covUVW_Secondary = R_UVW_Secondary @ covXYZ_Secondary @ R_UVW_Secondary.T
        sigma_UVW_Secondary = np.sqrt(np.diag(covUVW_Secondary))
    else:
        covUVW_Primary = np.zeros((3, 3))
        covUVW_Secondary = np.zeros((3, 3))
        sigma_UVW_Primary = np.zeros(3)
        sigma_UVW_Secondary = np.zeros(3)

    deltaR = np.array(
        (posPrimary.getX(), posPrimary.getY(), posPrimary.getZ())
    ) - np.array((posSecondary.getX(), posSecondary.getY(), posSecondary.getZ()))
    missDistance = np.linalg.norm(deltaR)

    deltaV = np.array(
        (velPrimary.getX(), velPrimary.getY(), velPrimary.getZ())
    ) - np.array((velSecondary.getX(), velSecondary.getY(), velSecondary.getZ()))

    deltaR_UVW = np.matmul(R_UVW_Primary, deltaR)

    if has_covariance:
        cov_mat1 = MatrixUtils.createRealMatrix(6, 6)
        for i in range(3):
            for j in range(3):
                # Enforce symmetry by averaging off-diagonal elements
                val = 0.5 * (float(covXYZ_Primary[i][j]) + float(covXYZ_Primary[j][i]))
                cov_mat1.setEntry(i, j, val)

        cov_mat2 = MatrixUtils.createRealMatrix(6, 6)
        for i in range(3):
            for j in range(3):
                # Enforce symmetry
                val = 0.5 * (float(covXYZ_Secondary[i][j]) + float(covXYZ_Secondary[j][i]))
                cov_mat2.setEntry(i, j, val)

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

        poc_values = {
            "alfriend1999": float(PoCAlfriend.getValue()),
            "alfriend1999_max": float(PoCMaxOrekit.getValue()),
            "alfano2005": float(PoCAlfano.getValue()),
            "patera2005": float(PoCPatera.getValue()),
            "laas2015": float(PoCLaas.getValue()),
        }
    else:
        poc_values = {
            "alfriend1999": 0.0,
            "alfriend1999_max": 0.0,
            "alfano2005": 0.0,
            "patera2005": 0.0,
            "laas2015": 0.0,
        }

    # Calculate kc^2 (Safety Ellipsoid Violation)
    # deltaR_UVW[0] => Radial (U)
    # deltaR_UVW[1] => In-Track (V)
    # deltaR_UVW[2] => Cross-Track (W)
    rc_u, rc_v, rc_w = ellipsoid_bounds

    # Avoid division by zero
    rc_u = max(rc_u, 1e-6)
    rc_v = max(rc_v, 1e-6)
    rc_w = max(rc_w, 1e-6)

    x_component = (deltaR_UVW[0] / rc_u)**2
    y_component = (deltaR_UVW[1] / rc_v)**2
    z_component = (deltaR_UVW[2] / rc_w)**2

    kc_squared = x_component + y_component + z_component

    # Default violation check (Safety Ellipsoid)
    is_violated_ellipsoid = float(kc_squared) < 1.0

    # If Ephemeris (State Vectors provided with covariance), use Probability of Collision
    if has_covariance:
        poc_max = poc_values["alfriend1999"]
        is_violated = poc_max >= POC_THRESHOLD
    else:
        is_violated = is_violated_ellipsoid


    # Relative Velocity in UVW frame
    deltaV_UVW = np.matmul(R_UVW_Primary, deltaV)
    relative_speed = np.linalg.norm(deltaV)
    if relative_speed > 0:
        rel_vel_versor = deltaV_UVW / relative_speed
    else:
        rel_vel_versor = np.zeros(3)

    if verbose:
        print(f'\nSecondary: {secondary["OBJECT_NAME"]}    NORAD:{secondary["NORAD_CAT_ID"]}')
        print(f'TCA: {tcaTime}')
        print(f"Miss Distance: {missDistance * 1.e-3:.4f} km")
        print(f"Relativity velocity: {np.linalg.norm(deltaV) * 1.e-3:.4f} km/s")
        print(f"Radial distance: {deltaR_UVW[0] * 1.e-3:.4f} km")
        print(f"In-track distance: {deltaR_UVW[1] * 1.e-3:.4f} km")
        print(f"Cross-track distance: {deltaR_UVW[2] * 1.e-3:.4f} km")

    if verbose:

        print(f"PoC calculated using Orekit: {poc_values['alfriend1999']:.4e} (Alfriend 1999)")
        print(f"Orekit's method is a max prob? {-1}\n") # Placeholder for isMaxProbability as it's not available here easily

        print(f"PoC calculated using Orekit: {poc_values['alfriend1999_max']:.4e} (Max Alfriend 1999)")
        print(f"Orekit's method is a max prob? {-1}\n")

        print(f"PoC calculated using Orekit: {poc_values['alfano2005']:.4e} (Alfano 2005)")
        print(f"Orekit's method is a max prob? {-1}\n")

        print(f"PoC calculated using Orekit: {poc_values['patera2005']:.4e} (Patera 2005)")
        print(f"Orekit's method is a max prob? {-1}\n")

        print(f"PoC calculated using Orekit: {poc_values['laas2015']:.4e} (Laas 2015)")
        print(f"Orekit's method is a max prob? {-1}\n")
    if verbose:
        print(f"Safety Ellipsoid Violation (kc^2): {float(kc_squared):.4f} (Violated if < 1.0)")
        print(f"Bounds (U, V, W): {rc_u:.1f}, {rc_v:.1f}, {rc_w:.1f} m")
        print("##########")

    result = {
        "primary_name": primary["OBJECT_NAME"],
        "primary_id": primary["NORAD_CAT_ID"],
        "secondary_name": secondary["OBJECT_NAME"],
        "secondary_id": secondary["NORAD_CAT_ID"],
        # ... and so it continues ...
        "tca_utc": tcaTime.toString(),
        "min_distance_m": float(missDistance),
        "rc": float(rc),
        "kc_squared": float(kc_squared),
        "radial_dist_m": float(deltaR_UVW[0]),
        "along_track_dist_m": float(deltaR_UVW[1]),
        "cross_track_dist_m": float(deltaR_UVW[2]),
        "relative_speed_m_s": float(relative_speed),
        "radial_velocity_m_s": float(deltaV_UVW[0]),
        "along_track_velocity_m_s": float(deltaV_UVW[1]),
        "cross_track_velocity_m_s": float(deltaV_UVW[2]),
        "relative_velocity_versor": [float(v) for v in rel_vel_versor],
        "is_violated": is_violated,
    }

    if "TLE_LINE1" in primary:
        result["primary_tle_line1"] = primary["TLE_LINE1"]
        result["primary_tle_line2"] = primary["TLE_LINE2"]

    if "TLE_LINE1" in secondary:
        result["secondary_tle_line1"] = secondary["TLE_LINE1"]
        result["secondary_tle_line2"] = secondary["TLE_LINE2"]

    result["covariance_matrix_uvw_primary"] = covUVW_Primary.tolist()
    result["covariance_matrix_uvw_secondary"] = covUVW_Secondary.tolist()

    result["sigma_uvw_primary"] = sigma_UVW_Primary.tolist()
    result["sigma_uvw_secondary"] = sigma_UVW_Secondary.tolist()

    result["collision_probability"] = poc_values

    return result
