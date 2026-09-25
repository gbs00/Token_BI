use std::env;
use std::os::unix::process::CommandExt;
use std::path::Path;
use std::process::{exit, Command};

fn main() {
    let current_exe = env::current_exe().unwrap_or_else(|error| {
        eprintln!("Unable to locate Token BI control launcher: {error}");
        exit(1);
    });
    let bin_dir = current_exe.parent().unwrap_or_else(|| Path::new("."));
    let runtime = [
        bin_dir.join("../Resources/token-bi-runtime"),
        bin_dir.join("../../dist/token-bi-runtime"),
    ]
    .into_iter()
    .find(|directory| {
        directory.join("token-bi-control").is_file() && directory.join("token-bi-backend").is_file()
    })
    .unwrap_or_else(|| {
        eprintln!("Unable to locate Token BI shared runtime.");
        exit(1);
    });

    let mut command = Command::new(runtime.join("token-bi-control"));
    command.args(env::args_os().skip(1));
    command.env(
        "TOKEN_BI_MAIN_BACKEND_BIN",
        runtime.join("token-bi-backend"),
    );

    let error = command.exec();
    eprintln!("Unable to start Token BI control runtime: {error}");
    exit(1);
}
