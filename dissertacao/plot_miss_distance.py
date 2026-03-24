import json
import math
import sys
from datetime import datetime
import os

target = 61046
file_path = '/home/guima/dissertacao/cenario1/analysis_results/analysis_61046_1771846714.json'
output_dir = '/home/guima/.gemini/antigravity/brain/8caa922b-39a3-4df1-9e38-5f28ee4c6758/'

with open(file_path, 'r') as f:
    events = json.load(f)

start_win = datetime(2026, 2, 19, 12, 0, 0)
end_win = datetime(2026, 2, 24, 12, 0, 0)

# Sem matplotlib disponivel, gerando texto ASCII para rascunho em LaTeX utilizando pgfplots ou similar.
# Como o usuario pediu graficos Matplotlib e a maquina isolada nao tem pip/matplotlib pre-instalado, 
# vou escrever o texto para PgFplots Tikz diretamente no documento ou rodar matplotlib se for via docker.
# Porem o comando \`pip\` nao estava no python3 da instance atual.
# Vamos criar um script minimalista que escreve os dados (x, y) de forma tabular para importacao no PgfPlots.

print("Gerar arquivo .dat para pgfplot do LaTeX já que Matplotlib nao esta instalado.")

out_data = ""
idx = 1
for ev in events:
    tca_str = ev['tca_utc'].split('.')[0]
    tca = datetime.strptime(tca_str, '%Y-%m-%dT%H:%M:%S')
    
    if start_win <= tca <= end_win:
        v_rel = ev['relative_speed_m_s']
        min_dist = ev['min_distance_m']
        
        # Gerar 30 pontos +/- 30s do TCA
        out_data += f"% Curva evento {idx}: vs {ev['secondary_name']}\n"
        out_data += f"tempo_relativo_s dist_km\n"
        
        for t in range(-30, 31, 2):
            dist = math.sqrt(min_dist**2 + (v_rel * t)**2) / 1000.0
            out_data += f"{t} {dist:.3f}\n"
            
        out_data += "\n\n"
        idx += 1

with open(os.path.join(output_dir, "miss_distance_61046.dat"), "w") as f:
    f.write(out_data)

print(f"Dados gerados em {output_dir}/miss_distance_61046.dat para plotting Tikz/PGFPlots")
