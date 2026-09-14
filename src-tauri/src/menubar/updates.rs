use sha2::{Digest, Sha256};
use std::io::Write;
use std::sync::Mutex;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tauri::{Manager, WebviewWindow};
use tauri_plugin_updater::{Update, UpdaterExt};

use super::{launch_services, trusted_window, DesktopState};
use serde_json::{json, Value};

const INTERVAL: Duration = Duration::from_secs(6 * 3600);

struct Package {
    file: tempfile::NamedTempFile,
    digest: Vec<u8>,
}

impl Package {
    fn save(bytes: &[u8]) -> Result<Self, String> {
        let mut file = tempfile::NamedTempFile::new().map_err(|e| e.to_string())?;
        file.write_all(bytes).map_err(|e| e.to_string())?;
        file.flush().map_err(|e| e.to_string())?;
        Ok(Self {
            file,
            digest: Sha256::digest(bytes).to_vec(),
        })
    }

    fn read_verified(&self) -> Result<Vec<u8>, String> {
        let bytes = std::fs::read(self.file.path()).map_err(|e| e.to_string())?;
        if Sha256::digest(&bytes).as_slice() != self.digest.as_slice() {
            return Err("已下载的更新包发生变化，请重新下载。".into());
        }
        Ok(bytes)
    }
}

pub(super) struct Updates(Mutex<Inner>);

struct Inner {
    phase: &'static str,
    error: String,
    release: Option<Update>,
    package: Option<Package>,
    received: u64,
    total: Option<u64>,
    checked_at: u64,
    due: Instant,
    failures: u32,
}

impl Default for Updates {
    fn default() -> Self {
        Self(Mutex::new(Inner {
            phase: "idle",
            error: String::new(),
            release: None,
            package: None,
            received: 0,
            total: None,
            checked_at: 0,
            due: Instant::now() + Duration::from_secs(10),
            failures: 0,
        }))
    }
}

impl Inner {
    fn busy(&self) -> bool {
        matches!(self.phase, "checking" | "downloading" | "installing")
    }
    fn fail(&mut self, phase: &'static str, error: String) {
        self.phase = phase;
        self.error = error;
        self.failures = self.failures.saturating_add(1);
        self.due = Instant::now() + retry_delay(self.failures);
    }
}

fn retry_delay(failures: u32) -> Duration {
    Duration::from_secs((60 * (1u64 << failures.saturating_sub(1).min(6))).min(3600))
}

impl Updates {
    pub(super) fn discard_package(&self) {
        self.0.lock().unwrap().package.take();
    }

    pub(super) fn installing(&self) -> bool {
        self.0.lock().unwrap().phase == "installing"
    }

    pub(super) fn snapshot(&self) -> Value {
        let inner = self.0.lock().unwrap();
        json!({
            "phase": inner.phase, "error": inner.error,
            "current_version": env!("CARGO_PKG_VERSION"),
            "version": inner.release.as_ref().map(|r| &r.version),
            "notes": inner.release.as_ref().and_then(|r| r.body.as_ref()),
            "available": inner.release.is_some(), "received": inner.received,
            "total": inner.total, "checked_at": inner.checked_at,
        })
    }
}

pub(super) fn start_scheduler(app: &tauri::AppHandle) {
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        loop {
            tokio::time::sleep(Duration::from_secs(10)).await;
            if app
                .state::<DesktopState>()
                .shutdown
                .load(std::sync::atomic::Ordering::SeqCst)
            {
                continue;
            }
            let due = {
                let inner = app.state::<Updates>();
                let inner = inner.0.lock().unwrap();
                !inner.busy() && inner.package.is_none() && Instant::now() >= inner.due
            };
            if due {
                check(&app, false);
            }
        }
    });
}

fn check(app: &tauri::AppHandle, manual: bool) {
    {
        let state = app.state::<Updates>();
        let mut inner = state.0.lock().unwrap();
        if inner.busy() || inner.package.is_some() || (!manual && Instant::now() < inner.due) {
            return;
        }
        inner.phase = "checking";
        inner.error.clear();
    }
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        let result = match app
            .updater_builder()
            .timeout(Duration::from_secs(20))
            .build()
        {
            Ok(updater) => updater.check().await,
            Err(error) => Err(error),
        };
        let state = app.state::<Updates>();
        let mut inner = state.0.lock().unwrap();
        inner.checked_at = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs();
        match result {
            Ok(release) => {
                // Never download from an unrelated source named by a malformed manifest.
                if release
                    .as_ref()
                    .is_some_and(|r| !allowed_download(r.download_url.as_str()))
                {
                    inner.fail(
                        "check_error",
                        "更新地址不属于 Token BI 官方发布，请稍后重试。".into(),
                    );
                    return;
                }
                inner.release = release;
                inner.phase = if inner.release.is_some() {
                    "available"
                } else {
                    "latest"
                };
                inner.failures = 0;
                inner.due = Instant::now() + INTERVAL;
            }
            Err(error) => inner.fail("check_error", friendly_error(&error)),
        }
    });
}

fn allowed_download(url: &str) -> bool {
    url.starts_with("https://github.com/gbs00/Token_BI/releases/download/")
}

fn friendly_error(error: &tauri_plugin_updater::Error) -> String {
    use tauri_plugin_updater::Error;
    match error {
        Error::Minisign(_) | Error::Base64(_) | Error::SignatureUtf8(_) => {
            "签名校验失败，已阻止安装。请重新下载。".into()
        }
        Error::Reqwest(e) if e.is_timeout() => "连接更新服务超时，请稍后重试。".into(),
        Error::Reqwest(_) | Error::Network(_) => {
            "无法连接更新服务，请检查网络或代理后重试。".into()
        }
        Error::Io(_) => "无法读写更新文件，请检查磁盘空间和安装目录权限。".into(),
        Error::ReleaseNotFound
        | Error::Serialization(_)
        | Error::TargetNotFound(_)
        | Error::TargetsNotFound(_)
        | Error::Semver(_) => "更新清单暂不可用或不支持此设备，请稍后重试。".into(),
        _ => "更新未完成，请稍后重试或手动安装官方 Release。".into(),
    }
}

fn download(app: &tauri::AppHandle) -> Result<(), String> {
    let mut release = {
        let state = app.state::<Updates>();
        let mut inner = state.0.lock().unwrap();
        if inner.busy() || inner.package.is_some() {
            return Ok(());
        }
        let release = inner.release.clone().ok_or("请先检查更新。")?;
        inner.phase = "downloading";
        inner.error.clear();
        inner.received = 0;
        inner.total = None;
        release
    };
    release.timeout = Some(Duration::from_secs(15 * 60));
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        let bytes = release
            .download(
                |chunk, total| {
                    let state = app.state::<Updates>();
                    let mut inner = state.0.lock().unwrap();
                    inner.received += chunk as u64;
                    inner.total = total;
                },
                || {},
            )
            .await;
        let result = match bytes {
            // download() has verified the publisher signature. Keep the large package on
            // disk while the user postpones, with a digest guarding the later read.
            Ok(bytes) => Package::save(&bytes),
            Err(error) => Err(friendly_error(&error)),
        };
        let state = app.state::<Updates>();
        let mut inner = state.0.lock().unwrap();
        if app
            .state::<DesktopState>()
            .shutdown
            .load(std::sync::atomic::Ordering::SeqCst)
        {
            return;
        }
        match result {
            Ok(package) => {
                inner.package = Some(package);
                inner.phase = "ready";
            }
            Err(error) => inner.fail("download_error", error),
        }
    });
    Ok(())
}

fn install(app: &tauri::AppHandle) -> Result<(), String> {
    let (release, package) = {
        let state = app.state::<Updates>();
        let mut inner = state.0.lock().unwrap();
        if inner.busy() {
            return Ok(());
        }
        if inner.phase != "ready" {
            return Err("请先完成下载和校验。".into());
        }
        // A pending bootstrap must finish before stopping/replacing bundled runtimes.
        if app.state::<DesktopState>().bootstrap.lock().unwrap()["phase"] == "starting" {
            return Err("本地服务正在启动，请稍后重试安装。".into());
        }
        let release = inner.release.clone().ok_or("请先检查更新。")?;
        let package = inner.package.take().ok_or("请重新下载更新。")?;
        inner.phase = "installing";
        inner.error.clear();
        (release, package)
    };
    let app = app.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let result = package.read_verified().and_then(|bytes| {
            ensure_writable_install()?;
            let state = app.state::<DesktopState>();
            super::super::stop_app_services_once(&state.child, &state.shutdown);
            release.install(bytes).map_err(|e| friendly_error(&e))
        });
        // restart() does not return; do not rely on stack unwinding to remove it.
        drop(package);
        match result {
            Ok(()) => app.restart(),
            Err(error) => {
                app.state::<Updates>()
                    .0
                    .lock()
                    .unwrap()
                    .fail("install_error", error);
                let state = app.state::<DesktopState>();
                if state
                    .shutdown
                    .swap(false, std::sync::atomic::Ordering::SeqCst)
                {
                    launch_services(&app);
                }
            }
        }
    });
    Ok(())
}

fn ensure_writable_install() -> Result<(), String> {
    let exe = std::env::current_exe().map_err(|e| e.to_string())?;
    let bundle = exe
        .ancestors()
        .find(|p| p.extension().is_some_and(|ext| ext == "app"))
        .ok_or("请从已安装的 Token BI.app 执行更新。")?;
    let parent = bundle.parent().ok_or("无法定位安装目录。")?;
    // Avoid entering the updater's privileged replacement path. A DMG/read-only
    // install must be copied into a writable Applications directory first.
    tempfile::NamedTempFile::new_in(parent)
        .map_err(|_| "安装目录不可写，请先将 App 移至可写的应用程序目录。")?;
    Ok(())
}

#[tauri::command]
pub(super) fn update_action(
    window: WebviewWindow,
    app: tauri::AppHandle,
    action: String,
) -> Result<(), String> {
    trusted_window(&window)?;
    match action.as_str() {
        "check" => {
            check(&app, true);
            Ok(())
        }
        "download" => download(&app),
        "install" => install(&app),
        _ => Err("未知更新操作。".into()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn retry_is_bounded_and_grows() {
        assert_eq!(retry_delay(1).as_secs(), 60);
        assert_eq!(retry_delay(2).as_secs(), 120);
        assert_eq!(retry_delay(100).as_secs(), 3600);
    }
    #[test]
    fn package_detects_tampering() {
        let package = Package::save(b"verified archive").unwrap();
        assert_eq!(package.read_verified().unwrap(), b"verified archive");
        std::fs::write(package.file.path(), b"changed").unwrap();
        assert!(package.read_verified().is_err());
    }

    #[test]
    fn quitting_discards_the_downloaded_package() {
        let updates = Updates::default();
        let package = Package::save(b"verified archive").unwrap();
        let path = package.file.path().to_owned();
        updates.0.lock().unwrap().package = Some(package);
        updates.discard_package();
        assert!(!path.exists());
        updates.discard_package();
    }
    #[test]
    fn only_official_release_assets_are_allowed() {
        assert!(allowed_download(
            "https://github.com/gbs00/Token_BI/releases/download/v1.2.2/app.tar.gz"
        ));
        assert!(!allowed_download(
            "http://github.com/gbs00/Token_BI/releases/download/x"
        ));
        assert!(!allowed_download(
            "https://github.com/other/repo/releases/download/x"
        ));
    }
    #[test]
    fn busy_states_and_failure_retry_preserve_download_metadata() {
        let updates = Updates::default();
        let before = updates.snapshot();
        assert_eq!(before["phase"], "idle");
        assert_eq!(before["available"], false);
        let mut inner = updates.0.lock().unwrap();
        inner.phase = "downloading";
        inner.received = 42;
        assert!(inner.busy());
        inner.fail("download_error", "offline".into());
        assert!(!inner.busy());
        assert_eq!(inner.error, "offline");
        assert_eq!(inner.received, 42);
        for phase in ["checking", "downloading", "installing"] {
            inner.phase = phase;
            assert!(inner.busy());
        }
    }
}
