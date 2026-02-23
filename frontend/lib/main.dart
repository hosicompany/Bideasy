import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:sentry_flutter/sentry_flutter.dart';
import 'theme/style.dart';
import 'screens/home_screen.dart';
import 'screens/login_screen.dart';
import 'screens/bid_calculator_screen.dart';
import 'models/notice.dart';
import 'providers/auth_provider.dart';
import 'services/push_notification_service.dart';

const String _sentryDsn = String.fromEnvironment('SENTRY_DSN', defaultValue: '');

Future<void> main() async {
  if (_sentryDsn.isNotEmpty) {
    await SentryFlutter.init(
      (options) {
        options.dsn = _sentryDsn;
        options.environment = const String.fromEnvironment('APP_ENV', defaultValue: 'development');
        options.tracesSampleRate = 0.1;
        options.sendDefaultPii = false;
      },
      appRunner: () => runApp(const ProviderScope(child: BidEasyApp())),
    );
  } else {
    runApp(const ProviderScope(child: BidEasyApp()));
  }
}

class BidEasyApp extends StatelessWidget {
  const BidEasyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'BidEasy',
      theme: AppTheme.lightTheme,
      home: const AuthGate(),
      debugShowCheckedModeBanner: false,
      onGenerateRoute: (settings) {
        if (settings.name == '/calculator') {
          final notice = settings.arguments as Notice;
          return MaterialPageRoute(
            builder: (context) => BidCalculatorScreen(notice: notice),
          );
        }
        return null;
      },
    );
  }
}

class AuthGate extends ConsumerStatefulWidget {
  const AuthGate({super.key});

  @override
  ConsumerState<AuthGate> createState() => _AuthGateState();
}

class _AuthGateState extends ConsumerState<AuthGate> {
  bool _fcmInitialized = false;

  @override
  void initState() {
    super.initState();
    Future(() => ref.read(authProvider.notifier).checkAuth());
  }

  void _initPushNotifications() {
    if (_fcmInitialized) return;
    _fcmInitialized = true;
    PushNotificationService().initialize();
  }

  void _showPaymentSnackbar(AuthState authState) {
    if (authState.paymentResult == null) return;

    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      if (authState.paymentResult == 'success') {
        final amount = authState.paymentAmount ?? '';
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('$amount원 충전이 완료되었어요!'),
            backgroundColor: AppColors.safeGreen,
            behavior: SnackBarBehavior.floating,
          ),
        );
      } else if (authState.paymentResult == 'fail') {
        final message = authState.paymentMessage ?? '결제가 취소되었습니다';
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(message),
            backgroundColor: AppColors.dangerRed,
            behavior: SnackBarBehavior.floating,
          ),
        );
      }
      ref.read(authProvider.notifier).clearPayment();
    });
  }

  @override
  Widget build(BuildContext context) {
    final authState = ref.watch(authProvider);

    if (authState.status == AuthStatus.checking) {
      return const Scaffold(
        backgroundColor: AppColors.surfaceWhite,
        body: Center(
          child: CircularProgressIndicator(
            valueColor: AlwaysStoppedAnimation<Color>(AppColors.primaryBlue),
          ),
        ),
      );
    }

    if (authState.status == AuthStatus.authenticated) {
      _initPushNotifications();
      _showPaymentSnackbar(authState);
      return const HomeScreen();
    }
    return const LoginScreen();
  }
}
