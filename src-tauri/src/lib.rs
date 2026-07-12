use std::io::{Read, Write};
use std::net::TcpStream;
use std::path::PathBuf;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Mutex,
};
use std::thread;
use std::time::{Duration, Instant};

use serde_json::Value;
use tauri::{AppHandle, Manager, WebviewUrl, WebviewWindow, WebviewWindowBuilder, WindowEvent};
use tauri_plugin_shell::{process::CommandChild, ShellExt};
use url::Url;

const CONTROL_URL: &str = "http://127.0.0.1:8790/";
const CONTROL_ADDR: &str = "127.0.0.1:8790";
const CONTROL_HEALTH_PATH: &str = "/api/app/health";
const CONTROL_SERVICE_MARKER: &str = "token-bi-control-panel";
const CONTROL_HEALTH_TIMEOUT: Duration = Duration::from_secs(30);
const CONTROL_HEALTH_POLL_INTERVAL: Duration = Duration::from_millis(200);

type SharedChild = Arc<Mutex<Option<CommandChild>>>;

pub fn run() {
    let cleanup_done = Arc::new(AtomicBool::new(false));
    let sidecar_child: SharedChild = Arc::new(Mutex::new(None));
    let setup_child = sidecar_child.clone();
    let setup_cleanup = cleanup_done.clone();
    let run_child = sidecar_child.clone();
    let run_cleanup = cleanup_done.clone();

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(move |app| {
            let window = create_control_window(app)?;

            let cleanup_child = setup_child.clone();
            let cleanup_flag = setup_cleanup.clone();
            window.on_window_event(move |event| {
                if matches!(event, WindowEvent::CloseRequested { .. }) {
                    stop_app_services_once(&cleanup_child, &cleanup_flag);
                }
            });

            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_focus();
            }

            let startup_window = window.clone();
            let startup_app = app.handle().clone();
            let startup_child = setup_child.clone();
            let startup_cleanup = setup_cleanup.clone();
            thread::spawn(move || {
                let result = ensure_control_panel(&startup_app, &startup_child);
                if startup_cleanup.load(Ordering::SeqCst) {
                    stop_started_services(&startup_child);
                    return;
                }

                match result {
                    Ok(()) => {
                        if let Ok(url) = Url::parse(CONTROL_URL) {
                            if let Err(error) = startup_window.navigate(url) {
                                let script =
                                    bootstrap_error_script("控制台无法打开", &error.to_string());
                                let _ = startup_window.eval(&script);
                            }
                        }
                    }
                    Err(error) => {
                        let script = bootstrap_error_script("本地服务启动失败", &error);
                        let _ = startup_window.eval(&script);
                    }
                }
            });

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Token BI app")
        .run(move |_app_handle, event| {
            if matches!(
                event,
                tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit
            ) {
                stop_app_services_once(&run_child, &run_cleanup);
            }
        });
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

fn create_control_window(app: &tauri::App) -> tauri::Result<WebviewWindow> {
    WebviewWindowBuilder::new(app, "main", WebviewUrl::App(PathBuf::from("index.html")))
        .title("Token BI")
        .inner_size(960.0, 760.0)
        .min_inner_size(720.0, 560.0)
        .resizable(true)
        .build()
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

fn bootstrap_error_script(title: &str, detail: &str) -> String {
    let payload = serde_json::json!({
        "title": title,
        "detail": detail,
    });
    format!(
        "if (window.__TOKEN_BI_BOOTSTRAP__) {{ window.__TOKEN_BI_BOOTSTRAP__.fail({payload}); }}"
    )
}

fn stop_app_services_once(sidecar_child: &SharedChild, cleanup_done: &AtomicBool) {
    if cleanup_done.swap(true, Ordering::SeqCst) {
        return;
    }

    stop_started_services(sidecar_child);
}

fn stop_started_services(sidecar_child: &SharedChild) {
    let shutdown_completed = post_control_shutdown();

    if let Ok(mut guard) = sidecar_child.lock() {
        if let Some(child) = guard.take() {
            if !shutdown_completed {
                let _ = child.kill();
            }
        }
    }
}

fn post_control_shutdown() -> bool {
    let Ok(mut stream) = TcpStream::connect("127.0.0.1:8790") else {
        return false;
    };
    if stream
        .set_read_timeout(Some(Duration::from_secs(15)))
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
    fn bootstrap_error_script_escapes_dynamic_failure_text() {
        let script = bootstrap_error_script("端口被占用", "127.0.0.1:8790 \"busy\"");

        assert!(script.contains("window.__TOKEN_BI_BOOTSTRAP__.fail"));
        assert!(script.contains("\\\"busy\\\""));
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
