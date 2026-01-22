import 'package:flutter/material.dart';
import '../theme/style.dart';
import '../widgets/notice_card.dart';
import '../widgets/bid_slider.dart';
import '../models/notice.dart';
import '../services/api_service.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final ApiService apiService = ApiService();
  late Future<List<Notice>> futureNotices;

  @override
  void initState() {
    super.initState();
    futureNotices = apiService.fetchNotices();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text("BidEasy"),
        actions: [
          IconButton(
            icon: const Icon(Icons.notifications_outlined),
            onPressed: () {},
          )
        ],
      ),
      body: FutureBuilder<List<Notice>>(
        future: futureNotices,
        builder: (context, snapshot) {
          if (snapshot.connectionState == ConnectionState.waiting) {
            return const Center(child: CircularProgressIndicator());
          } else if (snapshot.hasError) {
            return Center(child: Text("Error: ${snapshot.error}"));
          } else if (!snapshot.hasData || snapshot.data!.isEmpty) {
            return const Center(child: Text("No notices found."));
          }

          final notices = snapshot.data!;
          return ListView.builder(
            itemCount: notices.length,
            itemBuilder: (context, index) {
              return NoticeCard(
                notice: notices[index],
                onTap: () {
                  _showCalculator(context, notices[index]);
                },
              );
            },
          );
        },
      ),
    );
  }

  void _showCalculator(BuildContext context, Notice notice) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (context) => DraggableScrollableSheet(
        initialChildSize: 0.7,
        maxChildSize: 0.9,
        minChildSize: 0.5,
        builder: (_, controller) => Container(
          decoration: const BoxDecoration(
            color: AppColors.surfaceWhite,
            borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
          ),
          child: CalculatorView(notice: notice),
        ),
      ),
    );
  }
}

class CalculatorView extends StatefulWidget {
  final Notice notice;
  const CalculatorView({super.key, required this.notice});

  @override
  State<CalculatorView> createState() => _CalculatorViewState();
}

class _CalculatorViewState extends State<CalculatorView> {
  double _rate = 0.0;
  
  // Logic from backend/app/services/calculator.py
  int get _calculatedPrice {
    double target = widget.notice.basicPrice * (1 + _rate / 100);
    return (target / 10).floor() * 10;
  }

  // Check safety (Mock logic: < -2.0% is dangerous)
  bool get _isDangerous => _rate < -2.0; // Adjustable threshold

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(24.0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // Handle Bar
          Center(
            child: Container(
              width: 40,
              height: 4,
              decoration: BoxDecoration(
                color: AppColors.divider,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
          ),
          const SizedBox(height: 32),
          
          Text(widget.notice.title, style: AppTextStyles.h2),
          const SizedBox(height: 8),
          Text("기초금액: ${widget.notice.formattedPrice}원", style: AppTextStyles.body1),
          
          const Spacer(),
          
          // Result
          Center(
            child: Text(
              "${_calculatedPrice.toString().replaceAllMapped(RegExp(r'(\d{1,3})(?=(\d{3})+(?!\d))'), (Match m) => '${m[1]},')}원",
              style: AppTextStyles.h1.copyWith(fontSize: 32),
            ),
          ),
          const SizedBox(height: 40),
          
          // Slider
          BidSlider(
            currentRate: _rate,
            isDangerous: _isDangerous,
            onChanged: (val) {
              setState(() => _rate = val);
            },
          ),
          
          const Spacer(),
          
          // Action Button
          ElevatedButton(
            onPressed: _isDangerous ? null : () {
              // Submit logic
            },
            style: ElevatedButton.styleFrom(
              backgroundColor: _isDangerous ? AppColors.dangerRed : AppColors.primaryBlue,
              padding: const EdgeInsets.symmetric(vertical: 16),
              foregroundColor: Colors.white,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
              disabledBackgroundColor: AppColors.backgroundGrey,
            ),
            child: const Text("이 가격으로 저장하기", style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
          ),
          const SizedBox(height: 20),
        ],
      ),
    );
  }
}
