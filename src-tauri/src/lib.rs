use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Mutex,
};
use std::thread;
use std::time::{Duration, Instant};

use serde_json::Value;
use tauri::AppHandle;
use tauri_plugin_shell::{
    process::{CommandChild, CommandEvent},
    ShellExt,
};
mod menubar;

const CONTROL_URL: &str = "http://127.0.0.1:8790/";
const CONTROL_ADDR: &str = "127.0.0.1:8790";
const CONTROL_HEALTH_PATH: &str = "/api/app/health";
const CONTROL_SERVICE_MARKER: &str = "token-bi-control-panel";
const CONTROL_HEALTH_TIMEOUT: Duration = Duration::from_secs(30);
const CONTROL_HEALTH_POLL_INTERVAL: Duration = Duration::from_millis(200);

struct ControlProcess {
    child: CommandChild,
    exited: Arc<AtomicBool>,
}

type SharedChild = Arc<Mutex<Option<ControlProcess>>>;

pub fn run() {
    menubar::run();
}

fn start_control_panel_sidecar(app: &AppHandle) -> Result<ControlProcess, String> {
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

    let exited = Arc::new(AtomicBool::new(false));
    let finished = exited.clone();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            if matches!(event, CommandEvent::Terminated(_)) {
                finished.store(true, Ordering::SeqCst);
            }
        }
    });

    Ok(ControlProcess { child, exited })
}

fn ensure_control_panel(app: &AppHandle, sidecar_child: &SharedChild) -> Result<(), String> {
    match probe_control_panel_health_once() {
        HealthProbe::Ready => return Ok(()),
        HealthProbe::Invalid(reason) => return Err(reason),
        HealthProbe::Unreachable => {}
    }

    if sidecar_child
        .lock()
        .map_err(|_| "Unable to lock sidecar child state.".to_string())?
        .as_ref()
        .is_some_and(|process| !process.exited.load(Ordering::SeqCst))
    {
        return wait_for_control_panel_health();
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

fn stop_app_services_once(
    sidecar_child: &SharedChild,
    cleanup_done: &AtomicBool,
) -> Result<(), String> {
    // The child mutex serializes cleanup; a shutdown already in progress is not success.
    cleanup_done.store(true, Ordering::SeqCst);
    stop_started_services(sidecar_child)
}

fn stop_started_services(sidecar_child: &SharedChild) -> Result<(), String> {
    let mut guard = sidecar_child.lock().map_err(|_| "无法读取控制服务状态。")?;
    let Some(process) = guard.as_ref() else {
        return Ok(());
    };
    shutdown_control(
        CONTROL_ADDR,
        process.child.pid(),
        &process.exited,
        Duration::from_secs(5),
    )?;
    // Keep ownership on failure so the user can retry without orphaning the backend.
    guard.take();
    Ok(())
}

fn shutdown_control(
    address: &str,
    pid: u32,
    exited: &AtomicBool,
    timeout: Duration,
) -> Result<(), String> {
    if exited.load(Ordering::SeqCst) {
        return Err("控制服务已异常退出，无法确认主服务停止；请恢复本地服务后重试。".into());
    }
    let address: SocketAddr = address.parse().map_err(|_| "控制服务地址无效。")?;
    let mut stream = TcpStream::connect_timeout(&address, Duration::from_secs(2))
        .map_err(|_| "无法确认后台已停止，请恢复本地服务后重试。")?;
    stream
        .set_read_timeout(Some(Duration::from_secs(60)))
        .map_err(|e| e.to_string())?;
    stream
        .set_write_timeout(Some(Duration::from_secs(2)))
        .map_err(|e| e.to_string())?;
    let request = format!(
        "POST /api/app/shutdown HTTP/1.1\r\nHost: {address}\r\nX-Token-BI-Control-Pid: {pid}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
    );
    stream
        .write_all(request.as_bytes())
        .map_err(|e| e.to_string())?;
    let mut response = String::new();
    stream
        .read_to_string(&mut response)
        .map_err(|_| "停止后台服务超时，请重试。")?;
    if !shutdown_response_ok(&response) {
        return Err("后台服务未能安全停止，请恢复本地服务后重试。".into());
    }
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if exited.load(Ordering::SeqCst)
            && TcpStream::connect_timeout(&address, Duration::from_millis(100))
                .is_err_and(|error| error.kind() == std::io::ErrorKind::ConnectionRefused)
        {
            return Ok(());
        }
        thread::sleep(Duration::from_millis(50));
    }
    Err("控制服务尚未完全退出，请稍后重试。".into())
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
    fn shutdown_requires_acknowledgement_child_exit_and_closed_port() {
        for (acknowledged, report_exit, keep_port_open, succeeds) in [
            (false, true, false, false),
            (true, false, false, false),
            (true, true, true, false),
            (true, true, false, true),
        ] {
            let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
            let address = listener.local_addr().unwrap().to_string();
            let exited = Arc::new(AtomicBool::new(false));
            let finished = exited.clone();
            let (release, wait) = std::sync::mpsc::channel();
            let server = thread::spawn(move || {
                let (mut stream, _) = listener.accept().unwrap();
                stream
                    .set_read_timeout(Some(Duration::from_secs(2)))
                    .unwrap();
                let mut request = Vec::new();
                let mut byte = [0];
                while !request.ends_with(b"\r\n\r\n") {
                    stream.read_exact(&mut byte).unwrap();
                    request.push(byte[0]);
                }
                assert!(String::from_utf8(request)
                    .unwrap()
                    .contains("X-Token-BI-Control-Pid: 42"));
                write!(stream, "HTTP/1.0 200 OK\r\n\r\n{{\"ok\":{acknowledged}}}").unwrap();
                finished.store(report_exit, Ordering::SeqCst);
                drop(stream);
                if keep_port_open {
                    wait.recv_timeout(Duration::from_secs(2)).unwrap();
                }
                drop(listener);
            });
            let result = shutdown_control(&address, 42, &exited, Duration::from_millis(200));
            let _ = release.send(());
            server.join().unwrap();
            assert_eq!(result.is_ok(), succeeds, "{result:?}");
        }
    }

    #[test]
    fn exited_control_cannot_shut_down_replacement_listener() {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        listener.set_nonblocking(true).unwrap();
        let result = shutdown_control(
            &listener.local_addr().unwrap().to_string(),
            42,
            &AtomicBool::new(true),
            Duration::from_millis(100),
        );
        assert!(result.is_err());
        assert_eq!(
            listener.accept().unwrap_err().kind(),
            std::io::ErrorKind::WouldBlock
        );
    }

    #[test]
    fn control_health_timeout_covers_measured_cold_start() {
        assert!(CONTROL_HEALTH_TIMEOUT >= Duration::from_secs(30));
        assert!(CONTROL_HEALTH_POLL_INTERVAL <= Duration::from_millis(200));
    }
}
