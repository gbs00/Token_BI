use super::MENUBAR_TEMPLATE;
use serde_json::Value;
use std::f64::consts::{PI, TAU};

const SIZE: u32 = 36;
const CENTER: (f64, f64) = (17.5, 18.0);
const RADIUS: f64 = 9.0;
const HALF_STROKE: f64 = 1.4;
const INNER_BOUNDARY: f64 = 11.0;
const START: f64 = -3.0 * PI / 4.0;

#[derive(Clone, Debug, Default, PartialEq)]
struct Reading {
    percent: Option<u8>,
    label: &'static str,
    stale: bool,
}

impl Reading {
    fn from_status(status: &Value) -> Self {
        let dashboard = &status["dashboard"];
        if status["healthy"] != true
            || status["access_enabled"] == false
            || dashboard["account"]["status"] != "active"
        {
            return Self::default();
        }
        let Some(metrics) = dashboard["metrics"].as_array() else {
            return Self::default();
        };
        let selected = metrics
            .iter()
            .filter_map(|metric| {
                let percent = metric["remaining_pct"].as_f64().filter(|p| p.is_finite())?;
                let minutes = metric["window_minutes"]
                    .as_f64()
                    .or_else(|| metric["window_seconds"].as_f64().map(|s| s / 60.0));
                let rank = match (minutes, metric["metric_type"].as_str()) {
                    (Some(300.0), _) | (None, Some("session")) => 0,
                    (Some(10080.0), _) | (None, Some("weekly")) => 1,
                    _ => return None,
                };
                Some((rank, percent.clamp(0.0, 100.0).round() as u8))
            })
            .min_by_key(|(rank, _)| *rank);
        match selected {
            Some((rank, percent)) => Self {
                percent: Some(percent),
                label: if rank == 0 { "5h 额度" } else { "周额度" },
                stale: dashboard["state"] != "ready",
            },
            None => Self::default(),
        }
    }

    fn tooltip(&self) -> String {
        match self.percent {
            Some(percent) => format!(
                "Token BI · {}剩余 {}%{}",
                self.label,
                percent,
                if self.stale {
                    "（上次同步值，等待更新）"
                } else {
                    ""
                }
            ),
            None => "Token BI · 暂无有效额度".into(),
        }
    }
}

pub(super) fn image(percent: Option<u8>) -> tauri::image::Image<'static> {
    let mut rgba = MENUBAR_TEMPLATE.rgba().to_vec();
    let sweep = f64::from(percent.unwrap_or(0).min(100)) / 100.0 * TAU;
    let end = (
        RADIUS * (START + sweep).cos(),
        RADIUS * (START + sweep).sin(),
    );
    let start = (RADIUS * START.cos(), RADIUS * START.sin());
    for (index, pixel) in rgba.chunks_exact_mut(4).enumerate() {
        let x = (index % SIZE as usize) as f64 + 0.5 - CENTER.0;
        let y = (index / SIZE as usize) as f64 + 0.5 - CENTER.1;
        // 外环保留已验收的模板像素，只重绘内环及未知态。
        if x.hypot(y) >= INNER_BOUNDARY {
            continue;
        }
        let distance = match percent {
            None => (x.abs() - 2.5).max(0.0).hypot(y) - HALF_STROKE,
            Some(0) => f64::INFINITY,
            Some(_) => {
                let angle = (y.atan2(x) - START).rem_euclid(TAU);
                let centerline = if angle <= sweep {
                    (x.hypot(y) - RADIUS).abs()
                } else {
                    (x - start.0)
                        .hypot(y - start.1)
                        .min((x - end.0).hypot(y - end.1))
                };
                centerline - HALF_STROKE
            }
        };
        pixel.copy_from_slice(&[
            0,
            0,
            0,
            ((0.5 - distance).clamp(0.0, 1.0) * 255.0).round() as u8,
        ]);
    }
    tauri::image::Image::new_owned(rgba, SIZE, SIZE)
}

#[derive(Default)]
struct State {
    revision: u64,
    displayed: Option<Reading>,
}

impl State {
    fn begin(&mut self) -> u64 {
        self.revision = self.revision.wrapping_add(1);
        self.revision
    }

    fn accepts(&self, revision: u64, reading: &Reading) -> bool {
        revision == self.revision && self.displayed.as_ref() != Some(reading)
    }
}

#[cfg(target_os = "macos")]
mod runtime {
    use super::{image, Reading, State};
    use crate::menubar::{DesktopState, CONTROL_URL};
    use serde_json::Value;
    use std::sync::{atomic::Ordering, Mutex};
    use std::time::Duration;
    use tauri::Manager;

    #[derive(Default)]
    pub(crate) struct QuotaIcon(Mutex<State>);

    pub(crate) fn begin(app: &tauri::AppHandle) -> u64 {
        app.state::<QuotaIcon>().0.lock().unwrap().begin()
    }

    pub(crate) fn clear(app: &tauri::AppHandle) {
        complete(app, begin(app), None);
    }

    pub(crate) fn complete(app: &tauri::AppHandle, revision: u64, status: Option<&Value>) {
        let reading = status.map(Reading::from_status).unwrap_or_default();
        let handle = app.clone();
        let _ = app.run_on_main_thread(move || {
            let quota = handle.state::<QuotaIcon>();
            let mut state = quota.0.lock().unwrap();
            if !state.accepts(revision, &reading) {
                return;
            }
            let Some(tray) = handle.tray_by_id("token-bi") else {
                return;
            };
            let result = (|| -> Result<(), String> {
                if state.displayed.as_ref().map(|r| r.percent) != Some(reading.percent) {
                    let image = image(reading.percent);
                    tray.with_inner_tray_icon(move |inner| {
                        // set_icon 会清除模板标记，必须原子替换，避免深色模式黑色闪烁。
                        let icon = image.try_into().map_err(|e: tauri::Error| e.to_string())?;
                        inner
                            .set_icon_with_as_template(Some(icon), true)
                            .map_err(|e| e.to_string())
                    })
                    .map_err(|e| e.to_string())??;
                }
                tray.set_tooltip(Some(reading.tooltip()))
                    .map_err(|e| e.to_string())
            })();
            match result {
                Ok(()) => state.displayed = Some(reading),
                Err(error) => eprintln!("Token BI quota icon: {error}"),
            }
        });
    }

    pub(crate) fn start(app: &tauri::AppHandle) {
        let app = app.clone();
        tauri::async_runtime::spawn(async move {
            loop {
                let desktop = app.state::<DesktopState>();
                let ready = desktop.bootstrap.lock().unwrap()["phase"] == "ready";
                let visible = app
                    .get_webview_window("main")
                    .is_some_and(|w| w.is_visible().unwrap_or(false));
                // 展开时使用 panel_action 返回的同一份数据，收起时只读本机缓存。
                if ready && !visible && !desktop.shutdown.load(Ordering::SeqCst) {
                    let revision = begin(&app);
                    let result = async {
                        desktop
                            .client
                            .get(format!("{CONTROL_URL}api/status"))
                            .timeout(Duration::from_secs(6))
                            .send()
                            .await?
                            .error_for_status()?
                            .json::<Value>()
                            .await
                    }
                    .await;
                    if !desktop.shutdown.load(Ordering::SeqCst) {
                        complete(&app, revision, result.as_ref().ok());
                    }
                }
                tokio::time::sleep(Duration::from_secs(3)).await;
            }
        });
    }
}

#[cfg(target_os = "macos")]
pub(super) use runtime::{begin, clear, complete, start, QuotaIcon};

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn status(metrics: Value) -> Value {
        json!({"healthy":true,"access_enabled":true,"dashboard":{
            "account":{"status":"active"},"state":"ready","metrics":metrics}})
    }

    #[test]
    fn session_wins_even_when_weekly_is_lower_and_zero_is_valid() {
        for percent in [0, 25, 100] {
            let reading = Reading::from_status(&status(json!([
                {"metric_type":"weekly","remaining_pct":1},
                {"metric_type":"session","remaining_pct":percent}
            ])));
            assert_eq!(reading.percent, Some(percent));
            assert_eq!(reading.label, "5h 额度");
        }
    }

    #[test]
    fn absent_or_invalid_session_falls_back_to_weekly() {
        assert_eq!(
            Reading::from_status(&status(json!([{"metric_type":"weekly","remaining_pct":0}])))
                .percent,
            Some(0)
        );
        for missing in [Value::Null, json!("unknown"), json!(false)] {
            let reading = Reading::from_status(&status(json!([
                {"metric_type":"session","remaining_pct":missing},
                {"metric_type":"weekly","remaining_pct":47}
            ])));
            assert_eq!(reading.percent, Some(47));
            assert_eq!(reading.label, "周额度");
        }
        assert_eq!(Reading::from_status(&status(json!([]))).percent, None);
    }

    #[test]
    fn actual_window_duration_takes_precedence_over_legacy_type() {
        let reading = Reading::from_status(&status(json!([
            {"metric_type":"session","window_minutes":60,"remaining_pct":90},
            {"metric_type":"custom","window_seconds":604800,"remaining_pct":-10},
            {"metric_type":"custom","window_minutes":300,"remaining_pct":120}
        ])));
        assert_eq!(reading.percent, Some(100));
        assert_eq!(reading.label, "5h 额度");
    }

    #[test]
    fn unavailable_and_disconnected_never_render_zero_or_old_account_data() {
        let source = status(json!([{"metric_type":"weekly","remaining_pct":60}]));
        let mut disconnected = source.clone();
        disconnected["access_enabled"] = json!(false);
        let mut failed = source.clone();
        failed["healthy"] = json!(false);
        let mut expired = source.clone();
        expired["dashboard"]["account"]["status"] = json!("expired");
        let mut switching = source;
        switching["dashboard"]["metrics"] = json!([]);
        for value in [disconnected, failed, expired, switching, Value::Null] {
            assert_eq!(Reading::from_status(&value), Reading::default());
        }
    }

    #[test]
    fn stale_keeps_the_same_percentage_but_labels_it_as_cached() {
        let mut value = status(json!([{"metric_type":"weekly","remaining_pct":60}]));
        let ready = Reading::from_status(&value);
        value["dashboard"]["state"] = json!("stale");
        let stale = Reading::from_status(&value);
        assert_eq!(ready.percent, stale.percent);
        assert!(stale.tooltip().contains("上次同步值"));
        assert!(!ready.tooltip().contains("上次同步值"));
    }

    #[test]
    fn old_reads_cannot_restore_data_after_logout_or_overwrite_newer_sync() {
        let mut state = State::default();
        let old = state.begin();
        let current = state.begin();
        let reading = Reading {
            percent: Some(50),
            label: "5h 额度",
            stale: false,
        };
        assert!(!state.accepts(old, &reading));
        assert!(state.accepts(current, &reading));
        state.displayed = Some(reading.clone());
        assert!(!state.accepts(current, &reading));
        let logout = state.begin();
        assert!(!state.accepts(current, &reading));
        assert!(state.accepts(logout, &Reading::default()));
    }

    #[test]
    fn ring_preserves_outer_pixels_and_proportion_including_endpoints() {
        let mut previous = 0;
        for percent in [0, 25, 50, 75, 100] {
            let icon = image(Some(percent));
            assert_eq!((icon.width(), icon.height()), (SIZE, SIZE));
            let mut coverage = 0;
            for (index, pixel) in icon.rgba().chunks_exact(4).enumerate() {
                let x = (index % SIZE as usize) as f64 + 0.5 - CENTER.0;
                let y = (index / SIZE as usize) as f64 + 0.5 - CENTER.1;
                if x.hypot(y) >= INNER_BOUNDARY {
                    assert_eq!(pixel, &MENUBAR_TEMPLATE.rgba()[index * 4..index * 4 + 4]);
                } else {
                    coverage += pixel[3] as u32;
                    assert_eq!(&pixel[..3], &[0, 0, 0]);
                }
            }
            if percent == 0 {
                assert_eq!(coverage, 0);
            } else {
                assert!(coverage > previous);
            }
            previous = coverage;
        }
        assert_ne!(image(None).rgba(), image(Some(0)).rgba());
        // 未知态有中线；完整内环仍为空心，而不是实心圆。
        let center = (18 * SIZE as usize + 17) * 4 + 3;
        assert_eq!(image(None).rgba()[center], 255);
        assert_eq!(image(Some(100)).rgba()[center], 0);
    }

    #[test]
    fn arc_starts_at_upper_left_and_expands_clockwise() {
        let alpha = |percent, x, y| image(Some(percent)).rgba()[(y * SIZE as usize + x) * 4 + 3];
        assert!(alpha(25, 17, 9) > 200);
        assert_eq!(alpha(25, 26, 18), 0);
        assert!(alpha(50, 26, 18) > 200);
        assert_eq!(alpha(50, 17, 27), 0);
        assert!(alpha(75, 17, 27) > 200);
        assert_eq!(alpha(75, 8, 18), 0);
        assert!(alpha(100, 8, 18) > 200);
    }

    #[test]
    #[ignore = "显式导出生产渲染结果供本地视觉验收"]
    fn export_quota_icon_preview_when_requested() {
        let directory = std::env::var_os("TOKEN_BI_ICON_QA_DIR").expect("TOKEN_BI_ICON_QA_DIR");
        let directory = std::path::PathBuf::from(directory);
        std::fs::create_dir_all(&directory).unwrap();
        for percent in [
            None,
            Some(0),
            Some(1),
            Some(25),
            Some(50),
            Some(75),
            Some(100),
        ] {
            let name = percent
                .map(|p| p.to_string())
                .unwrap_or_else(|| "unknown".into());
            std::fs::write(
                directory.join(format!("{name}.rgba")),
                image(percent).rgba(),
            )
            .unwrap();
        }
    }
}
