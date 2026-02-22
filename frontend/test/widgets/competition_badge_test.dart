import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:bideasy_app/widgets/competition_badge.dart';
import 'package:bideasy_app/models/smart_bid.dart';

void main() {
  Widget buildBadge(CompetitionLevel level, {bool compact = true}) {
    return MaterialApp(
      home: Scaffold(
        body: CompetitionBadge(level: level, compact: compact),
      ),
    );
  }

  testWidgets('renders blue ocean badge with emoji and label', (tester) async {
    await tester.pumpWidget(buildBadge(CompetitionLevel.blueOcean));

    expect(find.textContaining('블루오션'), findsOneWidget);
    expect(find.textContaining('🔵'), findsOneWidget);
  });

  testWidgets('renders red ocean badge with emoji and label', (tester) async {
    await tester.pumpWidget(buildBadge(CompetitionLevel.redOcean));

    expect(find.textContaining('레드오션'), findsOneWidget);
    expect(find.textContaining('🔴'), findsOneWidget);
  });

  testWidgets('renders all competition levels correctly', (tester) async {
    for (final level in CompetitionLevel.values) {
      await tester.pumpWidget(buildBadge(level));

      expect(find.textContaining(level.label), findsOneWidget);
      expect(find.textContaining(level.emoji), findsOneWidget);
    }
  });
}
