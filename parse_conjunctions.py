import json
import glob
from datetime import datetime

start = datetime(2026, 2, 19, 12, 0, 0)
end = datetime(2026, 2, 24, 12, 0, 0)

targets = [61046, 64830, 65774]

files = glob.glob('/home/guima/dissertacao/cenario1/analysis_results/*.json')
for f in files:
    with open(f, 'r') as file:
        data = json.load(file)
        if not data: continue
        
        pid = data[0]['primary_id']
        if pid in targets:
            print(f"--- SAT {pid} ---")
            count = 0
            for ev in data:
                tca_str = ev['tca_utc'].split('.')[0]
                tca = datetime.strptime(tca_str, '%Y-%m-%dT%H:%M:%S')
                if start <= tca <= end:
                    count += 1
                    print(f"vs {ev['secondary_name']} ({ev['secondary_id']}) | TCA: {tca_str} | Dist: {ev['min_distance_m']:.2f}m | kc2: {ev['kc_squared']:.4f}")
            print(f"Total na janela: {count}\n")
