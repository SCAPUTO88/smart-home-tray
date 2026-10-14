#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Rect {
    pub x: i32,
    pub y: i32,
    pub width: u32,
    pub height: u32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Point {
    pub x: i32,
    pub y: i32,
}

/// Constrains a physical-pixel window position to a monitor's visible work area.
pub fn clamp_position(area: Rect, window_width: u32, window_height: u32, desired: Point) -> Point {
    let max_x = area
        .x
        .saturating_add(area.width.saturating_sub(window_width) as i32);
    let max_y = area
        .y
        .saturating_add(area.height.saturating_sub(window_height) as i32);
    Point {
        x: desired.x.clamp(area.x, max_x),
        y: desired.y.clamp(area.y, max_y),
    }
}

pub fn fallback_position(area: Rect, width: u32, height: u32) -> Point {
    clamp_position(
        area,
        width,
        height,
        Point {
            x: area
                .x
                .saturating_add(area.width as i32)
                .saturating_sub(width as i32),
            y: area
                .y
                .saturating_add(area.height as i32)
                .saturating_sub(height as i32),
        },
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn clamps_physical_window_on_monitor_with_negative_coordinates() {
        let work_area = Rect {
            x: -1920,
            y: -80,
            width: 1920,
            height: 1040,
        };
        let point = clamp_position(work_area, 525, 900, Point { x: -2300, y: 1200 });
        assert_eq!(point, Point { x: -1920, y: 60 });
    }

    #[test]
    fn clamps_popup_inside_work_area_below_a_top_taskbar() {
        let work_area = Rect {
            x: 0,
            y: 40,
            width: 1600,
            height: 860,
        };
        assert_eq!(
            clamp_position(work_area, 420, 720, Point { x: 30, y: 29 }),
            Point { x: 30, y: 40 }
        );
    }

    #[test]
    fn clamps_physical_size_scaled_to_125_percent() {
        let work_area = Rect {
            x: 0,
            y: 0,
            width: 1920,
            height: 1040,
        };
        assert_eq!(
            clamp_position(work_area, 525, 900, Point { x: 1850, y: 1000 }),
            Point { x: 1395, y: 140 }
        );
    }

    #[test]
    fn fallback_uses_the_visible_bottom_right_corner() {
        let work_area = Rect {
            x: 0,
            y: 0,
            width: 1280,
            height: 720,
        };
        assert_eq!(
            fallback_position(work_area, 420, 720),
            Point { x: 860, y: 0 }
        );
    }

    #[test]
    fn oversized_popup_is_anchored_at_work_area_origin_for_runtime_resize() {
        let work_area = Rect {
            x: -100,
            y: -20,
            width: 500,
            height: 400,
        };
        assert_eq!(
            clamp_position(work_area, 700, 600, Point { x: 50, y: 50 }),
            Point { x: -100, y: -20 }
        );
    }
}
#[cfg(test)]
mod tray_review_tests {
    use super::*;

    #[test]
    fn positions_popup_below_top_taskbar_tray() {
        let work = Rect {
            x: 0,
            y: 42,
            width: 1920,
            height: 1038,
        };
        let tray = Rect {
            x: 1800,
            y: 8,
            width: 40,
            height: 24,
        };
        assert_eq!(
            popup_position(work, tray, TaskbarEdge::Top, 420, 720, 10),
            Point { x: 1500, y: 42 }
        );
    }

    #[test]
    fn positions_popup_above_bottom_taskbar_tray() {
        let work = Rect {
            x: 0,
            y: 0,
            width: 1920,
            height: 1040,
        };
        let tray = Rect {
            x: 1800,
            y: 1040,
            width: 40,
            height: 24,
        };
        assert_eq!(
            popup_position(work, tray, TaskbarEdge::Bottom, 420, 720, 10),
            Point { x: 1500, y: 310 }
        );
    }

    #[test]
    fn positions_popup_right_of_left_taskbar_tray() {
        let work = Rect {
            x: 48,
            y: 0,
            width: 1872,
            height: 1080,
        };
        let tray = Rect {
            x: 8,
            y: 1000,
            width: 24,
            height: 40,
        };
        assert_eq!(
            popup_position(work, tray, TaskbarEdge::Left, 420, 720, 10),
            Point { x: 48, y: 360 }
        );
    }
    #[test]
    fn positions_popup_left_of_right_taskbar_tray() {
        let work = Rect {
            x: 0,
            y: 0,
            width: 1872,
            height: 1080,
        };
        let tray = Rect {
            x: 1896,
            y: 1000,
            width: 24,
            height: 40,
        };
        assert_eq!(
            popup_position(work, tray, TaskbarEdge::Right, 420, 720, 10),
            Point { x: 1452, y: 360 }
        );
    }

    #[test]
    fn infers_docked_taskbar_edge_from_monitor_and_work_area_gaps() {
        let monitor = Rect {
            x: -1920,
            y: 0,
            width: 1920,
            height: 1080,
        };
        let cases = [
            (
                Rect {
                    x: -1920,
                    y: 48,
                    width: 1920,
                    height: 1032,
                },
                TaskbarEdge::Top,
            ),
            (
                Rect {
                    x: -1920,
                    y: 0,
                    width: 1920,
                    height: 1032,
                },
                TaskbarEdge::Bottom,
            ),
            (
                Rect {
                    x: -1872,
                    y: 0,
                    width: 1872,
                    height: 1080,
                },
                TaskbarEdge::Left,
            ),
            (
                Rect {
                    x: -1920,
                    y: 0,
                    width: 1872,
                    height: 1080,
                },
                TaskbarEdge::Right,
            ),
        ];
        for (work, edge) in cases {
            assert_eq!(infer_taskbar_edge(monitor, work, None), edge);
        }
    }
    #[test]
    fn converts_preferred_logical_size_at_common_monitor_scales_and_restores_on_larger_area() {
        let large = Rect {
            x: 0,
            y: 0,
            width: 3000,
            height: 2000,
        };
        assert_eq!(
            preferred_size(large, 1.0),
            Size {
                width: 420,
                height: 720
            }
        );
        assert_eq!(
            preferred_size(large, 1.25),
            Size {
                width: 525,
                height: 900
            }
        );
        assert_eq!(
            preferred_size(large, 1.5),
            Size {
                width: 630,
                height: 1080
            }
        );
        let small = Rect {
            x: 0,
            y: 0,
            width: 500,
            height: 600,
        };
        assert_eq!(
            preferred_size(small, 1.5),
            Size {
                width: 500,
                height: 600
            }
        );
        assert_eq!(
            preferred_size(large, 1.5),
            Size {
                width: 630,
                height: 1080
            }
        );
    }

    #[test]
    fn clamps_tray_popup_on_monitor_with_negative_coordinates() {
        let work = Rect {
            x: -1920,
            y: 48,
            width: 1872,
            height: 1032,
        };
        let tray = Rect {
            x: -24,
            y: 8,
            width: 24,
            height: 32,
        };
        assert_eq!(
            popup_position(work, tray, TaskbarEdge::Top, 525, 900, 10),
            Point { x: -573, y: 50 }
        );
    }
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Size {
    pub width: u32,
    pub height: u32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TaskbarEdge {
    Top,
    Bottom,
    Left,
    Right,
}

pub fn preferred_size(work_area: Rect, scale_factor: f64) -> Size {
    let scale = if scale_factor.is_finite() && scale_factor > 0.0 {
        scale_factor
    } else {
        1.0
    };
    Size {
        width: ((420.0 * scale).round() as u32).min(work_area.width),
        height: ((720.0 * scale).round() as u32).min(work_area.height),
    }
}

pub fn infer_taskbar_edge(monitor: Rect, work_area: Rect, tray: Option<Rect>) -> TaskbarEdge {
    let monitor_right = monitor.x as i64 + monitor.width as i64;
    let monitor_bottom = monitor.y as i64 + monitor.height as i64;
    let work_right = work_area.x as i64 + work_area.width as i64;
    let work_bottom = work_area.y as i64 + work_area.height as i64;
    let gaps = [
        (
            TaskbarEdge::Top,
            (work_area.y as i64 - monitor.y as i64).max(0),
        ),
        (TaskbarEdge::Bottom, (monitor_bottom - work_bottom).max(0)),
        (
            TaskbarEdge::Left,
            (work_area.x as i64 - monitor.x as i64).max(0),
        ),
        (TaskbarEdge::Right, (monitor_right - work_right).max(0)),
    ];
    if let Some((edge, gap)) = gaps.iter().max_by_key(|(_, gap)| *gap) {
        if *gap > 0 {
            return *edge;
        }
    }

    let Some(tray) = tray else {
        return TaskbarEdge::Bottom;
    };
    let center_x = tray.x as i64 + tray.width as i64 / 2;
    let center_y = tray.y as i64 + tray.height as i64 / 2;
    let distances = [
        (TaskbarEdge::Top, (center_y - monitor.y as i64).abs()),
        (TaskbarEdge::Bottom, (monitor_bottom - center_y).abs()),
        (TaskbarEdge::Left, (center_x - monitor.x as i64).abs()),
        (TaskbarEdge::Right, (monitor_right - center_x).abs()),
    ];
    distances
        .iter()
        .min_by_key(|(_, distance)| *distance)
        .map(|(edge, _)| *edge)
        .unwrap_or(TaskbarEdge::Bottom)
}

pub fn popup_position(
    work_area: Rect,
    tray: Rect,
    edge: TaskbarEdge,
    window_width: u32,
    window_height: u32,
    gap: i32,
) -> Point {
    let gap = gap.max(0);
    let centered_x = tray
        .x
        .saturating_add((tray.width as i32).saturating_sub(window_width as i32) / 2);
    let centered_y = tray
        .y
        .saturating_add((tray.height as i32).saturating_sub(window_height as i32) / 2);
    let desired = match edge {
        TaskbarEdge::Top => Point {
            x: centered_x,
            y: tray
                .y
                .saturating_add(tray.height as i32)
                .saturating_add(gap),
        },
        TaskbarEdge::Bottom => Point {
            x: centered_x,
            y: tray
                .y
                .saturating_sub(window_height as i32)
                .saturating_sub(gap),
        },
        TaskbarEdge::Left => Point {
            x: tray.x.saturating_add(tray.width as i32).saturating_add(gap),
            y: centered_y,
        },
        TaskbarEdge::Right => Point {
            x: tray
                .x
                .saturating_sub(window_width as i32)
                .saturating_sub(gap),
            y: centered_y,
        },
    };
    clamp_position(work_area, window_width, window_height, desired)
}
