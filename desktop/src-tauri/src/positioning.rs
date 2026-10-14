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
