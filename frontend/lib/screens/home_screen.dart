import 'package:flutter/material.dart';
import '../theme/style.dart';
import '../widgets/notice_card.dart';
import '../widgets/bid_slider.dart';
import '../widgets/ai_analysis_card.dart';
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
  String? _keyword;

  @override
  void initState() {
    super.initState();
    futureNotices = apiService.fetchNotices();
  }

  Future<void> _refreshNotices() async {
    try {
      await apiService.triggerCrawl(); // Still crawl all
      setState(() {
        futureNotices = apiService.fetchNotices(keyword: _keyword);
      });
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
              content: Text(
                  "Notices updated${_keyword != null ? ' (Filter: $_keyword)' : ''}")),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text("Error: $e")));
      }
    }
  }

  void _showFilterDialog() {
    TextEditingController controller = TextEditingController(text: _keyword);
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text("관심 키워드 설정"),
        content: TextField(
          controller: controller,
          decoration: const InputDecoration(
            hintText: "예: 실내, 도로, 전기",
            border: OutlineInputBorder(),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () {
              setState(() {
                _keyword = null;
                futureNotices = apiService.fetchNotices();
              });
              Navigator.pop(context);
            },
            child: const Text("초기화", style: TextStyle(color: Colors.grey)),
          ),
          ElevatedButton(
            onPressed: () {
              setState(() {
                _keyword = controller.text.trim();
                futureNotices = apiService.fetchNotices(keyword: _keyword);
              });
              Navigator.pop(context);
            },
            child: const Text("적용"),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text("BidEasy"),
        actions: [
          // Filter Button
          IconButton(
            icon: Icon(Icons.filter_list,
                color: _keyword != null ? AppColors.primaryBlue : Colors.black),
            onPressed: _showFilterDialog,
          ),
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _refreshNotices,
          ),
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
  // Real Logic: Calculate Lower Limit Rate based on Contract Type
  double get _lowerLimitRate {
    // Basic values (Backend should ideally provide this, but calculation requires it here for slider)
    // Construction: 87.745%
    // Service: 87.995%
    // Goods: 88.0%
    switch (widget.notice.contractType) {
      case 'SERVICE':
        return 87.995;
      case 'GOODS':
        return 88.0;
      case 'CONSTRUCTION':
      default:
        return 87.745;
    }
  }

  // Calculate the rate difference from standard (100%) that corresponds to the lower limit
  // e.g. 87.745% means -12.255% from basic price
  double get _dangerousThreshold => _lowerLimitRate - 100.0;

  int get _calculatedPrice {
    double target = widget.notice.basicPrice * (1 + _rate / 100);
    return (target / 10).floor() * 10;
  }

  // Check safety: If user rate is BELOW the threshold
  bool get _isDangerous => _rate < _dangerousThreshold;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 16, left: 24, right: 24, bottom: 24),
      child: Column(
        children: [
          // Handle Bar and Close Button Row
          Stack(
            alignment: Alignment.center,
            children: [
              Container(
                width: 40,
                height: 4,
                decoration: BoxDecoration(
                  color: AppColors.divider,
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
              Align(
                alignment: Alignment.centerRight,
                child: IconButton(
                  icon: const Icon(Icons.close, color: AppColors.textMain),
                  onPressed: () => Navigator.pop(context),
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),

          // Scrollable Content
          Expanded(
            child: ListView(
              controller:
                  ScrollController(), // Internal controller since parent handles drag
              padding: EdgeInsets.zero,
              children: [
                Text(widget.notice.title, style: AppTextStyles.h2),
                const SizedBox(height: 8),
                Text("기초금액: ${widget.notice.formattedPrice}원",
                    style: AppTextStyles.body1),

                const SizedBox(height: 48),

                // Result
                Center(
                  child: Text(
                    "${_calculatedPrice.toString().replaceAllMapped(RegExp(r'(\d{1,3})(?=(\d{3})+(?!\d))'), (Match m) => '${m[1]},')}원",
                    style: AppTextStyles.h1.copyWith(fontSize: 32),
                  ),
                ),
                const SizedBox(height: 32),

                // AI Analysis (Real)
                AiAnalysisCard(
                  bidNo: widget.notice.bidNo,
                  noticeUrl: widget.notice.content,
                ),

                const SizedBox(height: 24),

                // Slider
                BidSlider(
                  currentRate: _rate,
                  isDangerous: _isDangerous,
                  onChanged: (val) {
                    setState(() => _rate = val);
                  },
                ),
                const SizedBox(height: 24),
              ],
            ),
          ),

          // Action Button (Fixed at bottom)
          const SizedBox(height: 16),
          SizedBox(
            width: double.infinity,
            child: ElevatedButton(
              onPressed: _isDangerous
                  ? null
                  : () {
                      // Submit logic
                    },
              style: ElevatedButton.styleFrom(
                backgroundColor:
                    _isDangerous ? AppColors.dangerRed : AppColors.primaryBlue,
                padding: const EdgeInsets.symmetric(vertical: 16),
                foregroundColor: Colors.white,
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(16)),
                disabledBackgroundColor: AppColors.backgroundGrey,
              ),
              child: const Text("이 가격으로 저장하기",
                  style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
            ),
          ),
        ],
      ),
    );
  }
}
