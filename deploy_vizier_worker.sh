#!/bin/bash
set -e

PROJECT_ID="cosmos-project-479403"
REGION="southamerica-east1"
REPO_NAME="cosmos-repo"
IMAGE_NAME="vizier-worker"
IMAGE_TAG="latest"

IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${IMAGE_NAME}:${IMAGE_TAG}"

echo "🚀 Iniciando processo de deploy do Worker do Vizier..."

# 1. Autenticar no Artifact Registry (se necessário)
echo "📦 Configurando credenciais Docker..."
gcloud auth configure-docker ${REGION}-docker.pkg.dev --quiet

# 2. Build da Imagem Docker
echo "🔨 Construindo a imagem Docker localmente..."
docker build -t ${IMAGE_URI} .

# 3. Push da Imagem para o Artifact Registry
echo "☁️ Fazendo Push da imagem para o Google Cloud..."
docker push ${IMAGE_URI}

# 4. Criar ou Atualizar o Cloud Run Job
echo "⚙️ Criando/Atualizando o Cloud Run Job..."
gcloud run jobs deploy vizier-optimizer-job \
  --project=${PROJECT_ID} \
  --region=${REGION} \
  --image=${IMAGE_URI} \
  --vpc-connector=projects/${PROJECT_ID}/locations/${REGION}/connectors/cosmos-connector \
  --memory=4Gi \
  --cpu=2 \
  --max-retries=3 \
  --task-timeout=1h \
  --parallelism=10 \
  --execute-now

echo "✅ Deploy concluído e Job executado!"
echo "Acompanhe os logs rodando: gcloud run jobs executions logs read vizier-optimizer-job --project=${PROJECT_ID} --region=${REGION}"
