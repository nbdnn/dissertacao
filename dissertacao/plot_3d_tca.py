import json
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime, timezone
import os
import sys
import glob

# Configuração para gráficos 3D
from mpl_toolkits.mplot3d import Axes3D

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

def plot_earth(ax):
    """Gera uma malha esférica representando a Terra (Raio ~6378 km)"""
    u, v = np.mgrid[0:2*np.pi:50j, 0:np.pi:25j]
    R_earth = 6378.137
    x = R_earth * np.cos(u) * np.sin(v)
    y = R_earth * np.sin(u) * np.sin(v)
    z = R_earth * np.cos(v)
    
    # Plota a superfície da Terra com wireframe leve
    ax.plot_surface(x, y, z, color='lightblue', alpha=0.3, edgecolor='white', linewidth=0.5)

# Janela de visualização da órbita: +/- 20 minutos (1200 segundos) para mostrar um arco substancial
win_s = 100*60 
step_s = 10 # Resolução de 10 segundos para deixar a curva suave

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
            
    for ev in filtered_events:
        tca_dt = parse_tca(ev['tca_utc'])
        sec_name = ev['secondary_name']
        sec_id = ev['secondary_id'] # ID utilizado para diferenciar objetos com mesmo nome
        
        tle_p1 = ev['primary_tle_line1']
        tle_p2 = ev['primary_tle_line2']
        tle_s1 = ev['secondary_tle_line1']
        tle_s2 = ev['secondary_tle_line2']
        
        tle_prim = TLE(tle_p1, tle_p2)
        tle_sec = TLE(tle_s1, tle_s2)
        
        tca_orekit = AbsoluteDate(tca_dt.year, tca_dt.month, tca_dt.day, 
                                  tca_dt.hour, tca_dt.minute, float(tca_dt.second), utc)
            
        prop_prim = TLEPropagator.selectExtrapolator(tle_prim)
        prop_sec = TLEPropagator.selectExtrapolator(tle_sec)
        
        t_delta = np.arange(-win_s, win_s + step_s, step_s)
        
        pos_p = {'x': [], 'y': [], 'z': []}
        pos_s = {'x': [], 'y': [], 'z': []}
        
        # Propagação para criar as linhas das órbitas
        for t in t_delta:
            date_eval = tca_orekit.shiftedBy(float(t))
            pv_p = prop_prim.propagate(date_eval).getPVCoordinates().getPosition()
            pv_s = prop_sec.propagate(date_eval).getPVCoordinates().getPosition()
            
            # Coordenadas em km
            pos_p['x'].append(pv_p.getX() / 1000.0)
            pos_p['y'].append(pv_p.getY() / 1000.0)
            pos_p['z'].append(pv_p.getZ() / 1000.0)
            
            pos_s['x'].append(pv_s.getX() / 1000.0)
            pos_s['y'].append(pv_s.getY() / 1000.0)
            pos_s['z'].append(pv_s.getZ() / 1000.0)
            
        # Posição exata no instante do TCA
        tca_pv_p = prop_prim.propagate(tca_orekit).getPVCoordinates().getPosition()
        tca_pv_s = prop_sec.propagate(tca_orekit).getPVCoordinates().getPosition()
        
        tca_p_km = [tca_pv_p.getX()/1000.0, tca_pv_p.getY()/1000.0, tca_pv_p.getZ()/1000.0]
        tca_s_km = [tca_pv_s.getX()/1000.0, tca_pv_s.getY()/1000.0, tca_pv_s.getZ()/1000.0]

        # --- Início da Plotagem 3D ---
        fig = plt.figure(figsize=(10, 8))
        ax = fig.add_subplot(111, projection='3d')
        
        plot_earth(ax)
        
        # Plotar as trajetórias
        ax.plot(pos_p['x'], pos_p['y'], pos_p['z'], label=f"{target_name} ({target_id})", color='#1f77b4', linewidth=2)
        ax.plot(pos_s['x'], pos_s['y'], pos_s['z'], label=f"{sec_name} ({sec_id})", color='#d62728', linewidth=2)
        
        # Marcar os pontos do TCA
        ax.scatter(*tca_p_km, color='blue', s=50, edgecolors='black', zorder=5)
        ax.scatter(*tca_s_km, color='red', s=50, edgecolors='black', zorder=5, marker='X', label='TCA')
        
        # Configurar limites simétricos para manter a proporção da Terra correta (aspect ratio)
        max_range = 8000 # Escala em km. LEO opera até ~8000km do centro da Terra
        ax.set_xlim([-max_range, max_range])
        ax.set_ylim([-max_range, max_range])
        ax.set_zlim([-max_range, max_range])
        
        # Definir a proporção da caixa do gráfico como 1:1:1
        ax.set_box_aspect([1, 1, 1])
        
        ax.set_xlabel('X (km)')
        ax.set_ylabel('Y (km)')
        ax.set_zlabel('Z (km)')
        
        # Título ajustado para incluir o ID
        titulo = f"Trajetória Orbital 3D - TCA\n{target_name} vs {sec_name} (ID: {sec_id})"
        ax.set_title(titulo, fontsize=14, pad=20)
        ax.legend(loc='upper right')
        
        # Ajustar o ângulo de visão inicial para visualizar melhor o cruzamento
        ax.view_init(elev=20., azim=45)
        
        # Salvar a figura de forma individual usando o ID no nome do arquivo
        nome_arquivo = f"orbita_3d_{target_id}_{sec_id}.png"
        out_file = os.path.join(output_dir, nome_arquivo)
        
        plt.tight_layout()
        plt.savefig(out_file, dpi=300, bbox_inches='tight')
        plt.close(fig)
        
        print(f"Gráfico 3D salvo: {out_file}")