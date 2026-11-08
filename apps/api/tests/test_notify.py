from app.schemas import AgendaItemRead
from app.services.canvas.notify import due_soon, message


def _item(title: str, days_left: int | None, status: str = "open") -> AgendaItemRead:
    return AgendaItemRead(
        id=title, kind="assignment", course_id=1, course_slug="dsp", course_name="DSP",
        title=title, days_left=days_left, status=status, bucket="later", place="later",
    )


def test_due_soon_keeps_open_items_within_window_sorted():
    items = [
        _item("far", 5),
        _item("in two", 2),
        _item("today", 0),
        _item("handed in", 1, status="submitted"),
        _item("past", -1, status="overdue"),
        _item("no date", None),
    ]
    soon = due_soon(items, days=3)
    assert [i.title for i in soon] == ["today", "in two"]
    assert message(soon) == "today: DSP - today\nin 2 days: DSP - in two"
