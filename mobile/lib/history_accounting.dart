/// Read-only projection helpers for canonical History accounting fields.
class HistoryAccounting {
  HistoryAccounting._();

  static double? _number(dynamic value) {
    if (value is num) return value.toDouble();
    return value == null ? null : double.tryParse(value.toString());
  }

  /// Quantity is the recorded trade quantity. Lot size is never used as a fallback.
  static int? recordedQuantity(Map<String, dynamic> row) {
    final quantity = _number(row['quantity']);
    return quantity?.round();
  }

  /// These values are supplied by the canonical P&L calendar projection.
  static double? grossPnl(Map<String, dynamic> row) => _number(row['gross_pnl']);
  static double? netPnl(Map<String, dynamic> row) => _number(row['net_pnl']);

  static double? chargesTotal(Map<String, dynamic> row) {
    final charges = row['charges'];
    return charges is Map ? _number(charges['total']) : null;
  }

  static String chargeBasis(Map<String, dynamic> row) {
    final charges = row['charges'];
    if (charges is! Map) return 'PENDING';
    final basis = (charges['basis'] ?? '').toString();
    if (basis == 'ACTUAL_SOURCE_BREAKDOWN' ||
        basis == 'ACTUAL_REPORTED_TOTAL_BREAKDOWN_UNAVAILABLE') {
      return 'ACTUAL';
    }
    if (basis.startsWith('ESTIMATED')) return 'ESTIMATED';
    return 'PENDING';
  }
}
