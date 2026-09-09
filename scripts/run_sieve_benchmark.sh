#!/bin/bash
# Roda o screening (sieve) e reporta se a JVM sobreviveu.
#
# O que este script existe para responder: o sieve paralelo segfaultava
# (SIGSEGV em JPClass::invoke) sob Python 3.13 + JPype 1.5.2. Rodando a mesma
# carga com SIEVE_WORKERS>1 em stacks diferentes, o exit code e a presença de
# arquivos hs_err_pid*.log dizem se a variável era a versão do Python.
#
# Variáveis:
#   SIEVE_WORKERS   1 = sequencial, N = ProcessPoolExecutor com N workers
#   OREKIT_JVM_XMX  cap de heap por JVM (ex: -Xmx400m); sem isso cada JVM
#                   reserva ~25% da RAM da máquina
#   BASE_ID         NORAD do primário (default 61046, satélite de teste)
#   DAYS            janela de simulação em dias
#   START_DATE      ISO; fixa a época para a comparação ser reproduzível

set -uo pipefail

BASE_ID="${BASE_ID:-61046}"
DAYS="${DAYS:-5}"
START_DATE="${START_DATE:-2026-09-01T12:00:00+00:00}"
SIEVE_WORKERS="${SIEVE_WORKERS:-1}"

echo "=============================================================="
echo " Sieve benchmark"
echo "=============================================================="
echo "Python        : $(python --version 2>&1)"
echo "JPype         : $(python -c 'import jpype; print(jpype.__version__)' 2>&1)"
echo "orekit_jpype  : $(python -c 'import orekit_jpype; print(getattr(orekit_jpype, "__version__", "?"))' 2>&1)"
echo "CPUs          : $(nproc)"
echo "RAM           : $(free -h 2>/dev/null | awk '/^Mem:/{print $2}')"
echo "SIEVE_WORKERS : ${SIEVE_WORKERS}"
echo "OREKIT_JVM_XMX: ${OREKIT_JVM_XMX:-<sem cap>}"
echo "BASE_ID       : ${BASE_ID}"
echo "DAYS          : ${DAYS}"
echo "START_DATE    : ${START_DATE}"
echo "=============================================================="

# hs_err ficam onde o processo rodar; limpa antes para não confundir com runs
# anteriores na mesma máquina.
rm -f /app/hs_err_pid*.log /app/replay_pid*.log

START_TS=$(date +%s)

cd /app
python app/conjunctions/screening.py \
    --base "${BASE_ID}" \
    --days "${DAYS}" \
    --start-date "${START_DATE}"
EXIT_CODE=$?

END_TS=$(date +%s)
ELAPSED=$((END_TS - START_TS))

echo
echo "=============================================================="
echo " Resultado"
echo "=============================================================="
echo "exit code     : ${EXIT_CODE}"
echo "wall time     : ${ELAPSED}s"

# 139 = 128+11 (SIGSEGV). É o sintoma exato que motivou a reversão do paralelo.
if [ "${EXIT_CODE}" -eq 139 ]; then
    echo "veredito      : SEGFAULT (SIGSEGV) — a JVM morreu"
elif [ "${EXIT_CODE}" -ne 0 ]; then
    echo "veredito      : FALHOU com exit ${EXIT_CODE}"
else
    echo "veredito      : OK"
fi

CRASH_LOGS=$(ls /app/hs_err_pid*.log 2>/dev/null | wc -l)
echo "hs_err logs   : ${CRASH_LOGS}"

if [ "${CRASH_LOGS}" -gt 0 ]; then
    for f in /app/hs_err_pid*.log; do
        echo "--- $(basename "$f") ---"
        grep -E "^#  (SIGSEGV|SIGBUS|SIGILL)|^# +Problematic frame|^C +\[|si_addr|^Time: " "$f" | head -8
    done
fi

# Contagem de candidatos, para conferir que o resultado bate entre modos.
LATEST=$(ls -t /app/screenings/screening_"${BASE_ID}"_*.json 2>/dev/null | head -1)
if [ -n "${LATEST}" ]; then
    COUNT=$(python -c "import json,sys; print(len(json.load(open(sys.argv[1]))))" "${LATEST}" 2>/dev/null)
    echo "candidatos    : ${COUNT}  (${LATEST})"
    echo "sha256 result : $(python -c "
import json,sys,hashlib
d=json.load(open(sys.argv[1]))
# ordena para que a comparação sequencial-vs-paralelo não dependa da ordem
k=sorted((str(c.get('secondary_id')), str(c.get('tca'))) for c in d)
print(hashlib.sha256(repr(k).encode()).hexdigest()[:16])
" "${LATEST}" 2>/dev/null)"
else
    echo "candidatos    : <nenhum arquivo de screening gerado>"
fi
echo "=============================================================="

exit "${EXIT_CODE}"
