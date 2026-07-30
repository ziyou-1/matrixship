import os
import sys
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
OUTPUT = ROOT / ".tmp-validation" / "account-billing"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import matrix_native_client as client
from PySide6 import QtCore, QtGui, QtWidgets


ANALYTICS = {
    "ok": True,
    "period": {
        "startDate": "2026-07-01",
        "endDate": "2026-07-30",
        "groupBy": "day",
        "timezone": "Asia/Shanghai",
    },
    "metrics": {
        "balance": "inf",
        "totalConsumption": 93.65,
        "activeConsumptionDays": 8,
        "dailyAverage": 11.71,
        "videoTaskCount": 4,
        "videoAverage": 15.3,
    },
    "trend": [
        {"bucket": "2026-07-%02d" % day, "amount": amount}
        for day, amount in enumerate((0, 4, 0, 9, 12, 0, 5, 0, 18, 11, 0, 7, 0, 14, 0, 6, 0, 0, 8, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0), 1)
    ],
    "distribution": [
        {"type": "video", "label": "视频生成", "amount": 61.2, "ratio": 65.35},
        {"type": "image", "label": "图片生成", "amount": 18.45, "ratio": 19.7},
        {"type": "voice", "label": "配音", "amount": 8, "ratio": 8.54},
        {"type": "other", "label": "其他", "amount": 6, "ratio": 6.41},
    ],
}


def ledger_payload():
    types = (
        ("视频生成", "seedance-2.0", -18.5, 175.5, "已扣费"),
        ("图片生成", "doubao-image", -6, 194, "已扣费"),
        ("配音", "volcano-tts", -2.4, None, "已扣费"),
        ("退款", "seedance-2.0", 18.5, 196.4, "已退款"),
    )
    rows = []
    for index, (kind, model, change, balance, status) in enumerate(types):
        rows.append({
            "createdAt": "2026-07-%02dT1%d:20:00+08:00" % (30 - index, index + 1),
            "typeLabel": kind,
            "modelId": model,
            "detail": "商品宣传片第 %d 段生成任务，保留完整详情供悬停查看" % (index + 1),
            "change": change,
            "balanceAfter": balance,
            "statusLabel": status,
        })
    return {
        "ok": True,
        "balance": "inf",
        "ledger": rows,
        "pagination": {"page": 1, "pageSize": 20, "total": 4, "totalPages": 1},
    }


def rect_in_page(widget, page):
    return QtCore.QRect(widget.mapTo(page, QtCore.QPoint(0, 0)), widget.size())


def assert_inside(widget, page, name):
    rect = rect_in_page(widget, page)
    if not page.rect().contains(rect):
        raise AssertionError("%s outside page: %s not in %s" % (name, rect, page.rect()))


def assert_label_text_fits(label, page):
    assert_inside(label, page, label.objectName())
    contents = label.contentsRect()
    flags = label.alignment() | QtCore.Qt.TextSingleLine
    rendered = label.fontMetrics().boundingRect(contents, flags, label.text())
    if not contents.contains(rendered):
        raise AssertionError(
            "%s text outside contents: %s not in %s" % (
                label.objectName(), rendered, contents,
            )
        )


def assert_table_geometry(table):
    header = table.horizontalHeader()
    header_viewport = header.viewport()
    for column in range(table.columnCount()):
        section = QtCore.QRect(
            header.sectionViewportPosition(column),
            0,
            header.sectionSize(column),
            header_viewport.height(),
        )
        if not header_viewport.rect().contains(section):
            raise AssertionError("header section %d outside viewport: %s" % (column, section))
        header_item = table.horizontalHeaderItem(column)
        text = header_item.text() if header_item else ""
        if header.fontMetrics().boundingRect(text).height() > section.height() or \
                header.fontMetrics().horizontalAdvance(text) > section.width():
            raise AssertionError("header text does not fit section %d: %s" % (column, text))

    viewport = table.viewport()
    long_detail_cells = 0
    for row in range(table.rowCount()):
        for column in range(table.columnCount()):
            item = table.item(row, column)
            if item is None:
                continue
            rect = table.visualItemRect(item)
            if not rect.intersects(viewport.rect()):
                continue
            if not viewport.rect().contains(rect):
                raise AssertionError("cell %d,%d outside viewport: %s" % (row, column, rect))
            if table.fontMetrics().height() > rect.height():
                raise AssertionError("cell %d,%d font exceeds row height" % (row, column))
            if column == 3 and table.fontMetrics().horizontalAdvance(item.text()) > rect.width():
                long_detail_cells += 1
                if item.toolTip() != item.text():
                    raise AssertionError("long detail cell %d lost its full tooltip" % row)
    if table.textElideMode() != QtCore.Qt.ElideRight:
        raise AssertionError("ledger table no longer uses right elision")
    if not long_detail_cells:
        raise AssertionError("fake ledger payload did not exercise long detail elision")


def render_dashboard(app, width, height, role, filename):
    with client._SLOCK:
        client._SHARED["appRole"] = role
    client.BRIDGE = client.Bridge()
    page = client.AccountPage()
    page.setFixedSize(width, height)
    page._analytics_seq = 1
    page._ledger_seq = 1
    client.BRIDGE.payload.emit("acct_analytics", {"seq": 1, "payload": ANALYTICS})
    client.BRIDGE.payload.emit("acct_ledger", {"seq": 1, "payload": ledger_payload()})
    client.BRIDGE.payload.emit("acct_users", {"ok": True, "users": [{"id": "should-stay-hidden"}]})
    page.show()
    app.processEvents()

    if not page.billing_box.isHidden() or not page.phone_bind_panel.isHidden() or not page.admin_box.isHidden():
        raise AssertionError("administrator controls visible for %s" % role)
    if page.distribution_bars.row_count() != 4:
        raise AssertionError("distribution row count changed")
    for object_name in ("billingMetricValue", "billingMetricLabel", "billingMetricNote"):
        labels = page.findChildren(QtWidgets.QLabel, object_name)
        if not labels:
            raise AssertionError("missing metric labels named %s" % object_name)
        for label in labels:
            assert_label_text_fits(label, page)
    assert_inside(page.trend_chart, page, "trend chart")
    assert_inside(page.distribution_bars, page, "distribution")
    assert_inside(page.ltable, page, "ledger table")
    assert_table_geometry(page.ltable)
    assert_inside(page.prev_page, page, "previous page")
    assert_inside(page.next_page, page, "next page")

    image = QtGui.QImage(width, height, QtGui.QImage.Format_ARGB32)
    image.fill(QtGui.QColor("#000000"))
    painter = QtGui.QPainter(image)
    page.render(painter, QtCore.QPoint(0, 0))
    painter.end()
    raw = image.constBits().tobytes()
    if not raw or len(set(raw[::97])) < 3:
        raise AssertionError("rendered image is blank")
    path = OUTPUT / filename
    if not image.save(str(path), "PNG"):
        raise AssertionError("failed to save %s" % path)
    page.close()
    page.deleteLater()
    app.processEvents()
    return path


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setStyle("Fusion")
    font_path = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "Deng.ttf"
    font_id = QtGui.QFontDatabase.addApplicationFont(str(font_path))
    families = QtGui.QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
    if not families:
        raise AssertionError("offscreen Chinese font unavailable: %s" % font_path)
    app.setFont(QtGui.QFont(families[0], 10))
    client.apply_theme("dark")
    paths = [
        render_dashboard(app, 1280, 900, "enterprise_admin", "account-billing-1280x900.png"),
        render_dashboard(app, 1024, 768, "normal_user", "account-billing-1024x768.png"),
    ]
    print("ok " + " ".join(str(path) for path in paths))


if __name__ == "__main__":
    main()
