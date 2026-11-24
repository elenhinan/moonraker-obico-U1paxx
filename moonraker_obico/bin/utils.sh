#!/usr/bin/env bash -e

debian_release() {
  if [ -f /etc/debian_version ]; then
    cut -d '.' -f1 /etc/debian_version
  fi
}

os_bit() {
  if command -v getconf >/dev/null 2>&1; then
    getconf LONG_BIT
  elif [ "$(uname -m)" = "aarch64" ] || [ "$(uname -m)" = "x86_64" ]; then
    echo "64"
  else
    echo "32"
  fi
}

debian_variant() {
  echo $( board_id ).debian.$( debian_release ).$( os_bit )-bit
}

precompiled_dir() {
  local root="$1"
  local exact="${root}/$( debian_variant )"
  if [ -d "${exact}" ]; then
    echo "${exact}"
    return
  fi

  local current_ver bit board prefix suffix
  current_ver=$( debian_release )
  case "${current_ver}" in
    ''|*[!0-9]*)
      echo "${exact}"
      return
      ;;
  esac
  bit=$( os_bit )-bit
  board=$( board_id )
  prefix="${board}.debian."
  suffix=".${bit}"

  local best_le_ver=-1 best_le_dir=""
  local best_gt_ver=-1 best_gt_dir=""
  local d name ver
  if [ -d "${root}" ]; then
    for d in "${root}"/${prefix}*${suffix}; do
      [ -d "$d" ] || continue
      name="${d##*/}"
      ver="${name#${prefix}}"
      ver="${ver%${suffix}}"
      case "$ver" in
        ''|*[!0-9]*) continue;;
      esac
      if [ "$ver" -le "$current_ver" ]; then
        if [ "$ver" -gt "$best_le_ver" ]; then
          best_le_ver="$ver"; best_le_dir="$d"
        fi
      else
        if [ "$best_gt_ver" -lt 0 ] || [ "$ver" -lt "$best_gt_ver" ]; then
          best_gt_ver="$ver"; best_gt_dir="$d"
        fi
      fi
    done
  fi

  if [ -n "${best_le_dir}" ]; then
    echo "${best_le_dir}"
  elif [ -n "${best_gt_dir}" ]; then
    echo "${best_gt_dir}"
  else
    echo "${exact}"
  fi
}

board_id() {
    local model_file="/sys/firmware/devicetree/base/model"

    if [ -f "$model_file" ]; then
        if grep -q -i -e "Raspberry" $model_file; then
            echo "rpi"
        elif grep -q -i -e "Makerbase" -e "roc-rk3328-cc" $model_file; then # Somehow some mks boards have 'Firefly roc-rk3328-cc' in /sys/firmware/devicetree/base/model
	    echo "mks"
        elif grep -q -i -e "rk3562" "$model_file" && [ -f /etc/os-release ] && grep -q -i -e "snapmaker" /etc/os-release; then
            echo "u1"
        else
            echo "NA"
        fi
    else
        echo "NA"
    fi
}
