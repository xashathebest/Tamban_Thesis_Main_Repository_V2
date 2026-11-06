"""Presentation colors and label rendering only; never used to infer a grade or mask ownership."""

# OpenCV uses BGR. Keep in sync with frontend/styles.css --grade-* tokens.
GRADE_COLORS_BGR = {
    "Class A": (100, 118, 8),       # #087664 green
    "Class B": (186, 92, 23),       # #175cba blue
    "Class C": (10, 77, 181),       # #b54d0a orange
    "Rejected": (64, 46, 181),      # #b52e40 red
    "Ungraded": (122, 108, 84),     # #546c7a gray
}

# Compact, low-contrast annotation style shared by every burned-in label.
LABEL_BACKGROUND_BGR = (28, 35, 42)
LABEL_TEXT_BGR = (255, 255, 255)
LABEL_PADDING = 4
LABEL_MIN_SCALE = 0.4
LABEL_MAX_SCALE = 0.62


def grade_mask_color(fish_id: object, grade: object = "Ungraded") -> tuple[int, int, int]:
    """Read the actual grade, then vary lightness slightly for neighboring IDs."""
    try:
        index = int(fish_id)
    except (TypeError, ValueError):
        index = sum((offset + 1) * ord(char) for offset, char in enumerate(str(fish_id)))
    tint = (abs(index) * .61803398875 % 1) * .24
    base = GRADE_COLORS_BGR.get(grade, GRADE_COLORS_BGR["Ungraded"])
    return tuple(int(channel * (1 - tint) + 255 * tint + .5) for channel in base)


def identity_mask_color(fish_id: object) -> tuple[int, int, int]:
    """Compatibility for callers without recorded quality: use Ungraded gray."""
    return grade_mask_color(fish_id, "Ungraded")


def label_font_scale(frame_height: object) -> float:
    """Return a small font scale proportional to the frame so text never dominates."""

    try:
        height = int(frame_height)
    except (TypeError, ValueError):
        height = 0
    return max(LABEL_MIN_SCALE, min(LABEL_MAX_SCALE, height / 1300))


def _rects_overlap(first: tuple[int, int, int, int], second: tuple[int, int, int, int]) -> bool:
    return first[0] < second[2] and second[0] < first[2] and first[1] < second[3] and second[1] < first[3]


def _settle_label_top(left: int, top: int, box_width: int, box_height: int, frame_height: int,
                      occupied: list[tuple[int, int, int, int]]) -> int:
    """Move a label upward until it clears labels that were already drawn."""

    for _ in range(16):
        candidate = (left, top, left + box_width, top + box_height)
        if not any(_rects_overlap(candidate, other) for other in occupied):
            return top
        if top - box_height - 2 < 0:
            break
        top -= box_height + 2
    return max(0, min(top, max(0, frame_height - box_height)))


def draw_compact_label(image: object, text: str, x: object, y: object, color: tuple[int, int, int], cv2: object,
                       occupied: list[tuple[int, int, int, int]] | None = None) -> tuple[int, int, int, int] | None:
    """Draw one compact label near a box, kept inside the frame and clear of earlier labels.

    The box outline and label keep the caller's grade color, while the fill stays a
    neutral dark so the label reads without covering the fish. ``occupied`` accumulates
    the drawn label rectangles for one frame so labels stack instead of overlapping.
    """

    if not text or not hasattr(image, "shape"):
        return None
    height, width = image.shape[:2]
    if height <= 0 or width <= 0:
        return None
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = label_font_scale(height)
    thickness = 1
    (text_width, text_height), baseline = cv2.getTextSize(text, font, scale, thickness)
    box_width = min(width, text_width + LABEL_PADDING * 2)
    box_height = text_height + baseline + LABEL_PADDING * 2
    left = max(0, min(int(x), max(0, width - box_width)))
    above = int(y) - box_height - 2
    top = above if above >= 0 else int(y) + 2
    top = max(0, min(top, max(0, height - box_height)))
    if occupied is not None:
        top = _settle_label_top(left, top, box_width, box_height, height, occupied)
    right, bottom = min(width - 1, left + box_width), min(height - 1, top + box_height)
    if occupied is not None:
        occupied.append((left, top, right, bottom))
    cv2.rectangle(image, (left, top), (right, bottom), LABEL_BACKGROUND_BGR, -1)
    cv2.rectangle(image, (left, top), (right, bottom), color, 1)
    cv2.putText(image, text, (left + LABEL_PADDING, bottom - LABEL_PADDING - baseline), font, scale,
                LABEL_TEXT_BGR, thickness, cv2.LINE_AA)
    return (left, top, right, bottom)
