import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

class AppColors {
  static const Color primaryBlue = Color(0xFF3182F6);
  static const Color backgroundGrey = Color(0xFFF2F4F6);
  static const Color surfaceWhite = Color(0xFFFFFFFF);
  
  static const Color textMain = Color(0xFF191F28);
  static const Color textSub = Color(0xFF8B95A1);
  
  static const Color safeGreen = Color(0xFF34C759);
  static const Color dangerRed = Color(0xFFFF3B30);
  
  static const Color divider = Color(0xFFE5E8EB);

  // Competition level colors
  static const Color competitionBlue = Color(0xFF3182F6);
  static const Color competitionGreen = Color(0xFF34C759);
  static const Color competitionYellow = Color(0xFFFFCC00);
  static const Color competitionOrange = Color(0xFFFF9500);
  static const Color competitionRed = Color(0xFFFF3B30);

  // Brand / external service colors
  static const Color kakaoYellow = Color(0xFFFEE500);
  static const Color naverGreen = Color(0xFF03C75A);

  // Semantic colors
  static const Color warningOrange = Color(0xFFFF9500);
  static const Color closedBadgeGrey = Color(0xFFF0F0F0);
  static const Color closedTextGrey = Color(0xFF888888);
  static const Color starGold = Color(0xFFFFD700);
  static const Color starInactive = Color(0xFFC4C4C4);
}

class AppTextStyles {
  static const TextStyle h1 = TextStyle(
    fontSize: 26,
    fontWeight: FontWeight.w700,
    color: AppColors.textMain,
    fontFamily: 'Pretendard', 
  );
  
  static const TextStyle h2 = TextStyle(
    fontSize: 20,
    fontWeight: FontWeight.w700,
    color: AppColors.textMain, // Slightly darker than sub
    fontFamily: 'Pretendard',
  );
  
  static const TextStyle body1 = TextStyle(
    fontSize: 16,
    fontWeight: FontWeight.w500,
    color: Color(0xFF4E5968),
    fontFamily: 'Pretendard',
  );
  
  static const TextStyle caption = TextStyle(
    fontSize: 13,
    fontWeight: FontWeight.w400,
    color: AppColors.textSub,
    fontFamily: 'Pretendard',
  );
}

class AppSpacing {
  static const double xs = 4;
  static const double sm = 8;
  static const double md = 16;
  static const double lg = 20;
  static const double xl = 24;
  static const double xxl = 32;
}

class AppShadow {
  static final List<BoxShadow> card = [
    BoxShadow(
      color: Colors.black.withValues(alpha: 0.05),
      blurRadius: 10,
      offset: const Offset(0, 2),
    ),
  ];

  static final List<BoxShadow> cardSubtle = [
    BoxShadow(
      color: Colors.black.withValues(alpha: 0.03),
      blurRadius: 10,
      offset: const Offset(0, 2),
    ),
  ];
}

class AppAnimation {
  static const Duration fast = Duration(milliseconds: 200);
  static const Duration normal = Duration(milliseconds: 400);
  static const Duration slow = Duration(milliseconds: 600);
}

class AppInputDecoration {
  static InputDecoration standard({
    required String hint,
    IconData? icon,
    String? suffix,
  }) {
    return InputDecoration(
      hintText: hint,
      hintStyle: TextStyle(color: AppColors.textSub.withValues(alpha: 0.5)),
      prefixIcon: icon != null
          ? Icon(icon, size: 20, color: AppColors.textSub)
          : null,
      suffixText: suffix,
      suffixStyle: const TextStyle(fontSize: 14, color: AppColors.textSub),
      filled: true,
      fillColor: AppColors.backgroundGrey,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: BorderSide.none,
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: AppColors.primaryBlue, width: 1.5),
      ),
      errorBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: AppColors.dangerRed, width: 1),
      ),
      focusedErrorBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: AppColors.dangerRed, width: 1.5),
      ),
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
    );
  }
}

class AppTheme {
  static ThemeData get lightTheme {
    return ThemeData(
      scaffoldBackgroundColor: AppColors.backgroundGrey,
      primaryColor: AppColors.primaryBlue,
      fontFamily: 'Pretendard',
      appBarTheme: const AppBarTheme(
        backgroundColor: AppColors.backgroundGrey,
        elevation: 0,
        systemOverlayStyle: SystemUiOverlayStyle.dark,
        titleTextStyle: TextStyle(
          color: AppColors.textMain,
          fontSize: 18,
          fontWeight: FontWeight.w600,
        ),
        iconTheme: IconThemeData(color: AppColors.textMain),
      ),
      colorScheme: ColorScheme.fromSwatch().copyWith(
        secondary: AppColors.primaryBlue,
      ),
    );
  }
}
