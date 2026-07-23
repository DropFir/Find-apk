#!/bin/sh
set -eu

if [ "$(uname -s)" != "Darwin" ]; then
    echo "tools/cloudflare_faker.sh currently supports macOS only." >&2
    exit 1
fi

faker_script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
faker_agent_root=$(dirname "$faker_script_dir")
faker_vendor_root="$faker_agent_root/tools/vendor"
faker_project="$faker_vendor_root/Cloudflare-Faker"
faker_runtime="$faker_vendor_root/runtime"
faker_java_home="$faker_runtime/jdk24/Contents/Home"
faker_java="$faker_java_home/bin/java"
faker_jar="$faker_project/target/Cloudflare-Faker-0.0.1-SNAPSHOT.jar"
faker_extension="$faker_project/cloudflare_monitor_chrome_plugin"
faker_patch="$faker_script_dir/cloudflare_faker_macos.patch"
faker_pid_file="$faker_runtime/cloudflare-faker.pid"
faker_log_file="$faker_runtime/cloudflare-faker.launch.log"
faker_error_log="$faker_runtime/cloudflare-faker.launch.err"
faker_address="127.0.0.1"
faker_port="8080"
faker_expected_commit="5b0f2a4759d7b84c36e37afbe5c2e6400706b6c6"
faker_launch_label="com.dropfir.findapk.cloudflare-faker"
faker_launch_domain="gui/$(id -u)"

faker_usage() {
    echo "Usage: $0 {build|start|stop|restart|status|check|log|extension-path}" >&2
}

faker_read_pid() {
    [ -f "$faker_pid_file" ] || return 1
    IFS= read -r faker_pid < "$faker_pid_file" || return 1
    case "$faker_pid" in
        ''|*[!0-9]*) return 1 ;;
    esac
}

faker_launch_pid() {
    faker_launch_info=$(launchctl print "$faker_launch_domain/$faker_launch_label" 2>/dev/null) || return 1
    faker_pid=$(printf '%s\n' "$faker_launch_info" | awk '$1 == "pid" && $2 == "=" { print $3; exit }')
    case "$faker_pid" in
        ''|*[!0-9]*) return 1 ;;
    esac
}

faker_pid_is_service() {
    faker_launch_pid || faker_read_pid || return 1
    kill -0 "$faker_pid" 2>/dev/null || return 1
    faker_command=$(ps -p "$faker_pid" -o command= 2>/dev/null || true)
    case "$faker_command" in
        *"$faker_jar"*) return 0 ;;
        *) return 1 ;;
    esac
}

faker_require_files() {
    if [ ! -x "$faker_java" ]; then
        echo "JDK 24 is missing: $faker_java" >&2
        return 1
    fi
    if [ ! -f "$faker_jar" ]; then
        echo "Cloudflare-Faker has not been built: $faker_jar" >&2
        echo "Run: $0 build" >&2
        return 1
    fi
    if [ ! -f "$faker_extension/manifest.json" ]; then
        echo "Chrome extension is missing: $faker_extension" >&2
        return 1
    fi
}

faker_status() {
    if ! faker_pid_is_service; then
        echo "Cloudflare-Faker is stopped"
        return 1
    fi
    if ! curl -fsS --max-time 2 "http://$faker_address:$faker_port/" >/dev/null 2>&1; then
        echo "Cloudflare-Faker process $faker_pid is running but the console is not ready"
        return 2
    fi
    faker_listener=$(lsof -nP -a -p "$faker_pid" -iTCP:"$faker_port" -sTCP:LISTEN 2>/dev/null || true)
    case "$faker_listener" in
        *"$faker_address:$faker_port"*) ;;
        *)
            echo "Cloudflare-Faker is not confirmed on loopback only" >&2
            return 3
            ;;
    esac
    faker_connections=$(curl -fsS --max-time 2 "http://$faker_address:$faker_port/console/connections" 2>/dev/null || true)
    faker_client_count=$(printf '%s\n' "$faker_connections" | sed -n 's/.*"count":\([0-9][0-9]*\).*/\1/p')
    if [ -n "$faker_client_count" ]; then
        echo "Cloudflare-Faker is ready on http://$faker_address:$faker_port (pid $faker_pid, Chrome clients $faker_client_count)"
    else
        echo "Cloudflare-Faker is ready on http://$faker_address:$faker_port (pid $faker_pid, Chrome client status unknown)"
    fi
}

faker_check() {
    faker_status
    faker_connections=$(curl -fsS --max-time 2 "http://$faker_address:$faker_port/console/connections" 2>/dev/null || true)
    faker_client_count=$(printf '%s\n' "$faker_connections" | sed -n 's/.*"count":\([0-9][0-9]*\).*/\1/p')
    case "$faker_client_count" in
        ''|0)
            echo "Cloudflare-Faker Chrome extension is not connected" >&2
            return 4
            ;;
        *)
            faker_health_response=$(curl -fsS --max-time 10 \
                -H 'Content-Type: application/json' \
                -X POST "http://$faker_address:$faker_port/api/remote-html" \
                --data-binary '{"pageUrl":"http://127.0.0.1:8080/","script":"","type":"LOAD_HTML"}' \
                2>/dev/null || true)
            case "$faker_health_response" in
                *'"html":'*'Cloudflare-Faker Dashboard'*)
                    echo "Cloudflare-Faker Chrome extension is connected and executable"
                    ;;
                *)
                    echo "Cloudflare-Faker Chrome extension is connected but failed the execution check" >&2
                    printf '%s\n' "$faker_health_response" | cut -c 1-500 >&2
                    return 5
                    ;;
            esac
            ;;
    esac
}

faker_build() {
    if [ ! -x "$faker_java" ]; then
        echo "JDK 24 is missing: $faker_java" >&2
        exit 1
    fi
    if [ ! -x "$faker_project/mvnw" ]; then
        echo "Cloudflare-Faker checkout is missing: $faker_project" >&2
        exit 1
    fi
    faker_commit=$(git -C "$faker_project" rev-parse HEAD)
    if [ "$faker_commit" != "$faker_expected_commit" ]; then
        echo "Unexpected Cloudflare-Faker commit: $faker_commit" >&2
        echo "Expected: $faker_expected_commit" >&2
        exit 1
    fi
    if git -C "$faker_project" apply --reverse --check "$faker_patch" >/dev/null 2>&1; then
        :
    elif git -C "$faker_project" apply --check "$faker_patch" >/dev/null 2>&1; then
        git -C "$faker_project" apply "$faker_patch"
    else
        echo "Cloudflare-Faker local compatibility patch cannot be applied cleanly" >&2
        exit 1
    fi
    JAVA_HOME="$faker_java_home" PATH="$faker_java_home/bin:$PATH" \
        "$faker_project/mvnw" -f "$faker_project/pom.xml" \
        -Dmaven.test.skip=true -Djavacpp.platform=macosx-arm64 package
}

faker_start() {
    faker_require_files
    mkdir -p "$faker_runtime"
    if faker_pid_is_service; then
        faker_status
        return 0
    fi
    if launchctl print "$faker_launch_domain/$faker_launch_label" >/dev/null 2>&1; then
        launchctl remove "$faker_launch_label" || true
        sleep 1
    fi
    if faker_read_pid; then
        rm -f "$faker_pid_file"
    fi
    if lsof -nP -iTCP:"$faker_port" -sTCP:LISTEN 2>/dev/null | grep -q .; then
        echo "Port $faker_port is already in use; Cloudflare-Faker was not started" >&2
        exit 1
    fi

    launchctl submit -l "$faker_launch_label" \
        -o "$faker_log_file" -e "$faker_error_log" -- \
        "$faker_java" -jar "$faker_jar" \
        --server.address="$faker_address" --server.port="$faker_port"

    faker_waited=0
    while [ "$faker_waited" -lt 45 ]; do
        if faker_launch_pid; then
            echo "$faker_pid" > "$faker_pid_file"
        fi
        if curl -fsS --max-time 2 "http://$faker_address:$faker_port/" >/dev/null 2>&1; then
            faker_status
            return 0
        fi
        sleep 1
        faker_waited=$((faker_waited + 1))
    done

    echo "Cloudflare-Faker did not become ready within 45 seconds" >&2
    tail -n 60 "$faker_log_file" >&2 || true
    tail -n 60 "$faker_error_log" >&2 || true
    launchctl remove "$faker_launch_label" 2>/dev/null || true
    exit 1
}

faker_stop() {
    if ! faker_pid_is_service; then
        echo "Cloudflare-Faker is already stopped"
        rm -f "$faker_pid_file"
        return 0
    fi
    launchctl remove "$faker_launch_label"
    faker_waited=0
    while kill -0 "$faker_pid" 2>/dev/null && [ "$faker_waited" -lt 10 ]; do
        sleep 1
        faker_waited=$((faker_waited + 1))
    done
    if kill -0 "$faker_pid" 2>/dev/null; then
        echo "Cloudflare-Faker did not stop cleanly (pid $faker_pid)" >&2
        exit 1
    fi
    rm -f "$faker_pid_file"
    echo "Cloudflare-Faker stopped"
}

faker_action=${1:-}
case "$faker_action" in
    build) faker_build ;;
    start) faker_start ;;
    stop) faker_stop ;;
    restart) faker_stop; faker_start ;;
    status) faker_status ;;
    check) faker_check ;;
    log) tail -n 80 "$faker_log_file"; tail -n 80 "$faker_error_log" ;;
    extension-path) echo "$faker_extension" ;;
    *) faker_usage; exit 2 ;;
esac
