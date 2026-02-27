#!/bin/bash

# Define os intervalos ou listas de valores
BASES=(61046 64830 65774)        # Substitua pelos seus valores de 'i'
SEEDS=$(seq 1 10)     # Gera sequência de 1 a 5 para 'n'

for i in "${BASES[@]}"; do
    for n in $SEEDS; do
        echo "Executando: base $i, seed $n"
        uv run cenario1/compare_maneuver.py --base "$i" --seed "$n" >> maneuvers.txt
    done
done