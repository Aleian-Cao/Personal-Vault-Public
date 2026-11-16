use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_clipboard_manager::ClipboardExt;
use tauri_plugin_global_shortcut::ShortcutState;
use serde::{Deserialize, Serialize};

const CLIPBOARD_CLEAR_SECS: u64 = 20;

#[derive(Clone, Serialize, Deserialize)]
struct JsonRpcRequest {
    id: u64,
    method: String,
    params: serde_json::Value,
}

#[derive(Clone, Serialize, Deserialize)]
struct JsonRpcResponse {
    id: Option<u64>,
    result: Option<serde_json::Value>,
    error: Option<String>,
}

struct SidecarProcess {
    child: Child,
    reader: BufReader<std::process::ChildStdout>,
}

struct AppState {
    sidecar: Arc<Mutex<Option<SidecarProcess>>>,
    sidecar_path: Arc<Mutex<Option<PathBuf>>>,
    request_counter: Arc<Mutex<u64>>,
}

/// One request/response exchange. Any transport failure is an Err the caller treats as "sidecar is gone".
fn exchange(
    sidecar: &mut SidecarProcess,
    req_id: u64,
    method: &str,
    params: serde_json::Value,
) -> Result<Result<serde_json::Value, String>, String> {
    let req = JsonRpcRequest { id: req_id, method: method.to_string(), params };
    let req_json = serde_json::to_string(&req).map_err(|e| e.to_string())?;
    let stdin = sidecar.child.stdin.as_mut().ok_or_else(|| "Sidecar stdin is unavailable".to_string())?;

    writeln!(stdin, "{}", req_json).map_err(|e| format!("Failed to write to sidecar: {}", e))?;
    stdin.flush().map_err(|e| format!("Failed to flush sidecar stdin: {}", e))?;

    let mut line = String::new();
    let n = sidecar.reader.read_line(&mut line).map_err(|e| format!("Failed to read sidecar response: {}", e))?;
    if n == 0 || line.trim().is_empty() {
        return Err("Empty response from sidecar (process may have crashed)".to_string());
    }

    // Never echo the raw line back on parse errors: it may contain vault data.
    let resp: JsonRpcResponse = serde_json::from_str(&line).map_err(|e| format!("Invalid JSON from sidecar: {}", e))?;
    if resp.id != Some(req_id) {
        return Err("Sidecar response did not match the request".to_string());
    }
    // An application-level error (e.g. "Vault is locked.") is a normal outcome, not a transport failure.
    Ok(match resp.error {
        Some(err) => Err(err),
        None => Ok(resp.result.unwrap_or(serde_json::Value::Null)),
    })
}

fn call_sidecar(
    state: &AppState,
    method: &str,
    params: serde_json::Value,
) -> Result<serde_json::Value, String> {
    let mut sidecar_lock = state.sidecar.lock().map_err(|_| "Failed to lock sidecar state".to_string())?;

    // Fail closed: a dead/missing sidecar is replaced by a FRESH one, which starts locked. We never reuse
    // anything from the process that died, so no stale vault state can survive a crash.
    let dead = match sidecar_lock.as_mut() {
        Some(s) => s.child.try_wait().map(|r| r.is_some()).unwrap_or(true),
        None => true,
    };
    if dead {
        if let Some(mut old) = sidecar_lock.take() {
            let _ = old.child.kill();
            let _ = old.child.wait();
        }
        let path = state.sidecar_path.lock().map_err(|_| "Failed to lock sidecar path".to_string())?.clone()
            .ok_or_else(|| "Sidecar process is not running".to_string())?;
        *sidecar_lock = Some(spawn_at(&path)?);
    }

    let mut id_lock = state.request_counter.lock().map_err(|_| "Failed to lock id counter".to_string())?;
    *id_lock += 1;
    let req_id = *id_lock;
    drop(id_lock);

    let sidecar = sidecar_lock.as_mut().ok_or_else(|| "Sidecar process is not running".to_string())?;
    match exchange(sidecar, req_id, method, params) {
        Ok(app_result) => app_result,
        Err(transport) => {
            if let Some(mut old) = sidecar_lock.take() {
                let _ = old.child.kill();
                let _ = old.child.wait();
            }
            Err(transport)
        }
    }
}

#[tauri::command]
fn invoke_sidecar(
    state: tauri::State<AppState>,
    method: String,
    params: serde_json::Value,
) -> Result<serde_json::Value, String> {
    call_sidecar(&state, &method, params)
}

/// Native password copy: the secret goes sidecar -> Rust -> OS clipboard and never reaches the webview.
/// Cleared after CLIPBOARD_CLEAR_SECS only if the clipboard still holds exactly this value.
#[tauri::command]
fn copy_password(
    app: AppHandle,
    state: tauri::State<AppState>,
    entry_id: String,
) -> Result<serde_json::Value, String> {
    let res = call_sidecar(&state, "reveal", serde_json::json!({ "entry_id": entry_id }))?;
    let pw = res
        .get("password")
        .and_then(|v| v.as_str())
        .ok_or_else(|| "Password unavailable".to_string())?
        .to_string();

    app.clipboard().write_text(pw.clone()).map_err(|e| e.to_string())?;

    let handle = app.clone();
    std::thread::spawn(move || {
        std::thread::sleep(Duration::from_secs(CLIPBOARD_CLEAR_SECS));
        if let Ok(current) = handle.clipboard().read_text() {
            if current == pw {
                let _ = handle.clipboard().write_text(String::new());
            }
        }
    });

    Ok(serde_json::json!({ "success": true, "clearedIn": CLIPBOARD_CLEAR_SECS }))
}

#[tauri::command]
fn show_main_window(app: AppHandle) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.unminimize();
        let _ = w.show();
        let _ = w.set_focus();
    }
}

fn locate_sidecar(app_handle: &AppHandle) -> Result<PathBuf, String> {
    let resource_dir = app_handle.path().resource_dir().map_err(|e| e.to_string())?;
    let exe_candidates = vec![
        resource_dir.join("pvault-sidecar.exe"),
        resource_dir.join("bin").join("pvault-sidecar.exe"),
        resource_dir.join("bin").join("pvault-sidecar-x86_64-pc-windows-msvc.exe"),
        std::env::current_exe()
            .map(|p| p.parent().unwrap_or(Path::new("")).join("pvault-sidecar.exe"))
            .unwrap_or_default(),
    ];
    exe_candidates.into_iter().find(|c| c.exists()).ok_or_else(|| "Could not locate pvault-sidecar.exe".to_string())
}

fn spawn_at(bin_path: &Path) -> Result<SidecarProcess, String> {
    #[cfg(windows)]
    // CREATE_NO_WINDOW keeps the sidecar's console hidden. (DETACHED_PROCESS was measured: it does not remove conhost.exe because
    // the PyInstaller bootloader allocates a console for the Python child, and it risks a visible console window.)
    const CREATE_NO_WINDOW: u32 = 0x08000000;

    #[cfg(windows)]
    use std::os::windows::process::CommandExt;

    let mut cmd = Command::new(bin_path);
    cmd.stdin(Stdio::piped())
       .stdout(Stdio::piped())
       .stderr(Stdio::null());

    #[cfg(windows)]
    cmd.creation_flags(CREATE_NO_WINDOW);

    let mut child = cmd.spawn().map_err(|e| format!("Failed to spawn sidecar at {:?}: {}", bin_path, e))?;
    let stdout = child.stdout.take().ok_or_else(|| "Failed to capture stdout of sidecar".to_string())?;
    let mut reader = BufReader::new(stdout);

    // Read initial "ready" banner
    let mut banner = String::new();
    reader.read_line(&mut banner).map_err(|e| format!("Failed to read ready banner: {}", e))?;

    Ok(SidecarProcess { child, reader })
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let sidecar_holder = Arc::new(Mutex::new(None));
    let sidecar_clone = sidecar_holder.clone();
    let path_holder: Arc<Mutex<Option<PathBuf>>> = Arc::new(Mutex::new(None));
    let path_clone = path_holder.clone();

    tauri::Builder::default()
        .plugin(tauri_plugin_clipboard_manager::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.unminimize();
                let _ = w.show();
                let _ = w.set_focus();
            }
        }))
        .manage(AppState {
            sidecar: sidecar_holder.clone(),
            sidecar_path: path_holder.clone(),
            request_counter: Arc::new(Mutex::new(0)),
        })
        .invoke_handler(tauri::generate_handler![invoke_sidecar, copy_password, show_main_window])
        .setup(move |app| {
            match locate_sidecar(&app.handle()) {
                Ok(path) => {
                    *path_clone.lock().unwrap() = Some(path.clone());
                    match spawn_at(&path) {
                        Ok(proc) => *sidecar_clone.lock().unwrap() = Some(proc),
                        Err(err) => eprintln!("Warning: could not spawn sidecar immediately: {}", err),
                    }
                }
                Err(err) => eprintln!("Warning: {}", err),
            }

            // Ctrl+Alt+V opens the compact Quick Access window (never bypasses the backend lock:
            // the window itself asks the backend for the lock state).
            use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut};
            let shortcut: Result<Shortcut, _> = "ctrl+alt+v".parse();
            if let Ok(sc) = shortcut {
                let app_handle = app.handle().clone();
                let _ = app.global_shortcut().on_shortcut(sc, move |_app, _sc, event| {
                    if event.state() != ShortcutState::Pressed {
                        return;
                    }
                    if let Some(w) = app_handle.get_webview_window("quick") {
                        let _ = w.center();
                        let _ = w.show();
                        let _ = w.set_focus();
                        let _ = w.emit("quick-access-open", ());
                    }
                });
            }

            Ok(())
        })
        .on_window_event(|window, event| match event {
            // Quick Access is hidden, never destroyed, so the app does not linger without a main window.
            tauri::WindowEvent::CloseRequested { api, .. } if window.label() == "quick" => {
                api.prevent_close();
                let _ = window.hide();
            }
            tauri::WindowEvent::Destroyed if window.label() == "main" => {
                if let Some(state) = window.try_state::<AppState>() {
                    if let Ok(mut lock) = state.sidecar.lock() {
                        if let Some(mut proc) = lock.take() {
                            let _ = proc.child.kill();
                        }
                    }
                }
                window.app_handle().exit(0);
            }
            _ => {}
        })
        .run(tauri::generate_context!())
        .expect("error while building tauri application");
}
