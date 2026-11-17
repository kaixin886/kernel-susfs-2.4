#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROFILE="$SCRIPT_DIR/odin-schedutil-fast-down.sh"
if [[ "$EUID" -ne 0 ]]; then
  if ! command -v sudo >/dev/null 2>&1; then
    echo "ERROR: run as root or install sudo" >&2
    exit 1
  fi
  exec sudo -- bash "$0" "$@"
fi

TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/odin-schedutil-test.XXXXXXXX")"
cleanup() {
  if [[ -n "${TEST_ROOT:-}" && -d "$TEST_ROOT" && ! -L "$TEST_ROOT" ]]; then
    case "$TEST_ROOT" in
      "${TMPDIR:-/tmp}"/odin-schedutil-test.*) rm -rf -- "$TEST_ROOT" ;;
      *) echo "Refusing to remove unexpected test path: $TEST_ROOT" >&2 ;;
    esac
  fi
}
trap cleanup EXIT

SYSFS_ROOT="$TEST_ROOT/sys"
STATE_FILE="$TEST_ROOT/state/profile.state"
BOOT_ID_FILE="$TEST_ROOT/boot_id"
POLICY_ROOT="$SYSFS_ROOT/devices/system/cpu/cpufreq"
mkdir -p "$POLICY_ROOT/policy0/schedutil" "$POLICY_ROOT/policy4/schedutil"
printf 'schedutil\n' > "$POLICY_ROOT/policy0/scaling_governor"
printf 'schedutil\n' > "$POLICY_ROOT/policy4/scaling_governor"
printf '1200\n' > "$POLICY_ROOT/policy0/schedutil/up_rate_limit_us"
printf '1500\n' > "$POLICY_ROOT/policy0/schedutil/down_rate_limit_us"
printf '2500\n' > "$POLICY_ROOT/policy4/schedutil/up_rate_limit_us"
printf '3000\n' > "$POLICY_ROOT/policy4/schedutil/down_rate_limit_us"
printf 'boot-a\n' > "$BOOT_ID_FILE"

run_profile() {
  SYSFS_ROOT="$SYSFS_ROOT" STATE_FILE="$STATE_FILE" BOOT_ID_FILE="$BOOT_ID_FILE" \
    sh "$PROFILE" "$@"
}
assert_value() {
  local path="$1" expected="$2" actual
  actual="$(cat "$path")"
  [[ "$actual" == "$expected" ]] || {
    echo "FAIL: $path expected '$expected', got '$actual'" >&2
    exit 1
  }
}

sh -n "$PROFILE"
run_profile apply
grep -qx 'boot_id|boot-a' "$STATE_FILE"
assert_value "$POLICY_ROOT/policy0/schedutil/down_rate_limit_us" 0
assert_value "$POLICY_ROOT/policy4/schedutil/down_rate_limit_us" 0
assert_value "$POLICY_ROOT/policy0/schedutil/up_rate_limit_us" 1200
assert_value "$POLICY_ROOT/policy4/schedutil/up_rate_limit_us" 2500
run_profile restore
assert_value "$POLICY_ROOT/policy0/schedutil/down_rate_limit_us" 1500
assert_value "$POLICY_ROOT/policy4/schedutil/down_rate_limit_us" 3000
[[ ! -e "$STATE_FILE" ]]
echo 'PASS: same-boot apply/restore preserves exact per-policy values'

run_profile apply >/dev/null
printf 'boot-b\n' > "$BOOT_ID_FILE"
printf '700\n' > "$POLICY_ROOT/policy0/schedutil/down_rate_limit_us"
restore_output="$(run_profile restore)"
grep -q 'boot changed since apply' <<< "$restore_output"
assert_value "$POLICY_ROOT/policy0/schedutil/down_rate_limit_us" 700
[[ ! -e "$STATE_FILE" ]]
echo 'PASS: stale rollback snapshot after reboot performs no tunable writes'

printf 'performance\n' > "$POLICY_ROOT/policy4/scaling_governor"
printf '900\n' > "$POLICY_ROOT/policy0/schedutil/down_rate_limit_us"
printf '800\n' > "$POLICY_ROOT/policy4/schedutil/down_rate_limit_us"
if run_profile apply > "$TEST_ROOT/non-schedutil.log" 2>&1; then
  echo 'FAIL: apply unexpectedly accepted a non-schedutil policy' >&2
  exit 1
fi
grep -q 'not schedutil; no policies were changed' "$TEST_ROOT/non-schedutil.log"
assert_value "$POLICY_ROOT/policy0/schedutil/down_rate_limit_us" 900
assert_value "$POLICY_ROOT/policy4/schedutil/down_rate_limit_us" 800
[[ ! -e "$STATE_FILE" ]]
if find "$TEST_ROOT/state" -type f -print -quit | grep -q .; then
  echo 'FAIL: failed apply left a temporary or rollback state file' >&2
  exit 1
fi
echo 'PASS: non-schedutil policy is rejected before any policy is changed'

status_before="$(cat "$POLICY_ROOT/policy0/schedutil/down_rate_limit_us")"
run_profile status >/dev/null
assert_value "$POLICY_ROOT/policy0/schedutil/down_rate_limit_us" "$status_before"
echo 'PASS: status is read-only'
