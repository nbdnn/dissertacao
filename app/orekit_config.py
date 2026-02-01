import os
import shutil
import sys
import urllib.request
import zipfile

from dotenv import load_dotenv

import orekit_jpype


def setup_orekit():
    """
    Verifica, baixa e carrega os dados físicos necessários para o Orekit.
    """
    # 1. Inicializa a JVM se necessário
    # O initVM do orekit_jpype deve lidar com chamadas repetidas
    try:
        orekit_jpype.initVM()
    except Exception:
        pass

    # Imports Java internos para evitar erros de inicialização e linting global
    from java.io import File  # type: ignore[reportMissingImports]
    from org.orekit.data import (  # type: ignore[reportMissingImports]
        DataContext,
        DirectoryCrawler,
    )

    load_dotenv()

    target_folder = os.getenv("OREKIT_DATA_FOLDER", "orekit-data")
    zip_filename = os.getenv("OREKIT_DATA_ZIP", "orekit-data-main.zip")
    default_url = (
        "https://gitlab.orekit.org/orekit/orekit-data/-/archive/main/"
        "orekit-data-main.zip"
    )
    url = os.getenv("OREKIT_DATA_URL", default_url)

    # --- ETAPA 1: VERIFICAÇÃO E DOWNLOAD ---
    if not os.path.exists(target_folder):
        print(f"⚠️  Configuração inicial: Pasta '{target_folder}' ausente.")

        if not os.path.exists(zip_filename):
            print("⬇️  Baixando dados do Orekit (pode demorar)...")
            try:
                urllib.request.urlretrieve(url, zip_filename)
                print("✅ Download concluído.")
            except Exception as e:
                print(f"❌ Erro crítico ao baixar dados: {e}")
                sys.exit(1)

        print("📦 Extraindo arquivos...")
        try:
            with zipfile.ZipFile(zip_filename, 'r') as zip_ref:
                zip_ref.extractall(".")

            # Renomeia a pasta extraída para o padrão 'orekit-data'
            if os.path.exists("orekit-data-main"):
                shutil.move("orekit-data-main", target_folder)
                print(f"✅ Pasta configurada: {target_folder}")
        except Exception as e:
            print(f"❌ Erro ao extrair: {e}")
            sys.exit(1)

    # --- ETAPA 2: CARREGAMENTO NO OREKIT ---
    orekit_data_dir = File(target_folder)

    if not orekit_data_dir.exists():
        print(f"❌ Erro: '{target_folder}' não encontrado após extração.")
        sys.exit(1)

    manager = DataContext.getDefault().getDataProvidersManager()

    # Evita adicionar o provider duplicado
    if not manager.getProviders():
        manager.addProvider(DirectoryCrawler(orekit_data_dir))
