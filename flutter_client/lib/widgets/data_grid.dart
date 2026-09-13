import 'package:flutter/material.dart';

import '../core/theme/tokens.dart';

class GridColumn<T> {
  const GridColumn({
    required this.label,
    required this.cell,
    this.width,
    this.flex = 1,
    this.alignRight = false,
    this.tooltip,
    this.sortValue,
  });

  final String label;
  final Widget Function(T row) cell;

  /// Fixed width in logical pixels. When null the column shares space by [flex].
  final double? width;
  final int flex;
  final bool alignRight;
  final String? tooltip;

  /// When provided, the column header becomes a sort control.
  final Comparable<Object>? Function(T row)? sortValue;
}

/// Dense, keyboard-navigable table for evidence and execution listings.
///
/// Horizontal scrolling is opt-in via [minWidth]: tables stay readable at
/// normal desktop scaling and only scroll when the content genuinely needs
/// more width than the window has.
class DataGrid<T> extends StatefulWidget {
  const DataGrid({
    super.key,
    required this.columns,
    required this.rows,
    this.onSelect,
    this.selected,
    this.rowKey,
    this.minWidth = 720,
    this.emptyState,
    this.dense = true,
    this.shrinkWrap = false,
  });

  final List<GridColumn<T>> columns;
  final List<T> rows;
  final ValueChanged<T>? onSelect;
  final bool Function(T row)? selected;
  final Object Function(T row)? rowKey;
  final double minWidth;
  final Widget? emptyState;
  final bool dense;
  final bool shrinkWrap;

  @override
  State<DataGrid<T>> createState() => _DataGridState<T>();
}

class _DataGridState<T> extends State<DataGrid<T>> {
  int? _sortColumn;
  bool _ascending = true;

  List<T> get _sortedRows {
    final index = _sortColumn;
    if (index == null || index >= widget.columns.length) return widget.rows;
    final extractor = widget.columns[index].sortValue;
    if (extractor == null) return widget.rows;
    final copy = [...widget.rows];
    copy.sort((a, b) {
      final left = extractor(a);
      final right = extractor(b);
      // Unavailable values sort last in both directions: a null measurement is
      // not a small measurement.
      if (left == null && right == null) return 0;
      if (left == null) return 1;
      if (right == null) return -1;
      final comparison = Comparable.compare(left, right);
      return _ascending ? comparison : -comparison;
    });
    return copy;
  }

  @override
  Widget build(BuildContext context) {
    if (widget.rows.isEmpty && widget.emptyState != null) return widget.emptyState!;

    final rows = _sortedRows;
    final rowHeight = widget.dense ? 34.0 : 42.0;

    return LayoutBuilder(
      builder: (context, constraints) {
        final width = constraints.maxWidth < widget.minWidth
            ? widget.minWidth
            : constraints.maxWidth;

        final table = SizedBox(
          width: width,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            mainAxisSize: MainAxisSize.min,
            children: [
              _header(),
              if (widget.shrinkWrap)
                Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    for (var i = 0; i < rows.length; i++) _row(rows[i], i, rowHeight),
                  ],
                )
              else
                Expanded(
                  child: ListView.builder(
                    itemCount: rows.length,
                    itemExtent: rowHeight,
                    itemBuilder: (context, index) => _row(rows[index], index, rowHeight),
                  ),
                ),
            ],
          ),
        );

        return constraints.maxWidth < widget.minWidth
            ? Scrollbar(
                child: SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: table,
                ),
              )
            : table;
      },
    );
  }

  Widget _header() {
    return Container(
      height: 30,
      decoration: const BoxDecoration(
        color: JockyColors.surfaceRaised,
        border: Border(bottom: BorderSide(color: JockyColors.border)),
      ),
      child: Row(
        children: [
          for (var i = 0; i < widget.columns.length; i++)
            _cellContainer(
              widget.columns[i],
              _headerCell(widget.columns[i], i),
            ),
        ],
      ),
    );
  }

  Widget _headerCell(GridColumn<T> column, int index) {
    final sortable = column.sortValue != null;
    final active = _sortColumn == index;
    final label = Row(
      mainAxisAlignment:
          column.alignRight ? MainAxisAlignment.end : MainAxisAlignment.start,
      children: [
        Flexible(
          child: Text(
            column.label.toUpperCase(),
            overflow: TextOverflow.ellipsis,
            style: TextStyle(
              fontSize: 10,
              fontWeight: FontWeight.w700,
              letterSpacing: 0.7,
              color: active ? JockyColors.accent : JockyColors.textMuted,
            ),
          ),
        ),
        if (active)
          Icon(
            _ascending ? Icons.arrow_upward : Icons.arrow_downward,
            size: 11,
            color: JockyColors.accent,
          ),
      ],
    );

    final wrapped = column.tooltip != null
        ? Tooltip(message: column.tooltip!, child: label)
        : label;

    if (!sortable) return wrapped;
    return InkWell(
      onTap: () => setState(() {
        if (_sortColumn == index) {
          _ascending = !_ascending;
        } else {
          _sortColumn = index;
          _ascending = true;
        }
      }),
      child: Semantics(
        button: true,
        label: 'Sort by ${column.label}',
        child: wrapped,
      ),
    );
  }

  Widget _cellContainer(GridColumn<T> column, Widget child) {
    final content = Padding(
      padding: const EdgeInsets.symmetric(horizontal: JockySpace.md),
      child: Align(
        alignment: column.alignRight ? Alignment.centerRight : Alignment.centerLeft,
        child: child,
      ),
    );
    return column.width != null
        ? SizedBox(width: column.width, child: content)
        : Expanded(flex: column.flex, child: content);
  }

  Widget _row(T row, int index, double height) {
    final isSelected = widget.selected?.call(row) ?? false;
    return _GridRow(
      key: widget.rowKey == null ? null : ValueKey(widget.rowKey!(row)),
      height: height,
      selected: isSelected,
      striped: index.isOdd,
      onTap: widget.onSelect == null ? null : () => widget.onSelect!(row),
      child: Row(
        children: [
          for (final column in widget.columns)
            _cellContainer(
              column,
              DefaultTextStyle.merge(
                style: const TextStyle(fontSize: 12, color: JockyColors.text),
                overflow: TextOverflow.ellipsis,
                maxLines: 1,
                child: column.cell(row),
              ),
            ),
        ],
      ),
    );
  }
}

class _GridRow extends StatefulWidget {
  const _GridRow({
    super.key,
    required this.child,
    required this.height,
    required this.selected,
    required this.striped,
    this.onTap,
  });

  final Widget child;
  final double height;
  final bool selected;
  final bool striped;
  final VoidCallback? onTap;

  @override
  State<_GridRow> createState() => _GridRowState();
}

class _GridRowState extends State<_GridRow> {
  bool _hovered = false;

  @override
  Widget build(BuildContext context) {
    final background = widget.selected
        ? JockyColors.accentWash
        : _hovered
            ? JockyColors.surfaceRaised
            : widget.striped
                ? const Color(0x08FFFFFF)
                : Colors.transparent;

    Widget row = Container(
      height: widget.height,
      decoration: BoxDecoration(
        color: background,
        border: Border(
          bottom: const BorderSide(color: JockyColors.border, width: 0.5),
          left: BorderSide(
            color: widget.selected ? JockyColors.accent : Colors.transparent,
            width: 2,
          ),
        ),
      ),
      child: widget.child,
    );

    if (widget.onTap == null) return row;

    return MouseRegion(
      cursor: SystemMouseCursors.click,
      onEnter: (_) => setState(() => _hovered = true),
      onExit: (_) => setState(() => _hovered = false),
      child: Focus(
        onKeyEvent: (node, event) => KeyEventResult.ignored,
        child: Builder(
          builder: (context) => GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTap: widget.onTap,
            child: Semantics(
              button: true,
              selected: widget.selected,
              child: row,
            ),
          ),
        ),
      ),
    );
  }
}
