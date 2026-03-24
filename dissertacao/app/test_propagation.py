import datetime
import math
import time

from .download_all_tles import requestTles
from .orekit_config import setup_orekit

# Importações Java (apenas para tipagem estática quando possível,
# mas aqui faremos dentro da função para garantir VM iniciada)


def track_iss_realtime():
    setup_orekit()

    # Imports Java após inicialização da VM
    from org.orekit.frames import FramesFactory  # type: ignore[reportMissingImports]
    from org.orekit.models.earth import ReferenceEllipsoid  # type: ignore[reportMissingImports]
    from org.orekit.propagation.analytical.tle import (  # type: ignore[reportMissingImports]
        TLE,
        TLEPropagator,
    )
    from org.orekit.time import (  # type: ignore[reportMissingImports]
        AbsoluteDate,
        TimeScalesFactory,
    )
    from org.orekit.utils import IERSConventions  # type: ignore[reportMissingImports]

    # --- TLE DA ISS ---
    print("\n🔄 Buscando TLE mais recente da ISS...")
    all_tles = requestTles()
    iss_data = None

    if all_tles:
        for sat in all_tles:
            if str(sat.get("NORAD_CAT_ID")) == "25544":
                iss_data = sat
                break

    if iss_data:
        print("✅ TLE encontrado e atualizado!")
        line1 = iss_data["TLE_LINE1"]
        line2 = iss_data["TLE_LINE2"]
    else:
        print("⚠️  ISS não encontrada ou falha no download. Usando backup.")
        line1 = "1 25544U 98067A   26032.11330074  .00006524  00000-0  12933-3 0  9990"
        line2 = "2 25544  51.6318 253.1662 0011128  51.9836 308.2155 15.48314896550661"

    tle = TLE(line1, line2)
    propagator = TLEPropagator.selectExtrapolator(tle)

    # Configurações do Orekit
    orekit_utc = TimeScalesFactory.getUTC()  # UTC do Orekit
    earth_frame = FramesFactory.getITRF(IERSConventions.IERS_2010, True)
    earth_shape = ReferenceEllipsoid.getWgs84(earth_frame)

    print(f"\n📡 RASTREIO EM TEMPO REAL: {tle.getSatelliteNumber()}")
    print("🌍 Frame: WGS84 | Pressione Ctrl+C para sair")
    print("=" * 75)
    print(
        f"{'HORA (UTC)':<25} | {'LATITUDE':>10} | "
        f"{'LONGITUDE':>10} | {'ALT (km)':>10}"
    )
    print("-" * 75)

    try:
        while True:
            # 1. Pega a hora atual do sistema já com fuso horário (CORREÇÃO AQUI)
            now_py = datetime.datetime.now(datetime.timezone.utc)

            # 2. Converte para AbsoluteDate do Orekit
            # Usamos os componentes da data Python para criar a data Java/Orekit
            current_date = AbsoluteDate(
                now_py.year,
                now_py.month,
                now_py.day,
                now_py.hour,
                now_py.minute,
                float(now_py.second + now_py.microsecond / 1e6),
                orekit_utc,
            )

            # 3. Propaga para esse instante
            pv_earth = propagator.getPVCoordinates(current_date, earth_frame)
            geo_point = earth_shape.transform(
                pv_earth.getPosition(), earth_frame, current_date
            )

            # 4. Cálculos
            lat = math.degrees(geo_point.getLatitude())
            lon = math.degrees(geo_point.getLongitude())
            alt = geo_point.getAltitude() / 1000.0

            # 5. Imprime
            # Usamos o objeto 'now_py' para formatar a string de hora
            timestamp = now_py.strftime("%Y-%m-%d %H:%M:%S")
            print(f"{timestamp:<25} | {lat:10.4f}° | {lon:10.4f}° | {alt:10.3f}")

            time.sleep(1)

    except KeyboardInterrupt:
        print("\n🛑 Rastreio finalizado pelo usuário.")


if __name__ == "__main__":
    track_iss_realtime()
