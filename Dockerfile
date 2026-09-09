# Imagem para rodar a dissertação como job (Cloud Run Job / GCE).
#
# A versão do Python e do stack JPype/Orekit são build args porque o objetivo
# imediato é justamente isolá-las: o sieve paralelo segfaultava em
# Python 3.13 + JPype 1.5.2 (SIGSEGV em JPClass::invoke), e precisamos saber
# se a variável é a versão do Python ou o JPype/Orekit.
#
#   docker build --build-arg PYTHON_VERSION=3.11 ...
#   docker build --build-arg PYTHON_VERSION=3.13 ...
ARG PYTHON_VERSION=3.11
FROM python:${PYTHON_VERSION}-slim-bookworm

ARG JPYPE_VERSION=1.5.2
ARG OREKIT_JPYPE_VERSION=13.1.3.0

# JRE para a JVM do JPype. procps entra para o `free`/`nproc` do relatório.
RUN apt-get update && apt-get install -y --no-install-recommends \
        openjdk-17-jre-headless \
        procps \
    && rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64

WORKDIR /app

# Instalação direta em vez de `uv sync`: o uv.lock do repo foi resolvido para
# >=3.13 e não serve para 3.11. As versões de JPype/Orekit vêm dos build args
# para que a imagem descreva exatamente o stack sob teste.
RUN pip install --no-cache-dir \
        "JPype1==${JPYPE_VERSION}" \
        "orekit_jpype==${OREKIT_JPYPE_VERSION}" \
        "numpy>=2.0" \
        "pymoo>=0.6.1.6" \
        "python-dotenv>=1.0" \
        "requests>=2.32"

# orekit-data vai assado na imagem: em job, deixar o setup_orekit() baixar do
# branch `main` em runtime tornaria os dados físicos um alvo móvel entre runs.
COPY orekit-data/ /app/orekit-data/
ENV OREKIT_DATA_FOLDER=/app/orekit-data

# TLE.json também vai assado. Congelar a entrada é requisito do experimento:
# requestTles() usa o cache local sem checar idade, então a imagem fixa
# exatamente qual catálogo os dois lados da comparação enxergam.
COPY TLE.json /app/TLE.json

COPY app/ /app/app/
COPY cenario1/ /app/cenario1/
COPY cenario2/ /app/cenario2/
COPY satellites_list.txt pyproject.toml /app/

COPY scripts/ /app/scripts/
RUN chmod +x /app/scripts/*.sh

ENTRYPOINT ["/app/scripts/run_sieve_benchmark.sh"]
