import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:bideasy_app/widgets/competition_gauge.dart';
import 'package:bideasy_app/models/smart_bid.dart';

void main() {
  Widget buildGauge({
    required int count,
    required CompetitionLevel level,
    double? blueOceanProb,
  }) {
    return MaterialApp(
      home: Scaffold(
        body: CompetitionGauge(
          predictedCount: count,
          level: level,
          blueOceanProb: blueOceanProb,
        ),
      ),
    );
  }

  testWidgets('renders count and label', (tester) async {
    await tester.pumpWidget(buildGauge(
      count: 15,
      level: CompetitionLevel.moderate,
    ));
    expect(find.text('15개사'), findsOneWidget);
    expect(find.text('참여 예상'), findsOneWidget);
  });

  testWidgets('renders all segment labels', (tester) async {
    await tester.pumpWidget(buildGauge(
      count: 10,
      level: CompetitionLevel.adequate,
    ));
    expect(find.text('🔵 1~5'), findsOneWidget);
    expect(find.text('🟢 6~10'), findsOneWidget);
    expect(find.text('🟡 11~20'), findsOneWidget);
    expect(find.text('🟠 21~50'), findsOneWidget);
    expect(find.text('🔴 51+'), findsOneWidget);
  });

  testWidgets('shows blue ocean bar when provided', (tester) async {
    await tester.pumpWidget(buildGauge(
      count: 3,
      level: CompetitionLevel.blueOcean,
      blueOceanProb: 0.75,
    ));
    expect(find.text('🔵 블루오션 확률'), findsOneWidget);
    expect(find.text('75%'), findsOneWidget);
  });

  testWidgets('hides blue ocean bar when null', (tester) async {
    await tester.pumpWidget(buildGauge(
      count: 30,
      level: CompetitionLevel.competitive,
    ));
    expect(find.textContaining('블루오션 확률'), findsNothing);
  });

  testWidgets('renders for each competition level', (tester) async {
    // Blue ocean
    await tester.pumpWidget(buildGauge(
      count: 3,
      level: CompetitionLevel.blueOcean,
    ));
    expect(find.text('3개사'), findsOneWidget);

    // Moderate
    await tester.pumpWidget(buildGauge(
      count: 15,
      level: CompetitionLevel.moderate,
    ));
    expect(find.text('15개사'), findsOneWidget);

    // Red ocean
    await tester.pumpWidget(buildGauge(
      count: 60,
      level: CompetitionLevel.redOcean,
    ));
    expect(find.text('60개사'), findsOneWidget);
  });
}
