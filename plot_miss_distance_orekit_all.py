import json
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime, timezone
import os
import sys
import glob

sys.path.insert(0, '/home/guima/dissertacao')
try:
    from app.orekit_config import setup_orekit
    setup_orekit()
except Exception as e:
    print(f"Erro no Orekit setup: {e}")

from org.orekit.time import AbsoluteDate, TimeScalesFactory
from org.orekit.propagation.analytical.tle import TLE, TLEPropagator

output_dir = '/home/guima/dissertacao/docs/figuras/'
os.makedirs(output_dir, exist_ok=True)

targets = {
    61046: 'SPACEMOBILE-005',
    64830: 'KUIPER-00084',
    65774: 'KUIPER-00155'
}

start_win = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
end_win = datetime(2026, 2, 24, 12, 0, 0, tzinfo=timezone.utc)
utc = TimeScalesFactory.getUTC()

def parse_tca(tca_str):
    tca_str = tca_str.split('.')[0]
    return datetime.strptime(tca_str, '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)

windows = [
    {"name": "6hours", "delta_s": 21600, "step_s": 60, "unit": "horas", "div": 3600},
    {"name": "30sec", "delta_s": 30, "step_s": 0.5, "unit": "segundos", "div": 1}
]

color = '#1f77b4'

for target_id, target_name in targets.items():
    pattern = f'/home/guima/dissertacao/cenario1/analysis_results/analysis_{target_id}_*.json'
    files = glob.glob(pattern)
    if not files: 
        continue
    file_path = files[0]
    
    with open(file_path, 'r') as f:
        events = json.load(f)
        
    filtered_events = []
    for ev in events:
        if start_win <= parse_tca(ev['tca_utc']) <= end_win:
            filtered_events.append(ev)
            
    if len(filtered_events) == 0:
        continue
        
    # Agora iteramos por evento e criamos uma figura isolada para cada um
    for ev in filtered_events:
        tca_dt = parse_tca(ev['tca_utc'])
        sec_name = ev['secondary_name']
        sec_id = ev['secondary_id']
        
        tle_p1 = ev['primary_tle_line1']
        tle_p2 = ev['primary_tle_line2']
        tle_s1 = ev['secondary_tle_line1']
        tle_s2 = ev['secondary_tle_line2']
        
        tle_prim = TLE(tle_p1, tle_p2)
        tle_sec = TLE(tle_s1, tle_s2)
        
        tca_year = tca_dt.year; tca_month = tca_dt.month; tca_day = tca_dt.day
        tca_hour = tca_dt.hour; tca_minute = tca_dt.minute; tca_second = float(tca_dt.second)
        tca_orekit = AbsoluteDate(tca_year, tca_month, tca_day, tca_hour, tca_minute, tca_second, utc)
            
        # Cria a figura com 1 linha e 2 colunas para o evento atual
        fig, axs = plt.subplots(1, 2, figsize=(14, 5))
        
        for j, win in enumerate(windows):
            prop_prim = TLEPropagator.selectExtrapolator(tle_prim)
            prop_sec = TLEPropagator.selectExtrapolator(tle_sec)
            
            t_delta = np.arange(-win["delta_s"], win["delta_s"] + win["step_s"], win["step_s"])
            dists = []
            
            for t in t_delta:
                date_eval = tca_orekit.shiftedBy(float(t))
                pos_prim = prop_prim.propagate(date_eval).getPVCoordinates().getPosition()
                pos_sec = prop_sec.propagate(date_eval).getPVCoordinates().getPosition()
                
                dist_m = pos_prim.distance(pos_sec)
                dists.append(dist_m / 1000.0)
                
            time_axis = t_delta / win["div"]
            
            # Como agora temos apenas 1 linha (1D array de eixos), usamos apenas axs[j]
            ax = axs[j]
            
            if j == 0:  # Grafico de 6 horas
                ax.plot(time_axis, dists, color=color, linewidth=2, label=f"v {sec_name}")
                ax.scatter([0], [ev['min_distance_m'] / 1000.0], color='red', s=60, zorder=5, label=r'Min. Dist ($t\approx0$)')
                ax.axvline(0, color='red', linestyle='--', alpha=0.5)
                ax.legend(loc='best', fontsize=10)
            else:       # Grafico de 30 segundos
                ax.plot(time_axis, dists, color=color, linewidth=2) 
                # Sem scatter (ponto vermelho), sem axvline (linha tracejada), sem label/legenda
                
            ax.set_xlabel(f'Tempo Relativo ao TCA ({win["unit"]})', fontsize=12)
            ax.set_ylabel('Distância Relativa SGP4 (km)', fontsize=12)
            
            titulo_tempo = "6 Horas" if win["name"] == "6hours" else "30 Segundos"
            titulo = fr'{target_name} vs {sec_name}' + '\n' + fr'Evolução ($\pm$ {titulo_tempo})'
            ax.set_title(titulo, fontsize=13, pad=10)
            
            ax.grid(True, linestyle=':', alpha=0.7)
            
        plt.tight_layout()
        
        # Salva usando o id primário e secundário para o nome não colidir
        out_file = os.path.join(output_dir, f'miss_distance_{target_id}_{sec_id}.png')
        plt.savefig(out_file, dpi=300, bbox_inches='tight')
        plt.close(fig)
        
        print(f"Salvo: {out_file}")