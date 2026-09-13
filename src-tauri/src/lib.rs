use std::io::{Read, Write};
use std::net::TcpStream;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Mutex,
};
use std::thread;
use std::time::{Duration, Instant};

use serde_json::Value;
use tauri::AppHandle;
use tauri_plugin_shell::{process::CommandChild, ShellExt};
mod menubar;

const CONTROL_URL: &str = "http://127.0.0.1:8790/";
const CONTROL_ADDR: &str = "127.0.0.1:8790";
const CONTROL_HEALTH_PATH: &str = "/api/app/health";
const CONTROL_SERVICE_MARKER: &str = "token-bi-control-panel";
const CONTROL_HEALTH_TIMEOUT: Duration = Duration::from_secs(30);
const CONTROL_HEALTH_POLL_INTERVAL: Duration = Duration::from_millis(200);

type SharedChild = Arc<Mutex<Option<CommandChild>>>;

pub fn run() {
    menubar::run();
}

fn start_control_panel_sidecar(app: &AppHandle) -> Result<CommandChild, String> {
    let command = app
        .shell()
        .sidecar("token-bi-control")
        .map_err(|error| format!("Unable to locate Token BI backend sidecar: {error}"))?;
    let (mut rx, child) = command
        .args([
            "--host",
            "127.0.0.1",
            "--port",
            "8790",
            "--main-port",
            "8787",
        ])
        .spawn()
        .map_err(|error| format!("Unable to start Token BI backend sidecar: {error}"))?;

    tauri::async_runtime::spawn(async move { while rx.recv().await.is_some() {} });

    Ok(child)
}

fn ensure_control_panel(app: &AppHandle, sidecar_child: &SharedChild) -> Result<(), String> {
    match probe_control_panel_health_once() {
        HealthProbe::Ready => return Ok(()),
        HealthProbe::Invalid(reason) => return Err(reason),
        HealthProbe::Unreachable => {}
    }

    let child = start_control_panel_sidecar(app)?;
    {
        let mut guard = sidecar_child
            .lock()
            .map_err(|_| "Unable to lock sidecar child state.".to_string())?;
        *guard = Some(child);
    }

    wait_for_control_panel_health()
}

fn wait_for_control_panel_health() -> Result<(), String> {
    let deadline = Instant::now() + CONTROL_HEALTH_TIMEOUT;
    while Instant::now() < deadline {
        match probe_control_panel_health_once() {
            HealthProbe::Ready => return Ok(()),
            HealthProbe::Invalid(reason) => return Err(reason),
            HealthProbe::Unreachable => thread::sleep(CONTROL_HEALTH_POLL_INTERVAL),
        }
    }
    Err("Token BI 控制台在 30 秒内未就绪，请重新打开 App 或查看运行日志。".to_string())
}

enum HealthProbe {
    Ready,
    Unreachable,
    Invalid(String),
}

#[derive(Debug, PartialEq, Eq)]
struct ControlHealth {
    service: String,
}

fn probe_control_panel_health_once() -> HealthProbe {
    match read_control_health_response() {
        Ok(response) => match parse_control_health_response(&response) {
            Ok(_health) => HealthProbe::Ready,
            Err(reason) => HealthProbe::Invalid(format!(
                "127.0.0.1:8790 已被占用，但未返回 Token BI 控制台健康信息：{reason}"
            )),
        },
        Err(HealthReadError::Unreachable) => HealthProbe::Unreachable,
        Err(HealthReadError::Invalid(reason)) => HealthProbe::Invalid(reason),
    }
}

enum HealthReadError {
    Unreachable,
    Invalid(String),
}

fn read_control_health_response() -> Result<String, HealthReadError> {
    let mut stream = TcpStream::connect(CONTROL_ADDR).map_err(|_| HealthReadError::Unreachable)?;
    stream
        .set_read_timeout(Some(Duration::from_secs(2)))
        .map_err(|error| HealthReadError::Invalid(error.to_string()))?;
    stream
        .set_write_timeout(Some(Duration::from_secs(2)))
        .map_err(|error| HealthReadError::Invalid(error.to_string()))?;

    let request = format!(
        "GET {CONTROL_HEALTH_PATH} HTTP/1.1\r\nHost: {CONTROL_ADDR}\r\nAccept: application/json\r\nConnection: close\r\n\r\n"
    );
    stream
        .write_all(request.as_bytes())
        .map_err(|error| HealthReadError::Invalid(error.to_string()))?;

    let mut response = String::new();
    stream
        .read_to_string(&mut response)
        .map_err(|error| HealthReadError::Invalid(error.to_string()))?;
    Ok(response)
}

fn parse_control_health_response(response: &str) -> Result<ControlHealth, String> {
    let (headers, body) = response
        .split_once("\r\n\r\n")
        .ok_or_else(|| "健康检查响应格式不完整。".to_string())?;
    if !headers.starts_with("HTTP/1.1 200") && !headers.starts_with("HTTP/1.0 200") {
        return Err("健康检查 HTTP 状态不是 200。".to_string());
    }

    let payload: Value = serde_json::from_str(body.trim())
        .map_err(|error| format!("健康检查 JSON 无法解析：{error}"))?;
    let ok = payload.get("ok").and_then(Value::as_bool).unwrap_or(false);
    let service = payload
        .get("service")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();

    if !ok || service != CONTROL_SERVICE_MARKER {
        return Err("缺少 Token BI 控制台身份标识。".to_string());
    }

    Ok(ControlHealth { service })
}

fn stop_app_services_once(sidecar_child: &SharedChild, cleanup_done: &AtomicBool) {
    if cleanup_done.swap(true, Ordering::SeqCst) {
        return;
    }

    stop_started_services(sidecar_child);
}

fn stop_started_services(sidecar_child: &SharedChild) {
    let owned_child = sidecar_child.lock().ok().and_then(|mut guard| guard.take());
    let Some(child) = owned_child else {
        return;
    };

    if !post_control_shutdown() {
        let _ = child.kill();
    }
}

fn post_control_shutdown() -> bool {
    let Ok(mut stream) = TcpStream::connect("127.0.0.1:8790") else {
        return false;
    };
    if stream
        .set_read_timeout(Some(Duration::from_secs(60)))
        .is_err()
        || stream
            .set_write_timeout(Some(Duration::from_secs(2)))
            .is_err()
    {
        return false;
    }

    let request =
        b"POST /api/app/shutdown HTTP/1.1\r\nHost: 127.0.0.1:8790\r\nContent-Length: 0\r\nConnection: close\r\n\r\n";
    if stream.write_all(request).is_err() {
        return false;
    }

    let mut response = String::new();
    if stream.read_to_string(&mut response).is_err() {
        return false;
    }
    shutdown_response_ok(&response)
}

fn shutdown_response_ok(response: &str) -> bool {
    let Some((headers, body)) = response.split_once("\r\n\r\n") else {
        return false;
    };
    if !headers.starts_with("HTTP/1.1 200") && !headers.starts_with("HTTP/1.0 200") {
        return false;
    }
    serde_json::from_str::<Value>(body.trim())
        .ok()
        .and_then(|payload| payload.get("ok").and_then(Value::as_bool))
        .unwrap_or(false)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_control_health_response_with_token_bi_marker() {
        let response = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{\"ok\":true,\"service\":\"token-bi-control-panel\"}";

        let health = parse_control_health_response(response).expect("health should parse");

        assert_eq!(health.service, "token-bi-control-panel");
    }

    #[test]
    fn rejects_health_response_without_token_bi_marker() {
        let response = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{\"ok\":true}";

        let error = parse_control_health_response(response).expect_err("missing marker must fail");

        assert!(error.contains("Token BI"));
    }

    #[test]
    fn accepts_completed_shutdown_response() {
        let response = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{\"ok\":true}";

        assert!(shutdown_response_ok(response));
        assert!(!shutdown_response_ok(
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{\"ok\":false}"
        ));
    }

    #[test]
    fn control_health_timeout_covers_measured_cold_start() {
        assert!(CONTROL_HEALTH_TIMEOUT >= Duration::from_secs(30));
        assert!(CONTROL_HEALTH_POLL_INTERVAL <= Duration::from_millis(200));
    }
}
