use std::path::{Path, PathBuf};
use tauri::{Manager, WebviewUrl, WebviewWindow, WebviewWindowBuilder, WindowEvent};

const WIDTH: f64 = 284.0;
const HEIGHT: f64 = 214.0;

fn marker(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let root = std::env::var_os("TOKEN_BI_APP_DATA_DIR")
        .map(PathBuf::from)
        .map(Ok)
        .unwrap_or_else(|| app.path().app_data_dir().map_err(|e| e.to_string()))?;
    Ok(root.join("menubar-onboarding-v1"))
}

fn completed(path: &Path) -> bool {
    std::fs::read(path).is_ok_and(|bytes| bytes == b"1")
}

fn complete(path: &Path) -> Result<(), String> {
    if completed(path) {
        return Ok(());
    }
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    std::fs::write(path, b"1").map_err(|e| e.to_string())
}

pub(super) fn prepare(app: &tauri::AppHandle) -> Result<(), String> {
    if completed(&marker(app)?) {
        return Ok(());
    }
    let window =
        WebviewWindowBuilder::new(app, "onboarding", WebviewUrl::App("onboarding.html".into()))
            .title("Token BI")
            .inner_size(WIDTH, HEIGHT)
            .resizable(false)
            .decorations(false)
            .visible(false)
            .focused(false)
            .skip_taskbar(true)
            .always_on_top(true)
            .background_color(tauri::webview::Color(43, 45, 43, 255))
            .on_navigation(|url| {
                url.scheme() == "tauri" || url.host_str() == Some("tauri.localhost")
            })
            .build()
            .map_err(|e| e.to_string())?;
    #[cfg(target_os = "macos")]
    super::macos::configure(&window)?;
    let weak = app.clone();
    window.on_window_event(move |event| {
        if let WindowEvent::CloseRequested { api, .. } = event {
            api.prevent_close();
            let _ = acknowledge(&weak);
        }
        if matches!(event, WindowEvent::Focused(false)) {
            if let Some(window) = weak.get_webview_window("onboarding") {
                let _ = window.hide();
            }
        }
    });
    Ok(())
}

pub(super) fn acknowledge(app: &tauri::AppHandle) -> Result<(), String> {
    // Once the user finds the real panel, the introductory window can be destroyed.
    if let Some(window) = app.get_webview_window("onboarding") {
        complete(&marker(app)?)?;
        window.destroy().map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
pub(super) fn onboarding_action(
    window: WebviewWindow,
    app: tauri::AppHandle,
    action: String,
) -> Result<(), String> {
    let url = window.url().map_err(|e| e.to_string())?;
    if window.label() != "onboarding"
        || !(url.scheme() == "tauri" || url.host_str() == Some("tauri.localhost"))
    {
        return Err("仅允许本地引导操作。".into());
    }
    match action.as_str() {
        "ready" => {
            let handle = app.clone();
            app.run_on_main_thread(move || {
                #[cfg(target_os = "macos")]
                let _ = super::macos::position(&handle, &window, WIDTH, HEIGHT);
                let _ = window.show();
            })
            .map_err(|e| e.to_string())?;
        }
        "dismiss" => acknowledge(&app)?,
        "open" => super::show_panel(&app),
        _ => return Err("未知引导操作。".into()),
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn onboarding_is_completed_only_after_an_explicit_acknowledgment() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("prefs/marker");
        assert!(!completed(&path));
        complete(&path).unwrap();
        assert!(completed(&path));
        complete(&path).unwrap();
        std::fs::write(&path, b"").unwrap();
        assert!(!completed(&path));
    }
}
