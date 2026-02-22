import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:bideasy_app/widgets/notice_card.dart';
import 'package:bideasy_app/models/smart_bid.dart';
import '../helpers/test_factories.dart';

void main() {
  Widget buildCard({
    bool isFavorite = false,
    CompetitionLevel? competitionLevel,
    bool closed = false,
  }) {
    final notice = closed
        ? createClosedNotice()
        : createTestNotice();

    return MaterialApp(
      home: Scaffold(
        body: NoticeCard(
          notice: notice,
          isFavorite: isFavorite,
          competitionLevel: competitionLevel,
          onTap: () {},
          onFavoriteChanged: () {},
        ),
      ),
    );
  }

  testWidgets('renders title and formatted price', (tester) async {
    await tester.pumpWidget(buildCard());

    expect(find.text('서울시 도로 보수 공사'), findsOneWidget);
    expect(find.textContaining('100,000,000원'), findsOneWidget);
  });

  testWidgets('shows bid number with No. prefix', (tester) async {
    await tester.pumpWidget(buildCard());

    expect(find.textContaining('No. 20260223-001'), findsOneWidget);
  });

  testWidgets('shows filled star when favorite', (tester) async {
    await tester.pumpWidget(buildCard(isFavorite: true));

    expect(find.byIcon(Icons.star_rounded), findsOneWidget);
    expect(find.byIcon(Icons.star_border_rounded), findsNothing);
  });

  testWidgets('shows outlined star when not favorite', (tester) async {
    await tester.pumpWidget(buildCard(isFavorite: false));

    expect(find.byIcon(Icons.star_border_rounded), findsOneWidget);
    expect(find.byIcon(Icons.star_rounded), findsNothing);
  });

  testWidgets('shows 개찰 완료 badge for closed notice', (tester) async {
    await tester.pumpWidget(buildCard(closed: true));

    expect(find.text('개찰 완료'), findsOneWidget);
    expect(find.text('안전한 공고'), findsNothing);
  });

  testWidgets('shows 안전한 공고 badge for active notice', (tester) async {
    await tester.pumpWidget(buildCard(closed: false));

    expect(find.text('안전한 공고'), findsOneWidget);
  });
}
