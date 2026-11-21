#!/usr/bin/env bash
set -euo pipefail

# Reproduceerbare lokale OSRM-voorbereiding (CH + car.lua) via vastgelegde Docker-image
OSRM_IMAGE="ghcr.io/project-osrm/osrm-backend:v6.0.0"
OSRM_DIR="$(pwd)/data/osrm"
PBF_FILE="${1:-belgium-latest.osm.pbf}"
BASE_NAME="${PBF_FILE%.osm.pbf}"

mkdir -p "${OSRM_DIR}"

if [[ ! -f "${OSRM_DIR}/${PBF_FILE}" ]]; then
  echo "Fout: ${OSRM_DIR}/${PBF_FILE} niet gevonden."
  echo "Download bv. België via:"
  echo "  curl -L -o ${OSRM_DIR}/belgium-latest.osm.pbf https://download.geofabrik.de/europe/belgium-latest.osm.pbf"
  exit 1
fi

echo "==> 1/3 osrm-extract (${PBF_FILE} met /opt/car.lua)"
docker run --rm -v "${OSRM_DIR}:/data" "${OSRM_IMAGE}" \
  osrm-extract -p /opt/car.lua "/data/${PBF_FILE}"

echo "==> 2/3 osrm-contract (Contraction Hierarchies)"
docker run --rm -v "${OSRM_DIR}:/data" "${OSRM_IMAGE}" \
  osrm-contract "/data/${BASE_NAME}.osrm"

echo "==> 3/3 Klaar! Start de OSRM-server met:"
echo "  docker run --rm -p 5000:5000 -v \"${OSRM_DIR}:/data\" ${OSRM_IMAGE} osrm-routed --algorithm ch --max-table-size 1000 \"/data/${BASE_NAME}.osrm\""
