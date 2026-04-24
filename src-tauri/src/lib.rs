use std::io::Write;
use std::net::TcpStream;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Mutex,
};
use std::thread;
use std::time::{Duration, Instant};

use tauri::{Manager, WebviewUrl, WebviewWindowBuilder, WindowEvent};
use tauri_plugin_shell::{process::CommandChild, ShellExt};
use url::Url;

const CONTROL_URL: &str = "http://127.0.0.1:8790/";

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
            let child = start_control_panel_sidecar(app)?;
            {
                let mut guard = setup_child
                    .lock()
                    .map_err(|_| "Unable to lock sidecar child state.".to_string())?;
                *guard = Some(child);
            }
            wait_for_control_panel()?;

            let url = Url::parse(CONTROL_URL).map_err(|error| error.to_string())?;
            let window = WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url))
                .title("Token BI")
                .inner_size(960.0, 760.0)
                .min_inner_size(720.0, 560.0)
                .resizable(true)
                .build()?;

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

fn start_control_panel_sidecar(app: &tauri::App) -> Result<CommandChild, String> {
    let command = app
        .shell()
        .sidecar("token-bi-backend")
        .map_err(|error| format!("Unable to locate Token BI backend sidecar: {error}"))?;
    let (mut rx, child) = command
        .args([
            "control-panel",
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

fn wait_for_control_panel() -> Result<(), String> {
    let deadline = Instant::now() + Duration::from_secs(12);
    while Instant::now() < deadline {
        if TcpStream::connect("127.0.0.1:8790").is_ok() {
            return Ok(());
        }
        thread::sleep(Duration::from_millis(300));
    }
    Err("Control panel did not become reachable on 127.0.0.1:8790.".to_string())
}

fn stop_app_services_once(sidecar_child: &SharedChild, cleanup_done: &AtomicBool) {
    if cleanup_done.swap(true, Ordering::SeqCst) {
        return;
    }

    post_control_shutdown();
    thread::sleep(Duration::from_millis(500));

    if let Ok(mut guard) = sidecar_child.lock() {
        if let Some(child) = guard.take() {
            let _ = child.kill();
        }
    }
}

fn post_control_shutdown() {
    if let Ok(mut stream) = TcpStream::connect("127.0.0.1:8790") {
        let request =
            b"POST /api/app/shutdown HTTP/1.1\r\nHost: 127.0.0.1:8790\r\nContent-Length: 0\r\nConnection: close\r\n\r\n";
        let _ = stream.write_all(request);
    }
}
