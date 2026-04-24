use std::net::TcpStream;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use std::thread;
use std::time::{Duration, Instant};

use tauri::{Manager, WebviewUrl, WebviewWindowBuilder, WindowEvent};
use url::Url;

const CONTROL_URL: &str = "http://127.0.0.1:8790/";

pub fn run() {
    let project_root = PathBuf::from(env!("TOKEN_BI_PROJECT_ROOT"));
    let cleanup_done = Arc::new(AtomicBool::new(false));
    let setup_root = project_root.clone();
    let setup_cleanup = cleanup_done.clone();
    let run_root = project_root.clone();
    let run_cleanup = cleanup_done.clone();

    tauri::Builder::default()
        .setup(move |app| {
            start_control_panel(&setup_root)?;
            wait_for_control_panel()?;

            let url = Url::parse(CONTROL_URL).map_err(|error| error.to_string())?;
            let window = WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url))
                .title("Token BI")
                .inner_size(960.0, 760.0)
                .min_inner_size(720.0, 560.0)
                .resizable(true)
                .build()?;

            let cleanup_root = setup_root.clone();
            let cleanup_flag = setup_cleanup.clone();
            window.on_window_event(move |event| {
                if matches!(event, WindowEvent::CloseRequested { .. }) {
                    stop_app_services_once(&cleanup_root, &cleanup_flag);
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
                stop_app_services_once(&run_root, &run_cleanup);
            }
        });
}

fn start_control_panel(project_root: &Path) -> Result<(), String> {
    let script = project_root.join("scripts/start_control_panel.sh");
    let output = Command::new(&script)
        .current_dir(project_root)
        .output()
        .map_err(|error| format!("Unable to start control panel: {error}"))?;

    if output.status.success() {
        return Ok(());
    }

    let stderr = String::from_utf8_lossy(&output.stderr);
    let stdout = String::from_utf8_lossy(&output.stdout);
    Err(format!(
        "Control panel start failed.\n{}\n{}",
        stdout.trim(),
        stderr.trim()
    ))
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

fn stop_app_services_once(project_root: &Path, cleanup_done: &AtomicBool) {
    if cleanup_done.swap(true, Ordering::SeqCst) {
        return;
    }

    let script = project_root.join("scripts/stop_app_services.sh");
    let _ = Command::new(&script).current_dir(project_root).status();
}
