# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "requests",
#     "python-dotenv",
# ]
# ///

import requests
import time
import json
import os
from dotenv import load_dotenv

# Carrega as variáveis do arquivo .env para o ambiente
load_dotenv()

def requestTle(primariesID: list):
    print("Downloading data...")

    uriBase = "https://www.space-track.org/"
    uriLogin = f"{uriBase}ajaxauth/login"
    
    uri_gp = "basicspacedata/query/class/gp/"
    uriNotDecayed = "DECAY_DATE/null-val/"
    uriFilterEpoch = "epoch/%3Enow-3/"

    # Verifica se é int ou string
    if isinstance(primariesID[0], int):
        uriReqPri = f"{uriBase}{uri_gp}NORAD_CAT_ID/"
    else:
        uriReqPri = f"{uriBase}{uri_gp}OBJECT_ID/"

    # Monta a string de IDs
    ids_str = ",".join(str(id) for id in primariesID)
    uriReqPri += f"{ids_str}/{uriNotDecayed}{uriFilterEpoch}"

    uriReqSec = f"{uriBase}{uri_gp}{uriNotDecayed}{uriFilterEpoch}"

    # Pega as credenciais carregadas do .env
    user = os.getenv("ST_USER")
    password = os.getenv("ST_PASSWORD")

    if not user or not password:
        print("ERRO: Credenciais não encontradas no arquivo .env")
        return None, None

    siteCred = {
        "identity": user,
        "password": password,
    }

    s = requests.Session()
    resp_login = s.post(uriLogin, data=siteCred)
    
    if resp_login.status_code != 200:
        print(f"Erro no login: {resp_login.status_code}")
        return None, None

    # Request Primaries
    print(f"Requisitando Primários...")
    respP = s.get(uriReqPri)
    
    if respP.status_code == 200:
        primaries = json.loads(respP.text)
    else:
        print(f"Falha ao baixar primários: {respP.text}")
        primaries = []

    timeStruct = time.gmtime()
    file_suffix = f"{timeStruct.tm_year}_{timeStruct.tm_yday}_T{timeStruct.tm_hour}.json"

    # Salvar Primaries
    with open(f"Primaries{file_suffix}", "w+") as fid:
        fid.write(respP.text)

    # Lógica de Cache para Secondaries
    filename_s = f"Secondaries{file_suffix}"
    try:
        with open(filename_s, "r") as fid:
            secondaries = json.loads(fid.read())
            print("Secondaries carregados do arquivo local.")
    except FileNotFoundError:
        print("Baixando Secondaries...")
        respS = s.get(uriReqSec)
        secondaries = json.loads(respS.text)
        with open(filename_s, "w+") as fid:
            fid.write(respS.text)

    return primaries, secondaries

if __name__ == "__main__":
    # Teste com ID da ISS
    p, s = requestTle([25544])
    if p:
        print("Download concluído com sucesso.")