import json
from datetime import datetime, timezone
import os

def pt(v, fmt):
    return f"{v:{fmt}}".replace('.', ',')

targets = {
    61046: 'SPACEMOBILE-005',
    64830: 'KUIPER-00084',
    65774: 'KUIPER-00155'
}

start_win = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
end_win = datetime(2026, 2, 24, 12, 0, 0, tzinfo=timezone.utc)

def parse_tca(tca_str):
    tca_str = tca_str.split('.')[0]
    return datetime.strptime(tca_str, '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)

def tle_to_elements(line1, line2):
    # a simple extraction of relevant elements from TLE line 2
    # Field 3: Inclination (degrees)
    inc = float(line2[8:16])
    # Field 4: Right Ascension of the Ascending Node (degrees)
    raan = float(line2[17:25])
    # Field 5: Eccentricity (decimal point assumed)
    ecc = float("0." + line2[26:33])
    # Field 6: Argument of Perigee (degrees)
    argp = float(line2[34:42])
    # Field 7: Mean Anomaly (degrees)
    ma = float(line2[43:51])
    # Field 8: Mean Motion (revolutions per day)
    mm = float(line2[52:63])
    
    # Calculate Orbital Period in minutes
    period = 1440.0 / mm
    
    # Calculate semi-major axis (km) using Kepler's Third Law
    # mu = 398600.4418 km^3/s^2, n in rad/s
    mu = 398600.4418
    n_rad_s = mm * 2 * 3.141592653589793 / 86400.0
    a = (mu / (n_rad_s**2))**(1.0/3.0)
    
    # bstar
    bstar_str = line1[53:61]
    # parse bstar
    try:
        if bstar_str.strip() == '':
            bstar = 0.0
        else:
            mantissa = float(bstar_str[0] + '.' + bstar_str[1:6])
            exp = int(bstar_str[6:8])
            bstar = mantissa * (10**exp)
    except:
        bstar = 0.0

    return {
        'a': a,
        'e': ecc,
        'i': inc,
        'raan': raan,
        'argp': argp,
        'ma': ma,
        'n': mm,
        'period': period,
        'bstar': bstar
    }

for target_id, target_name in targets.items():
    file_path = f'/home/guima/dissertacao/cenario1/analysis_results/analysis_{target_id}_1771846714.json'
    if not os.path.exists(file_path):
        import glob
        pattern = f'/home/guima/dissertacao/cenario1/analysis_results/analysis_{target_id}_*.json'
        files = glob.glob(pattern)
        if files:
            file_path = files[0]
        else:
            continue
            
    with open(file_path, 'r') as f:
        events = json.load(f)
        
    filtered = [ev for ev in events if start_win <= parse_tca(ev['tca_utc']) <= end_win]
    
    print(f"% --- Tabelas para {target_name} ---")
    
    for ev in filtered:
        sec_name = ev['secondary_name']
        sec_id = ev['secondary_id']
        elems = tle_to_elements(ev['secondary_tle_line1'], ev['secondary_tle_line2'])
        
        print(f"\\begin{{table}}[H]")
        print(f"    \\centering")
        print(f"    \\caption{{Elementos Orbitais do Secundário - {sec_name} (SSC {sec_id})}}")
        print(f"    \\label{{tab:sec_{target_id}_{sec_id}}}")
        print(f"    \\small")
        print(f"    \\begin{{tabular}}{{lc}}")
        print(f"        \\toprule")
        print(f"        \\textbf{{Parâmetro}} & \\textbf{{Valor}} \\\\")
        print(f"        \\midrule")
        print(f"        Semieixo Maior ($a$) & ${pt(elems['a'], '.3f')}\\text{{ km}}$ \\\\")
        print(f"        Excentricidade ($e$) & ${pt(elems['e'], '.5f')}$ \\\\")
        print(f"        Inclinação ($i$) & ${pt(elems['i'], '.2f')}^\\circ$ \\\\")
        print(f"        RAAN ($\\Omega$) & ${pt(elems['raan'], '.2f')}^\\circ$ \\\\")
        print(f"        Argumento do Perigeu ($\\omega$) & ${pt(elems['argp'], '.2f')}^\\circ$ \\\\")
        print(f"        Anomalia Média ($M$) & ${pt(elems['ma'], '.2f')}^\\circ$ \\\\")
        print(f"        Movimento Médio ($n$) & ${pt(elems['n'], '.2f')}\\text{{ rev/dia}}$ \\\\")
        print(f"        Período Orbital ($T$) & ${pt(elems['period'], '.2f')}\\text{{ min}}$ \\\\")
        
        # Formata o BSTAR com notação científica elegante
        if elems['bstar'] != 0:
            bstar_str = f"{elems['bstar']:.5e}".replace('e', '\\times 10^{').replace('+0', '').replace('-0', '-').replace('.', ',') + '}'
        else:
            bstar_str = "0"
        
        print(f"        BSTAR & ${bstar_str} \\text{{ ER}}^{{-1}}$ \\\\")
        print(f"        \\bottomrule")
        print(f"    \\end{{tabular}}")
        print(f"\\end{{table}}\n")
