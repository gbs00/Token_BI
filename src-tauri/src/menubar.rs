use super::{
    ensure_control_panel, stop_app_services_once, stop_started_services, SharedChild, CONTROL_URL,
};
use serde_json::{json, Value};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Mutex,
};
use std::time::{Duration, Instant};
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{Manager, WebviewUrl, WebviewWindow, WebviewWindowBuilder, WindowEvent};

#[cfg(target_os = "macos")]
mod macos;
mod onboarding;
mod updates;

const PANEL_WIDTH: f64 = 311.0;
const PANEL_HEIGHT: f64 = 600.0;

struct DesktopState {
    child: SharedChild,
    shutdown: AtomicBool,
    open_qr: AtomicBool,
    bootstrap: Mutex<Value>,
    last_blur: Mutex<Option<Instant>>,
    client: reqwest::Client,
}

fn local_http_client() -> reqwest::Client {
    // The updater enables rustls without a provider; choose the existing ring backend.
    let _ = rustls::crypto::ring::default_provider().install_default();
    reqwest::Client::builder()
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .timeout(Duration::from_secs(95))
        .build()
        .expect("local HTTP client")
}

pub fn run() {
    let state = DesktopState {
        child: Arc::new(Mutex::new(None)),
        shutdown: AtomicBool::new(false),
        open_qr: AtomicBool::new(false),
        bootstrap: Mutex::new(json!({"phase": "idle"})),
        last_blur: Mutex::new(None),
        client: local_http_client(),
    };
    tauri::Builder::default()
        .manage(state)
        .manage(updates::Updates::default())
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            show_panel(app)
        }))
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .invoke_handler(tauri::generate_handler![
            panel_state,
            panel_action,
            updates::update_action,
            onboarding::onboarding_action,
            panel_hide,
            panel_quit
        ])
        .setup(|app| {
            #[cfg(target_os = "macos")]
            app.set_activation_policy(tauri::ActivationPolicy::Accessory);
            let window =
                WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                    .title("Token BI")
                    .inner_size(PANEL_WIDTH, PANEL_HEIGHT)
                    .resizable(false)
                    .decorations(false)
                    .visible(false)
                    .skip_taskbar(true)
                    .always_on_top(true)
                    .visible_on_all_workspaces(true)
                    .background_color(tauri::webview::Color(38, 38, 38, 255))
                    .on_navigation(|url| {
                        matches!(url.scheme(), "tauri" | "about")
                            || url.host_str() == Some("tauri.localhost")
                    })
                    .build()?;
            #[cfg(target_os = "macos")]
            macos::configure(&window).map_err(std::io::Error::other)?;
            let handle = app.handle().clone();
            window.on_window_event(move |event| {
                let state = handle.state::<DesktopState>();
                match event {
                    WindowEvent::CloseRequested { api, .. } => {
                        api.prevent_close();
                        if let Some(window) = handle.get_webview_window("main") {
                            let _ = window.hide();
                        }
                    }
                    WindowEvent::Focused(false) => {
                        *state.last_blur.lock().unwrap() = Some(Instant::now());
                        if let Some(window) = handle.get_webview_window("main") {
                            let _ = window.hide();
                        }
                    }
                    _ => {}
                }
            });
            let open = MenuItem::with_id(app, "open", "查看额度", true, None::<&str>)?;
            let qr = MenuItem::with_id(app, "qr", "扫码连接副屏", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "退出 Token BI", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open, &qr, &quit])?;
            let tray = TrayIconBuilder::with_id("token-bi")
                .icon(tauri::include_image!("icons/icon.png"))
                .tooltip("Token BI")
                .show_menu_on_left_click(false);
            // macOS 27 consumes left clicks when NSStatusItem has a resident menu
            // (tray-icon #355). Keep it detached and present it on right press only.
            #[cfg(not(target_os = "macos"))]
            let tray = tray.menu(&menu);
            tray.on_menu_event(|app, event| match event.id.as_ref() {
                "quit" => app.exit(0),
                "qr" => {
                    app.state::<DesktopState>()
                        .open_qr
                        .store(true, Ordering::Relaxed);
                    show_panel(app);
                }
                _ => show_panel(app),
            })
            .on_tray_icon_event(move |tray, event| {
                #[cfg(target_os = "macos")]
                if let TrayIconEvent::Click {
                    button: MouseButton::Right,
                    button_state: MouseButtonState::Down,
                    ..
                } = event
                {
                    if let Some(window) = tray.app_handle().get_webview_window("main") {
                        let _ = window.hide();
                        if let Err(error) = macos::popup_tray_menu(tray, &window, &menu) {
                            eprintln!("Token BI tray menu: {error}");
                        }
                    }
                    return;
                }
                if let TrayIconEvent::Click {
                    button: MouseButton::Left,
                    button_state: MouseButtonState::Up,
                    ..
                } = event
                {
                    let app = tray.app_handle();
                    if let Some(window) = app.get_webview_window("main") {
                        let just_hidden = app
                            .state::<DesktopState>()
                            .last_blur
                            .lock()
                            .unwrap()
                            .is_some_and(|at| at.elapsed() < Duration::from_millis(250));
                        if window.is_visible().unwrap_or(false) {
                            let _ = window.hide();
                        } else if !just_hidden {
                            show_panel(app);
                        }
                    }
                }
            })
            .build(app)?;
            if let Err(error) = onboarding::prepare(app.handle()) {
                eprintln!("Token BI onboarding: {error}");
            }
            launch_services(app.handle());
            updates::start_scheduler(app.handle());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("Token BI menu bar")
        .run(|app, event| match event {
            tauri::RunEvent::ExitRequested {
                code: None, api, ..
            } => api.prevent_exit(),
            tauri::RunEvent::ExitRequested { code, api, .. }
                if code != Some(tauri::RESTART_EXIT_CODE)
                    && app.state::<updates::Updates>().installing() =>
            {
                api.prevent_exit()
            }
            tauri::RunEvent::ExitRequested { api, .. } => {
                let state = app.state::<DesktopState>();
                if let Err(error) = stop_app_services_once(&state.child, &state.shutdown) {
                    api.prevent_exit();
                    state.shutdown.store(false, Ordering::SeqCst);
                    *state.bootstrap.lock().unwrap() = json!({"phase": "error", "message": error});
                    show_panel(app);
                } else {
                    app.state::<updates::Updates>().discard_package();
                }
            }
            tauri::RunEvent::Exit => {
                let state = app.state::<DesktopState>();
                if let Err(error) = stop_app_services_once(&state.child, &state.shutdown) {
                    eprintln!("Token BI shutdown: {error}");
                }
            }
            #[cfg(target_os = "macos")]
            tauri::RunEvent::Reopen { .. } => show_panel(app),
            _ => {}
        });
}

fn launch_services(app: &tauri::AppHandle) {
    let state = app.state::<DesktopState>();
    let mut boot = state.bootstrap.lock().unwrap();
    if boot["phase"] == "starting" || state.shutdown.load(Ordering::SeqCst) {
        return;
    }
    *boot = json!({"phase": "starting"});
    drop(boot);
    let app = app.clone();
    std::thread::spawn(move || {
        let state = app.state::<DesktopState>();
        let result = ensure_control_panel(&app, &state.child).and_then(|_| {
            if state.shutdown.load(Ordering::SeqCst) {
                return Err("App 正在退出".into());
            }
            let client = reqwest::blocking::Client::builder()
                .no_proxy()
                .redirect(reqwest::redirect::Policy::none())
                .timeout(Duration::from_secs(80))
                .build()
                .map_err(|e| e.to_string())?;
            let response: Value = client
                .post(format!("{CONTROL_URL}api/start"))
                .send()
                .and_then(|r| r.error_for_status())
                .and_then(|r| r.json())
                .map_err(|e| e.to_string())?;
            if response["ok"] == true {
                Ok(())
            } else {
                Err(response["message"]
                    .as_str()
                    .unwrap_or("本地服务未就绪")
                    .to_owned())
            }
        });
        if state.shutdown.load(Ordering::SeqCst) {
            if let Err(error) = stop_started_services(&state.child) {
                eprintln!("Token BI shutdown: {error}");
            }
            return;
        }
        *state.bootstrap.lock().unwrap() = match result {
            Ok(()) => json!({"phase": "ready"}),
            Err(error) => json!({"phase": "error", "message": error}),
        };
    });
}

fn show_panel(app: &tauri::AppHandle) {
    let handle = app.clone();
    let _ = app.run_on_main_thread(move || show_panel_on_main(&handle));
}

fn show_panel_on_main(app: &tauri::AppHandle) {
    if let Err(error) = onboarding::acknowledge(app) {
        eprintln!("Token BI onboarding: {error}");
    }
    let Some(window) = app.get_webview_window("main") else {
        return;
    };
    #[cfg(target_os = "macos")]
    if let Err(error) = macos::position(app, &window, PANEL_WIDTH, PANEL_HEIGHT) {
        eprintln!("Token BI panel positioning: {error}");
    }
    #[cfg(not(target_os = "macos"))]
    if let Some(tray) = app.tray_by_id("token-bi") {
        if let Ok(Some(rect)) = tray.rect() {
            let scale = window.scale_factor().unwrap_or(1.0);
            let position = rect.position.to_physical::<f64>(scale);
            let size = rect.size.to_physical::<f64>(scale);
            if let Ok(Some(monitor)) = window.monitor_from_point(position.x, position.y) {
                let area = monitor.work_area();
                let scale = monitor.scale_factor();
                let width = (PANEL_WIDTH * scale).min(area.size.width as f64);
                let height = (PANEL_HEIGHT * scale)
                    .min(area.size.height as f64 - 12.0)
                    .max(100.0);
                let (x, y) = fit_panel(
                    position.x + size.width / 2.0,
                    position.y + size.height + 6.0,
                    width,
                    height,
                    area.position.x as f64,
                    area.position.y as f64,
                    area.size.width as f64,
                    area.size.height as f64,
                );
                let _ = window.set_size(tauri::PhysicalSize::new(width as u32, height as u32));
                let _ = window.set_position(tauri::PhysicalPosition::new(x as i32, y as i32));
            }
        }
    }
    let _ = window.show();
    let _ = window.set_focus();
}

#[allow(clippy::too_many_arguments)]
#[cfg(any(not(target_os = "macos"), test))]
fn fit_panel(
    anchor_x: f64,
    anchor_y: f64,
    width: f64,
    height: f64,
    left: f64,
    top: f64,
    screen_width: f64,
    screen_height: f64,
) -> (f64, f64) {
    (
        (anchor_x - width / 2.0).clamp(left, (left + screen_width - width).max(left)),
        anchor_y.clamp(top, (top + screen_height - height).max(top)),
    )
}

fn trusted_window(window: &WebviewWindow) -> Result<(), String> {
    let url = window.url().map_err(|e| e.to_string())?;
    if window.label() == "main"
        && (url.scheme() == "tauri" || url.host_str() == Some("tauri.localhost"))
    {
        Ok(())
    } else {
        Err("仅允许本地菜单栏操作".into())
    }
}

#[tauri::command]
fn panel_state(
    window: WebviewWindow,
    state: tauri::State<DesktopState>,
    updates: tauri::State<updates::Updates>,
) -> Result<Value, String> {
    trusted_window(&window)?;
    let mut result = state.bootstrap.lock().unwrap().clone();
    let visible = window.is_visible().unwrap_or(false);
    result["visible"] = json!(visible);
    // Keep tray requests until the bundled page is visible and ready to consume them.
    result["open_qr"] = json!(visible && state.open_qr.swap(false, Ordering::Relaxed));
    result["update"] = updates.snapshot();
    Ok(result)
}

fn action_route(action: &str) -> Result<(&'static str, &'static str), String> {
    match action {
        "status" => Ok(("GET", "api/status")),
        "refresh" => Ok(("POST", "api/refresh-status")),
        "login" => Ok(("POST", "api/add-account")),
        "logout" => Ok(("POST", "api/logout")),
        "open_local" => Ok(("POST", "api/open-url?kind=local")),
        "open_lan" => Ok(("POST", "api/open-url?kind=lan")),
        "open_fixed" => Ok(("POST", "api/open-url?kind=fixed")),
        "qr_lan" => Ok(("GET", "api/pairing?kind=lan")),
        "qr_fixed" => Ok(("GET", "api/pairing?kind=fixed")),
        _ => Err("未知菜单栏操作".into()),
    }
}

#[tauri::command]
async fn panel_action(
    window: WebviewWindow,
    app: tauri::AppHandle,
    action: String,
    state: tauri::State<'_, DesktopState>,
) -> Result<Value, String> {
    trusted_window(&window)?;
    if app.state::<updates::Updates>().installing() {
        return Err("正在安装更新，请稍候。".into());
    }
    if action == "retry_start" {
        launch_services(&app);
        return Ok(json!({"ok": true}));
    }
    let (method, path) = action_route(&action)?;
    if state.bootstrap.lock().unwrap()["phase"] != "ready" {
        return Err("本地服务尚未就绪".into());
    }
    let response = state
        .client
        .request(method.parse().unwrap(), format!("{CONTROL_URL}{path}"))
        .timeout(Duration::from_secs(if method == "GET" { 12 } else { 95 }))
        .send()
        .await
        .and_then(|r| r.error_for_status())
        .map_err(|e| e.to_string())?;
    response.json().await.map_err(|e| e.to_string())
}

#[tauri::command]
fn panel_hide(window: WebviewWindow) -> Result<(), String> {
    trusted_window(&window)?;
    window.hide().map_err(|e| e.to_string())
}

#[tauri::command]
fn panel_quit(window: WebviewWindow, app: tauri::AppHandle) -> Result<(), String> {
    trusted_window(&window)?;
    if app.state::<updates::Updates>().installing() {
        return Err("正在安装更新，请等待自动重启。".into());
    }
    app.exit(0);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn http_clients_initialize_with_updater_tls_features() {
        let _ = local_http_client();
        assert!(reqwest::blocking::Client::builder()
            .no_proxy()
            .build()
            .is_ok());
    }
    #[test]
    fn anchors_inside_negative_origin_and_small_monitors() {
        assert_eq!(
            fit_panel(-10.0, 28.0, 311.0, 600.0, -1440.0, 24.0, 1440.0, 876.0),
            (-311.0, 28.0)
        );
        assert_eq!(
            fit_panel(20.0, 35.0, 320.0, 400.0, 0.0, 24.0, 320.0, 400.0),
            (0.0, 24.0)
        );
    }
    #[test]
    fn bridge_only_exposes_explicit_actions() {
        assert!(action_route("http://example.com").is_err());
        assert!(action_route("stop").is_err());
        assert_eq!(action_route("logout").unwrap(), ("POST", "api/logout"));
        assert_eq!(
            action_route("qr_lan").unwrap(),
            ("GET", "api/pairing?kind=lan")
        );
    }
}
