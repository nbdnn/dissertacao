# Imagem base Python oficial
FROM python:3.13-slim

# Evita que o Python grave arquivos .pyc no disco e habilita stdout/stderr limpo
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Instalação do uv (gerenciador rápido de dependências) e dependências do sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    default-jre \
    && curl -LsSf https://astral.sh/uv/install.sh | sh \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/root/.cargo/bin:${PATH}"

WORKDIR /app

# Copia os arquivos de dependência
COPY pyproject.toml uv.lock ./

# Instala as dependências de sistema do projeto usando uv
RUN uv pip install --system -r pyproject.toml

# Copia o resto do código da aplicação
COPY . .

# Variável de ambiente padrão
ENV PROJECT_ID="cosmos-project-479403"
ENV LOCATION="southamerica-east1"

# O Entrypoint é configurado para rodar o script Vizier
ENTRYPOINT ["python", "cenario1/optimize_maneuver_vizier.py"]
