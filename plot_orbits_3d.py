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
from org.orekit.frames import FramesFactory

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
inertial_frame = FramesFactory.getTEME() # TLEs usam TEME

def parse_tca(tca_str):
    tca_str = tca_str.split('.')[0]
    return datetime.strptime(tca_str, '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)

# Janela de visualizacao 3D: +/- 10 minutos (600 segundos) para mostrar bem as orbitas, passo de 5 s
delta_s = 600
step_s = 5

for target_id, target_name in targets.items():
    pattern = f'/home/guima/dissertacao/cenario1/analysis_results/analysis_{target_id}_*.json'
    files = glob.glob(pattern)
    if not files: 
        continue
    file_path = files[0]
    
    with open(file_path, 'r') as f:
        events = json.load(f)
        
    filtered_events = [ev for ev in events if start_win <= parse_tca(ev['tca_utc']) <= end_win]
            
    n_events = len(filtered_events)
    if n_events == 0:
        continue
        
    # Uma figura principal (grid 3D) por satelite
    fig = plt.figure(figsize=(12, 6 * n_events))
        
    for i, ev in enumerate(filtered_events):
        tca_dt = parse_tca(ev['tca_utc'])
        sec_name = ev['secondary_name']
        
        tle_p1 = ev['primary_tle_line1']
        tle_p2 = ev['primary_tle_line2']
        tle_s1 = ev['secondary_tle_line1']
        tle_s2 = ev['secondary_tle_line2']
        
        tle_prim = TLE(tle_p1, tle_p2)
        tle_sec = TLE(tle_s1, tle_s2)
        
        tca_year = tca_dt.year; tca_month = tca_dt.month; tca_day = tca_dt.day
        tca_hour = tca_dt.hour; tca_minute = tca_dt.minute; tca_second = float(tca_dt.second)
        tca_orekit = AbsoluteDate(tca_year, tca_month, tca_day, tca_hour, tca_minute, tca_second, utc)
            
        prop_prim = TLEPropagator.selectExtrapolator(tle_prim)
        prop_sec = TLEPropagator.selectExtrapolator(tle_sec)
        
        t_delta = np.arange(-delta_s, delta_s + step_s, step_s)
        
        p_x, p_y, p_z = [], [], []
        s_x, s_y, s_z = [], [], []
        
        p_tca_pos = None
        s_tca_pos = None
        
        for t in t_delta:
            date_eval = tca_orekit.shiftedBy(float(t))
            
            # Obtendo posicao no referencial inercial do TLE (TEME)
            pv_prim = prop_prim.propagate(date_eval).getPVCoordinates(inertial_frame)
            pv_sec = prop_sec.propagate(date_eval).getPVCoordinates(inertial_frame)
            
            pos_p = pv_prim.getPosition()
            pos_s = pv_sec.getPosition()
            
            p_x.append(pos_p.getX() / 1000.0)
            p_y.append(pos_p.getY() / 1000.0)
            p_z.append(pos_p.getZ() / 1000.0)
            
            s_x.append(pos_s.getX() / 1000.0)
            s_y.append(pos_s.getY() / 1000.0)
            s_z.append(pos_s.getZ() / 1000.0)
            
            if abs(t) < 1e-3:
                p_tca_pos = (pos_p.getX()/1000.0, pos_p.getY()/1000.0, pos_p.getZ()/1000.0)
                s_tca_pos = (pos_s.getX()/1000.0, pos_s.getY()/1000.0, pos_s.getZ()/1000.0)
        
        # O 3D nao suporta grids tradicionais ax=axs[i], requer add_subplot iterativo com projection='3d'
        ax = fig.add_subplot(n_events, 1, i + 1, projection='3d')
        
        # Linhas Orbitais
        ax.plot(p_x, p_y, p_z, color='blue', linewidth=2, label=f'Alvo: {target_name}')
        ax.plot(s_x, s_y, s_z, color='orange', linewidth=2, linestyle='--', label=f'Secundário: {sec_name}')
        
        # Ponto Critico (TCA)
        ax.scatter([p_tca_pos[0]], [p_tca_pos[1]], [p_tca_pos[2]], color='red', s=80, marker='o', zorder=5)
        ax.scatter([s_tca_pos[0]], [s_tca_pos[1]], [s_tca_pos[2]], color='red', s=80, marker='x', zorder=5, label='Ponto de TCA')
        
        # Ligacao critica na distancia minima
        ax.plot([p_tca_pos[0], s_tca_pos[0]], 
                [p_tca_pos[1], s_tca_pos[1]], 
                [p_tca_pos[2], s_tca_pos[2]], 
                color='red', linewidth=1.5, linestyle=':', label=f'Separação Mínima: {ev["min_distance_m"]:.1f} m')
        
        # Estetica
        ax.set_xlabel('X (TEME) [km]', labelpad=10)
        ax.set_ylabel('Y (TEME) [km]', labelpad=10)
        ax.set_zlabel('Z (TEME) [km]', labelpad=10)
        
        ax.set_title(fr'Trânsito Orbital 3D ($\pm 10$ min)' + '\n' + fr'{target_name} vs {sec_name}' + '\n' + f'TCA: {tca_dt.strftime("%d/%m/%Y %H:%M:%S")} UTC', fontsize=12, pad=15)
        
        ax.tick_params(axis='x', pad=3, labelsize=9)
        ax.tick_params(axis='y', pad=3, labelsize=9)
        ax.tick_params(axis='z', pad=3, labelsize=9)
        
        ax.legend(loc='best', fontsize=10)
        
        # Alinhando escala dos eixos para evitar distorcoes dobras (aspect ratio 1:1:1 pseudo)
        max_range = np.array([max(p_x)-min(p_x), max(p_y)-min(p_y), max(p_z)-min(p_z),
                              max(s_x)-min(s_x), max(s_y)-min(s_y), max(s_z)-min(s_z)]).max() / 2.0
        
        mid_x = (max(p_x)+min(p_x)) * 0.5
        mid_y = (max(p_y)+min(p_y)) * 0.5
        mid_z = (max(p_z)+min(p_z)) * 0.5
        
        ax.set_xlim(mid_x - max_range, mid_x + max_range)
        ax.set_ylim(mid_y - max_range, mid_y + max_range)
        ax.set_zlim(mid_z - max_range, mid_z + max_range)
            
    plt.tight_layout()
    
    out_file = os.path.join(output_dir, f'orbita_3d_{target_id}_grid.png')
    plt.savefig(out_file, dpi=300, bbox_inches='tight')
    plt.close(fig)
    print(f"Salvo diagrama inercial 3D: {out_file}")
