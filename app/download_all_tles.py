import requests
import json
import os
import sys
from dotenv import load_dotenv

# Carrega variáveis de ambiente (.env)
load_dotenv()


def requestTles():

    filename = "TLE.json"

    # 2. Tenta carregar do cache local primeiro
    if os.path.exists(filename):
        print(f"📦 Cache encontrado: {filename}")
        try:
            with open(filename, "r") as fid:
                tles = json.load(fid)
                print(f"✅ Carregado {len(tles)} objetos do arquivo local.")
                return tles
        except json.JSONDecodeError:
            print("⚠️ Arquivo corrompido ou vazio. Baixando novamente...")

    # ====================================================
    # Se chegou aqui, precisa baixar do Space-Track
    # ====================================================
    print("🌍 Cache não encontrado. Iniciando download de TODOS os objetos...")
    print("⏳ Isso pode levar alguns segundos...")

    uriBase = "https://www.space-track.org/"
    uriLogin = f"{uriBase}ajaxauth/login"

    uri_gp = "basicspacedata/query/class/gp/"
    uriNotDecayed = "DECAY_DATE/null-val/"
    uriFilterEpoch = "epoch/%3Enow-3/"

    # URI para pegar TUDO que não decaiu e foi atualizado nos últimos 3 dias
    uriReq = f"{uriBase}{uri_gp}{uriNotDecayed}{uriFilterEpoch}"

    # Credenciais via .env (Mais seguro)
    user = os.getenv("ST_USER")
    password = os.getenv("ST_PASSWORD")

    if not user or not password:
        print("❌ ERRO: Credenciais não encontradas no arquivo .env")
        sys.exit(1)

    siteCred = {
        "identity": user,
        "password": password,
    }

    s = requests.Session()

    # Login
    print("🔑 Autenticando...")
    resp_login = s.post(uriLogin, data=siteCred)
    if resp_login.status_code != 200:
        print(f"❌ Erro no login: {resp_login.status_code}")
        return None

    # Download
    print("⬇️ Baixando catálogo completo...")
    resp = s.get(uriReq)

    if resp.status_code == 200:
        tles = json.loads(resp.text)

        # Salva o arquivo
        with open(filename, "w+") as fid:
            # fid.write(resp.text)  # Assim salva como string
            json.dump(tles, fid, indent=0)  # Assim salva formatado (opcional)

        print(f"💾 Sucesso! {len(tles)} objetos salvos em: {filename}")
        return tles
    else:
        print(f"❌ Erro no download: {resp.text}")
        return []


if __name__ == "__main__":
    import argparse

    # 1. Configura para receber os IDs via linha de comando
    parser = argparse.ArgumentParser(
        description="Busca TLEs específicos no catálogo completo."
    )

    parser.add_argument(
        "ids",
        nargs='*',
        help="Lista de NORAD IDs (ex: 25544 20580)."
    )

    args = parser.parse_args()

    # 2. Baixa TUDO (ou pega do cache)
    all_data = requestTles()

    if all_data:
        # ---------------------------------------------------------
        # OTIMIZAÇÃO: Cria um "Mapa" para busca rápida (Hash Map)
        # Chave = ID, Valor = Dados do Satélite
        # ---------------------------------------------------------
        print("Mapeando dados para busca rápida...")
        tle_map = {str(sat['NORAD_CAT_ID']): sat for sat in all_data}

        # Se o usuário não passou nada no terminal, usa essa lista de teste
        target_ids = args.ids if args.ids else ['25544', '47699', '123456']

        print(f"\n🔍 Buscando informações para: {target_ids}")
        print("=" * 60)

        for search_id in target_ids:
            search_id = str(search_id)

            # Busca direta no mapa (muito rápido)
            found_sat = tle_map.get(search_id)

            if found_sat:
                print(f"🛰️  OBJETO: {found_sat.get('OBJECT_NAME')}")
                print(f"    NORAD:  {found_sat.get('NORAD_CAT_ID')}")
                print(f"    Line 1: {found_sat.get('TLE_LINE1')}")
                print(f"    Line 2: {found_sat.get('TLE_LINE2')}")
            else:
                print(f"❌  NORAD {search_id}: Não encontrado no catálogo.")

            print("-" * 60)
