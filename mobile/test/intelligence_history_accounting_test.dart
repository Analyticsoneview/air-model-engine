import 'package:flutter_test/flutter_test.dart';
import 'package:air_model_engine/history_accounting.dart';

void main() {
  group('HistoryAccounting', () {
    test('recorded quantity and canonical P&L do not change with lot metadata', () {
      final first = <String, dynamic>{
        'quantity': 75, 'lot_size': 25, 'gross_pnl': 1500.0, 'net_pnl': 1420.0,
      };
      final changedLotMetadata = <String, dynamic>{
        'quantity': 75, 'lot_size': 50, 'gross_pnl': 1500.0, 'net_pnl': 1420.0,
      };

      expect(HistoryAccounting.recordedQuantity(first), 75);
      expect(HistoryAccounting.recordedQuantity(changedLotMetadata), 75);
      expect(HistoryAccounting.grossPnl(first), 1500.0);
      expect(HistoryAccounting.grossPnl(changedLotMetadata), 1500.0);
      expect(HistoryAccounting.netPnl(first), 1420.0);
      expect(HistoryAccounting.netPnl(changedLotMetadata), 1420.0);
    });

    test('lot size alone never fabricates a recorded quantity', () {
      expect(HistoryAccounting.recordedQuantity({'lot_size': 25}), isNull);
    });

    test('P&L remains pending when canonical values are absent', () {
      final row = <String, dynamic>{
        'lot_size': 25,
        'evidence': {
          'daily_option_bars': [
            {'date': '2026-10-29', 'underlying_close': 120.0},
          ],
        },
      };
      expect(HistoryAccounting.recordedQuantity(row), isNull);
      expect(HistoryAccounting.grossPnl(row), isNull);
      expect(HistoryAccounting.netPnl(row), isNull);
    });

    test('charge source basis remains explicit', () {
      expect(HistoryAccounting.chargeBasis({
        'charges': {'total': 12.5, 'basis': 'ACTUAL_REPORTED_TOTAL_BREAKDOWN_UNAVAILABLE'},
      }), 'ACTUAL');
      expect(HistoryAccounting.chargeBasis({
        'charges': {'total': 12.5, 'basis': 'ESTIMATED_NSE_OPTIONS_ROUND_TRIP'},
      }), 'ESTIMATED');
      expect(HistoryAccounting.chargeBasis({}), 'PENDING');
    });
  });
}
