import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:bideasy_app/widgets/glossary_chip.dart';

void main() {
  Widget buildTestWidget(String term) {
    return MaterialApp(
      home: Scaffold(
        body: Row(children: [
          const Text('테스트'),
          GlossaryChip(term: term),
        ]),
      ),
    );
  }

  testWidgets('renders info icon for known term', (tester) async {
    await tester.pumpWidget(buildTestWidget('기초금액'));
    expect(find.byIcon(Icons.info_outline_rounded), findsOneWidget);
  });

  testWidgets('renders nothing for unknown term', (tester) async {
    await tester.pumpWidget(buildTestWidget('없는용어'));
    expect(find.byIcon(Icons.info_outline_rounded), findsNothing);
  });

  testWidgets('tap opens bottom sheet with term', (tester) async {
    await tester.pumpWidget(buildTestWidget('기초금액'));
    await tester.tap(find.byIcon(Icons.info_outline_rounded));
    await tester.pumpAndSettle();

    // Term badge should appear in the bottom sheet
    expect(find.text('기초금액'), findsWidgets);
    // Simple explanation
    expect(find.text('입찰의 기준이 되는 금액이에요'), findsOneWidget);
  });

  testWidgets('bottom sheet shows detail explanation', (tester) async {
    await tester.pumpWidget(buildTestWidget('기초금액'));
    await tester.tap(find.byIcon(Icons.info_outline_rounded));
    await tester.pumpAndSettle();

    expect(
      find.textContaining('발주처가 공고에 제시하는'),
      findsOneWidget,
    );
  });
}
