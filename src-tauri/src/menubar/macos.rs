#[cfg(test)]
use super::{PANEL_HEIGHT, PANEL_WIDTH};
use objc2::MainThreadMarker;
use objc2_app_kit::{NSColor, NSScreen, NSWindow};
use objc2_foundation::{NSPoint, NSRect, NSSize};
use tauri::WebviewWindow;

const CORNER_RADIUS: f64 = 12.0;
const SCREEN_MARGIN: f64 = 6.0;

fn native_window(window: &WebviewWindow) -> Result<&NSWindow, String> {
    MainThreadMarker::new().ok_or("Panel must be configured on the main thread")?;
    let pointer = window.ns_window().map_err(|error| error.to_string())?;
    // Tauri owns this NSWindow; the borrow cannot outlive its WebviewWindow handle.
    unsafe { pointer.cast::<NSWindow>().as_ref() }.ok_or("Panel window unavailable".into())
}

pub(super) fn configure(window: &WebviewWindow) -> Result<(), String> {
    let native = native_window(window)?;
    let content = native
        .contentView()
        .ok_or("Panel content view unavailable")?;
    content.setWantsLayer(true);
    let layer = content.layer().ok_or("Panel content layer unavailable")?;
    // Clip the opaque WKWebView at the native boundary, without private WK settings.
    layer.setCornerRadius(CORNER_RADIUS);
    layer.setMasksToBounds(true);
    native.setOpaque(false);
    native.setBackgroundColor(Some(&NSColor::clearColor()));
    native.setHasShadow(true);
    Ok(())
}

pub(super) fn position(
    app: &tauri::AppHandle,
    window: &WebviewWindow,
    width: f64,
    height: f64,
) -> Result<(), String> {
    let mtm = MainThreadMarker::new().ok_or("Panel must be positioned on the main thread")?;
    let native = native_window(window)?;
    let anchor = app.tray_by_id("token-bi").and_then(|tray| {
        tray.with_inner_tray_icon(|inner| {
            let mtm = MainThreadMarker::new()?;
            let item = inner.ns_status_item()?;
            let button = item.button(mtm)?;
            let tray_window = button.window()?;
            let screen = tray_window.screen()?;
            Some((tray_window.frame(), screen.visibleFrame()))
        })
        .ok()
        .flatten()
    });
    let (tray, area) = match anchor {
        Some((tray, area)) => (Some(tray), area),
        None => {
            let screen = native
                .screen()
                .or_else(|| NSScreen::mainScreen(mtm))
                .ok_or("Panel display unavailable")?;
            (None, screen.visibleFrame())
        }
    };
    // AppKit frames are all logical points, even across mixed-DPI displays. Apply
    // origin and size together before showing; do not divide by the old window scale.
    native.setFrame_display(window_frame(tray, area, NSSize::new(width, height)), false);
    native.invalidateShadow();
    Ok(())
}

fn window_frame(tray: Option<NSRect>, area: NSRect, size: NSSize) -> NSRect {
    let margin = SCREEN_MARGIN
        .min(area.size.width / 2.0)
        .min(area.size.height / 2.0);
    let width = size.width.min((area.size.width - margin * 2.0).max(1.0));
    let height = size.height.min((area.size.height - margin * 2.0).max(1.0));
    let left = area.origin.x + margin;
    let bottom = area.origin.y + margin;
    let right = (area.origin.x + area.size.width - margin - width).max(left);
    let top = (area.origin.y + area.size.height - margin - height).max(bottom);
    let (x, y) = tray
        .map(|tray| {
            (
                tray.origin.x + tray.size.width / 2.0 - width / 2.0,
                tray.origin.y - margin - height,
            )
        })
        .unwrap_or((right, top));
    NSRect::new(
        NSPoint::new(x.clamp(left, right), y.clamp(bottom, top)),
        NSSize::new(width, height),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rect(x: f64, y: f64, width: f64, height: f64) -> NSRect {
        NSRect::new(NSPoint::new(x, y), NSSize::new(width, height))
    }

    #[test]
    fn panel_frame_is_in_logical_points_below_the_tray() {
        let area = rect(0.0, 48.0, 1440.0, 824.0);
        let tray = rect(1200.0, 872.0, 24.0, 28.0);
        let expected = rect(1056.5, 266.0, 311.0, 600.0);
        assert_eq!(
            window_frame(Some(tray), area, NSSize::new(PANEL_WIDTH, PANEL_HEIGHT)),
            expected
        );
    }

    #[test]
    fn negative_origin_and_dock_insets_are_respected() {
        let area = rect(-1870.0, -120.0, 1814.0, 1052.0);
        let frame = window_frame(
            Some(rect(-64.0, 932.0, 24.0, 28.0)),
            area,
            NSSize::new(PANEL_WIDTH, PANEL_HEIGHT),
        );
        assert_eq!(frame, rect(-373.0, 326.0, 311.0, 600.0));
    }

    #[test]
    fn short_display_shrinks_height_without_halving_width() {
        assert_eq!(
            window_frame(
                Some(rect(760.0, 440.0, 24.0, 28.0)),
                rect(0.0, 24.0, 800.0, 416.0),
                NSSize::new(PANEL_WIDTH, PANEL_HEIGHT)
            ),
            rect(483.0, 30.0, 311.0, 404.0)
        );
    }

    #[test]
    fn missing_tray_and_small_work_area_stay_on_screen() {
        assert_eq!(
            window_frame(
                None,
                rect(-320.0, 24.0, 320.0, 400.0),
                NSSize::new(PANEL_WIDTH, PANEL_HEIGHT)
            ),
            rect(-314.0, 30.0, 308.0, 388.0)
        );
    }
}
