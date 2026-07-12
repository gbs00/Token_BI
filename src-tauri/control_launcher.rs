use std::env;
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{exit, Command};

fn first_executable(candidates: &[PathBuf]) -> Option<PathBuf> {
    candidates.iter().find(|path| path.is_file()).cloned()
}

fn packaged_runtime(bin_dir: &Path) -> PathBuf {
    bin_dir.join("../Resources/token-bi-control-runtime/token-bi-control")
}

fn development_runtime(bin_dir: &Path) -> PathBuf {
    bin_dir.join("../../dist/token-bi-control/token-bi-control")
}

fn packaged_backend(bin_dir: &Path) -> PathBuf {
    bin_dir.join("../Resources/token-bi-backend-runtime/token-bi-backend")
}

fn development_backend(bin_dir: &Path) -> PathBuf {
    bin_dir.join("../../dist/token-bi-backend/token-bi-backend")
}

fn main() {
    let current_exe = env::current_exe().unwrap_or_else(|error| {
        eprintln!("Unable to locate Token BI control launcher: {error}");
        exit(1);
    });
    let bin_dir = current_exe.parent().unwrap_or_else(|| Path::new("."));
    let runtime = first_executable(&[packaged_runtime(bin_dir), development_runtime(bin_dir)])
        .unwrap_or_else(|| {
            eprintln!("Unable to locate Token BI control runtime.");
            exit(1);
        });

    let backend = first_executable(&[packaged_backend(bin_dir), development_backend(bin_dir)]);
    let mut command = Command::new(runtime);
    command.args(env::args_os().skip(1));
    if let Some(backend) = backend {
        command.env("TOKEN_BI_MAIN_BACKEND_BIN", backend);
    }

    let error = command.exec();
    eprintln!("Unable to start Token BI control runtime: {error}");
    exit(1);
}
