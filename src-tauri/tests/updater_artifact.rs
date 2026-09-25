//! Exercises the official updater against the signed release in a temporary app.
//! It never modifies /Applications or starts the user's account services.
#![cfg(target_os = "macos")]
use serde_json::{json, Value};
use std::io::{Read, Write};
use std::net::TcpListener;
use std::path::PathBuf;
use std::time::Duration;
use tauri_plugin_updater::UpdaterExt;

#[test]
#[ignore = "requires a signed package; run via scripts/release_local.sh"]
fn signed_release_download_install_and_tamper_rejection() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .to_path_buf();
    let config: Value =
        serde_json::from_slice(&std::fs::read(root.join("src-tauri/tauri.conf.json")).unwrap())
            .unwrap();
    let staged = std::env::var_os("TOKEN_BI_TEST_RELEASE_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            root.join(format!(
                "dist/release-v{}",
                config["version"].as_str().unwrap()
            ))
        });
    let mut manifest: Value =
        serde_json::from_slice(&std::fs::read(staged.join("latest.json")).unwrap()).unwrap();
    let filename = manifest["platforms"]["darwin-aarch64"]["url"]
        .as_str()
        .unwrap()
        .rsplit('/')
        .next()
        .unwrap();
    let bytes = std::fs::read(staged.join(filename)).unwrap();
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let url = format!("http://{}", listener.local_addr().unwrap());
    manifest["platforms"]["darwin-aarch64"]["url"] = json!(format!("{url}/archive"));
    let manifest = serde_json::to_vec(&manifest).unwrap();
    // Check + valid download + altered download. Every request has bounded IO.
    let server = std::thread::spawn(move || {
        for index in 0..3 {
            let (mut stream, _) = listener.accept().unwrap();
            stream
                .set_read_timeout(Some(Duration::from_secs(10)))
                .unwrap();
            stream
                .set_write_timeout(Some(Duration::from_secs(30)))
                .unwrap();
            let mut request = Vec::new();
            while !request.ends_with(b"\r\n\r\n") {
                let mut byte = [0u8];
                stream.read_exact(&mut byte).unwrap();
                request.push(byte[0]);
                assert!(request.len() < 8192);
            }
            let body = if index == 0 {
                &manifest[..]
            } else if index == 1 {
                &bytes[..]
            } else {
                b"tampered archive"
            };
            write!(
                stream,
                "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                body.len()
            )
            .unwrap();
            stream.write_all(body).unwrap();
        }
    });
    let sandbox = tempfile::tempdir().unwrap();
    let app_path = sandbox.path().join("Token BI.app");
    let exe = app_path.join("Contents/MacOS/token-bi");
    std::fs::create_dir_all(exe.parent().unwrap()).unwrap();
    std::fs::write(&exe, b"old version").unwrap();
    for name in ["token-bi-control", "token-bi-backend"] {
        let old_runtime = app_path.join(format!("Contents/Resources/{name}-runtime"));
        std::fs::create_dir_all(&old_runtime).unwrap();
        std::fs::write(old_runtime.join(name), b"old runtime").unwrap();
    }
    let mut context = tauri::test::mock_context(tauri::test::noop_assets());
    context
        .config_mut()
        .plugins
        .0
        .insert("updater".into(), config["plugins"]["updater"].clone());
    let app = tauri::test::mock_builder()
        .plugin(tauri_plugin_updater::Builder::new().build())
        .build(context)
        .unwrap();
    tauri::async_runtime::block_on(async {
        let update = app
            .updater_builder()
            .no_proxy()
            .timeout(Duration::from_secs(30))
            .target("darwin-aarch64")
            .executable_path(&exe)
            .endpoints(vec![format!("{url}/latest.json").parse().unwrap()])
            .unwrap()
            .build()
            .unwrap()
            .check()
            .await
            .unwrap()
            .expect("0.1.0 fixture must find a newer release");
        assert_eq!(update.version, config["version"].as_str().unwrap());
        let verified = update.download(|_, _| {}, || {}).await.unwrap();
        assert!(
            update.download(|_, _| {}, || {}).await.is_err(),
            "Tampered bytes must fail signature verification"
        );
        assert_eq!(
            std::fs::read(&exe).unwrap(),
            b"old version",
            "No replacement before explicit install"
        );
        update.install(verified).unwrap();
    });
    server.join().unwrap();
    assert!(std::fs::metadata(&exe).unwrap().len() > 1000);
    let canonical_app = app_path.canonicalize().unwrap();
    let runtime = app_path.join("Contents/Resources/token-bi-runtime");
    let alias = runtime.join("_internal/Python3");
    assert!(std::fs::symlink_metadata(&alias)
        .unwrap()
        .file_type()
        .is_symlink());
    assert!(alias.canonicalize().unwrap().starts_with(&canonical_app));
    for name in ["token-bi-control", "token-bi-backend"] {
        assert!(runtime.join(name).is_file());
        assert!(!app_path
            .join(format!("Contents/Resources/{name}-runtime"))
            .exists());
    }
    assert!(std::process::Command::new("codesign")
        .args(["--verify", "--deep", "--strict"])
        .arg(&app_path)
        .status()
        .unwrap()
        .success());
}
