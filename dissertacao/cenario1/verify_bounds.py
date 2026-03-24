import json
import glob
import math

bounds = (20000.0, 50000.0, 20000.0)
files = glob.glob("/home/guima/dissertacao/cenario1/*_top5_threats.json")

for f in files:
    with open(f, 'r') as file:
        data = json.load(file)
        
    print(f"\\n--- File: {f.split('/')[-1]} ---")
    
    # Sort by kc_squared ascending (smallest kc2 first)
    data.sort(key=lambda x: x.get('kc_squared', float('inf')))
    top5 = data[:5]
    
    for i, threat in enumerate(top5):
        rd = threat['radial_dist_m']
        ad = threat['along_track_dist_m']
        cd = threat['cross_track_dist_m']
        kc2 = threat.get('kc_squared', None)
        
        ellipsoid_dist_sq = (rd / bounds[0])**2 + (ad / bounds[1])**2 + (cd / bounds[2])**2
        avoided = ellipsoid_dist_sq >= 1.0
        
        print(f"Threat {i+1} (Sec_ID: {threat['secondary_id']}, kc2: {kc2:.4f}):")
        print(f"  Radial: {rd:.2f} m, Along-track: {ad:.2f} m, Cross-track: {cd:.2f} m")
        print(f"  Ellipsoid distance sq: {ellipsoid_dist_sq:.4f} -> Avoided? {avoided}")
