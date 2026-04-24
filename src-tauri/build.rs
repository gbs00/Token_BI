use std::path::PathBuf;

fn main() {
    let manifest_dir = PathBuf::from(std::env::var("CARGO_MANIFEST_DIR").unwrap());
    let project_root = manifest_dir
        .parent()
        .expect("src-tauri should be inside the project root");
    println!("cargo:rustc-env=TOKEN_BI_PROJECT_ROOT={}", project_root.display());
    tauri_build::build();
}
