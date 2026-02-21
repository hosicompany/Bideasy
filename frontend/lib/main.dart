import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'theme/style.dart';
import 'screens/home_screen.dart';
import 'screens/login_screen.dart';
import 'screens/bid_calculator_screen.dart';
import 'services/api_service.dart';
import 'models/notice.dart';
import 'utils/web_utils.dart';

void main() {
  runApp(const ProviderScope(child: BidEasyApp()));
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

class AuthGate extends StatefulWidget {
  const AuthGate({super.key});

  @override
  State<AuthGate> createState() => _AuthGateState();
}

class _AuthGateState extends State<AuthGate> {
  bool _checking = true;
  bool _loggedIn = false;
  String? _paymentResult;
  String? _paymentAmount;
  String? _paymentMessage;

  @override
  void initState() {
    super.initState();
    _checkAuth();
  }

  Future<void> _checkAuth() async {
    // Check if we arrived via payment redirect (?payment=success|fail)
    final paymentResult = getPaymentResultFromUrl();
    if (paymentResult != null) {
      _paymentResult = paymentResult;
      _paymentAmount = getPaymentAmountFromUrl();
      _paymentMessage = getPaymentMessageFromUrl();
      cleanUrl();
    }

    // Check if we arrived via OAuth redirect (?token=...)
    final tokenFromUrl = getTokenFromUrl();
    if (tokenFromUrl != null && tokenFromUrl.isNotEmpty) {
      await ApiService.saveTokenDirect(tokenFromUrl);
      cleanUrl();
      if (mounted) {
        setState(() {
          _loggedIn = true;
          _checking = false;
        });
      }
      return;
    }

    // Check for OAuth error
    final errorFromUrl = getErrorFromUrl();
    if (errorFromUrl != null) {
      cleanUrl();
    }

    // Normal flow: check saved token
    final hasToken = await ApiService.loadToken();
    if (mounted) {
      setState(() {
        _loggedIn = hasToken;
        _checking = false;
      });
    }
  }

  void _showPaymentSnackbar() {
    if (_paymentResult == null) return;

    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      if (_paymentResult == 'success') {
        final amount = _paymentAmount ?? '';
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('$amount원 충전이 완료되었어요!'),
            backgroundColor: AppColors.safeGreen,
            behavior: SnackBarBehavior.floating,
          ),
        );
      } else if (_paymentResult == 'fail') {
        final message = _paymentMessage ?? '결제가 취소되었습니다';
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(message),
            backgroundColor: AppColors.dangerRed,
            behavior: SnackBarBehavior.floating,
          ),
        );
      }
      _paymentResult = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    if (_checking) {
      return const Scaffold(
        backgroundColor: AppColors.surfaceWhite,
        body: Center(
          child: CircularProgressIndicator(
            valueColor: AlwaysStoppedAnimation<Color>(AppColors.primaryBlue),
          ),
        ),
      );
    }

    if (_loggedIn) {
      _showPaymentSnackbar();
      return const HomeScreen();
    }
    return const LoginScreen();
  }
}
