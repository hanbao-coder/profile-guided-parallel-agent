#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 OUTPUT_DIRECTORY" >&2
  exit 2
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/.." && pwd)"
output_dir="$1"
python_bin="${PYTHON_BIN:-python3}"
ray_bin="${RAY_BIN:-ray}"
extra_site="${PARALLEL_AGENT_EXTRA_SITE:-}"

if [[ -z "${extra_site}" && -d /tmp/pa-ray-site ]]; then
  extra_site=/tmp/pa-ray-site
fi
if ! command -v "${ray_bin}" >/dev/null 2>&1; then
  if [[ -n "${extra_site}" && -x "${extra_site}/bin/ray" ]]; then
    ray_bin="${extra_site}/bin/ray"
  else
    echo "Ray CLI was not found. Activate the project environment first." >&2
    exit 2
  fi
fi

if [[ "${output_dir}" != /* ]]; then
  output_dir="${repo_root}/${output_dir}"
fi
if [[ -e "${output_dir}" ]]; then
  echo "Refusing to overwrite existing formal output: ${output_dir}" >&2
  exit 2
fi

export PYTHONPATH="${repo_root}/src${extra_site:+:${extra_site}}${PYTHONPATH:+:${PYTHONPATH}}"
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export PYTHONUTF8=1
export RAY_USAGE_STATS_ENABLED=0

cleanup() {
  "${ray_bin}" stop --force >/dev/null 2>&1 || true
}
trap cleanup EXIT

mkdir -p "${output_dir}"
for run_index in 1 2 3; do
  cleanup
  run_dir="${output_dir}/run_$(printf '%02d' "${run_index}")"
  echo "[formal-ray] independent run ${run_index}/3"
  (
    cd "${repo_root}"
    "${python_bin}" -m parallel_agent.cli suite \
      --config configs/benchmarks.yaml \
      --scale large \
      --workers 4 \
      --backend ray \
      --repeats 5 \
      --warmups 1 \
      --output-dir "${run_dir}"
  )
done

(
  cd "${repo_root}"
  "${python_bin}" scripts/summarize_ray_formal.py \
    "${output_dir}" \
    "${output_dir}/summary" \
    --expected-runs 3 \
    --expected-workloads 8
)
