from datetime import datetime, timezone
import logging
from typing import TYPE_CHECKING
from .filter_pre import filterPre
from .bisection import bisectionMethod
from .conjunction_analysis import conjunctionAnalysis
from ..download_all_tles import requestTles
from .config import ELLIPSOID_BOUNDS

if TYPE_CHECKING:
    from org.orekit.time import AbsoluteDate  # type: ignore  # noqa: F401

logger = logging.getLogger(__name__)


# Helper temporário para adaptar a chamada de requestTle
def requestTle(ids):
    # Baixa TUDO (ineficiente mas mapeia para o que temos)
    # Na verdade, o codigo original talvez filtrasse no servidor.
    # Vamos usar requestTles e filtrar em memória.
    all_tles = requestTles()
    primaries = []
    secondaries = []

    # Converte para o formato de dicionário esperado pelo código do usuário
    # O código espera chaves: NORAD_CAT_ID, OBJECT_NAME, TLE_LINE1,
    # TLE_LINE2, APOAPSIS, PERIAPSIS, OBJECT_TYPE
    # Nossos models têm isso? requestTles retorna dicts com chaves parecidas.

    # O TLEData não é usado aqui, o código usa dicts crus.

    for item in all_tles:
        # Verifica se é um dos primários
        norad = int(item['NORAD_CAT_ID'])
        if norad in ids:
            primaries.append(item)
        else:
            secondaries.append(item)

    return primaries, secondaries


def sieveAlgorithm(
        primariesID: list,
        daysOfSimulation: int,
        threshold: float,
        ellipsoid_bounds=ELLIPSOID_BOUNDS,
        verbose=False,
        verboseConjAnalysis=False,
        start_date=None,
        tles=None,
        screening_mode=False):

    # type: ignore[reportMissingImports]
    from org.orekit.time import AbsoluteDate, TimeScalesFactory  # type: ignore  # noqa: F811

    conjunctions = []

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

    if tles:
        primaries, secondaries = tles
    else:
        primaries, secondaries = requestTle(primariesID)

    for primary in primaries:

        if verbose:
            print(f'Primary: {primary["OBJECT_NAME"]}    NORAD:{primary["NORAD_CAT_ID"]}')

        total_secondaries = len(secondaries)
        for idx, secondary in enumerate(secondaries):
            # Update progress check to every 1 item to show life, as processing is slow
            percent = 100.0 * idx / total_secondaries
            print(
                f"\rProgress: {percent:.2f}% ",
                f"({idx}/{total_secondaries}) ",
                f"- Checking {secondary['OBJECT_NAME'][:10]}...", end="", flush=True)

            if secondary["NORAD_CAT_ID"] != primary["NORAD_CAT_ID"]:
                if verbose:
                    print(
                        f'\nSecondary: {secondary["OBJECT_NAME"]}    '
                        f'NORAD:{secondary["NORAD_CAT_ID"]}'
                    )
                    print(f"TLE\n{secondary['TLE_LINE1']}\n{secondary['TLE_LINE2']}")

                if verbose:
                    print(f'Ecentricidade: {secondary["ECCENTRICITY"]}')
                    print(f'Apogeu: {secondary["APOAPSIS"]}, Perigeo: {secondary["PERIAPSIS"]}')

                t, __ = filterPre(
                    initialTime,
                    endTime,
                    primary=primary,
                    secondary=secondary,
                    rc=threshold,
                    verbose=verbose
                )

                tcas = []

                for i in range(len(t)):
                    times, distances = bisectionMethod(
                        initialTime.shiftedBy(t[i]),
                        primary=primary,
                        secondary=secondary,
                        h=1.
                    )
                    if not t:
                        print(
                            f'\nSecondary: {secondary["OBJECT_NAME"]}    '
                            f'NORAD:{secondary["NORAD_CAT_ID"]}'
                        )
                        print(f"TLE\n{secondary['TLE_LINE1']}\n{secondary['TLE_LINE2']}")

                    if distances[-1] < distances[-2]:
                        tca, missDistance = times[-1], distances[-1]
                    else:
                        tca, missDistance = times[-2], distances[-2]

                    if missDistance < threshold:
                        tcas.append(t[i])

                        if len(tcas) == 1 or abs(tcas[-1] - tcas[-2]) > 10 * 60:
                            result = conjunctionAnalysis(
                                primary=primary,
                                secondary=secondary,
                                tcaTime=initialTime.shiftedBy(t[i] + tca),
                                verbose=verboseConjAnalysis,
                                ellipsoid_bounds=ellipsoid_bounds
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
                                    # Removed break as requested to save all conjunctions
                                else:
                                    conjunctions.append(result)
        print()
    return conjunctions  # Could be implemented returns when an error occurred
