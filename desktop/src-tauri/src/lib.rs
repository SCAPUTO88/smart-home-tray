mod positioning;

use std::sync::{
    Mutex,
    atomic::{AtomicBool, Ordering},
};
use tauri::{
    Manager, PhysicalPosition, PhysicalSize, WebviewWindow, WindowEvent,
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
};
use tauri_plugin_positioner::{Position, WindowExt};

const OPEN_MENU_ID: &str = "open-panel";
const QUIT_MENU_ID: &str = "quit-app";

#[derive(Default)]
struct ExitRequested(AtomicBool);

#[derive(Default)]
struct TrayAnchor(Mutex<Option<positioning::Rect>>);

fn show_panel(window: &WebviewWindow, tray: Option<positioning::Rect>) {
    if window.is_minimized().unwrap_or(false) {
        let _ = window.unminimize();
    }

    let tray_monitor = tray.and_then(|rect| {
        let center_x = rect.x as f64 + rect.width as f64 / 2.0;
        let center_y = rect.y as f64 + rect.height as f64 / 2.0;
        window.monitor_from_point(center_x, center_y).ok().flatten()
    });
    let monitor = tray_monitor
        .or_else(|| window.current_monitor().ok().flatten())
        .or_else(|| window.primary_monitor().ok().flatten());

    if let Some(monitor) = monitor {
        let work = monitor.work_area();
        let area = positioning::Rect {
            x: work.position.x,
            y: work.position.y,
            width: work.size.width,
            height: work.size.height,
        };
        let original_size = window.outer_size().unwrap_or(PhysicalSize::new(420, 720));
        let width = original_size.width.min(area.width);
        let height = original_size.height.min(area.height);
        if width != original_size.width || height != original_size.height {
            let _ = window.set_size(PhysicalSize::new(width, height));
        }

        let positioned_from_tray =
            tray.is_some() && window.move_window(Position::TrayRight).is_ok();
        let desired = if positioned_from_tray {
            window
                .outer_position()
                .ok()
                .map(|point| positioning::Point {
                    x: point.x,
                    y: point.y,
                })
                .unwrap_or_else(|| positioning::fallback_position(area, width, height))
        } else {
            positioning::fallback_position(area, width, height)
        };
        let point = positioning::clamp_position(area, width, height, desired);
        let _ = window.set_position(PhysicalPosition::new(point.x, point.y));
    }

    let _ = window.show();
    let _ = window.set_focus();
}

fn remember_tray_rect(event: &TrayIconEvent) -> Option<positioning::Rect> {
    let rect = match event {
        TrayIconEvent::Click { rect, .. }
        | TrayIconEvent::DoubleClick { rect, .. }
        | TrayIconEvent::Enter { rect, .. }
        | TrayIconEvent::Move { rect, .. }
        | TrayIconEvent::Leave { rect, .. } => rect,
        _ => return None,
    };
    let position: PhysicalPosition<f64> = rect.position.to_physical(1.0);
    let size: PhysicalSize<f64> = rect.size.to_physical(1.0);
    Some(positioning::Rect {
        x: (position.x as f64).round() as i32,
        y: (position.y as f64).round() as i32,
        width: (size.width as f64).round() as u32,
        height: (size.height as f64).round() as u32,
    })
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                show_panel(&window, None);
            }
        }))
        .plugin(tauri_plugin_positioner::init())
        .setup(|app| {
            app.manage(ExitRequested::default());
            app.manage(TrayAnchor::default());

            let open = MenuItem::with_id(
                app,
                OPEN_MENU_ID,
                "Abrir Smart Home Tray",
                true,
                None::<&str>,
            )?;
            let quit = MenuItem::with_id(app, QUIT_MENU_ID, "Sair", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open, &quit])?;

            let _tray = TrayIconBuilder::new()
                .icon(
                    app.default_window_icon()
                        .expect("default app icon is configured")
                        .clone(),
                )
                .tooltip("Smart Home Tray")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id().as_ref() {
                    OPEN_MENU_ID => {
                        let anchor = app
                            .state::<TrayAnchor>()
                            .0
                            .lock()
                            .ok()
                            .and_then(|anchor| *anchor);
                        if let Some(window) = app.get_webview_window("main") {
                            show_panel(&window, anchor);
                        }
                    }
                    QUIT_MENU_ID => {
                        app.state::<ExitRequested>().0.store(true, Ordering::SeqCst);
                        app.exit(0);
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    tauri_plugin_positioner::on_tray_event(tray.app_handle(), &event);
                    let anchor = remember_tray_rect(&event);
                    if let Some(anchor) = anchor {
                        if let Ok(mut last_anchor) =
                            tray.app_handle().state::<TrayAnchor>().0.lock()
                        {
                            *last_anchor = Some(anchor);
                        }
                    }

                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        if let Some(window) = tray.app_handle().get_webview_window("main") {
                            if window.is_visible().unwrap_or(false) {
                                let _ = window.hide();
                            } else {
                                show_panel(&window, anchor);
                            }
                        }
                    }
                })
                .build(app)?;

            if let Some(window) = app.get_webview_window("main") {
                let app_handle = app.handle().clone();
                window.on_window_event(move |event| {
                    if let WindowEvent::CloseRequested { api, .. } = event {
                        if !app_handle.state::<ExitRequested>().0.load(Ordering::SeqCst) {
                            api.prevent_close();
                            if let Some(window) = app_handle.get_webview_window("main") {
                                let _ = window.hide();
                            }
                        }
                    }
                });
            }

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while building tauri application");
}
