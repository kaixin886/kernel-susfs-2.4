#!/system/bin/sh
# Experimental runtime-only schedutil profile for Xiaomi MIX 4 (odin).
# apply: set down_rate_limit_us=0 for every schedutil policy, preserving up rate.
# restore: restore the per-policy values captured by apply.
# No values are written at boot, and this script never changes governor, OPP,
# frequency limits, voltage, CPU topology, IRQ affinity, or thermal policy.
set -eu

SYSFS_ROOT=${SYSFS_ROOT:-/sys}
POLICY_ROOT="$SYSFS_ROOT/devices/system/cpu/cpufreq"
BOOT_ID_FILE=${BOOT_ID_FILE:-/proc/sys/kernel/random/boot_id}
STATE_FILE=${STATE_FILE:-/data/local/tmp/odin-schedutil-fast-down.state}
ACTION=${1:-}

fail() {
    echo "ERROR: $*" >&2
    exit 1
}

is_uint() {
    case "$1" in
        ''|*[!0-9]*) return 1 ;;
        *) return 0 ;;
    esac
}

require_root() {
    [ "$(id -u)" -eq 0 ] || fail "run from a root shell (for example: su -c 'sh $0 apply')"
}

valid_policy_path() {
    case "$1" in
        "$POLICY_ROOT"/policy*) ;;
        *) return 1 ;;
    esac
    name=${1##*/}
    case "$name" in
        policy[0-9]*) ;;
        *) return 1 ;;
    esac
    digits=${name#policy}
    case "$digits" in
        ''|*[!0-9]*) return 1 ;;
        *) return 0 ;;
    esac
}

status() {
    found=0
    for policy in "$POLICY_ROOT"/policy[0-9]*; do
        [ -d "$policy" ] || continue
        found=1
        governor_file="$policy/scaling_governor"
        [ -r "$governor_file" ] || fail "cannot read $governor_file"
        governor=$(cat "$governor_file")
        up_file="$policy/schedutil/up_rate_limit_us"
        down_file="$policy/schedutil/down_rate_limit_us"
        if [ -r "$up_file" ] && [ -r "$down_file" ]; then
            up=$(cat "$up_file")
            down=$(cat "$down_file")
            printf '%s governor=%s up_rate_limit_us=%s down_rate_limit_us=%s\n' \
                "${policy##*/}" "$governor" "$up" "$down"
        else
            printf '%s governor=%s schedutil_tunables=unavailable\n' \
                "${policy##*/}" "$governor"
        fi
    done
    [ "$found" -eq 1 ] || fail "no CPUFreq policies found under $POLICY_ROOT"
    if [ -e "$STATE_FILE" ]; then
        echo "saved rollback state: $STATE_FILE"
    else
        echo "saved rollback state: none"
    fi
}

restore_state() {
    [ -f "$STATE_FILE" ] || fail "rollback state is missing: $STATE_FILE"
    [ -r "$BOOT_ID_FILE" ] || fail "cannot read boot ID: $BOOT_ID_FILE"
    current_boot_id=$(cat "$BOOT_ID_FILE")
    {
        IFS='|' read -r state_header saved_boot_id || fail "rollback state header is missing"
        [ "$state_header" = boot_id ] || fail "rollback state has an unexpected header"
        if [ "$saved_boot_id" != "$current_boot_id" ]; then
            rm -f -- "$STATE_FILE"
            echo "boot changed since apply; runtime tunables were not written and stale state was removed"
            return 0
        fi
        while IFS='|' read -r policy old_up old_down; do
            [ -n "$policy" ] || continue
            valid_policy_path "$policy" || fail "invalid policy path in rollback state: $policy"
            is_uint "$old_up" && is_uint "$old_down" || fail "invalid saved tunable value for $policy"
            up_file="$policy/schedutil/up_rate_limit_us"
            down_file="$policy/schedutil/down_rate_limit_us"
            [ -w "$up_file" ] && [ -w "$down_file" ] || fail "schedutil tunables are unavailable for $policy; switch it back to schedutil and retry"
            printf '%s\n' "$old_up" > "$up_file" || fail "could not restore $up_file"
            printf '%s\n' "$old_down" > "$down_file" || fail "could not restore $down_file"
            printf 'restored %s: up=%s us down=%s us\n' "${policy##*/}" "$old_up" "$old_down"
        done
    } < "$STATE_FILE"
    rm -f -- "$STATE_FILE"
    echo "original per-policy schedutil values restored; state file removed"
}

case "$ACTION" in
    status)
        status
        ;;
    apply)
        require_root
        [ -d "$POLICY_ROOT" ] || fail "CPUFreq policy directory does not exist: $POLICY_ROOT"
        [ -r "$BOOT_ID_FILE" ] || fail "cannot read boot ID: $BOOT_ID_FILE"
        current_boot_id=$(cat "$BOOT_ID_FILE")
        [ -n "$current_boot_id" ] || fail "boot ID is empty: $BOOT_ID_FILE"
        [ ! -e "$STATE_FILE" ] || fail "rollback state already exists; run '$0 restore' before applying again"
        state_dir=${STATE_FILE%/*}
        [ "$state_dir" != "$STATE_FILE" ] || state_dir=.
        mkdir -p "$state_dir" || fail "cannot create state directory: $state_dir"
        state_tmp="$STATE_FILE.tmp.$$"
        (umask 077; set -C; : > "$state_tmp") 2>/dev/null || fail "cannot create temporary rollback state: $state_tmp"
        chmod 600 "$state_tmp" || fail "cannot protect temporary rollback state"
        printf 'boot_id|%s\n' "$current_boot_id" >> "$state_tmp" || { rm -f -- "$state_tmp"; fail "could not save boot ID"; }
        found=0
        for policy in "$POLICY_ROOT"/policy[0-9]*; do
            [ -d "$policy" ] || continue
            found=1
            valid_policy_path "$policy" || { rm -f -- "$state_tmp"; fail "unexpected CPUFreq policy path: $policy"; }
            governor_file="$policy/scaling_governor"
            [ -r "$governor_file" ] || { rm -f -- "$state_tmp"; fail "cannot read $governor_file"; }
            governor=$(cat "$governor_file")
            [ "$governor" = schedutil ] || { rm -f -- "$state_tmp"; fail "${policy##*/} is using '$governor', not schedutil; no policies were changed"; }
            up_file="$policy/schedutil/up_rate_limit_us"
            down_file="$policy/schedutil/down_rate_limit_us"
            [ -r "$up_file" ] && [ -w "$up_file" ] && [ -r "$down_file" ] && [ -w "$down_file" ] || { rm -f -- "$state_tmp"; fail "schedutil tunables are not readable and writable for $policy"; }
            old_up=$(cat "$up_file")
            old_down=$(cat "$down_file")
            is_uint "$old_up" && is_uint "$old_down" || { rm -f -- "$state_tmp"; fail "invalid schedutil tunable value for $policy"; }
            printf '%s|%s|%s\n' "$policy" "$old_up" "$old_down" >> "$state_tmp" || { rm -f -- "$state_tmp"; fail "could not save rollback state"; }
        done
        [ "$found" -eq 1 ] || { rm -f -- "$state_tmp"; fail "no CPUFreq policies found under $POLICY_ROOT"; }
        mv "$state_tmp" "$STATE_FILE" || { rm -f -- "$state_tmp"; fail "could not publish rollback state"; }
        chmod 600 "$STATE_FILE" || fail "could not protect rollback state"
        while IFS='|' read -r policy old_up old_down; do
            [ -n "$policy" ] || continue
            [ "$policy" = boot_id ] && continue
            if ! printf '0\n' > "$policy/schedutil/down_rate_limit_us"; then
                echo "write failed for $policy; attempting rollback" >&2
                restore_state || echo "rollback incomplete; keep $STATE_FILE and retry restore" >&2
                exit 1
            fi
            printf 'applied %s: down_rate_limit_us %s -> 0 us (up remains %s us)\n' \
                "${policy##*/}" "$old_down" "$old_up"
        done < "$STATE_FILE"
        echo "fast-down profile applied for this boot only; use '$0 restore' to roll back"
        ;;
    restore)
        require_root
        restore_state
        ;;
    *)
        echo "Usage: sh $0 {status|apply|restore}" >&2
        echo "  status  Read current per-policy schedutil tunables (no writes)" >&2
        echo "  apply   Set down_rate_limit_us=0 and save exact original values" >&2
        echo "  restore Restore values saved by apply" >&2
        exit 2
        ;;
esac
