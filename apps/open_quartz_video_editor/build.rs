fn main() {
    let config = slint_build::CompilerConfiguration::new()
        .with_include_paths(vec![std::env::var_os("DEP_SLINT_CODE_EDITOR_UI_DIR").expect("Slint source directory").into()])
        .with_debug_info(std::env::var_os("CARGO_FEATURE_UI_AUTOMATION").is_some());
    slint_build::compile_with_config("ui/editor.slint", config)
        .expect("cannot compile OpenQuartz video editor UI");

    #[cfg(windows)]
    if std::env::var("CARGO_CFG_TARGET_ENV").as_deref() == Ok("msvc") {
        embed_windows_icon();
    }
}

#[cfg(windows)]
fn embed_windows_icon() {
    use std::{path::PathBuf, process::Command};

    println!("cargo:rerun-if-changed=assets/icon.rc");
    println!("cargo:rerun-if-changed=assets/icon.ico");
    let sdk = find_msvc_tools::find_windows_sdk(std::env::consts::ARCH)
        .expect("cannot find the Windows SDK for the Studio icon");
    let compiler = sdk.path().map(|dir| dir.join("rc.exe")).find(|path| path.is_file())
        .expect("cannot find rc.exe in the Windows SDK");
    let resource = PathBuf::from(std::env::var_os("OUT_DIR").expect("Cargo output directory"))
        .join("studio-icon.res");
    let status = Command::new(compiler)
        .arg("/nologo")
        .arg("/fo")
        .arg(&resource)
        .arg("assets/icon.rc")
        .status()
        .expect("cannot start the Windows resource compiler");
    assert!(status.success(), "cannot compile the Studio icon resource");
    println!("cargo:rustc-link-arg-bin=open_quartz_video_editor={}", resource.display());
}
