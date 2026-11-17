use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::sync::Mutex;

use tauri::menu::{Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{Manager, RunEvent, WindowEvent};

/// Keeps the Python sidecar alive for the lifetime of the window.
struct Backend(Mutex<Option<Child>>);

fn sidecar_name() -> &'static str {
    if cfg!(windows) {
        "funpay-monitor-core.exe"
    } else {
        "funpay-monitor-core"
    }
}

fn python_candidates(project: &Path) -> Vec<PathBuf> {
    let mut candidates = Vec::new();
    if let Ok(explicit) = std::env::var("FUNPAY_PYTHON") {
        candidates.push(PathBuf::from(explicit));
    }
    if cfg!(windows) {
        candidates.push(project.join(".venv").join("Scripts").join("python.exe"));
        candidates.push(PathBuf::from("python"));
    } else {
        candidates.push(project.join(".venv").join("bin").join("python"));
        candidates.push(PathBuf::from("python3"));
        candidates.push(PathBuf::from("python"));
    }
    candidates
}

#[cfg_attr(
    not(all(windows, not(debug_assertions))),
    allow(unused_variables)
)]
fn prepare(command: &mut Command) {
    #[cfg(all(windows, not(debug_assertions)))]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }
}

/// Start the bundled core, or fall back to `python -m app.desktop` in a source checkout.
fn spawn_backend(app: &tauri::AppHandle) -> Option<Child> {
    let data_dir = app.path().app_data_dir().ok()?;
    std::fs::create_dir_all(&data_dir).ok()?;

    if let Ok(explicit) = std::env::var("FUNPAY_CORE_BIN") {
        let mut command = Command::new(explicit);
        command.env("FUNPAY_DATA_DIR", &data_dir);
        prepare(&mut command);
        return command.spawn().ok();
    }

    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            let bundled = dir.join(sidecar_name());
            if bundled.exists() {
                let mut command = Command::new(bundled);
                command.env("FUNPAY_DATA_DIR", &data_dir);
                prepare(&mut command);
                return command.spawn().ok();
            }
        }
    }

    // `CARGO_MANIFEST_DIR` is `frontend/src-tauri`; the Python package lives
    // two levels up in the repository root.
    let project = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .map(Path::to_path_buf)?;
    for python in python_candidates(&project) {
        let mut command = Command::new(&python);
        command
            .arg("-m")
            .arg("app.desktop")
            .current_dir(&project)
            .env("FUNPAY_DATA_DIR", &data_dir);
        prepare(&mut command);
        if let Ok(child) = command.spawn() {
            return Some(child);
        }
    }

    eprintln!("FunPay Monitor: could not start the Python backend");
    None
}

fn show_main_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

pub fn run() {
    let app = tauri::Builder::default()
        .setup(|app| {
            let child = spawn_backend(app.handle());
            app.manage(Backend(Mutex::new(child)));

            let show = MenuItem::with_id(app, "show", "Открыть", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Выход", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &quit])?;
            TrayIconBuilder::new()
                .icon(app.default_window_icon().expect("missing app icon").clone())
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => show_main_window(app),
                    "quit" => app.exit(0),
                    _ => {}
                })
                .build(app)?;
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .build(tauri::generate_context!())
        .expect("failed to build the Tauri application");

    app.run(|app_handle, event| {
        if let RunEvent::Exit = event {
            if let Some(state) = app_handle.try_state::<Backend>() {
                if let Some(mut child) = state.0.lock().expect("backend mutex poisoned").take() {
                    let _ = child.kill();
                    let _ = child.wait();
                }
            }
        }
    });
}
