import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:bideasy_app/widgets/state_widgets.dart';

void main() {
  group('LoadingStateWidget', () {
    testWidgets('renders message and skeleton cards', (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: LoadingStateWidget(
                message: '불러오는 중...',
                skeletonCount: 3,
              ),
            ),
          ),
        ),
      );

      expect(find.text('불러오는 중...'), findsOneWidget);
      expect(find.byType(SkeletonNoticeCard), findsNWidgets(3));
      expect(find.byType(CircularProgressIndicator), findsOneWidget);
    });

    testWidgets('hides message when null', (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: LoadingStateWidget(skeletonCount: 2),
            ),
          ),
        ),
      );

      expect(find.byType(SkeletonNoticeCard), findsNWidgets(2));
      // No message text besides what's in the spinner
    });
  });

  group('EmptyStateWidget', () {
    testWidgets('renders icon, title, and message', (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: EmptyStateWidget(
              icon: Icons.star_border_rounded,
              title: '즐겨찾기가 없어요',
              message: '공고를 즐겨찾기에 추가해보세요',
            ),
          ),
        ),
      );

      expect(find.byIcon(Icons.star_border_rounded), findsOneWidget);
      expect(find.text('즐겨찾기가 없어요'), findsOneWidget);
      expect(find.text('공고를 즐겨찾기에 추가해보세요'), findsOneWidget);
    });

    testWidgets('renders action widget when provided', (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: EmptyStateWidget(
              title: '검색 결과 없음',
              action: TextButton(
                onPressed: () {},
                child: const Text('검색어 지우기'),
              ),
            ),
          ),
        ),
      );

      expect(find.text('검색어 지우기'), findsOneWidget);
    });
  });

  group('ErrorStateWidget', () {
    testWidgets('renders title, message, and retry button', (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: ErrorStateWidget(
              title: '오류 발생',
              message: '다시 시도해주세요',
              onRetry: () {},
            ),
          ),
        ),
      );

      expect(find.text('오류 발생'), findsOneWidget);
      expect(find.text('다시 시도해주세요'), findsOneWidget);
      expect(find.text('다시 시도'), findsOneWidget);
    });

    testWidgets('retry button calls onRetry callback', (tester) async {
      var retried = false;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: ErrorStateWidget(
              title: '오류',
              onRetry: () => retried = true,
            ),
          ),
        ),
      );

      await tester.tap(find.text('다시 시도'));
      expect(retried, isTrue);
    });

    testWidgets('hides retry button when onRetry is null', (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: ErrorStateWidget(
              title: '오류 발생',
            ),
          ),
        ),
      );

      expect(find.text('다시 시도'), findsNothing);
    });
  });
}
