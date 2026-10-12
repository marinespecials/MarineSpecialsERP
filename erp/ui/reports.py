"""Reports: spend per month and per supplier (Qt Charts - no matplotlib)."""
import datetime

from PySide6.QtCharts import (QChart, QChartView, QBarSeries, QBarSet, QBarCategoryAxis, QValueAxis,
                              QHorizontalBarSeries)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QGridLayout

from .common import Card, money, ACCENT, BLUE, GREEN, is_dark


class ReportsPage(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        head = QHBoxLayout()
        t = QLabel("Reports")
        t.setObjectName("pageTitle")
        head.addWidget(t)
        head.addStretch()
        head.addWidget(QLabel("Year"))
        self.year = QComboBox()
        self.year.currentIndexChanged.connect(self.draw)
        head.addWidget(self.year)
        root.addLayout(head)

        cards = QHBoxLayout()
        self.c_total = Card("Spend", BLUE)
        self.c_count = Card("Invoices", BLUE)
        self.c_avg = Card("Average invoice", BLUE)
        self.c_top = Card("Top supplier", GREEN)
        for c in (self.c_total, self.c_count, self.c_avg, self.c_top):
            cards.addWidget(c)
        root.addLayout(cards)

        grid = QGridLayout()
        self.month_view = QChartView()
        self.supplier_view = QChartView()
        for v in (self.month_view, self.supplier_view):
            v.setRenderHint(QPainter.Antialiasing)
            v.setMinimumHeight(320)
        grid.addWidget(self.month_view, 0, 0)
        grid.addWidget(self.supplier_view, 0, 1)
        root.addLayout(grid, 1)
        ctx.invoices_changed.connect(self.reload)
        self.reload()

    def reload(self):
        years = sorted({(r["invoice_date"] or "")[:4] for r in self.ctx.db.invoices() if r["invoice_date"]}, reverse=True)
        cur = self.year.currentData()
        self.year.blockSignals(True)
        self.year.clear()
        this_year = str(datetime.date.today().year)
        for y in years or [this_year]:
            self.year.addItem(y, y)
        i = self.year.findData(cur or (years[0] if years else this_year))
        self.year.setCurrentIndex(max(i, 0))
        self.year.blockSignals(False)
        self.draw()

    def _chart(self, title):
        ch = QChart()
        ch.setTitle(title)
        ch.legend().hide()
        ch.setAnimationOptions(QChart.SeriesAnimations)
        dark = is_dark(self.ctx.settings.get("theme", "system"))
        ch.setTheme(QChart.ChartThemeDark if dark else QChart.ChartThemeLight)
        ch.setBackgroundRoundness(10)
        return ch

    def draw(self):
        year = self.year.currentData() or str(datetime.date.today().year)
        rows = [r for r in self.ctx.db.invoices() if (r["invoice_date"] or "").startswith(year)]
        total = sum(r["total"] or 0 for r in rows)
        self.c_total.set(money(total) or "€ 0,00", year)
        self.c_count.set(str(len(rows)))
        self.c_avg.set(money(total / len(rows)) if rows else "–")
        by_sup = {}
        for r in rows:
            by_sup[r["supplier_name"]] = by_sup.get(r["supplier_name"], 0) + (r["total"] or 0)
        top = sorted(by_sup.items(), key=lambda kv: kv[1], reverse=True)
        self.c_top.set(top[0][0].replace("_", " ") if top else "–", money(top[0][1]) if top else "")

        # spend per month
        months = [0.0] * 12
        for r in rows:
            try:
                months[int(r["invoice_date"][5:7]) - 1] += r["total"] or 0
            except (ValueError, IndexError):
                pass
        ch = self._chart(f"Spend per month · {year}")
        bars = QBarSet("Spend")
        bars.setColor(QColor(ACCENT))
        bars.append(months)
        s = QBarSeries()
        s.append(bars)
        ch.addSeries(s)
        ax = QBarCategoryAxis()
        ax.append(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])
        ay = QValueAxis()
        ay.setLabelFormat("%.0f")
        ay.setTitleText("€")
        ay.setRange(0, max(months + [1]) * 1.15)
        ch.addAxis(ax, Qt.AlignBottom)
        ch.addAxis(ay, Qt.AlignLeft)
        s.attachAxis(ax)
        s.attachAxis(ay)
        self.month_view.setChart(ch)

        # top suppliers
        top10 = list(reversed(top[:10]))
        ch2 = self._chart(f"Top suppliers · {year}")
        bars2 = QBarSet("Spend")
        bars2.setColor(QColor(BLUE))
        bars2.append([v for _, v in top10] or [0])
        s2 = QHorizontalBarSeries()
        s2.append(bars2)
        ch2.addSeries(s2)
        ay2 = QBarCategoryAxis()
        ay2.append([k.replace("_", " ")[:24] for k, _ in top10] or ["–"])
        ax2 = QValueAxis()
        ax2.setLabelFormat("%.0f")
        ax2.setTitleText("€")
        ax2.setRange(0, max([v for _, v in top10] + [1]) * 1.15)
        ch2.addAxis(ay2, Qt.AlignLeft)
        ch2.addAxis(ax2, Qt.AlignBottom)
        s2.attachAxis(ay2)
        s2.attachAxis(ax2)
        self.supplier_view.setChart(ch2)
